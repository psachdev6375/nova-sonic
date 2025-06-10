import os
import asyncio
import base64
import json
import uuid
import warnings
import pyaudio
import queue
import datetime
import time
import inspect
from rx.subject import Subject
from rx import operators as ops
from rx.scheduler.eventloop import AsyncIOScheduler
from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config, HTTPAuthSchemeResolver, SigV4AuthScheme
from smithy_aws_core.credentials_resolvers.environment import EnvironmentCredentialsResolver
import constants as constants
import boto3

# Suppress warnings
warnings.filterwarnings("ignore")

def debug_print(message):
    """Print only if debug mode is enabled"""
    if constants.__DEBUG__:
        functionName = inspect.stack()[1].function
        if  functionName == 'time_it' or functionName == 'time_it_async':
            functionName = inspect.stack()[2].function
        print('{:%Y-%m-%d %H:%M:%S.%f}'.format(datetime.datetime.now())[:-3] + ' ' + functionName + ' ' + message)

def time_it(label, methodToRun):
    start_time = time.perf_counter()
    result = methodToRun()
    end_time = time.perf_counter()
    debug_print(f"Execution time for {label}: {end_time - start_time:.4f} seconds")
    return result

async def time_it_async(label, methodToRun):
    start_time = time.perf_counter()
    result = await methodToRun()
    end_time = time.perf_counter()
    debug_print(f"Execution time for {label}: {end_time - start_time:.4f} seconds")
    return result

class BedrockStreamManager:
    """Manages bidirectional streaming with AWS Bedrock using RxPy for event processing"""
    
    def __init__(self, model_id='amazon.nova-sonic-v1:0', region='us-east-1'):
        """Initialize the stream manager."""
        self.model_id = model_id
        self.region = region
        self.input_subject = Subject()
        self.output_subject = Subject()
        self.audio_subject = Subject()
        
        self.response_task = None
        self.stream_response = None
        self.is_active = False
        self.barge_in = False
        self.bedrock_client = None
        self.scheduler = None
        
        # Audio playback components
        self.audio_output_queue = asyncio.Queue()

        # Text response components
        self.display_assistant_text = False
        self.role = None
        
        # Session information
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        boto3_session = boto3.Session(
            aws_access_key_id=constants.__AWS_ACCESS_KEY_ID__,
            aws_secret_access_key=constants.__AWS_SECRET_ACCESS_KEY__,
        )
        self.bedrock_agent_runtime = boto3_session.client('bedrock-agent-runtime')

    def _initialize_client(self):
        """Initialize the Bedrock client."""
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{self.region}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            http_auth_scheme_resolver=HTTPAuthSchemeResolver(),
            http_auth_schemes={"aws.auth#sigv4": SigV4AuthScheme()}
        )
        self.bedrock_client = BedrockRuntimeClient(config=config)
    
    async def initialize_stream(self):
        """Initialize the bidirectional stream with Bedrock."""
        if not self.bedrock_client:
            self._initialize_client()
        
        self.scheduler = AsyncIOScheduler(asyncio.get_event_loop())      
        try:
            self.stream_response = await time_it_async("invoke_model_with_bidirectional_stream", lambda : self.bedrock_client.invoke_model_with_bidirectional_stream( InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)))


            self.is_active = True
            default_system_prompt = constants.__SYSTEM_PROMPT__
            
            # Send initialization events
            prompt_event = constants.__START_PROMPT_EVENT__ % (self.prompt_name, json.dumps(constants.__TOOLS_ARRAY_CONFIG__))
            text_content_start = constants.__TEXT_CONTENT_START_EVENT__ % (self.prompt_name, self.content_name, "SYSTEM")
            text_content = constants.__TEXT_INPUT_EVENT__ % (self.prompt_name, self.content_name, default_system_prompt)
            text_content_end = constants.__CONTENT_END_EVENT__ % (self.prompt_name, self.content_name)
            
            init_events = [constants.__SESSION_START__, prompt_event, text_content_start, text_content, text_content_end]
            
            for event in init_events:
                await self.send_raw_event(event)
            
            # Start listening for responses
            self.response_task = asyncio.create_task(self._process_responses())
            
            # Set up subscription for input events
            self.input_subject.pipe(
                ops.subscribe_on(self.scheduler)
            ).subscribe(
                on_next=lambda event: asyncio.create_task(self.send_raw_event(event)),
                on_error=lambda e: debug_print(f"Input stream error: {e}")
            )
            
            # Set up subscription for audio chunks
            self.audio_subject.pipe(
                ops.subscribe_on(self.scheduler)
            ).subscribe(
                on_next=lambda audio_data: asyncio.create_task(self._handle_audio_input(audio_data)),
                on_error=lambda e: debug_print(f"Audio stream error: {e}")
            )
            debug_print("Stream initialized successfully")
            return self
        except Exception as e:
            self.is_active = False
            print(f"Failed to initialize stream: {str(e)}")
            import traceback
            traceback.print_exc()
            raise
    
    async def send_raw_event(self, event_json):
        """Send a raw event JSON to the Bedrock stream."""
        if not self.stream_response or not self.is_active:
            debug_print("Stream not initialized or closed")
            return
        
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        
        try:
            await self.stream_response.input_stream.send(event)
            # For debugging large events, you might want to log just the type
            if DEBUG:
                if len(event_json) > 200:
                    event_type = json.loads(event_json).get("event", {}).keys()
                    debug_print(f"Sent event type: {list(event_type)}")
                else:
                    debug_print(f"Sent event: {event_json}")
        except Exception as e:
            debug_print(f"Error sending event: {str(e)}")
            if DEBUG:
                import traceback
                traceback.print_exc()
            self.input_subject.on_error(e)
    
    def tool_result_event(self, content_name, content, role):
        """Create a tool result event"""

        if isinstance(content, dict):
            content_json_string = json.dumps(content)
        else:
            content_json_string = content
            
        tool_result_event = {
            "event": {
                "toolResult": {
                    "promptName": self.prompt_name,
                    "contentName": content_name,
                    "content": content_json_string
                }
            }
        }
        return json.dumps(tool_result_event)

    async def send_tool_start_event(self, content_name):
        # print('in send_tool_start_event')
        """Send a tool content start event to the Bedrock stream."""
        content_start_event =  constants.__TOOL_CONTENT_START_EVENT__ % (self.prompt_name, content_name, self.toolUseId)
        await self.send_raw_event(content_start_event)

    async def send_tool_result_event(self, content_name, tool_result):
        # print('in send_tool_result_event')
        """Send a tool content event to the Bedrock stream."""
        # Use the actual tool result from processToolUse
        tool_result_event = self.tool_result_event(content_name=content_name, content=tool_result, role="TOOL")
        await self.send_raw_event(tool_result_event)
    
    async def send_tool_content_end_event(self, content_name):
        # print('in send_tool_content_end_event')
        """Send a tool content end event to the Bedrock stream."""
        tool_content_end_event = constants.__CONTENT_END_EVENT__ % (self.prompt_name, content_name)
        await self.send_raw_event(tool_content_end_event)

    async def send_audio_content_start_event(self):
        """Send a content start event to the Bedrock stream."""
        content_start_event = constants.__CONTENT_START_EVENT__ % (self.prompt_name, self.audio_content_name)
        await self.send_raw_event(content_start_event)
    
    async def _handle_audio_input(self, data):
        """Process audio input before sending it to the stream."""
        audio_bytes = data.get('audio_bytes')
        if not audio_bytes:
            debug_print("No audio bytes received")
            return
        
        try:
            # Ensure the audio is properly formatted
            debug_print(f"Processing audio chunk of size {len(audio_bytes)} bytes")
            
            # Base64 encode the audio data
            blob = base64.b64encode(audio_bytes)
            audio_event = constants.__AUDIO_EVENT_TEMPLATE__ % (self.prompt_name, self.audio_content_name, blob.decode('utf-8'))
            
            # Send the event directly
            await self.send_raw_event(audio_event)
        except Exception as e:
            debug_print(f"Error processing audio: {e}")
            if DEBUG:
                import traceback
                traceback.print_exc()
    
    def add_audio_chunk(self, audio_bytes):
        """Add an audio chunk to the stream."""
        self.audio_subject.on_next({
            'audio_bytes': audio_bytes,
            'prompt_name': self.prompt_name,
            'content_name': self.audio_content_name
        })
    
    async def send_audio_content_end_event(self):
        """Send a content end event to the Bedrock stream."""
        if not self.is_active:
            debug_print("Stream is not active")
            return
        
        content_end_event = self.CONTENT_END_EVENT % (self.prompt_name, self.audio_content_name)
        await self.send_raw_event(content_end_event)
        debug_print("Audio ended")
    
    async def send_prompt_end_event(self):
        """Close the stream and clean up resources."""
        if not self.is_active:
            debug_print("Stream is not active")
            return
        
        prompt_end_event = self.PROMPT_END_EVENT % (self.prompt_name)
        await self.send_raw_event(prompt_end_event)
        debug_print("Prompt ended")
        
    async def send_session_end_event(self):
        """Send a session end event to the Bedrock stream."""
        if not self.is_active:
            debug_print("Stream is not active")
            return

        await self.send_raw_event(self.SESSION_END_EVENT)
        self.is_active = False
        debug_print("Session ended")
    
    async def _process_responses(self):
        """Process incoming responses from Bedrock."""
        try:            
            while self.is_active:
                try:
                    output = await self.stream_response.await_output()
                    result = await output[1].receive()
                    
                    if result.value and result.value.bytes_:
                        try:
                            response_data = result.value.bytes_.decode('utf-8')
                            json_data = json.loads(response_data)
                            # Handle different response types
                            if 'event' in json_data:
                                # print(json_data['event'])
                                if 'contentStart' in json_data['event']:
                                    debug_print("Content start detected")
                                    content_start = json_data['event']['contentStart']
                                    # set role
                                    self.role = content_start['role']
                                    # Check for speculative content
                                    if 'additionalModelFields' in content_start:
                                        try:
                                            additional_fields = json.loads(content_start['additionalModelFields'])
                                            if additional_fields.get('generationStage') == 'SPECULATIVE':
                                                debug_print("Speculative content detected")
                                                self.display_assistant_text = True
                                            else:
                                                self.display_assistant_text = False
                                        except json.JSONDecodeError:
                                            debug_print("Error parsing additionalModelFields")
                                elif 'textOutput' in json_data['event']:
                                    text_content = json_data['event']['textOutput']['content']
                                    # Check if there is a barge-in
                                    if '{ "interrupted" : true }' in text_content:
                                        if DEBUG:
                                            print("Barge-in detected. Stopping audio output.")
                                        self.barge_in = True

                                    if (self.role == "ASSISTANT" and self.display_assistant_text):
                                        print(f"Assistant: {text_content}")
                                    elif (self.role == "USER"):
                                        print(f"User: {text_content}")
                                elif 'audioOutput' in json_data['event']:
                                    audio_content = json_data['event']['audioOutput']['content']
                                    audio_bytes = base64.b64decode(audio_content)
                                    await self.audio_output_queue.put(audio_bytes)
                                elif 'toolUse' in json_data['event']:
                                    self.toolUseContent = json_data['event']['toolUse']
                                    self.toolName = json_data['event']['toolUse']['toolName']
                                    self.toolUseId = json_data['event']['toolUse']['toolUseId']
                                    print("---------------------------------------------------------")
                                    print(f"Tool use detected: {self.toolName}, ID: {self.toolUseId}")
                                    print("---------------------------------------------------------")
                                elif 'contentEnd' in json_data['event']: 
                                    if json_data['event'].get('contentEnd', {}).get('type') == 'TOOL':
                                        # print (json_data)
                                        toolResult = await self.processToolUse(self.toolName, self.toolUseContent)
                                        toolContent = str(uuid.uuid4())
                                        await self.send_tool_start_event(toolContent)
                                        await self.send_tool_result_event(toolContent, toolResult)
                                        await self.send_tool_content_end_event(toolContent)
                                    else:
                                        # print (json_data)
                                        debug_print("Content end detected")
                                # else:
                                    # print ("Last ELSE")
                                    # print (json_data)
                            self.output_subject.on_next(json_data)
                        except json.JSONDecodeError:
                            self.output_subject.on_next({"raw_data": response_data})
                except StopAsyncIteration:
                    # Stream has ended
                    break
                except Exception as e:
                    debug_print(f"Error receiving response: {e}")
                    self.output_subject.on_error(e)
                    break
        except Exception as e:
            debug_print(f"Response processing error: {e}")
            self.output_subject.on_error(e)
        finally:
            if self.is_active:  
                self.output_subject.on_completed()
    

    async def processToolUse(self, toolName, toolUseContent):
        """Return the tool result"""
        tool = toolName.lower()
        # print('In processToolUse ' + tool)
        # print(json.dumps(toolUseContent, indent=4))
        try:
            if "i12katong" in toolName:
                tool_input = json.loads(toolUseContent['content'])
                query = tool_input['query']
                print(query)
                # Call the retrieve API
                response = self.bedrock_agent_runtime.retrieve(
                    knowledgeBaseId=constants.__KNOWLEDGE_BASE_ID_I12__,  # Replace with your KB ID
                    retrievalQuery={
                        'text': query
                    },
                    retrievalConfiguration={
                        'vectorSearchConfiguration': {
                            'numberOfResults': 5  # Adjust based on your needs
                        }
                    }
                )
                # print(response)
                # Process the retrieved results
                retrieved_results = []
                for result in response['retrievalResults']:
                    retrieved_results.append({
                        'content': result['content'],
                        'score': result['score'],
                        'location': result.get('location', {})
                    })
            elif "centralworld" in toolName:
                tool_input = json.loads(toolUseContent['content'])
                query = tool_input['query']
                # print(query)
                # Call the retrieve API
                response = self.bedrock_agent_runtime.retrieve(
                    knowledgeBaseId=constants.__KNOWLEDGE_BASE_ID_CENTRAL__,  # Replace with your KB ID
                    retrievalQuery={
                        'text': query
                    },
                    retrievalConfiguration={
                        'vectorSearchConfiguration': {
                            'numberOfResults': 5  # Adjust based on your needs
                        }
                    }
                )
                # print(response)
                # Process the retrieved results
                retrieved_results = []
                for result in response['retrievalResults']:
                    retrieved_results.append({
                        'content': result['content'],
                        'score': result['score'],
                        'location': result.get('location', {})
                    })
            elif "amadeus" in toolName:
                #Make a call to Bedrock Agent
                tool_input = json.loads(toolUseContent['content'])
                query = tool_input['query']
                # print(query)
                sessionId = str(uuid.uuid4())
                beginResponse = self.bedrock_agent_runtime.invoke_agent(
                    agentId=constants.__AMADEUS_BEDROCK_AGENT__,
                    agentAliasId=constants.__AMADEUS_BEDROCK_AGENT_ALIAS__,
                    sessionId=sessionId,
                    inputText=query, 
                    enableTrace=True
                )
                # print(beginResponse)
                retrieved_results = []
                
                for event in beginResponse.get("completion"):
                    if "chunk" in event:
                        chunk = event["chunk"]
                        response = chunk["bytes"].decode()
                        print("FROM EVENT of AGENT = "+response)
                        retrieved_results.append({
                            'content': response
                        })
                        
            else:
                retrieved_results = []
                retrieved_results.append({
                        'Error': f"Unknown tool {toolName}"
                    })
        except Exception as e:
            print(f"Error querying knowledge base: {e}")
            retrieved_results = []
            retrieved_results.append({
                        'Error': f"Failed to query knowledge base {str(e)}"
                    })
        
        return json.dumps({"retrievedResults": retrieved_results})

    
    async def close(self):
        """Close the stream properly."""
        if not self.is_active:
            return
            
        # Complete the subjects
        self.input_subject.on_completed()
        self.audio_subject.on_completed()

        self.is_active = False
        if self.response_task and not self.response_task.done():
            self.response_task.cancel()
        
        await self.send_audio_content_end_event()
        await self.send_prompt_end_event()
        await self.send_session_end_event()

        if self.stream_response:
            await self.stream_response.input_stream.close()

class AudioStreamer:
    """Handles continuous microphone input and audio output using separate streams."""
    
    def __init__(self, stream_manager):
        self.stream_manager = stream_manager
        self.is_streaming = False
        self.loop = asyncio.get_event_loop()

        # Initialize PyAudio
        debug_print("AudioStreamer Initializing PyAudio...")
        self.p = time_it("AudioStreamerInitPyAudio", pyaudio.PyAudio)
        debug_print("AudioStreamer PyAudio initialized")

        # Initialize separate streams for input and output
        # Input stream with callback for microphone
        debug_print("Opening input audio stream...")
        self.input_stream = time_it("AudioStreamerOpenAudio", lambda  : self.p.open(
            format=constants.__FORMAT__,
            channels=constants.__CHANNELS__,
            rate=constants.__INPUT_SAMPLE_RATE__,
            input=True,
            frames_per_buffer=constants.__CHUNK_SIZE__,
            stream_callback=self.input_callback
        ))
        debug_print("input audio stream opened")

        # Output stream for direct writing (no callback)
        debug_print("Opening output audio stream...")
        self.output_stream = time_it("AudioStreamerOpenAudio", lambda  : self.p.open(
            format=constants.__FORMAT__,
            channels=constants.__CHANNELS__,
            rate=constants.__OUTPUT_SAMPLE_RATE__,
            output=True,
            frames_per_buffer=constants.__CHUNK_SIZE__
        ))

        debug_print("output audio stream opened")

    def input_callback(self, in_data, frame_count, time_info, status):
        """Callback function that schedules audio processing in the asyncio event loop"""
        if self.is_streaming and in_data:
            # Schedule the task in the event loop
            asyncio.run_coroutine_threadsafe(
                self.process_input_audio(in_data), 
                self.loop
            )
        return (None, pyaudio.paContinue)

    async def process_input_audio(self, audio_data):
        """Process a single audio chunk directly"""
        try:
            # Send audio to Bedrock immediately
            self.stream_manager.add_audio_chunk(audio_data)
        except Exception as e:
            if self.is_streaming:
                print(f"Error processing input audio: {e}")
    
    async def play_output_audio(self):
        """Play audio responses from Nova Sonic"""
        while self.is_streaming:
            try:
                # Check for barge-in flag
                if self.stream_manager.barge_in:
                    # Clear the audio queue
                    while not self.stream_manager.audio_output_queue.empty():
                        try:
                            self.stream_manager.audio_output_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    self.stream_manager.barge_in = False
                    # Small sleep after clearing
                    await asyncio.sleep(0.05)
                    continue
                
                # Get audio data from the stream manager's queue
                audio_data = await asyncio.wait_for(
                    self.stream_manager.audio_output_queue.get(),
                    timeout=0.1
                )
                
                if audio_data and self.is_streaming:
                    # Write directly to the output stream in smaller chunks
                    chunk_size = constants.__CHUNK_SIZE__  # Use the same chunk size as the stream
                    
                    # Write the audio data in chunks to avoid blocking too long
                    for i in range(0, len(audio_data), chunk_size):
                        if not self.is_streaming:
                            break
                        
                        end = min(i + chunk_size, len(audio_data))
                        chunk = audio_data[i:end]
                        
                        # Create a new function that captures the chunk by value
                        def write_chunk(data):
                            return self.output_stream.write(data)
                        
                        # Pass the chunk to the function
                        await asyncio.get_event_loop().run_in_executor(None, write_chunk, chunk)
                        
                        # Brief yield to allow other tasks to run
                        await asyncio.sleep(0.001)
                    
            except asyncio.TimeoutError:
                # No data available within timeout, just continue
                continue
            except Exception as e:
                if self.is_streaming:
                    print(f"Error playing output audio: {str(e)}")
                    import traceback
                    traceback.print_exc()
                await asyncio.sleep(0.05)
    
    async def start_streaming(self):
        """Start streaming audio."""
        if self.is_streaming:
            return
        
        print("Starting audio streaming. Speak into your microphone...")
        print("Press Enter to stop streaming...")
        
        # Send audio content start event
        await time_it_async("send_audio_content_start_event", lambda : self.stream_manager.send_audio_content_start_event())
        
        self.is_streaming = True
        
        # Start the input stream if not already started
        if not self.input_stream.is_active():
            self.input_stream.start_stream()
        
        # Start processing tasks
        #self.input_task = asyncio.create_task(self.process_input_audio())
        self.output_task = asyncio.create_task(self.play_output_audio())
        
        # Wait for user to press Enter to stop
        await asyncio.get_event_loop().run_in_executor(None, input)
        
        # Once input() returns, stop streaming
        await self.stop_streaming()
    
    async def stop_streaming(self):
        """Stop streaming audio."""
        if not self.is_streaming:
            return
            
        self.is_streaming = False

        # Cancel the tasks
        tasks = []
        if hasattr(self, 'input_task') and not self.input_task.done():
            tasks.append(self.input_task)
        
        if hasattr(self, 'output_task') and not self.output_task.done():
            tasks.append(self.output_task)
        
        for task in tasks:
            task.cancel()
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        # Stop and close the streams
        if self.input_stream:
            if self.input_stream.is_active():
                self.input_stream.stop_stream()
            self.input_stream.close()
        
        if self.output_stream:
            if self.output_stream.is_active():
                self.output_stream.stop_stream()
            self.output_stream.close()
        
        if self.p:
            self.p.terminate()
        
        await self.stream_manager.close() 


async def main(debug=False):
    """Main function to run the application."""
    global DEBUG
    DEBUG = debug

    # Create stream manager
    stream_manager = BedrockStreamManager(model_id=constants.__MODEL_ID__, region=constants.__REGION__)

    # Create audio streamer
    audio_streamer = AudioStreamer(stream_manager)

    # Initialize the stream
    await time_it_async("initialize_stream", stream_manager.initialize_stream)

    try:
        # This will run until the user presses Enter
        await audio_streamer.start_streaming()
        
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        # Clean up
        await audio_streamer.stop_streaming()
        

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Nova Sonic Python Streaming')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    args = parser.parse_args()
    os.environ['AWS_ACCESS_KEY_ID'] = constants.__AWS_ACCESS_KEY_ID__
    os.environ['AWS_SECRET_ACCESS_KEY'] = constants.__AWS_SECRET_ACCESS_KEY__
    os.environ['AWS_DEFAULT_REGION'] = constants.__REGION__

    # Run the main function
    try:
        asyncio.run(main(debug=args.debug))
    except Exception as e:
        print(f"Application error: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()