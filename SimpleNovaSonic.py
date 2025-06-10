#author puneetsd
import asyncio
import base64
import json
import uuid
import pyaudio
from aws_sdk_bedrock_runtime.client import BedrockRuntimeClient, InvokeModelWithBidirectionalStreamOperationInput
from aws_sdk_bedrock_runtime.models import InvokeModelWithBidirectionalStreamInputChunk, BidirectionalInputPayloadPart
from aws_sdk_bedrock_runtime.config import Config, HTTPAuthSchemeResolver, SigV4AuthScheme
from smithy_aws_core.credentials_resolvers.environment import EnvironmentCredentialsResolver
import asyncio
import os
import boto3
import constants as constants

class SimpleNovaSonic:
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
        await self.send_event(content_start_event)

    async def send_tool_result_event(self, content_name, tool_result):
        # print('in send_tool_result_event')
        """Send a tool content event to the Bedrock stream."""
        # Use the actual tool result from processToolUse
        tool_result_event = self.tool_result_event(content_name=content_name, content=tool_result, role="TOOL")
        await self.send_event(tool_result_event)
    
    async def send_tool_content_end_event(self, content_name):
        # print('in send_tool_content_end_event')
        """Send a tool content end event to the Bedrock stream."""
        tool_content_end_event = constants.__CONTENT_END_EVENT__ % (self.prompt_name, content_name)
        await self.send_event(tool_content_end_event)

    def __init__(self, model_id=constants.__MODEL_ID__, region=constants.__REGION__):
        self.model_id = model_id
        self.region = region
        self.client = None
        self.stream = None
        self.response = None
        self.is_active = False
        self.prompt_name = str(uuid.uuid4())
        self.content_name = str(uuid.uuid4())
        self.audio_content_name = str(uuid.uuid4())
        self.audio_queue = asyncio.Queue()
        self.display_assistant_text = False
        self.toolUseContent = ""
        self.toolUseId = ""
        self.toolName = ""
        self.barge_in = False
        boto3_session = boto3.Session(
            aws_access_key_id=constants.__AWS_ACCESS_KEY_ID__,
            aws_secret_access_key=constants.__AWS_SECRET_ACCESS_KEY__,
        )
        self.bedrock_agent_runtime = boto3_session.client('bedrock-agent-runtime')

    def _initialize_client(self):
        """Initialize the Bedrock client."""
        config = Config(
            endpoint_uri=f"https://bedrock-runtime.{constants.__REGION__}.amazonaws.com",
            region=self.region,
            aws_credentials_identity_resolver=EnvironmentCredentialsResolver(),
            http_auth_scheme_resolver=HTTPAuthSchemeResolver(),
            http_auth_schemes={"aws.auth#sigv4": SigV4AuthScheme()}
        )
        self.client = BedrockRuntimeClient(config=config)


    async def send_event(self, event_json):
        """Send an event to the stream."""
        event = InvokeModelWithBidirectionalStreamInputChunk(
            value=BidirectionalInputPayloadPart(bytes_=event_json.encode('utf-8'))
        )
        await self.stream.input_stream.send(event)

    async def start_session(self):
        # print('In StartSession')
        """Start a new session with Nova Sonic."""
        if not self.client:
            self._initialize_client()
            
        # Initialize the stream
        self.stream = await self.client.invoke_model_with_bidirectional_stream(
            InvokeModelWithBidirectionalStreamOperationInput(model_id=self.model_id)
        )
        self.is_active = True
        
        await self.send_event(constants.__SESSION_START__)
        
        prompt_start = {
          "event": {
            "promptStart": {
              "promptName": self.prompt_name,
              "textOutputConfiguration": {
                "mediaType": "text/plain"
              },
              "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 24000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": "tiffany",
                "encoding": "base64",
                "audioType": "SPEECH"
              },
              "toolUseOutputConfiguration": {
                  "mediaType": "application/json"
              },
              "toolConfiguration": {
                "tools": constants.__TOOLS_ARRAY_CONFIG__
              }
            }
          }
        }
        
        await self.send_event(json.dumps(prompt_start))
        
        # Send system prompt
        text_content_start = f'''
        {{
            "event": {{
                "contentStart": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.content_name}",
                    "type": "TEXT",
                    "interactive": true,
                    "role": "SYSTEM",
                    "textInputConfiguration": {{
                        "mediaType": "text/plain"
                    }}
                }}
            }}
        }}
        '''
        
        await self.send_event(text_content_start)

        text_input = f'''
        {{
            "event": {{
                "textInput": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.content_name}",
                    "content": "{constants.__SYSTEM_PROMPT__}"
                }}
            }}
        }}
        '''
        await self.send_event(text_input)
        
        text_content_end = f'''
        {{
            "event": {{
                "contentEnd": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.content_name}"
                }}
            }}
        }}
        '''
        await self.send_event(text_content_end)
        
        # Start processing responses
        self.response = asyncio.create_task(self._process_responses())
    
    async def start_audio_input(self):
        """Start audio input stream."""
        audio_content_start = f'''
        {{
            "event": {{
                "contentStart": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.audio_content_name}",
                    "type": "AUDIO",
                    "interactive": true,
                    "role": "USER",
                    "audioInputConfiguration": {{
                        "mediaType": "audio/lpcm",
                        "sampleRateHertz": 16000,
                        "sampleSizeBits": 16,
                        "channelCount": 1,
                        "audioType": "SPEECH",
                        "encoding": "base64"
                    }}
                }}
            }}
        }}
        '''
        await self.send_event(audio_content_start)
    
    async def send_audio_chunk(self, audio_bytes):
        """Send an audio chunk to the stream."""
        if not self.is_active:
            return
            
        blob = base64.b64encode(audio_bytes)
        audio_event = f'''
        {{
            "event": {{
                "audioInput": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.audio_content_name}",
                    "content": "{blob.decode('utf-8')}"
                }}
            }}
        }}
        '''
        await self.send_event(audio_event)
    
    async def end_audio_input(self):
        """End audio input stream."""
        audio_content_end = f'''
        {{
            "event": {{
                "contentEnd": {{
                    "promptName": "{self.prompt_name}",
                    "contentName": "{self.audio_content_name}"
                }}
            }}
        }}
        '''
        await self.send_event(audio_content_end)


    async def end_session(self):
        """End the session."""
        if not self.is_active:
            return
            
        prompt_end = f'''
        {{
            "event": {{
                "promptEnd": {{
                    "promptName": "{self.prompt_name}"
                }}
            }}
        }}
        '''
        await self.send_event(prompt_end)
        
        session_end = '''
        {
            "event": {
                "sessionEnd": {}
            }
        }
        '''
        await self.send_event(session_end)
        # close the stream
        await self.stream.input_stream.close()


    async def _process_responses(self):
        """Process responses from the stream."""
        try:
            while self.is_active:
                output = await self.stream.await_output()
                result = await output[1].receive()
                if result.value and result.value.bytes_:
                    response_data = result.value.bytes_.decode('utf-8')
                    json_data = json.loads(response_data)
                    if 'event' in json_data:
                        # Handle content start event
                        if 'contentStart' in json_data['event']:
                            content_start = json_data['event']['contentStart'] 
                            # set role
                            self.role = content_start['role']
                            # Check for speculative content
                            if 'additionalModelFields' in content_start:
                                additional_fields = json.loads(content_start['additionalModelFields'])
                                if additional_fields.get('generationStage') == 'SPECULATIVE':
                                    self.display_assistant_text = True
                                else:
                                    self.display_assistant_text = False
                                
                        # Handle text output event
                        elif 'textOutput' in json_data['event']:
                            text = json_data['event']['textOutput']['content']
                            if '{ "interrupted" : true }' in text:
                                print("Barge-in detected. Stopping audio output.")
                                self.barge_in = True
                            if (self.role == "ASSISTANT" and self.display_assistant_text):
                                print(f"Assistant: {text}")
                            elif self.role == "USER":
                                print(f"User: {text}")
                            
                        
                        # Handle audio output
                        elif 'audioOutput' in json_data['event']:
                            audio_content = json_data['event']['audioOutput']['content']
                            audio_bytes = base64.b64decode(audio_content)
                            await self.audio_queue.put(audio_bytes)

                        elif 'toolUse' in json_data['event']:
                            self.toolUseContent = json_data['event']['toolUse']
                            self.toolName = json_data['event']['toolUse']['toolName']
                            self.toolUseId = json_data['event']['toolUse']['toolUseId']
                            print("---------------------------------------------------------")
                            print(f"Tool use detected: {self.toolName}, ID: {self.toolUseId}")
                            print("---------------------------------------------------------")
                        
                        elif 'contentEnd' in json_data['event'] and json_data['event'].get('contentEnd', {}).get('type') == 'TOOL':
                            toolResult = await self.processToolUse(self.toolName, self.toolUseContent)
                            toolContent = str(uuid.uuid4())
                            await self.send_tool_start_event(toolContent)
                            await self.send_tool_result_event(toolContent, toolResult)
                            await self.send_tool_content_end_event(toolContent)

        except Exception as e:
            print(f"Error processing responses: {e}")
    
    async def processToolUse(self, toolName, toolUseContent):
        """Return the tool result"""
        tool = toolName.lower()
        # print('In processToolUse ' + tool)
        # print(json.dumps(toolUseContent, indent=4))
        try:
            if "i12katong" in toolName:
                tool_input = json.loads(toolUseContent['content'])
                query = tool_input['query']
                # print(query)
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


    async def play_audio(self):
        """Play audio responses."""
        
        p = pyaudio.PyAudio()
        stream = p.open(
            format=constants.__FORMAT__,
            channels=constants.__CHANNELS__,
            rate=constants.__OUTPUT_SAMPLE_RATE__,
            output=True
        )
        
        try:
            while self.is_active:
                if self.barge_in:
                     self.barge_in = False
                     while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                else:
                    audio_data = await self.audio_queue.get()
                    stream.write(audio_data)
        except Exception as e:
            print(f"Error playing audio: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()


    async def capture_audio(self):
        """Capture audio from microphone and send to Nova Sonic."""
        p = pyaudio.PyAudio()
        stream = p.open(
            format=constants.__FORMAT__,
            channels=constants.__CHANNELS__,
            rate=constants.__INPUT_SAMPLE_RATE__,
            input=True,
            frames_per_buffer=constants.__CHUNK_SIZE__
        )
        
        print("Starting audio capture. Speak into your microphone...")
        print("Press Enter to stop...")
        
        await self.start_audio_input()
        
        try:
            while self.is_active:
                audio_data = stream.read(constants.__CHUNK_SIZE__, exception_on_overflow=False)
                await self.send_audio_chunk(audio_data)
                await asyncio.sleep(0.01)
        except Exception as e:
            print(f"Error capturing audio: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            p.terminate()
            print("Audio capture stopped.")
            await self.end_audio_input()

async def main():
    # Create Nova Sonic client
    nova_client = SimpleNovaSonic()

    # Start session
    await nova_client.start_session()

    # Start audio playback task
    playback_task = asyncio.create_task(nova_client.play_audio())

    # Start audio capture task
    capture_task = asyncio.create_task(nova_client.capture_audio())

    # Wait for user to press Enter to stop
    await asyncio.get_event_loop().run_in_executor(None, input)

    # End session
    nova_client.is_active = False

    # First cancel the tasks
    tasks = []
    if not playback_task.done():
        tasks.append(playback_task)
    if not capture_task.done():
        tasks.append(capture_task)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)

    # cancel the response task
    if nova_client.response and not nova_client.response.done():
        nova_client.response.cancel()

    await nova_client.end_session()
    print("Session ended")

if __name__ == "__main__":
    os.environ['AWS_ACCESS_KEY_ID'] = constants.__AWS_ACCESS_KEY_ID__
    os.environ['AWS_SECRET_ACCESS_KEY'] = constants.__AWS_SECRET_ACCESS_KEY__
    os.environ['AWS_DEFAULT_REGION'] = constants.__REGION__
    asyncio.run(main())
