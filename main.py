#!/usr/bin/env python3
"""CLI orchestrator for the session news-report pipeline.

Ingests one or more PPTX files that make up a session, extracts the
embedded videos, transcribes them, synthesises cross-session themes
via an LLM, and produces a single ~2-minute news-style audio report
in English.

Usage:
    python main.py --input ./presentations/
    python main.py --input talk1.pptx talk2.pptx --session-name "My Session"
"""

import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
import time

from extractor import extract_videos, extract_title
from transcriber import transcribe_all
from synthesizer import synthesize_session
from producer import generate_audio

log = logging.getLogger(__name__)


def discover_pptx_files(input_paths: list[str]) -> list[str]:
    """Resolve input paths to a sorted list of PPTX files."""
    files: list[str] = []
    for path in input_paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith(".pptx") and not name.startswith("~"):
                    files.append(os.path.join(path, name))
        elif os.path.isfile(path):
            files.append(path)
        else:
            log.warning("Path does not exist, skipping: %s", path)
    return files


def process_session(
    pptx_paths: list[str],
    session_name: str | None,
    output_dir: str,
) -> str:
    """Run the full session report pipeline.

    Returns the path to the generated MP3.
    """
    work_dir = tempfile.mkdtemp(prefix="session_report_")
    log.info("Work directory: %s", work_dir)

    # ── Phase 1: Extract videos from all PPTX files ─────────────────
    log.info("Phase 1: Extracting videos from %d PPTX file(s) …", len(pptx_paths))
    t0 = time.time()
    all_video_paths: list[str] = []
    video_to_presentation: dict[str, str] = {}  # video temp_path -> presentation title
    for pptx_path in pptx_paths:
        title = extract_title(pptx_path)
        log.info("  Presentation: %s", title)
        videos = extract_videos(pptx_path, os.path.join(work_dir, "videos"))
        for v in videos:
            all_video_paths.append(v.temp_path)
            video_to_presentation[v.temp_path] = title
            log.info("    Extracted: %s (slide %d)", v.media_filename, v.slide_index)

    if not all_video_paths:
        log.error("No embedded videos found in any PPTX file — aborting")
        sys.exit(1)

    log.info("Extracted %d video(s) in %.1fs", len(all_video_paths), time.time() - t0)

    # If no session name was provided, derive one from the first presentation title
    if not session_name:
        titles = list(dict.fromkeys(video_to_presentation.values()))  # unique, ordered
        session_name = titles[0] if len(titles) == 1 else titles[0]

    # ── Phase 2: Transcribe ──────────────────────────────────────────
    log.info("Phase 2: Transcribing %d video(s) …", len(all_video_paths))
    t1 = time.time()
    transcripts = transcribe_all(all_video_paths)
    log.info("Transcription finished in %.1fs", time.time() - t1)

    # Tag each transcript with its source presentation title
    for t in transcripts:
        video_path = all_video_paths[t["order"]]
        t["presentation"] = video_to_presentation.get(video_path, "Unknown")

    nonempty = sum(1 for t in transcripts if t["transcript"])
    if nonempty == 0:
        log.error("All transcriptions failed or returned empty — aborting")
        sys.exit(1)

    # ── Phase 3: Synthesize script ───────────────────────────────────
    log.info("Phase 3: Synthesizing news script from %d transcript(s) …", nonempty)
    t2 = time.time()
    script = synthesize_session(transcripts, session_name)
    log.info("Script generation finished in %.1fs", time.time() - t2)

    # ── Phase 4: Produce audio ───────────────────────────────────────
    # Name output after the source PPTX file (if single file), otherwise use session name
    if len(pptx_paths) == 1:
        pptx_stem = os.path.splitext(os.path.basename(pptx_paths[0]))[0]
        safe_name = re.sub(r"[^\w\s-]", "", pptx_stem).strip().replace(" ", "_").lower()
    else:
        safe_name = re.sub(r"[^\w\s-]", "", session_name).strip().replace(" ", "_").lower()
    safe_name = safe_name or "session"
    output_file = os.path.join(output_dir, f"{safe_name}.mp3")
    os.makedirs(output_dir, exist_ok=True)

    log.info("Phase 4: Generating audio → %s", output_file)
    t3 = time.time()
    result_path = generate_audio(script, output_file)
    log.info("Audio production finished in %.1fs", time.time() - t3)

    # Cleanup
    try:
        shutil.rmtree(work_dir)
    except OSError:
        log.debug("Could not clean up work directory: %s", work_dir)

    return result_path


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Generate a ~2-minute news-style audio report from session "
            "PPTX files. Extracts embedded videos, transcribes them, "
            "synthesises themes, and produces a single MP3."
        ),
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        nargs="+",
        help="Path to a directory of PPTX files, or one or more PPTX file paths.",
    )
    parser.add_argument(
        "--session-name", "-s",
        default=None,
        help="Optional session name (used in the report intro; inferred from content if omitted).",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default="./output",
        help="Directory for the output MP3 (default: ./output).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    # Suppress noisy Azure SDK HTTP logging unless --verbose
    if not args.verbose:
        logging.getLogger("azure").setLevel(logging.WARNING)
        logging.getLogger("azure.core").setLevel(logging.WARNING)
        logging.getLogger("azure.identity").setLevel(logging.WARNING)

    pptx_files = discover_pptx_files(args.input)
    if not pptx_files:
        log.error("No PPTX files found in the provided input paths.")
        sys.exit(1)

    log.info("=" * 60)
    log.info("Session News Report Pipeline")
    log.info("  PPTX files : %d", len(pptx_files))
    for p in pptx_files:
        log.info("    • %s", os.path.basename(p))
    if args.session_name:
        log.info("  Session    : %s", args.session_name)
    log.info("  Output dir : %s", args.output_dir)
    log.info("=" * 60)

    start = time.time()
    all_outputs: list[str] = []

    # Process each PPTX independently — one report per file
    for pptx in pptx_files:
        log.info("-" * 60)
        log.info("Processing: %s", os.path.basename(pptx))
        log.info("-" * 60)
        try:
            output_path = process_session([pptx], args.session_name, args.output_dir)
            all_outputs.append(output_path)
        except Exception:
            log.exception("Failed to process %s", os.path.basename(pptx))

    elapsed = time.time() - start

    log.info("=" * 60)
    log.info("Done in %.1fs — generated %d report(s):", elapsed, len(all_outputs))
    for p in all_outputs:
        log.info("  %s", p)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
