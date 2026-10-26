"""Small SQLite store. One file on disk, no separate database service."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from inbox_brief.config import data_dir
from inbox_brief.settings import DEFAULTS, effective_settings, migrate_stored_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    message_id TEXT,
    thread_id TEXT,
    from_name TEXT,
    from_addr TEXT,
    to_addr TEXT,
    subject TEXT,
    date TEXT,
    clean_body TEXT,
    raw_body TEXT,
    source TEXT,
    is_noise INTEGER NOT NULL DEFAULT 0,
    noise_reason TEXT,
    in_reply_to TEXT,
    references_json TEXT,
    list_unsubscribe TEXT,
    precedence TEXT,
    auto_submitted TEXT
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    title TEXT,
    brief_date TEXT,
    status TEXT,
    error TEXT,
    engine TEXT,
    script_model TEXT,
    script_json TEXT,
    audio_path TEXT,
    audio_mime TEXT,
    duration_ms INTEGER,
    created_at TEXT,
    is_sample INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS segments (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    speaker TEXT,
    speaker_name TEXT,
    text TEXT,
    delivery TEXT,
    nonverbal TEXT,
    exaggeration REAL,
    source_ids TEXT,
    start_ms INTEGER,
    end_ms INTEGER
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT,
    status TEXT,
    error TEXT,
    episode_id TEXT,
    created_at TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS schedule_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_date TEXT
);
CREATE TABLE IF NOT EXISTS secrets (
    name TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chains (
    id TEXT PRIMARY KEY,
    title TEXT,
    reason TEXT,
    recommended INTEGER NOT NULL DEFAULT 0,
    participants_json TEXT,
    message_ids_json TEXT,
    message_count INTEGER,
    date_start TEXT,
    date_end TEXT,
    project TEXT,
    period_key TEXT,
    search_text TEXT,
    updated_at TEXT
);
"""


def db_path():
    return data_dir() / "inbox-brief.sqlite"


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db() -> None:
    with connect() as connection:
        connection.executescript(SCHEMA)
        row = connection.execute("SELECT json FROM settings WHERE id = 1").fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO settings (id, json) VALUES (1, ?)",
                (json.dumps(DEFAULTS),),
            )
        state = connection.execute("SELECT last_date FROM schedule_state WHERE id = 1").fetchone()
        if state is None:
            connection.execute("INSERT INTO schedule_state (id, last_date) VALUES (1, NULL)")
        _migrate(connection)


def get_settings() -> dict:
    with connect() as connection:
        row = connection.execute("SELECT json FROM settings WHERE id = 1").fetchone()
    stored = json.loads(row["json"]) if row else {}
    migrated = migrate_stored_settings(stored)
    cleaned = effective_settings(migrated)
    if row and migrated != stored:
        with connect() as connection:
            connection.execute("UPDATE settings SET json = ? WHERE id = 1", (json.dumps(_persistable(cleaned)),))
    from inbox_brief.secrets import read_secret

    cleaned["llm_api_key"] = read_secret("llm_api_key")
    return cleaned


def save_settings(updates: dict) -> dict:
    from inbox_brief.secrets import delete_secret, write_secret

    current = get_settings()
    updates = dict(updates)
    password = updates.get("imap_password", "")
    if not password or password == "__unchanged__":
        updates["imap_password"] = current.get("imap_password", "")
    incoming_key = updates.get("llm_api_key", "")
    if incoming_key == "__clear__":
        delete_secret("llm_api_key")
    elif incoming_key:
        write_secret("llm_api_key", incoming_key)
    updates["llm_api_key"] = ""
    merged = dict(current)
    merged["llm_api_key"] = ""
    for key, value in updates.items():
        if key in DEFAULTS:
            merged[key] = value
    if "timezone" in updates:
        merged["tz_chosen"] = True
    cleaned = effective_settings(merged)
    with connect() as connection:
        connection.execute(
            "UPDATE settings SET json = ? WHERE id = 1",
            (json.dumps(_persistable(cleaned)),),
        )
    return get_settings()


def _persistable(cleaned: dict) -> dict:
    stored = {key: cleaned[key] for key in DEFAULTS}
    stored["llm_api_key"] = ""
    return stored


def _migrate(connection) -> None:
    message_columns = {row["name"] for row in connection.execute("PRAGMA table_info(messages)")}
    if "provider_thread_id" not in message_columns:
        connection.execute("ALTER TABLE messages ADD COLUMN provider_thread_id TEXT")
    episode_columns = {row["name"] for row in connection.execute("PRAGMA table_info(episodes)")}
    for name in ("chain_id", "question", "style", "length", "deleted_at", "covered_json"):
        if name not in episode_columns:
            connection.execute(f"ALTER TABLE episodes ADD COLUMN {name} TEXT")


def remember_oauth_state(state: str, provider: str) -> None:
    with connect() as connection:
        connection.execute("DELETE FROM oauth_states WHERE created_at < ?", (utc_now_minus_minutes(20),))
        connection.execute(
            "INSERT OR REPLACE INTO oauth_states (state, provider, created_at) VALUES (?, ?, ?)",
            (state, provider, utc_now()),
        )


def take_oauth_state(state: str) -> str | None:
    with connect() as connection:
        row = connection.execute("SELECT provider FROM oauth_states WHERE state = ?", (state,)).fetchone()
        connection.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
    return row["provider"] if row else None


def utc_now_minus_minutes(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
