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
- Python 3.12+
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

3. Configure AWS credentials:
Update `constants.py` with your AWS credentials:
```python
__AWS_ACCESS_KEY_ID__ = "<YOUR ACCESS KEY>"
__AWS_SECRET_ACCESS_KEY__ = "<YOUR SECRET ACCESS KEY>"
```

4. Run the app 
```bash
python NovaSonic.py
```
