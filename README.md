# Conference Track News-Report Pipeline

Generate a ~2-minute news-style audio report from a folder of conference PPTX files using Azure AI Services and Azure OpenAI.

## How It Works

```
Folder of PPTX files (one conference track / theme)
  → Extract embedded media (video + audio) from each PPTX
  → Extract text from the first 2 slides of each PPTX (for context)
  → Transcribe each media file in parallel (Azure AI fast transcription)
  → Synthesise cross-presentation themes (Azure OpenAI)
  → Generate a news-anchor script (Azure OpenAI)
  → Render the script as audio (Azure Speech TTS, SSML)
  → Output: one MP3 named after the input folder
```

1. **Media extraction** — Embedded videos and audio clips are extracted from each PPTX (a PPTX is a ZIP archive with media under `ppt/media/`).
2. **Slide-text extraction** — Text from the first two slides of each deck is extracted to give the LLM cover-slide context (titles, speakers, affiliations).
3. **Transcription** — Each media file is transcribed in parallel via the Azure AI fast transcription API. Non-native containers are converted to WAV with `ffmpeg` first.
4. **Synthesis** — All transcripts plus slide context are sent to Azure OpenAI, which infers speaker names, presentation topics, and cross-cutting themes, and returns a structured JSON analysis.
5. **Script generation** — A second LLM call transforms the analysis into a news-anchor script sized for the target duration.
6. **Audio production** — The script is rendered to MP3 using Azure Speech TTS with SSML for natural pacing and pronunciation overrides.

Transcriptions and slide-text extraction are cached on disk under `<input>/.cache/`, keyed by SHA-256 of each source file, so re-runs are fast.

## Prerequisites

- **Python 3.11+** (the code uses PEP 604 union syntax: `str | None`)
- **ffmpeg** on `PATH` (used to convert video containers to WAV before transcription)
- **Azure AI Services** resource (multi-service; provides fast transcription and TTS)
- **Azure OpenAI** resource with a chat-completions deployment (e.g. GPT-4o)

## Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment (create a .env file in the repo root)
#   AZURE_OPENAI_ENDPOINT       - e.g. https://my-openai.openai.azure.com/
#   AZURE_OPENAI_DEPLOYMENT     - chat model deployment name (e.g. gpt-4o)
#   AZURE_AI_SERVICES_ENDPOINT  - e.g. https://my-resource.cognitiveservices.azure.com
#   AZURE_SPEECH_REGION         - e.g. eastus, westeurope
#
# Authentication uses DefaultAzureCredential (az login, managed identity, etc.)
# No API keys are required.
```

## Usage

The pipeline operates on a **folder** of PPTX files representing one conference track / theme. The output MP3 is named after the folder.

```bash
# Process all PPTX files in a folder
python main.py --input ./presentations/my-theme/

# Custom output directory with verbose logging
python main.py --input ./presentations/my-theme/ --output-dir ./reports --verbose

# Skip files that cannot be opened (e.g. information-protected PPTX)
python main.py --input ./presentations/my-theme/ --skip-broken

# Disable disk caching of transcripts and slide text
python main.py --input ./presentations/my-theme/ --no-cache

# Print the full LLM prompts to the console for debugging
python main.py --input ./presentations/my-theme/ --show-prompts
```

### CLI Arguments

| Argument | Short | Default | Description |
|----------|-------|---------|-------------|
| `--input` | `-i` | *(required)* | Path to a folder containing PPTX files for one track. |
| `--output-dir` | `-o` | `./output` | Directory for the output MP3. |
| `--verbose` | `-v` | off | Enable debug logging. |
| `--show-prompts` | — | off | Print the full LLM prompts to the console. |
| `--no-cache` | — | off | Disable on-disk caching of transcriptions and slide text. |
| `--skip-broken` | — | off | Skip PPTX files that cannot be opened instead of aborting. |

### Output

One MP3 report per input folder, named after the folder (lowercased, non-alphanumeric characters stripped):

```
output/
└── my_theme.mp3   # ~2-minute news-style audio report
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Yes | — | Azure OpenAI endpoint URL. |
| `AZURE_OPENAI_DEPLOYMENT` | Yes | — | Chat-completions deployment name. |
| `AZURE_AI_SERVICES_ENDPOINT` | Yes | — | Azure AI Services (multi-service) endpoint URL. |
| `AZURE_SPEECH_REGION` | Yes | — | Azure region for the Speech TTS endpoint (e.g. `eastus`). |
| `TTS_VOICE` | No | `en-US-Iris:MAI-Voice-1` | Azure TTS voice name. |
| `TTS_STYLE` | No | *(empty)* | TTS voice style (e.g. `narration`, `newscast-formal`). |
| `TARGET_DURATION_SECONDS` | No | `120` | Target audio duration in seconds. |
| `MAX_CONCURRENT_TRANSCRIPTIONS` | No | `6` | Max parallel transcription workers. |

Authentication uses `DefaultAzureCredential` (e.g. `az login`, managed identity). No API keys are required.

## Supported Inputs

- **Decks**: `.pptx`, `.ppsx`
- **Embedded video**: `.mp4`, `.m4v`, `.wmv`, `.avi`, `.mov`
- **Embedded audio**: `.mp3`, `.wav`, `.m4a`, `.wma`, `.flac`, `.ogg`, `.webm`

## Caching

Unless `--no-cache` is passed, results are cached under the input folder:

```
<input>/.cache/
├── slides/<sha256>.json       # extracted slide text per PPTX
└── transcripts/<sha256>.json  # transcript text per media file
```

Cache entries are keyed by a SHA-256 hash of the source file, so the cache auto-invalidates when a file changes.

## Architecture

```
main.py         – CLI orchestrator & pipeline entry point
config.py       – Environment configuration & shared Entra credential
extractor.py    – Extract embedded media and slide text from PPTX files
transcriber.py  – Azure AI fast transcription API (with ffmpeg fallback)
synthesizer.py  – Azure OpenAI analysis & news-script generation
producer.py     – Azure Speech TTS with SSML → MP3
cache.py        – On-disk SHA-256-keyed cache for slide text & transcripts
```
