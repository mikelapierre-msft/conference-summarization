"""Produce an MP3 audio file from a script using Azure Speech TTS REST API."""

import logging
import os
import re

import requests

from config import (
    AZURE_SPEECH_REGION,
    TTS_VOICE,
    TTS_STYLE,
    TARGET_DURATION_SECONDS,
    get_tts_authorization_token,
)

log = logging.getLogger(__name__)


def _script_to_ssml(script: str, voice: str, style: str) -> str:
    """Wrap a plain-text script in SSML with configurable voice and style.

    Inserts short pauses between paragraphs.  If *style* is set (e.g.
    'newscast-formal', 'cheerful'), wraps content in <mstts:express-as>.
    """
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", script) if p.strip()]
    body_parts = []
    for para in paragraphs:
        escaped = (
            para.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
        )
        body_parts.append(f"        <p>{escaped}</p>")
        body_parts.append('        <break time="600ms"/>')

    if body_parts and body_parts[-1].startswith("        <break"):
        body_parts.pop()

    body = "\n".join(body_parts)

    # Wrap in style if specified
    if style:
        inner = (
            f'      <mstts:express-as style="{style}">\n'
            f"{body}\n"
            "      </mstts:express-as>"
        )
    else:
        inner = body

    return (
        '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" '
        'xmlns:mstts="https://www.w3.org/2001/mstts" xml:lang="en-US">\n'
        f'  <voice name="{voice}">\n'
        f"{inner}\n"
        "  </voice>\n"
        "</speak>"
    )


def generate_audio(script: str, output_path: str) -> str:
    """Synthesize *script* to an MP3 file at *output_path* via TTS REST API.

    Calls the AI Services TTS endpoint directly so it routes through the
    same AIServices resource where MAI-Voice-1 is deployed.

    Returns the absolute path to the generated file.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    ssml = _script_to_ssml(script, TTS_VOICE, TTS_STYLE)
    log.debug("SSML:\n%s", ssml)
    log.info("Synthesizing audio with voice=%s style=%s …", TTS_VOICE, TTS_STYLE or "(default)")

    # TTS REST API via regional endpoint with STS authorization token
    tts_url = (
        f"https://{AZURE_SPEECH_REGION}.tts.speech.microsoft.com"
        "/cognitiveservices/v1"
    )

    token = get_tts_authorization_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-16khz-128kbitrate-mono-mp3",
        "User-Agent": "producer",
    }

    resp = requests.post(tts_url, headers=headers, data=ssml.encode("utf-8"))
    resp.raise_for_status()

    with open(output_path, "wb") as f:
        f.write(resp.content)

    # Estimate duration from file size (128 kbps MP3)
    size_bytes = os.path.getsize(output_path)
    duration_s = size_bytes * 8 / (128 * 1000)
    log.info("Audio generated: %s (~%.1fs)", output_path, duration_s)

    lo = TARGET_DURATION_SECONDS - 30
    hi = TARGET_DURATION_SECONDS + 30
    if not (lo <= duration_s <= hi):
        log.warning(
            "Estimated audio duration %.1fs is outside target range %d–%ds. "
            "Consider adjusting TARGET_DURATION_SECONDS=%d.",
            duration_s, lo, hi, TARGET_DURATION_SECONDS,
        )

    return os.path.abspath(output_path)
