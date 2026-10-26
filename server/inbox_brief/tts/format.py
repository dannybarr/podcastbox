"""Turn a neutral script into the cues each engine actually understands."""

from __future__ import annotations

import re

from inbox_brief.domain import SegmentDraft

# Tags Dia-1.6B documents. Unlisted tags are omitted so they are not spoken
# as the word "laughs" or turned into noise.
DIA_NONVERBALS = {
    "laughs",
    "chuckle",
    "sighs",
    "gasps",
    "coughs",
    "inhales",
    "exhales",
    "clears throat",
    "mumbles",
}

# Chatterbox Turbo's documented paralinguistic tags. Exaggeration is a
# separate float on the original Chatterbox model, not on Turbo.
CHATTERBOX_TAGS = {
    "laughs": "[laugh]",
    "chuckle": "[chuckle]",
    "sighs": "[sigh]",
    "coughs": "[cough]",
}

_TAG_CHARS = re.compile(r"\s+")


def plain_text(segment: SegmentDraft) -> str:
    return _TAG_CHARS.sub(" ", segment.text).strip()


def format_dia(segments: list[SegmentDraft]) -> str:
    parts: list[str] = []
    for segment in segments:
        nonverbal = (segment.nonverbal or "").strip().lower()
        cue = f" ({nonverbal})" if nonverbal in DIA_NONVERBALS else ""
        parts.append(f"[{segment.speaker}]{cue} {plain_text(segment)}")
    text = " ".join(parts)
    if not segments:
        return text
    anchor = segments[-2].speaker if len(segments) >= 2 else segments[0].speaker
    return f"{text} [{anchor}]"


def dia_chunks(segments: list[SegmentDraft], *, max_chars: int = 420) -> list[list[SegmentDraft]]:
    """Keep each Dia call to about one exchange.

    Dia sounds rushed past roughly twenty seconds, and it wants the turn
    order to start on S1. Pairs preserve that.
    """
    chunks: list[list[SegmentDraft]] = []
    current: list[SegmentDraft] = []
    for segment in segments:
        prospective = current + [segment]
        too_long = len(format_dia(prospective)) > max_chars
        too_many = len(prospective) > 2
        starts_wrong = current and segment.speaker == "S1" and current[-1].speaker == "S2"
        if current and (too_long or too_many or starts_wrong):
            chunks.append(current)
            current = [segment]
        else:
            current = prospective
    if current:
        chunks.append(current)
    return chunks


def format_chatterbox(segment: SegmentDraft) -> tuple[str, float]:
    nonverbal = (segment.nonverbal or "").strip().lower()
    tag = CHATTERBOX_TAGS.get(nonverbal, "")
    text = plain_text(segment)
    if tag:
        text = f"{tag} {text}"
    exaggeration = max(0.25, min(0.7, float(segment.exaggeration)))
    return text, exaggeration


def kokoro_speed(segment: SegmentDraft) -> float:
    return {"warm": 1.0, "steady": 1.0, "curious": 1.02, "emphasis": 0.94}.get(segment.delivery, 1.0)
