#!/usr/bin/env python3
"""CLI orchestrator for the session news-report pipeline.

Ingests one or more PPTX files that make up a session, extracts the
embedded videos, transcribes them, synthesises cross-presentation themes
via an LLM, and produces a single ~2-minute news-style audio report
in English.  The output file is named after the input folder.

Usage:
    python main.py --input ./presentations/my-theme/
"""

import argparse
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import zipfile

from extractor import extract_videos, extract_title, extract_slide_text
from transcriber import transcribe_all
from synthesizer import synthesize_session
from producer import generate_audio
from cache import (
    get_cache_dir,
    get_cached_slide_text,
    save_slide_text,
    get_cached_transcription,
    save_transcription,
)

log = logging.getLogger(__name__)


def discover_pptx_files(input_paths: list[str]) -> list[str]:
    """Resolve input paths to a sorted list of PPTX/PPSX files."""
    files: list[str] = []
    for path in input_paths:
        if os.path.isdir(path):
            for name in sorted(os.listdir(path)):
                if name.lower().endswith((".pptx", ".ppsx")) and not name.startswith("~"):
                    files.append(os.path.join(path, name))
        elif os.path.isfile(path):
            files.append(path)
        else:
            log.warning("Path does not exist, skipping: %s", path)
    return files


def precheck_files(pptx_files: list[str]) -> tuple[list[str], list[str]]:
    """Verify each file can be opened as a ZIP archive.

    Returns (valid_files, failed_files).
    """
    valid: list[str] = []
    failed: list[str] = []
    for path in pptx_files:
        try:
            with zipfile.ZipFile(path, "r"):
                pass
            valid.append(path)
        except (zipfile.BadZipFile, Exception):
            failed.append(path)
    return valid, failed


def process_session(
    pptx_paths: list[str],
    track_name: str,
    output_dir: str,
    output_stem: str = "session",
    show_prompts: bool = False,
    cache_dir: str | None = None,
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
    presentation_slide_text: dict[str, list[dict]] = {}  # pptx filename -> slide text entries
    video_to_presentation: dict[str, str] = {}  # video temp_path -> presentation filename
    for pptx_path in pptx_paths:
        pptx_name = os.path.basename(pptx_path)
        pptx_stem = os.path.splitext(pptx_name)[0]
        title = extract_title(pptx_path)
        log.info("  Presentation: %s", title)
        videos = extract_videos(pptx_path, os.path.join(work_dir, "videos", pptx_stem))
        for v in videos:
            all_video_paths.append(v.temp_path)
            video_to_presentation[v.temp_path] = pptx_name
            log.info("    Extracted: %s (slide %d)", v.media_filename, v.slide_index)
        # Extract text from first 2 slides for the LLM (with cache)
        if cache_dir:
            cached_text = get_cached_slide_text(cache_dir, pptx_path)
        else:
            cached_text = None
        if cached_text is not None:
            presentation_slide_text[pptx_name] = cached_text
            log.info("    Using cached slide text (%d slides)", len(cached_text))
        else:
            slides = extract_slide_text(pptx_path)
            if cache_dir:
                save_slide_text(cache_dir, pptx_path, slides)
            presentation_slide_text[pptx_name] = slides
            log.info("    Extracted text from %d slide(s)", len(slides))

    if not all_video_paths:
        log.error("No embedded videos found in any PPTX file — aborting")
        sys.exit(1)

    log.info("Extracted %d video(s) in %.1fs", len(all_video_paths), time.time() - t0)

    # ── Phase 2: Transcribe ──────────────────────────────────────────
    log.info("Phase 2: Transcribing %d video(s) …", len(all_video_paths))
    t1 = time.time()

    # Check cache for each media file; only transcribe uncached ones
    cached_transcripts: dict[int, str] = {}  # order -> transcript
    paths_to_transcribe: list[tuple[int, str]] = []  # (original_index, path)
    for idx, vpath in enumerate(all_video_paths):
        if cache_dir:
            cached = get_cached_transcription(cache_dir, vpath)
        else:
            cached = None
        if cached is not None:
            cached_transcripts[idx] = cached
            log.info("  Using cached transcription for %s", os.path.basename(vpath))
        else:
            paths_to_transcribe.append((idx, vpath))

    # Transcribe only the uncached files
    if paths_to_transcribe:
        uncached_paths = [p for _, p in paths_to_transcribe]
        new_transcripts = transcribe_all(uncached_paths)
        # Map results back to original indices and save to cache
        for t_result, (orig_idx, vpath) in zip(
            sorted(new_transcripts, key=lambda r: r["order"]), paths_to_transcribe
        ):
            cached_transcripts[orig_idx] = t_result["transcript"]
            if cache_dir and t_result["transcript"]:
                save_transcription(cache_dir, vpath, t_result["transcript"])

    # Build the final transcripts list in original order
    transcripts = [
        {
            "file": os.path.basename(all_video_paths[idx]),
            "order": idx,
            "transcript": cached_transcripts.get(idx, ""),
        }
        for idx in range(len(all_video_paths))
    ]
    log.info("Transcription finished in %.1fs", time.time() - t1)

    # Tag each transcript with its source presentation filename
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
    script = synthesize_session(
        transcripts, track_name,
        slide_text_by_presentation=presentation_slide_text,
        show_prompts=show_prompts,
    )
    log.info("Script generation finished in %.1fs", time.time() - t2)

    # ── Phase 4: Produce audio ───────────────────────────────────────
    output_file = os.path.join(output_dir, f"{output_stem}.mp3")
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
            "Generate a ~2-minute news-style audio report from a theme "
            "folder of PPTX files. Extracts embedded videos, transcribes "
            "them, synthesises themes, and produces a single MP3 named "
            "after the folder."
        ),
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to a folder containing PPTX files for a theme.",
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
    parser.add_argument(
        "--show-prompts",
        action="store_true",
        help="Print the full LLM prompts to the console.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable caching of transcriptions and slide images.",
    )
    parser.add_argument(
        "--skip-broken",
        action="store_true",
        help="Skip files that cannot be opened instead of aborting.",
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

    input_dir = args.input
    if not os.path.isdir(input_dir):
        log.error("Input path is not a directory: %s", input_dir)
        sys.exit(1)

    pptx_files = discover_pptx_files([input_dir])
    if not pptx_files:
        log.error("No PPTX files found in %s", input_dir)
        sys.exit(1)

    # ── Pre-check: verify all files can be opened ────────────────────
    pptx_files, broken_files = precheck_files(pptx_files)
    if broken_files:
        log.error("The following file(s) cannot be opened (information protection might be enabled):")
        for f in broken_files:
            log.error("  ✗ %s", os.path.basename(f))
        if not args.skip_broken:
            log.error("Aborting. Use --skip-broken to process the remaining files.")
            sys.exit(1)
        log.warning("Skipping %d broken file(s) and continuing with %d valid file(s).",
                     len(broken_files), len(pptx_files))

    if not pptx_files:
        log.error("No valid PPTX files remaining after pre-check.")
        sys.exit(1)

    # Derive the output file stem from the folder name
    theme_name = os.path.basename(os.path.normpath(input_dir))
    safe_name = re.sub(r"[^\w\s-]", "", theme_name).strip().replace(" ", "_").lower()
    safe_name = safe_name or "theme"

    log.info("=" * 60)
    log.info("Theme News Report Pipeline")
    log.info("  Theme      : %s", theme_name)
    log.info("  PPTX files : %d", len(pptx_files))
    for p in pptx_files:
        log.info("    • %s", os.path.basename(p))
    log.info("  Output dir : %s", args.output_dir)
    log.info("  Output file: %s.mp3", safe_name)
    # Set up cache directory
    cache_dir = None if args.no_cache else get_cache_dir(input_dir)
    if cache_dir:
        log.info("  Cache dir  : %s", cache_dir)

    log.info("=" * 60)

    start = time.time()

    # Process all PPTX files in the folder together as one theme
    try:
        output_path = process_session(
            pptx_files,
            theme_name,
            args.output_dir,
            output_stem=safe_name,
            show_prompts=args.show_prompts,
            cache_dir=cache_dir,
        )
    except Exception:
        log.exception("Failed to process theme %s", theme_name)
        sys.exit(1)

    elapsed = time.time() - start

    log.info("=" * 60)
    log.info("Done in %.1fs — generated report:", elapsed)
    log.info("  %s", output_path)
    log.info("=" * 60)


if __name__ == "__main__":
    main()
