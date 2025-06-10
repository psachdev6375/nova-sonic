#author puneetsd
import pyaudio
import json

__AWS_ACCESS_KEY_ID__ = "<YOUR ACCESS KEY>"
__AWS_SECRET_ACCESS_KEY__ = "<YOUR SECRET ACCESS KEY>"
__INPUT_SAMPLE_RATE__ = 16000
__OUTPUT_SAMPLE_RATE__ = 24000
__CHANNELS__ = 1
__FORMAT__ = pyaudio.paInt16
__CHUNK_SIZE__ = 1024
__MODEL_ID__ = "amazon.nova-sonic-v1:0"
__REGION__ = "us-east-1"
__KNOWLEDGE_BASE_ID_I12__ = "VAC1FDMZ7E" 
__KNOWLEDGE_BASE_ID_CENTRAL__ = "F6RKXGKLHZ" 
__AMADEUS_BEDROCK_AGENT__ = "UBJNBHWST0"
__AMADEUS_BEDROCK_AGENT_ALIAS__ = "TSTALIASID"
__DEBUG__ = False


__START_PROMPT_EVENT__ = '''{
        "event": {
            "promptStart": {
            "promptName": "%s",
            "textOutputConfiguration": {
                "mediaType": "text/plain"
                },
            "audioOutputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 24000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "voiceId": "amy",
                "encoding": "base64",
                "audioType": "SPEECH"
                },
            "toolUseOutputConfiguration": {
                "mediaType": "application/json"
                },
            "toolConfiguration": {
                "tools": %s
                }
            }
        }
    }'''

__TOOL_CONTENT_START_EVENT__ = '''{
        "event": {
            "contentStart": {
                "promptName": "%s",
                "contentName": "%s",
                "interactive": true,
                "type": "TOOL",
                "role": "TOOL",
                "toolResultInputConfiguration": {
                    "toolUseId": "%s",
                    "type": "TEXT",
                    "textInputConfiguration": {
                        "mediaType": "text/plain"
                    }
                }
            }
        }
    }'''

__CONTENT_END_EVENT__ = '''{
        "event": {
            "contentEnd": {
            "promptName": "%s",
            "contentName": "%s"
            }
        }
    }'''


__SESSION_START__ = '''
        {
          "event": {
            "sessionStart": {
              "inferenceConfiguration": {
                "maxTokens": 1024,
                "topP": 0.9,
                "temperature": 0.7
              }
            }
          }
        }
        '''

__SYSTEM_PROMPT__ = "You are a friendly assistant. Your name is Jasmine. The user and you will engage in a spoken dialog " \
            "exchanging the transcripts of a natural real-time conversation. Keep your responses short, " \
            "generally two or three sentences for chatty scenarios. " \
            "You can do the following tasks: " \
            "1. Answer questions about i12Katong shopping mall. For this you MUST use a i12katong TOOL" \
            "2. Answer questions about CentralWorld shopping mall in Bangkok. For this you MUST use a centralworld TOOL" \
            "3. Answer questions about hotels in a city or flight connections. For this you MUST use Amadeus TOOL" \
            "4. Answer any other question on your own. Do not call TOOL for it." \
            "IMPORTANT: Use a TOOL only for answering questions about i12Katong shopping mall, centralworld shopping mall, hotels and flights in a city. Do not USE The tool for any other type of question" \
            "For answering any questions about i12Katong or Centralworld, or Hotels in a city you MUST use the appropriate TOOL." \
            "These tools lookup relevant knowledgebases. DO NOT make up information. ALWAYS do a knowledge base lookup." \
            "Core Rules" \
            "- Be conversational and authentic rather than following rigid scripts" \
            "- Listen actively to understand the customer's specific situation" 


__CONTENT_START_EVENT__ = '''{
        "event": {
            "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "type": "AUDIO",
            "interactive": true,
            "role": "USER",
            "audioInputConfiguration": {
                "mediaType": "audio/lpcm",
                "sampleRateHertz": 16000,
                "sampleSizeBits": 16,
                "channelCount": 1,
                "audioType": "SPEECH",
                "encoding": "base64"
                }
            }
        }
    }'''

__AUDIO_EVENT_TEMPLATE__ = '''{
        "event": {
            "audioInput": {
            "promptName": "%s",
            "contentName": "%s",
            "content": "%s"
            }
        }
    }'''

__TEXT_CONTENT_START_EVENT__ = '''{
        "event": {
            "contentStart": {
            "promptName": "%s",
            "contentName": "%s",
            "role": "%s",
            "type": "TEXT",
            "interactive": true,
                "textInputConfiguration": {
                    "mediaType": "text/plain"
                }
            }
        }
    }'''

__TEXT_INPUT_EVENT__ = f'''
    {{
        "event": {{
            "textInput": {{
                "promptName": "%s",
                "contentName": "%s",
                "content": "%s"
            }}
        }}
    }}
    '''

__CONTENT_END_EVENT__ = '''{
        "event": {
            "contentEnd": {
            "promptName": "%s",
            "contentName": "%s"
            }
        }
    }'''

__PROMPT_END_EVENT__ = '''{
        "event": {
            "promptEnd": {
            "promptName": "%s"
            }
        }
    }'''

__SESSION_END_EVENT__ = '''{
        "event": {
            "sessionEnd": {}
        }
    }'''

__TOOLS_ARRAY_CONFIG__ = [
                    {
                        "toolSpec": {
                            "name": "i12katong",
                            "description": "Information about stores, eating joints, loyalty program and general information about i12Katong mall in Singapore",
                            "inputSchema": {
                                "json": json.dumps({
                                    "$schema": "http://json-schema.org/draft-07/schema#",
                                    "type": "object",
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "The search query to find relevant information"
                                        }
                                    },
                                    "required": ["query"]
                                })
                            }
                        }
                    },
                    {
                        "toolSpec": {
                            "name": "centralworld",
                            "description": "Information about stores, eating joints, loyalty program and general information about i12Katong mall in Singapore",
                            "inputSchema": {
                                "json": json.dumps({
                                    "$schema": "http://json-schema.org/draft-07/schema#",
                                    "type": "object",
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "The search query to find relevant information"
                                        }
                                    },
                                    "required": ["query"]
                                })
                            }
                        }
                    },
                    {
                        "toolSpec": {
                            "name": "amadeus",
                            "description": "Get details about hotels in a city, or flight connections from a city",
                            "inputSchema": {
                                "json": json.dumps({
                                    "$schema": "http://json-schema.org/draft-07/schema#",
                                    "type": "object",
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "Query about hotels in a city, or flight connections from a city"
                                        }
                                    },
                                    "required": ["query"]
                                })
                            }
                        }
                    }
                ]