import os
import logging

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

# ── Shared Entra credential ──────────────────────────────────────────
_credential = DefaultAzureCredential()

# ── Azure OpenAI (GPT-4o for synthesis & script generation) ──────────
AZURE_OPENAI_ENDPOINT = os.environ["AZURE_OPENAI_ENDPOINT"]
AZURE_OPENAI_DEPLOYMENT = os.environ["AZURE_OPENAI_DEPLOYMENT"]
openai_token_provider = get_bearer_token_provider(
    _credential, "https://cognitiveservices.azure.com/.default",
)

# ── Azure AI Services endpoint (for fast transcription + TTS) ────────
AZURE_AI_SERVICES_ENDPOINT = os.environ["AZURE_AI_SERVICES_ENDPOINT"]
AZURE_SPEECH_REGION = os.environ["AZURE_SPEECH_REGION"]

# TTS voice and style
TTS_VOICE = os.environ.get("TTS_VOICE", "en-US-Iris:MAI-Voice-1")
TTS_STYLE = os.environ.get("TTS_STYLE", "")


def get_tts_authorization_token() -> str:
    """Exchange an Entra token for a Speech authorization token via STS.

    The AI Services resource issues a short-lived token at its STS endpoint
    that the regional TTS endpoint accepts as a Bearer token.
    """
    import requests as _requests

    entra_token = _credential.get_token("https://cognitiveservices.azure.com/.default").token
    endpoint = AZURE_AI_SERVICES_ENDPOINT.rstrip("/")
    sts_url = f"{endpoint}/sts/v1.0/issueToken"
    resp = _requests.post(
        sts_url,
        headers={"Authorization": f"Bearer {entra_token}"},
    )
    resp.raise_for_status()
    return resp.text


# ── Pipeline settings ────────────────────────────────────────────────
TARGET_DURATION_SECONDS = int(os.environ.get("TARGET_DURATION_SECONDS", "120"))
MAX_CONCURRENT_TRANSCRIPTIONS = int(os.environ.get("MAX_CONCURRENT_TRANSCRIPTIONS", "6"))
VIDEO_EXTENSIONS = {'.mp4', '.m4v', '.wmv', '.avi', '.mov'}
SUPPORTED_AUDIO_EXTENSIONS = {".mp4", ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".webm"}
