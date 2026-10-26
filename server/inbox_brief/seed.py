"""Load the sample mailbox and, when present, the committed demo episode."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from inbox_brief.config import demo_dir, fixtures_dir
from inbox_brief.db import get_settings
from inbox_brief.domain import HOSTS, ParsedMessage
from inbox_brief.ingest.parse import parse_path
from inbox_brief.settings import now_in
from inbox_brief.store import episode_count, list_messages, save_episode, upsert_messages

logger = logging.getLogger(__name__)


def sync_fixtures() -> None:
    """Insert any fixture the database does not already have, then rebuild chains."""
    settings = get_settings()
    folder = fixtures_dir()
    parsed = []
    if folder.exists():
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in {".eml", ".mbox"} and path.is_file():
                parsed.extend(parse_path(str(path), source="fixture"))
    if parsed:
        upsert_messages(_in_window(parsed, settings), settings)
    else:
        from inbox_brief.store import rebuild_chains

        rebuild_chains(settings)


def seed_if_empty() -> None:
    if episode_count() > 0:
        return
    settings = get_settings()
    folder = fixtures_dir()
    if folder.exists():
        parsed = []
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() in {".eml", ".mbox"} and path.is_file():
                parsed.extend(parse_path(str(path), source="fixture"))
        if parsed:
            upsert_messages(_in_window(parsed, settings), settings)
    loaded = _load_demo_episode()
    if not loaded:
        logger.info("Sample mailbox is loaded. No demo audio file was found.")


def place_in_review_window(messages: list[ParsedMessage], now: datetime) -> list[ParsedMessage]:
    """Slide the sample forward so its newest day is today.

    The fixtures are the week of 16 October 2026. Home only shows the last
    seven days, so a clone after that week would otherwise be empty.
    """
    dated = [(message, when) for message in messages if (when := _parse_date(message.date)) is not None]
    if not dated:
        return messages
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    newest = max(when for _, when in dated)
    # Compare calendar days in the viewer's zone, not the message's offset.
    delta_days = (now.date() - newest.astimezone(now.tzinfo).date()).days
    if delta_days == 0:
        return messages
    placed: list[ParsedMessage] = []
    for message in messages:
        when = _parse_date(message.date)
        if when is None:
            placed.append(message)
            continue
        placed.append(replace(message, date=(when + timedelta(days=delta_days)).isoformat()))
    return placed


def _in_window(messages: list[ParsedMessage], settings: dict) -> list[ParsedMessage]:
    return place_in_review_window(messages, now_in(settings.get("timezone") or "Europe/London"))


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _load_demo_episode() -> bool:
    folder = demo_dir()
    transcript = folder / "transcript-british.json"
    if not transcript.exists():
        transcript = folder / "transcript.json"
    if not transcript.exists():
        return False
    payload = json.loads(transcript.read_text(encoding="utf-8"))
    by_header = {item["message_id"]: item["id"] for item in list_messages() if item.get("message_id")}
    by_id = {item["id"]: item for item in list_messages()}
    segments = []
    for row in payload.get("segments", []):
        source_ids = []
        for header in row.get("source_message_ids") or []:
            matched = by_header.get(header)
            if matched:
                source_ids.append(matched)
        for source_id in row.get("source_ids") or []:
            if source_id in by_id and source_id not in source_ids:
                source_ids.append(source_id)
        if not source_ids:
            continue
        speaker = row.get("speaker") if row.get("speaker") in HOSTS else "S1"
        segments.append(
            {
                "speaker": speaker,
                "speaker_name": HOSTS[speaker],
                "text": row.get("text") or "",
                "delivery": row.get("delivery") or "steady",
                "nonverbal": row.get("nonverbal"),
                "exaggeration": row.get("exaggeration") or 0.3,
                "source_ids": source_ids,
                "start_ms": int(row.get("start_ms") or 0),
                "end_ms": int(row.get("end_ms") or 0),
            }
        )
    if not segments:
        return False
    audio_name = payload.get("audio_file") or ""
    audio_path = demo_dir() / audio_name if audio_name else None
    audio = audio_path.read_bytes() if audio_path and audio_path.exists() else None
    mime = "audio/mpeg" if audio_name.endswith(".mp3") else "audio/wav"
    save_episode(
        title=payload.get("title") or "Sample brief",
        brief_date=payload.get("brief_date") or "2026-10-16",
        status="ready" if audio else "empty",
        error=None if audio else "The sample script is ready, but the audio file is missing.",
        engine=payload.get("engine") or "kokoro",
        script_model=payload.get("script_model") or "extractive",
        script={
            "title": payload.get("title"),
            "notes": payload.get("notes") or [],
            "dia_prompt": payload.get("dia_prompt") or "",
            "engine_detail": payload.get("engine_detail") or "",
        },
        audio=audio,
        mime=mime if audio else None,
        segments=segments,
        is_sample=True,
    )
    return True


def demo_audio_path() -> Path:
    return demo_dir()
