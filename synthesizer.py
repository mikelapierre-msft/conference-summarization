"""Synthesise session transcripts into a news-style audio script using Azure OpenAI."""

import json
import logging

from openai import AzureOpenAI

from config import (
    AZURE_OPENAI_ENDPOINT,
    AZURE_OPENAI_DEPLOYMENT,
    TARGET_DURATION_SECONDS,
    openai_token_provider,
)

log = logging.getLogger(__name__)

# Rough estimate: 150 words ≈ 1 minute of spoken English
_WORDS_PER_MINUTE = 150

_client = AzureOpenAI(
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
    azure_ad_token_provider=openai_token_provider,
    api_version="2024-12-01-preview",
)

ANALYSIS_SYSTEM_PROMPT = """\
You are an expert conference analyst.  You will receive transcripts from
multiple presentations that together form ONE track at a technology
conference.  Each transcript is labelled with its presentation title
(inferred from the PowerPoint file).

You will also receive the text extracted from the first two slides of
each presentation.  Use this to identify session titles, speaker names,
affiliations, and any other useful context.

Your task:
1. Try to infer each speaker's name from the slide text and transcript
   content (e.g. title slides, self-introductions, being addressed by
   name).  If you cannot determine a speaker's name with confidence,
   set "inferred_speaker" to null.
2. Try to infer each presentation's title or topic from the transcript.
   If not apparent, summarise the topic in a few words.
3. Identify the 3-5 key CROSS-CUTTING themes that span the track as a
   whole (not per-presentation summaries).
4. Extract notable insights, data points, or memorable quotes.
5. Identify the overarching narrative or story of the track.

Respond with ONLY valid JSON matching this schema (no markdown fences):
{
  "track_topic": "...",
  "presentations": [
    {"order": 1, "title": "...", "inferred_speaker": "... or null if unknown"}
  ],
  "themes": [
    {"theme": "...", "description": "..."}
  ],
  "key_insights": ["..."],
  "notable_quotes": ["..."],
  "overall_narrative": "..."
}
"""

SCRIPT_SYSTEM_PROMPT = """\
You are a professional news anchor writing a script for a short podcast
segment.  You will receive a structured analysis of a conference track.

Write a cohesive, engaging script of approximately {word_count} words
(~{duration_minutes} minutes when read aloud at a natural pace).

Rules:
- Write in English.
- Use a professional, energetic news-anchor tone.
- Open with a compelling hook that draws the listener in.
- Early in the script, mention the total number of presentations in the
  track (e.g. "across five presentations …").
- Mention and briefly summarize EVERY presentation in the track — make
  sure no presentation is left out.
- If a speaker's name is known, attribute the presentation to them by name.
  If the speaker's name is unknown, refer to it as "a session about <topic>"
  or similar phrasing — do NOT invent or guess names.
- Weave the individual presentations into a cohesive narrative arc,
  connecting them through cross-cutting themes and insights.
- You may highlight memorable quotes or data points when impactful.
- Close with a forward-looking takeaway or call to reflection.
- Do NOT include stage directions, sound effects, or formatting cues.
- Output ONLY the script text, ready to be read aloud.
"""


def _build_user_content(
    transcripts: list[dict],
    track_name: str | None,
    slide_text_by_presentation: dict[str, list[dict]] | None,
) -> str:
    """Build a plain-text user prompt grouped by session.

    Each session block contains:
      - A text header with the session number and file name
      - Text from the cover slides
      - Transcriptions labelled by slide/video order
    """
    parts: list[str] = []
    if track_name:
        parts.append(f"Track name: {track_name}\n")

    slide_text_map = slide_text_by_presentation or {}

    # Group transcripts by presentation filename, preserving order
    from collections import OrderedDict
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for t in transcripts:
        pres = t.get("presentation", t["file"])
        grouped.setdefault(pres, []).append(t)

    for idx, (pres_name, pres_transcripts) in enumerate(grouped.items(), start=1):
        parts.append(f"\nSession #{idx} file name: {pres_name}")

        # Cover slide text
        slides = slide_text_map.get(pres_name, [])
        for s in slides:
            parts.append(f"--- Cover slide {s['slide']} text: {s['text']}")

        # Transcriptions
        for slide_num, t in enumerate(pres_transcripts, start=1):
            if not t["transcript"]:
                continue
            parts.append(f"--- Slide {slide_num} transcription: {t['transcript']}")

    return "\n".join(parts)


def synthesize_session(
    transcripts: list[dict],
    track_name: str | None = None,
    slide_text_by_presentation: dict[str, list[dict]] | None = None,
    show_prompts: bool = False,
) -> str:
    """Analyse all session transcripts and generate a news-style script.

    Makes two LLM calls:
      1. Analyse transcripts (+ slide images) → structured JSON summary
      2. Generate spoken script from the summary

    Returns the final script as plain text.
    """
    nonempty = [t for t in transcripts if t["transcript"]]
    if not nonempty:
        raise ValueError("No non-empty transcripts to synthesize")

    log.info("Synthesizing %d transcript(s) into a session report", len(nonempty))

    # ── Call 1: Analysis ─────────────────────────────────────────────
    user_prompt = _build_user_content(
        transcripts, track_name=track_name, slide_text_by_presentation=slide_text_by_presentation,
    )

    if show_prompts:
        print("\n" + "=" * 60)
        print("LLM CALL 1/2 — ANALYSIS PROMPT")
        print("=" * 60)
        print(f"SYSTEM:\n{ANALYSIS_SYSTEM_PROMPT}")
        print("-" * 60)
        print(f"USER:\n{user_prompt}")
        print("=" * 60 + "\n")

    log.info("LLM call 1/2: Analysing transcripts …")
    analysis_resp = _client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        max_completion_tokens=4096,
    )
    analysis_text = analysis_resp.choices[0].message.content.strip()
    log.debug("Analysis response:\n%s", analysis_text)

    # Validate JSON
    try:
        analysis = json.loads(analysis_text)
    except json.JSONDecodeError:
        log.warning("Analysis response is not valid JSON — using raw text for script generation")
        analysis = {"raw_analysis": analysis_text}

    # ── Call 2: Script generation ────────────────────────────────────
    target_minutes = TARGET_DURATION_SECONDS / 60
    target_words = int(target_minutes * _WORDS_PER_MINUTE)

    script_system = SCRIPT_SYSTEM_PROMPT.format(
        word_count=target_words,
        duration_minutes=f"{target_minutes:.1f}",
    )

    if show_prompts:
        print("\n" + "=" * 60)
        print("LLM CALL 2/2 — SCRIPT PROMPT")
        print("=" * 60)
        print(f"SYSTEM:\n{script_system}")
        print("-" * 60)
        print(f"USER:\n{json.dumps(analysis, indent=2)}")
        print("=" * 60 + "\n")

    log.info("LLM call 2/2: Generating ~%d-word news script …", target_words)
    script_resp = _client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": script_system},
            {"role": "user", "content": json.dumps(analysis, indent=2)},
        ],
        max_completion_tokens=4096,
    )
    script = script_resp.choices[0].message.content.strip()
    word_count = len(script.split())
    log.info("Script generated: %d words (target: %d)", word_count, target_words)

    return script
