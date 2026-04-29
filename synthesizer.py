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
multiple presentations that together form ONE session at a technology
conference.  Each transcript is labelled with its presentation title
(inferred from the PowerPoint file).

Your task:
1. Infer each speaker's name from the content of their presentation
   (do NOT ask for metadata — figure it out).
2. Identify the 3-5 key CROSS-CUTTING themes that span the session as a
   whole (not per-presentation summaries).
3. Extract notable insights, data points, or memorable quotes.
4. Identify the overarching narrative or story of the session.

Respond with ONLY valid JSON matching this schema (no markdown fences):
{
  "session_topic": "...",
  "presentations": [
    {"order": 1, "title": "...", "inferred_speaker": "..."}
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
segment.  You will receive a structured analysis of a conference session.

Write a cohesive, engaging script of approximately {word_count} words
(~{duration_minutes} minutes when read aloud at a natural pace).

Rules:
- Write in English.
- Use a professional, energetic news-anchor tone.
- Open with a compelling hook that draws the listener in.
- Cover the session as ONE story — do NOT list presentations one-by-one.
- Weave themes and insights into a narrative arc.
- You may attribute quotes or insights to speakers by name when impactful.
- Close with a forward-looking takeaway or call to reflection.
- Do NOT include stage directions, sound effects, or formatting cues.
- Output ONLY the script text, ready to be read aloud.
"""


def _build_transcript_prompt(transcripts: list[dict], session_name: str | None) -> str:
    """Format transcripts into a single user prompt for analysis."""
    parts = []
    if session_name:
        parts.append(f"Session name: {session_name}\n")
    for t in transcripts:
        if not t["transcript"]:
            continue
        presentation = t.get("presentation", t["file"])
        parts.append(f"--- Presentation {t['order'] + 1}: {presentation} ---")
        parts.append(t["transcript"])
        parts.append("")
    return "\n".join(parts)


def synthesize_session(transcripts: list[dict], session_name: str | None = None) -> str:
    """Analyse all session transcripts and generate a news-style script.

    Makes two LLM calls:
      1. Analyse transcripts → structured JSON summary
      2. Generate spoken script from the summary

    Returns the final script as plain text.
    """
    nonempty = [t for t in transcripts if t["transcript"]]
    if not nonempty:
        raise ValueError("No non-empty transcripts to synthesize")

    log.info("Synthesizing %d transcript(s) into a session report", len(nonempty))

    # ── Call 1: Analysis ─────────────────────────────────────────────
    transcript_prompt = _build_transcript_prompt(transcripts, session_name)

    log.info("LLM call 1/2: Analysing transcripts …")
    analysis_resp = _client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": transcript_prompt},
        ],
        temperature=0.3,
        max_tokens=4096,
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

    log.info("LLM call 2/2: Generating ~%d-word news script …", target_words)
    script_resp = _client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=[
            {"role": "system", "content": script_system},
            {"role": "user", "content": json.dumps(analysis, indent=2)},
        ],
        temperature=0.7,
        max_tokens=4096,
    )
    script = script_resp.choices[0].message.content.strip()
    word_count = len(script.split())
    log.info("Script generated: %d words (target: %d)", word_count, target_words)

    return script
