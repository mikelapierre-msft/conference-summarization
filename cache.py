"""Disk cache for transcriptions and slide text.

Cache layout (under <input_dir>/.cache/):
    slides/<file_hash>.json      — extracted slide text per PPTX
    transcripts/<file_hash>.json — transcription text per media file

Files are keyed by a SHA-256 hash of the source file so the cache
auto-invalidates when the source changes.
"""

import hashlib
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

_BUF_SIZE = 1 << 16  # 64 KiB read buffer


def _file_hash(path: str) -> str:
    """Return a hex SHA-256 digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_BUF_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def get_cache_dir(input_dir: str) -> str:
    """Return the cache root directory for a given input folder."""
    return os.path.join(input_dir, ".cache")


# ── Slide-text cache ─────────────────────────────────────────────────

def get_cached_slide_text(cache_dir: str, pptx_path: str) -> list[dict[str, str]] | None:
    """Return cached slide text list, or None if not cached."""
    fh = _file_hash(pptx_path)
    json_path = os.path.join(cache_dir, "slides", f"{fh}.json")
    if not os.path.isfile(json_path):
        return None
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_slide_text(
    cache_dir: str, pptx_path: str, slides: list[dict[str, str]]
) -> None:
    """Write slide text to the cache."""
    fh = _file_hash(pptx_path)
    out_dir = os.path.join(cache_dir, "slides")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, f"{fh}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(slides, f, ensure_ascii=False, indent=2)


# ── Transcription cache ──────────────────────────────────────────────

def get_cached_transcription(cache_dir: str, media_path: str) -> str | None:
    """Return cached transcript text, or None if not cached."""
    fh = _file_hash(media_path)
    json_path = os.path.join(cache_dir, "transcripts", f"{fh}.json")
    if not os.path.isfile(json_path):
        return None
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("transcript")


def save_transcription(cache_dir: str, media_path: str, transcript: str) -> None:
    """Write a transcript to the cache."""
    fh = _file_hash(media_path)
    out_dir = os.path.join(cache_dir, "transcripts")
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, f"{fh}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "source": os.path.basename(media_path),
            "transcript": transcript,
        }, f, ensure_ascii=False, indent=2)
