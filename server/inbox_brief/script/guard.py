"""Remove claims the source emails do not support, and host judgement.

Emotion cues live on the segment, not in the spoken sentence, so a chuckle
is not treated as an opinion about the mail.
"""

from __future__ import annotations

import re

from inbox_brief.domain import ParsedMessage, Script, SegmentDraft, Speaker

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_TOKEN = re.compile(r"[a-z0-9']{3,}")

# Words that evaluate, advise, or guess. A sentence may keep one only when
# the same word is already in the source text.
_JUDGEMENT = {
    "advice",
    "advise",
    "amazing",
    "annoying",
    "apparently",
    "awful",
    "bad",
    "best",
    "better",
    "brilliant",
    "clearly",
    "concerning",
    "critical",
    "disappointing",
    "dumb",
    "excellent",
    "exciting",
    "failure",
    "failed",
    "fortunately",
    "frustrating",
    "glad",
    "good",
    "great",
    "happy",
    "hate",
    "hopefully",
    "important",
    "impressive",
    "interesting",
    "likely",
    "love",
    "luckily",
    "maybe",
    "must",
    "nice",
    "notable",
    "obviously",
    "optimal",
    "perfect",
    "perhaps",
    "poor",
    "probably",
    "problem",
    "recommend",
    "recommended",
    "ridiculous",
    "risky",
    "sad",
    "seems",
    "should",
    "shouldnt",
    "smart",
    "stupid",
    "suggest",
    "terrible",
    "unfortunate",
    "unfortunately",
    "unlikely",
    "urgent",
    "useful",
    "useless",
    "waste",
    "wonderful",
    "worry",
    "worried",
    "worse",
    "worst",
    "wrong",
}

_PHRASES = (
    "a bad idea",
    "a good idea",
    "i believe",
    "i recommend",
    "i think",
    "in my view",
    "it seems",
    "makes sense",
    "might want",
    "sounds like",
    "the best",
    "we should",
    "we think",
    "you might",
    "you should",
)

_STOP = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "before",
    "brief",
    "but",
    "for",
    "from",
    "have",
    "her",
    "his",
    "into",
    "mina",
    "not",
    "owen",
    "replied",
    "said",
    "she",
    "that",
    "the",
    "their",
    "there",
    "they",
    "this",
    "today",
    "was",
    "were",
    "with",
    "wrote",
    "you",
    "your",
}


def apply_guard(script: Script, messages: dict[str, ParsedMessage]) -> tuple[Script, list[str]]:
    notes: list[str] = []
    kept: list[SegmentDraft] = []
    for segment in script.segments:
        ids = [source_id for source_id in segment.source_ids if source_id in messages]
        if not ids:
            notes.append("Removed a line with no source email.")
            continue
        source_text = _source_text(ids, messages)
        sentences = _sentences(segment.text)
        surviving: list[str] = []
        for sentence in sentences:
            reason = _problem(sentence, source_text)
            if reason:
                notes.append(f"Removed “{sentence}” ({reason}).")
                continue
            surviving.append(sentence)
        if not surviving:
            notes.append("Removed a line that had no supported sentence left.")
            continue
        segment.text = " ".join(surviving).strip()
        segment.source_ids = ids
        segment.exaggeration = max(0.2, min(0.55, float(segment.exaggeration)))
        if segment.nonverbal:
            segment.nonverbal = segment.nonverbal.strip().lower()
        kept.append(segment)
    script.segments = repair_speakers(kept)
    script.notes.extend(notes)
    return script, notes


def repair_speakers(segments: list[SegmentDraft]) -> list[SegmentDraft]:
    """Dia has to hear [S1] and [S2] in turn, starting with S1."""
    if not segments:
        return segments
    if segments[0].speaker == "S2":
        for segment in segments:
            segment.speaker = "S1" if segment.speaker == "S2" else "S2"
    previous: Speaker | None = None
    for segment in segments:
        if segment.speaker == previous:
            segment.speaker = "S2" if previous == "S1" else "S1"
        previous = segment.speaker
    return segments


def _source_text(ids: list[str], messages: dict[str, ParsedMessage]) -> str:
    chunks = []
    for source_id in ids:
        message = messages[source_id]
        chunks.append(
            " ".join(
                [
                    message.from_name,
                    message.from_addr,
                    message.subject,
                    message.clean_body,
                ]
            )
        )
    return " ".join(chunks).lower()


def _sentences(text: str) -> list[str]:
    parts = _SENTENCE.split(text.strip())
    return [part.strip() for part in parts if part.strip()]


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text.lower()) if token not in _STOP}


def _problem(sentence: str, source_text: str) -> str | None:
    lowered = sentence.lower().replace("’", "'")
    source_tokens = _tokens(source_text)
    words = set(re.findall(r"[a-z']+", lowered))
    for word in words:
        bare = word.replace("'", "")
        if bare in _JUDGEMENT and bare not in source_tokens and word not in source_tokens:
            return f"judgement word {bare!r} is not in the source"
    for phrase in _PHRASES:
        if phrase in lowered and phrase not in source_text:
            return f"phrase {phrase!r} is not in the source"
    content = _tokens(sentence)
    if content and not (content & source_tokens):
        return "no overlap with the source email"
    return None
