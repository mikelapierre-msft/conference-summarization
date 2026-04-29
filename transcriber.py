"""Transcribe audio/video recordings using the fast transcription API (azure-ai-transcription SDK)."""

import logging
import os
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionContent, TranscriptionOptions

from config import AZURE_AI_SERVICES_ENDPOINT, _credential, MAX_CONCURRENT_TRANSCRIPTIONS

log = logging.getLogger(__name__)

# Fast transcription supports these formats; video containers need ffmpeg conversion
_NATIVE_FORMATS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".webm"}

_client = TranscriptionClient(
    endpoint=AZURE_AI_SERVICES_ENDPOINT,
    credential=_credential,
)


def _extract_audio(video_path: str) -> str:
    """Extract audio from a video file to a temporary WAV using ffmpeg."""
    wav_path = os.path.join(
        tempfile.gettempdir(),
        Path(video_path).stem + f"_{os.getpid()}.wav",
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        wav_path,
    ]
    log.debug("Extracting audio: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {video_path}: {result.stderr.strip()}")
    return wav_path


def transcribe_file(file_path: str) -> str:
    """Transcribe a single audio/video file using the fast transcription API.

    Routes through the AI Services endpoint where MAI-Transcribe-1 is deployed.
    Returns the full transcript as a string.
    """
    log.info("Transcribing: %s", os.path.basename(file_path))

    ext = os.path.splitext(file_path)[1].lower()
    temp_file = None
    if ext not in _NATIVE_FORMATS:
        temp_file = _extract_audio(file_path)
        audio_path = temp_file
    else:
        audio_path = file_path

    try:
        with open(audio_path, "rb") as audio_file:
            options = TranscriptionOptions(locales=["en-US"])
            content = TranscriptionContent(definition=options, audio=audio_file)
            result = _client.transcribe(content)

        transcript = result.combined_phrases[0].text if result.combined_phrases else ""
        log.info("Transcribed %s: %d characters", os.path.basename(file_path), len(transcript))
        return transcript

    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except PermissionError:
                log.debug("Could not delete temp file: %s", temp_file)


def transcribe_all(file_paths: list[str]) -> list[dict]:
    """Transcribe multiple recordings in parallel.

    Returns a list of dicts sorted by input order:
        [{"file": str, "order": int, "transcript": str}, ...]
    Files that fail transcription are included with an empty transcript.
    """
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TRANSCRIPTIONS) as executor:
        futures = {
            executor.submit(transcribe_file, path): idx
            for idx, path in enumerate(file_paths)
        }
        for future in as_completed(futures):
            idx = futures[future]
            path = file_paths[idx]
            try:
                transcript = future.result()
            except Exception:
                log.exception("Failed to transcribe %s — skipping", path)
                transcript = ""
            results.append({
                "file": os.path.basename(path),
                "order": idx,
                "transcript": transcript,
            })

    results.sort(key=lambda r: r["order"])
    successful = sum(1 for r in results if r["transcript"])
    log.info("Transcription complete: %d/%d succeeded", successful, len(results))
    return results
