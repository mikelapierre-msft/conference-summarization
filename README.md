# Session News Report Pipeline

Generate a ~2-minute news-style audio report from multiple conference session recordings using Azure Speech and Azure OpenAI.

## How It Works

```
Session Recordings (MP4/WAV/MP3/…)
  → Transcribe each recording (Azure Speech STT, parallel)
  → Synthesise cross-session themes & generate news script (Azure OpenAI GPT-4o)
  → Render script as audio (Azure Speech TTS)
  → Output: single MP3 report
```

1. **Transcription** — Each recording is transcribed in parallel using Azure Speech SDK continuous recognition.
2. **Synthesis** — All transcripts are sent to Azure OpenAI GPT-4o which infers speaker names and topics, identifies cross-cutting themes, and generates a structured analysis.
3. **Script generation** — A second LLM call transforms the analysis into a ~300-word news-anchor script covering the session as one cohesive story.
4. **Audio production** — The script is rendered to MP3 using Azure Speech TTS with SSML for natural pacing.

## Prerequisites

- **Python 3.11+**
- **Azure AI Speech** resource (for STT transcription and TTS audio generation)
- **Azure OpenAI** resource with a GPT-4o deployment (for synthesis and script writing)

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set:
#   AZURE_SPEECH_KEY            - your Speech resource key
#   AZURE_SPEECH_REGION         - e.g. eastus, westeurope
#   AZURE_OPENAI_ENDPOINT       - e.g. https://my-openai.openai.azure.com/
#   AZURE_OPENAI_KEY            - your Azure OpenAI key
#   AZURE_OPENAI_DEPLOYMENT     - model deployment name (e.g. gpt-4o)
```

## Usage

```bash
# Process all recordings in a directory
python main.py --input ./recordings/

# Specify individual files and a session name
python main.py --input rec1.mp4 rec2.mp4 rec3.mp4 --session-name "My Session"

# Custom output directory with verbose logging
python main.py --input ./recordings/ --output-dir ./reports --verbose
```

### CLI Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--input` | `-i` | *(required)* | Directory of recordings, or one or more recording file paths |
| `--session-name` | `-s` | *(inferred)* | Optional session name for the report intro |
| `--output-dir` | `-o` | `./output` | Directory for the output MP3 |
| `--verbose` | `-v` | off | Enable debug logging |

### Output

A single MP3 file in the output directory:

```
output/
└── my_session_report.mp3   # ~2-minute news-style audio report
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_SPEECH_KEY` | Yes | — | Azure Speech resource key |
| `AZURE_SPEECH_REGION` | Yes | — | Azure region (e.g. `eastus`) |
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_KEY` | Yes | — | Azure OpenAI API key |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | — | GPT-4o deployment name |
| `TTS_VOICE_NAME` | No | `en-US-JennyNeural` | Azure TTS neural voice |
| `TARGET_DURATION_SECONDS` | No | `120` | Target audio duration in seconds |
| `MAX_CONCURRENT_TRANSCRIPTIONS` | No | `6` | Max parallel transcription workers |

## Supported Input Formats

`.mp4`, `.mp3`, `.wav`, `.m4a`, `.flac`, `.ogg`, `.webm`

## Architecture

```
main.py           – CLI orchestrator & pipeline entry point
config.py         – Environment configuration
transcriber.py    – Azure Speech SDK continuous recognition (STT)
synthesizer.py    – Azure OpenAI GPT-4o analysis & script generation
producer.py       – Azure Speech TTS with SSML → MP3
```
