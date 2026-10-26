"""Shared records for mail, scripts, and rendered episodes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Speaker = Literal["S1", "S2"]
Delivery = Literal["warm", "steady", "curious", "emphasis"]

HOSTS: dict[str, str] = {"S1": "Mina", "S2": "Owen"}


@dataclass
class ParsedMessage:
    id: str
    message_id: str
    from_name: str
    from_addr: str
    to_addr: str
    subject: str
    date: str
    clean_body: str
    raw_body: str
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)
    list_unsubscribe: str = ""
    precedence: str = ""
    auto_submitted: str = ""
    source: str = "upload"
    provider_thread_id: str = ""

    @property
    def sender_label(self) -> str:
        return self.from_name or self.from_addr or "Someone"


@dataclass
class SegmentDraft:
    speaker: Speaker
    text: str
    source_ids: list[str]
    delivery: Delivery = "steady"
    nonverbal: str | None = None
    exaggeration: float = 0.3

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "speaker_name": HOSTS[self.speaker],
            "text": self.text,
            "delivery": self.delivery,
            "nonverbal": self.nonverbal,
            "exaggeration": self.exaggeration,
            "source_ids": list(self.source_ids),
        }


@dataclass
class Script:
    title: str
    segments: list[SegmentDraft]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "segments": [segment.to_dict() for segment in self.segments],
            "notes": list(self.notes),
        }


@dataclass
class RenderResult:
    audio: bytes
    mime: str
    timings: list[tuple[int, int]]
    engine: str
    detail: str = ""
