"""Read and write mail, episodes, and jobs."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from inbox_brief.config import data_dir
from inbox_brief.db import connect, utc_now
from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.noise import noise_reason
from inbox_brief.ingest.thread import thread_messages


def upsert_messages(messages: list[ParsedMessage], settings: dict) -> dict[str, int]:
    inserted = 0
    duplicate = 0
    with connect() as connection:
        for message in messages:
            if message.message_id:
                existing = connection.execute(
                    "SELECT id FROM messages WHERE message_id = ?",
                    (message.message_id,),
                ).fetchone()
            else:
                existing = connection.execute(
                    "SELECT id FROM messages WHERE id = ?",
                    (message.id,),
                ).fetchone()
            if existing:
                duplicate += 1
                continue
            reason = noise_reason(
                message,
                drop_newsletters=settings["drop_newsletters"],
                drop_noreply=settings["drop_noreply"],
                extra_patterns=settings["extra_noise_patterns"],
            )
            connection.execute(
                """
                INSERT INTO messages (
                    id, message_id, thread_id, from_name, from_addr, to_addr, subject,
                    date, clean_body, raw_body, source, is_noise, noise_reason,
                    in_reply_to, references_json, list_unsubscribe, precedence, auto_submitted,
                    provider_thread_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.message_id,
                    None,
                    message.from_name,
                    message.from_addr,
                    message.to_addr,
                    message.subject,
                    message.date,
                    message.clean_body,
                    message.raw_body,
                    message.source,
                    1 if reason else 0,
                    reason,
                    message.in_reply_to,
                    json.dumps(message.references),
                    message.list_unsubscribe,
                    message.precedence,
                    message.auto_submitted,
                    message.provider_thread_id,
                ),
            )
            inserted += 1
    rethread()
    reclassify(settings)
    rebuild_chains(settings)
    return {"inserted": inserted, "duplicate": duplicate}


def reclassify(settings: dict) -> None:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM messages").fetchall()
        for row in rows:
            reason = noise_reason(
                _row_to_message(row),
                drop_newsletters=settings["drop_newsletters"],
                drop_noreply=settings["drop_noreply"],
                extra_patterns=settings["extra_noise_patterns"],
            )
            connection.execute(
                "UPDATE messages SET is_noise = ?, noise_reason = ? WHERE id = ?",
                (1 if reason else 0, reason, row["id"]),
            )


def rethread() -> None:
    with connect() as connection:
        rows = connection.execute("SELECT * FROM messages").fetchall()
        messages = [_row_to_message(row) for row in rows]
        threads = thread_messages(messages)
        for thread_id, members in threads.items():
            for member in members:
                connection.execute(
                    "UPDATE messages SET thread_id = ? WHERE id = ?",
                    (thread_id, member.id),
                )


def list_messages(include_noise: bool = True) -> list[dict]:
    query = "SELECT * FROM messages ORDER BY date DESC, id"
    with connect() as connection:
        rows = connection.execute(query).fetchall()
    items = [_public_message(row) for row in rows]
    if not include_noise:
        items = [item for item in items if not item["is_noise"]]
    return items


def get_message(message_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
    return _public_message(row, full=True) if row else None


def messages_for_brief(settings: dict, scope: str) -> list[ParsedMessage]:
    reclassify(settings)
    with connect() as connection:
        rows = connection.execute("SELECT * FROM messages ORDER BY date, id").fetchall()
    messages = []
    for row in rows:
        if row["is_noise"]:
            continue
        if not (row["clean_body"] or "").strip():
            continue
        if scope == "window" and not _in_window(row["date"], settings):
            continue
        messages.append(_row_to_message(row))
    return messages


def message_map(ids: list[str] | None = None) -> dict[str, ParsedMessage]:
    with connect() as connection:
        if ids:
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"SELECT * FROM messages WHERE id IN ({placeholders})",
                ids,
            ).fetchall()
        else:
            rows = connection.execute("SELECT * FROM messages").fetchall()
    return {row["id"]: _row_to_message(row) for row in rows}


def create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO jobs (id, kind, status, error, episode_id, created_at, updated_at)
            VALUES (?, ?, 'running', NULL, NULL, ?, ?)
            """,
            (job_id, kind, utc_now(), utc_now()),
        )
    return job_id


def active_job() -> dict | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM jobs WHERE status = 'running' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def finish_job(job_id: str, *, status: str, error: str | None = None, episode_id: str | None = None) -> None:
    with connect() as connection:
        connection.execute(
            """
            UPDATE jobs SET status = ?, error = ?, episode_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, error, episode_id, utc_now(), job_id),
        )


def get_job(job_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return dict(row) if row else None


def save_episode(
    *,
    title: str,
    brief_date: str,
    status: str,
    error: str | None,
    engine: str | None,
    script_model: str | None,
    script: dict | None,
    audio: bytes | None,
    mime: str | None,
    segments: list[dict],
    is_sample: bool = False,
    chain_id: str | None = None,
    question: str | None = None,
    style: str | None = None,
    length: str | None = None,
    covered_ids: list[str] | None = None,
    covered_through: str | None = None,
    created_at: str | None = None,
) -> str:
    episode_id = uuid.uuid4().hex[:12]
    audio_path = None
    if audio and mime:
        extension = "mp3" if mime == "audio/mpeg" else "wav"
        directory = data_dir() / "audio"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{episode_id}.{extension}"
        path.write_bytes(audio)
        audio_path = str(path)
    duration = 0
    if segments:
        duration = max(int(segment.get("end_ms") or 0) for segment in segments)
    with connect() as connection:
        connection.execute(
            """
            INSERT INTO episodes (
                id, title, brief_date, status, error, engine, script_model, script_json,
                audio_path, audio_mime, duration_ms, created_at, is_sample,
                chain_id, question, style, length, deleted_at, covered_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                episode_id,
                title,
                brief_date,
                status,
                error,
                engine,
                script_model,
                json.dumps(script) if script else None,
                audio_path,
                mime,
                duration,
                created_at or utc_now(),
                1 if is_sample else 0,
                chain_id,
                question,
                style,
                length,
                json.dumps({"message_ids": list(covered_ids or []), "through": covered_through or ""}),
            ),
        )
        for position, segment in enumerate(segments):
            connection.execute(
                """
                INSERT INTO segments (
                    id, episode_id, position, speaker, speaker_name, text, delivery,
                    nonverbal, exaggeration, source_ids, start_ms, end_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex[:12],
                    episode_id,
                    position,
                    segment.get("speaker"),
                    segment.get("speaker_name"),
                    segment.get("text"),
                    segment.get("delivery"),
                    segment.get("nonverbal"),
                    segment.get("exaggeration"),
                    json.dumps(segment.get("source_ids") or []),
                    segment.get("start_ms"),
                    segment.get("end_ms"),
                ),
            )
    return episode_id


def coverage_records() -> list[dict]:
    """Message ids already read in a podcast that has not been deleted."""
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, chain_id, covered_json FROM episodes WHERE deleted_at IS NULL"
        ).fetchall()
        segments = connection.execute("SELECT episode_id, source_ids FROM segments").fetchall()
    spoken: dict[str, set[str]] = {}
    for segment in segments:
        spoken.setdefault(segment["episode_id"], set()).update(json.loads(segment["source_ids"] or "[]"))
    records = []
    for row in rows:
        if row["chain_id"] == "overview":
            continue
        payload = json.loads(row["covered_json"]) if row["covered_json"] else {}
        if not isinstance(payload, dict):
            payload = {}
        ids = set(payload.get("message_ids") or [])
        ids.update(spoken.get(row["id"], set()))
        records.append(
            {
                "chain_id": row["chain_id"],
                "message_ids": sorted(ids),
                "through": payload.get("through") or "",
            }
        )
    return records


def podcast_index(settings: dict) -> dict:
    from inbox_brief.days import bucket_podcasts

    full = []
    for item in list_episodes():
        episode = get_episode(item["id"])
        if episode:
            full.append(episode)
    buckets = bucket_podcasts(full, settings.get("timezone") or "Europe/London")
    return {
        "podcasts": list_episodes(),
        "today": buckets["today"],
        "library": buckets["library"],
        "timezone": buckets["timezone"],
    }


def annotated_chains(settings: dict) -> list[dict]:
    from inbox_brief.days import annotate_chain

    dates = _message_dates()
    records = coverage_records()
    zone = settings.get("timezone") or "Europe/London"
    return [annotate_chain(chain, records, dates, zone) for chain in list_chains()]


def home_chains(settings: dict, query: str) -> list[dict]:
    from inbox_brief.curate import ask_chains

    annotated = annotated_chains(settings)
    if (query or "").strip():
        return ask_chains(annotated, query)
    return [
        chain
        for chain in annotated
        if chain["recommended"]
        and (
            not chain["covered"]
            or set(chain.get("covered_ids") or []) != set(chain.get("message_ids") or [])
            or chain["new_count"] > 0
        )
    ]


def inbox_chains(settings: dict, query: str) -> list[dict]:
    annotated = annotated_chains(settings)
    text = (query or "").strip().lower()
    if not text:
        return annotated
    tokens = [token for token in text.split() if token]
    return [
        chain
        for chain in annotated
        if all(token in (chain.get("search_text") or "").lower() for token in tokens)
    ]


def overview_records() -> list[dict]:
    """Covered message ids for overview episodes that have not been deleted."""
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, covered_json FROM episodes
            WHERE deleted_at IS NULL AND chain_id = 'overview' AND status = 'ready'
            ORDER BY created_at DESC
            """
        ).fetchall()
    records = []
    for row in rows:
        payload = json.loads(row["covered_json"]) if row["covered_json"] else {}
        if not isinstance(payload, dict):
            payload = {}
        records.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "message_ids": list(payload.get("message_ids") or []),
            }
        )
    return records


def _message_dates() -> dict[str, str]:
    with connect() as connection:
        rows = connection.execute("SELECT id, date FROM messages").fetchall()
    return {row["id"]: row["date"] or "" for row in rows}


def list_episodes() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM episodes WHERE deleted_at IS NULL ORDER BY created_at DESC"
        ).fetchall()
    return [_public_episode(row) for row in rows]


def latest_episode() -> dict | None:
    episodes = list_episodes()
    ready = [episode for episode in episodes if episode["status"] == "ready"]
    return ready[0] if ready else (episodes[0] if episodes else None)


def get_episode(episode_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM episodes WHERE id = ?", (episode_id,)).fetchone()
        if row is None:
            return None
        segments = connection.execute(
            "SELECT * FROM segments WHERE episode_id = ? ORDER BY position",
            (episode_id,),
        ).fetchall()
    episode = _public_episode(row)
    episode["segments"] = [_public_segment(segment) for segment in segments]
    script = json.loads(row["script_json"]) if row["script_json"] else {}
    episode["notes"] = script.get("notes", [])
    return episode


def episode_audio(episode_id: str) -> tuple[bytes, str] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT audio_path, audio_mime FROM episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
    if row is None or not row["audio_path"]:
        return None
    path = Path(row["audio_path"])
    if not path.exists():
        return None
    return path.read_bytes(), row["audio_mime"] or "audio/wav"


def delete_episode(episode_id: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE episodes SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
            (utc_now(), episode_id),
        )
    return cursor.rowcount > 0


def restore_episode(episode_id: str) -> bool:
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE episodes SET deleted_at = NULL WHERE id = ?",
            (episode_id,),
        )
    return cursor.rowcount > 0


def rebuild_chains(settings: dict, *, use_model: bool = False) -> list[dict]:
    from inbox_brief.curate import build_chains, chain_to_row, period_start, suggest_links
    from inbox_brief.settings import now_in

    with connect() as connection:
        rows = connection.execute("SELECT * FROM messages").fetchall()
    messages = [_row_to_message(row) for row in rows]
    now = now_in(settings["timezone"])
    chains = build_chains(
        messages,
        now=now,
        period=settings.get("review_period") or "week",
        drop_newsletters=bool(settings.get("drop_newsletters", True)),
        drop_noreply=bool(settings.get("drop_noreply", True)),
        extra_patterns=settings.get("extra_noise_patterns") or [],
        linker=(lambda threads: suggest_links(threads, settings)) if use_model else None,
    )
    period_key = period_start(now, settings.get("review_period") or "week").date().isoformat()
    with connect() as connection:
        connection.execute("DELETE FROM chains")
        for chain in chains:
            connection.execute(
                """
                INSERT INTO chains (
                    id, title, reason, recommended, participants_json, message_ids_json,
                    message_count, date_start, date_end, project, period_key, search_text, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*chain_to_row(chain, period_key), utc_now()),
            )
    return chains


def list_chains() -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM chains ORDER BY recommended DESC, date_end DESC"
        ).fetchall()
    return [_public_chain(row) for row in rows]


def get_chain(chain_id: str) -> dict | None:
    with connect() as connection:
        row = connection.execute("SELECT * FROM chains WHERE id = ?", (chain_id,)).fetchone()
    return _public_chain(row) if row else None


def chain_messages(chain_id: str) -> list[ParsedMessage]:
    chain = get_chain(chain_id)
    if chain is None:
        return []
    found = message_map(chain["message_ids"])
    return [found[item] for item in chain["message_ids"] if item in found]


def episode_count() -> int:
    with connect() as connection:
        row = connection.execute("SELECT COUNT(*) AS n FROM episodes").fetchone()
    return int(row["n"])


def get_schedule_date() -> str | None:
    with connect() as connection:
        row = connection.execute("SELECT last_date FROM schedule_state WHERE id = 1").fetchone()
    return row["last_date"] if row else None


def set_schedule_date(value: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE schedule_state SET last_date = ? WHERE id = 1", (value,))


def _in_window(value: str | None, settings: dict) -> bool:
    if not value:
        return False
    from datetime import datetime, timedelta, timezone

    from inbox_brief.settings import now_in

    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    current = now_in(settings["timezone"])
    return when >= current - timedelta(hours=int(settings["window_hours"]))


def _row_to_message(row: sqlite3_row) -> ParsedMessage:
    return ParsedMessage(
        id=row["id"],
        message_id=row["message_id"] or "",
        from_name=row["from_name"] or "",
        from_addr=row["from_addr"] or "",
        to_addr=row["to_addr"] or "",
        subject=row["subject"] or "",
        date=row["date"] or "",
        clean_body=row["clean_body"] or "",
        raw_body=row["raw_body"] or "",
        in_reply_to=row["in_reply_to"] or "",
        references=json.loads(row["references_json"] or "[]"),
        list_unsubscribe=row["list_unsubscribe"] or "",
        precedence=row["precedence"] or "",
        auto_submitted=row["auto_submitted"] or "",
        source=row["source"] or "",
        provider_thread_id=(row["provider_thread_id"] or "") if "provider_thread_id" in row.keys() else "",
    )


def _public_message(row, full: bool = False) -> dict:
    item = {
        "id": row["id"],
        "message_id": row["message_id"],
        "thread_id": row["thread_id"],
        "from_name": row["from_name"],
        "from_addr": row["from_addr"],
        "to_addr": row["to_addr"],
        "subject": row["subject"],
        "date": row["date"],
        "source": row["source"],
        "is_noise": bool(row["is_noise"]),
        "noise_reason": row["noise_reason"],
        "clean_body": row["clean_body"],
    }
    if full:
        item["raw_body"] = row["raw_body"]
    return item


def _public_episode(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "brief_date": row["brief_date"],
        "status": row["status"],
        "error": row["error"],
        "engine": row["engine"],
        "script_model": row["script_model"],
        "audio_mime": row["audio_mime"],
        "has_audio": bool(row["audio_path"]),
        "duration_ms": row["duration_ms"] or 0,
        "created_at": row["created_at"],
        "is_sample": bool(row["is_sample"]),
        "chain_id": row["chain_id"] if "chain_id" in row.keys() else None,
        "question": row["question"] if "question" in row.keys() else None,
        "style": row["style"] if "style" in row.keys() else None,
        "length": row["length"] if "length" in row.keys() else None,
    }


def _public_chain(row) -> dict:
    return {
        "id": row["id"],
        "title": row["title"],
        "reason": row["reason"],
        "recommended": bool(row["recommended"]),
        "participants": json.loads(row["participants_json"] or "[]"),
        "message_ids": json.loads(row["message_ids_json"] or "[]"),
        "message_count": row["message_count"] or 0,
        "date_start": row["date_start"],
        "date_end": row["date_end"],
        "project": row["project"] or "",
        "search_text": row["search_text"] or "",
    }


def _public_segment(row) -> dict:
    return {
        "id": row["id"],
        "position": row["position"],
        "speaker": row["speaker"],
        "speaker_name": row["speaker_name"],
        "text": row["text"],
        "delivery": row["delivery"],
        "nonverbal": row["nonverbal"],
        "exaggeration": row["exaggeration"],
        "source_ids": json.loads(row["source_ids"] or "[]"),
        "start_ms": row["start_ms"] or 0,
        "end_ms": row["end_ms"] or 0,
    }


# Help the type checker without importing sqlite3.Row in annotations above.
sqlite3_row = object
