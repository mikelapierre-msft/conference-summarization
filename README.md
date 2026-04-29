# Session News Report Pipeline

Generate a ~2-minute news-style audio report from conference session PPTX files using Azure AI Services and Azure OpenAI.

## How It Works

```
Session PPTX files
  → Extract embedded videos from each PPTX
  → Transcribe each video (Azure AI fast transcription, parallel)
  → Synthesise cross-session themes & generate news script (Azure OpenAI GPT-4o)
  → Render script as audio (Azure Speech TTS)
  → Output: single MP3 report
```

1. **Video extraction** — Embedded videos are extracted from each PPTX file (which is a ZIP archive containing media in `ppt/media/`).
2. **Transcription** — Each video is transcribed in parallel using the Azure AI fast transcription API.
3. **Synthesis** — All transcripts are sent to Azure OpenAI GPT-4o which infers speaker names and topics, identifies cross-cutting themes, and generates a structured analysis.
4. **Script generation** — A second LLM call transforms the analysis into a ~300-word news-anchor script covering the session as one cohesive story.
5. **Audio production** — The script is rendered to MP3 using Azure Speech TTS with SSML for natural pacing.

## Prerequisites

- **Python 3.11+**
- **ffmpeg** on `PATH` (for extracting audio from video files)
- **Azure AI Services** resource (multi-service, with fast transcription and TTS)
- **Azure OpenAI** resource with a GPT-4o deployment (for synthesis and script writing)

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and set:
#   AZURE_OPENAI_ENDPOINT       - e.g. https://my-openai.openai.azure.com/
#   AZURE_OPENAI_DEPLOYMENT     - model deployment name (e.g. gpt-4o)
#   AZURE_AI_SERVICES_ENDPOINT  - e.g. https://my-resource.cognitiveservices.azure.com
#   AZURE_SPEECH_REGION         - e.g. eastus, westeurope
#
# Authentication uses DefaultAzureCredential (az login, managed identity, etc.)
```

## Usage

```bash
# Process all PPTX files in a directory
python main.py --input ./presentations/

# Specify individual files and a session name
python main.py --input talk1.pptx talk2.pptx --session-name "My Session"

# Custom output directory with verbose logging
python main.py --input ./presentations/ --output-dir ./reports --verbose
```

### CLI Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--input` | `-i` | *(required)* | Directory of PPTX files, or one or more PPTX file paths |
| `--session-name` | `-s` | *(inferred)* | Optional session name for the report intro |
| `--output-dir` | `-o` | `./output` | Directory for the output MP3 |
| `--verbose` | `-v` | off | Enable debug logging |

### Output

One MP3 report per PPTX file in the output directory:

```
output/
├── talk1.mp3   # ~2-minute news-style audio report
└── talk2.mp3
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | — | GPT-4o deployment name |
| `AZURE_AI_SERVICES_ENDPOINT` | Yes | — | Azure AI Services (multi-service) endpoint URL |
| `AZURE_SPEECH_REGION` | Yes | — | Azure region (e.g. `eastus`) |
| `TTS_VOICE` | No | `en-US-Iris:MAI-Voice-1` | Azure TTS voice name |
| `TTS_STYLE` | No | *(empty)* | TTS voice style (e.g. `narration`, `neutral`) |
| `TARGET_DURATION_SECONDS` | No | `120` | Target audio duration in seconds |
| `MAX_CONCURRENT_TRANSCRIPTIONS` | No | `6` | Max parallel transcription workers |

Authentication uses `DefaultAzureCredential` (e.g. `az login`, managed identity). No API keys required.

## Supported Input Formats

`.pptx` files with embedded video (`.mp4`, `.m4v`, `.wmv`, `.avi`, `.mov`)

## Architecture

```
main.py           – CLI orchestrator & pipeline entry point
config.py         – Environment configuration & Entra credential
extractor.py      – Extract embedded videos from PPTX files
transcriber.py    – Azure AI fast transcription API (STT)
synthesizer.py    – Azure OpenAI GPT-4o analysis & script generation
producer.py       – Azure Speech TTS with SSML → MP3
```
