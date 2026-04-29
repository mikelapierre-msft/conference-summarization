"""Extract embedded videos from PPTX files.

PPTX is a ZIP archive. Videos live in ppt/media/ and are referenced
by relationship entries in ppt/slides/_rels/slideN.xml.rels.
"""

import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from config import VIDEO_EXTENSIONS

_NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass
class VideoInfo:
    slide_index: int
    rel_id: str
    media_filename: str
    temp_path: str
    content_type: str = ""
    extra_media: list = field(default_factory=list)


def _find_video_rels_on_slide(
    zf: zipfile.ZipFile, slide_name: str
) -> list[tuple[str, str]]:
    """Return (rId, media_target) pairs for video relationships on a slide."""
    rels_path = slide_name.replace("ppt/slides/", "ppt/slides/_rels/") + ".rels"
    if rels_path not in zf.namelist():
        return []

    tree = etree.fromstring(zf.read(rels_path))
    results = []
    for rel in tree.findall("rel:Relationship", _NS):
        rel_type = rel.get("Type", "")
        target = rel.get("Target", "")
        rid = rel.get("Id", "")
        if "video" in rel_type.lower() or "media" in rel_type.lower():
            # Target is relative, e.g. ../media/video1.mp4
            media_path = os.path.normpath(
                os.path.join(os.path.dirname(slide_name), target)
            ).replace("\\", "/")
            ext = os.path.splitext(media_path)[1].lower()
            if ext in VIDEO_EXTENSIONS:
                results.append((rid, media_path))
    return results


def extract_videos(pptx_path: str, work_dir: str | None = None) -> list[VideoInfo]:
    """Extract all embedded videos from a PPTX file.

    Returns a list of VideoInfo with videos written to work_dir.
    """
    if work_dir is None:
        work_dir = tempfile.mkdtemp(prefix="pptx_videos_")
    os.makedirs(work_dir, exist_ok=True)

    videos: list[VideoInfo] = []

    with zipfile.ZipFile(pptx_path, "r") as zf:
        # Enumerate slides
        slide_names = sorted(
            n for n in zf.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )

        seen_media: set[str] = set()

        for slide_idx, slide_name in enumerate(slide_names, start=1):
            rels = _find_video_rels_on_slide(zf, slide_name)
            for rel_id, media_path in rels:
                if media_path in seen_media:
                    continue
                seen_media.add(media_path)

                media_filename = os.path.basename(media_path)
                dest = os.path.join(work_dir, media_filename)
                with zf.open(media_path) as src, open(dest, "wb") as dst:
                    shutil.copyfileobj(src, dst)

                videos.append(
                    VideoInfo(
                        slide_index=slide_idx,
                        rel_id=rel_id,
                        media_filename=media_filename,
                        temp_path=dest,
                    )
                )

    return videos


def list_all_media(pptx_path: str) -> list[str]:
    """List all file paths inside ppt/media/ in a PPTX."""
    with zipfile.ZipFile(pptx_path, "r") as zf:
        return [n for n in zf.namelist() if n.startswith("ppt/media/")]


def extract_title(pptx_path: str) -> str:
    """Infer a presentation title from a PPTX file.

    Tries in order:
      1. dc:title from docProps/core.xml (document properties)
      2. First title-shaped placeholder on slide 1
      3. Filename stem as fallback
    """
    with zipfile.ZipFile(pptx_path, "r") as zf:
        # ── Try document properties ──────────────────────────────────
        if "docProps/core.xml" in zf.namelist():
            core = etree.fromstring(zf.read("docProps/core.xml"))
            dc_title = core.find("{http://purl.org/dc/elements/1.1/}title")
            if dc_title is not None and dc_title.text and dc_title.text.strip():
                return dc_title.text.strip()

        # ── Try first slide title placeholder ────────────────────────
        slide_names = sorted(
            n for n in zf.namelist()
            if n.startswith("ppt/slides/slide") and n.endswith(".xml")
        )
        if slide_names:
            slide = etree.fromstring(zf.read(slide_names[0]))
            # Look for <p:sp> with <p:ph type="title" or "ctrTitle">
            for sp in slide.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}sp"):
                for ph in sp.iter("{http://schemas.openxmlformats.org/presentationml/2006/main}ph"):
                    ph_type = ph.get("type", "")
                    if ph_type in ("title", "ctrTitle"):
                        # Collect all text runs in this shape
                        texts = [
                            r.text
                            for r in sp.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}r")
                            for t in [r.find("{http://schemas.openxmlformats.org/drawingml/2006/main}t")]
                            if t is not None and t.text
                        ]
                        # Actually get the <a:t> elements directly
                        texts = [
                            t.text
                            for t in sp.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t")
                            if t.text and t.text.strip()
                        ]
                        if texts:
                            return " ".join(t.strip() for t in texts)

    # ── Fallback to filename ─────────────────────────────────────────
    return Path(pptx_path).stem
