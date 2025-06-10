# NovaSonic: A Bidirectional Streaming Voice Assistant with AWS Bedrock Integration

NovaSonic is a Python-based voice assistant that enables real-time bidirectional streaming conversations using AWS Bedrock's machine learning capabilities. It provides a natural conversational interface with support for both voice and text interactions, along with integrated knowledge base lookups for specific domains like shopping malls and travel information.

The project implements a sophisticated event-driven architecture that handles audio streaming, text processing, and tool-based knowledge retrieval. It features a flexible system prompt configuration, customizable voice settings, and seamless integration with AWS services. The assistant, named Jasmine, can engage in natural conversations while accessing structured knowledge through specialized tools for i12Katong mall, CentralWorld mall, and Amadeus travel information.

## Repository Structure
```
.
├── NovaSonic.py           # Core implementation of bidirectional streaming manager
├── SimpleNovaSonic.py     # Simplified interface for voice assistant interactions
├── constants.py           # Configuration constants and event templates
├── requirements.txt       # Project dependencies
└── README.md             # Project documentation
```

## Usage Instructions
### Prerequisites
- Python 3.7+
- AWS Account with Bedrock access
- AWS Access Key ID and Secret Access Key
- PyAudio system dependencies

Required Python packages:
```
boto3
pyaudio
asyncio
aws_sdk_bedrock_runtime
tk
pytz
numpy
rx>=3.2.0
smithy-aws-core>=0.0.1
```

### Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd novasonic
```

2. Install dependencies:

**MacOS**:
```bash
brew install portaudio
pip install -r requirements.txt
```

**Linux/Debian**:
```bash
sudo apt-get install python3-pyaudio portaudio19-dev
pip install -r requirements.txt
```

**Windows**:
```bash
pip install -r requirements.txt
```

3. Configure AWS credentials:
Update `constants.py` with your AWS credentials:
```python
__AWS_ACCESS_KEY_ID__ = "<YOUR ACCESS KEY>"
__AWS_SECRET_ACCESS_KEY__ = "<YOUR SECRET ACCESS KEY>"
```

### Quick Start
```python
from SimpleNovaSonic import SimpleNovaSonic

async def main():
    # Initialize the voice assistant
    nova = SimpleNovaSonic()
    
    # Start a new session
    await nova.start_session()
    
    # Start audio input
    await nova.start_audio_input()
    
    # Send audio chunks
    audio_chunk = get_audio_data()  # Your audio capture logic
    await nova.send_audio_chunk(audio_chunk)
    
    # End audio input
    await nova.end_audio_input()
    
    # End session
    await nova.end_session()

# Run the async main function
asyncio.run(main())
```

### More Detailed Examples

1. Using the BedrockStreamManager for custom implementations:
```python
from NovaSonic import BedrockStreamManager

async def custom_implementation():
    manager = BedrockStreamManager()
    await manager.initialize_stream()
    
    # Subscribe to output events
    manager.output_subject.subscribe(
        on_next=lambda x: print("Received:", x),
        on_error=lambda e: print("Error:", e)
    )
    
    # Send custom events
    await manager.send_raw_event(your_custom_event)
```

2. Using tools for knowledge base queries:
```python
# Query about i12Katong mall
await nova.send_tool_start_event("mall_query")
await nova.send_tool_result_event("mall_query", {
    "query": "What restaurants are in i12Katong?"
})
await nova.send_tool_content_end_event("mall_query")
```

### Troubleshooting

1. Audio Input Issues
- Error: "PortAudio error: Invalid sample rate"
  - Solution: Check if your system supports the configured sample rate (16000Hz for input, 24000Hz for output)
  - Verify PyAudio installation: `python -m pip install --upgrade pyaudio`

2. AWS Connection Issues
- Error: "Could not connect to the endpoint URL"
  - Verify AWS credentials in constants.py
  - Check if your AWS account has Bedrock access
  - Ensure proper network connectivity

3. Stream Initialization Failures
- Enable debug mode in constants.py: `__DEBUG__ = True`
- Check console output for detailed error messages
- Verify model ID and region settings

## Data Flow
The NovaSonic system processes data through a bidirectional streaming pipeline.

```ascii
[Audio Input] -> [PyAudio Capture] -> [Base64 Encoding] -> [AWS Bedrock Stream]
                                                                  |
[Audio Output] <- [PyAudio Playback] <- [Base64 Decoding] <- [Response]
```

Component Interactions:
- Audio capture occurs in configurable chunks (1024 bytes)
- Raw audio is encoded in base64 format before transmission
- AWS Bedrock processes audio and generates responses
- Knowledge base tools are invoked based on conversation context
- Responses are streamed back as both text and audio
- Event system manages bidirectional communication flow
- RxPY handles asynchronous event processing