"""Background generate / IMAP jobs."""

from __future__ import annotations

import logging
import threading

from inbox_brief.db import get_settings
from inbox_brief.ingest.imap_client import fetch_imap
from inbox_brief.pipeline import generate_episode
from inbox_brief.settings import now_in
from inbox_brief.store import active_job, create_job, finish_job, upsert_messages

logger = logging.getLogger(__name__)


def start_generate(scope: str = "window") -> str:
    running = active_job()
    if running:
        return running["id"]
    job_id = create_job("generate")
    threading.Thread(target=_generate, args=(job_id, scope), daemon=True).start()
    return job_id


def start_podcast(
    chain_id: str,
    question: str,
    style: str,
    length: str,
    voice_preset: str,
    scope: str = "changed",
    chain_ids: list[str] | None = None,
) -> str:
    running = active_job()
    if running:
        return running["id"]
    job_id = create_job("podcast")
    threading.Thread(
        target=_podcast,
        args=(job_id, chain_id, question, style, length, voice_preset, scope, list(chain_ids or [chain_id])),
        daemon=True,
    ).start()
    return job_id


def start_overview(
    question: str,
    style: str,
    length: str,
    voice_preset: str,
    scope: str = "full",
) -> str:
    running = active_job()
    if running:
        return running["id"]
    job_id = create_job("overview")
    threading.Thread(
        target=_overview,
        args=(job_id, question, style, length, voice_preset, scope),
        daemon=True,
    ).start()
    return job_id


def start_imap_pull() -> str:
    running = active_job()
    if running:
        return running["id"]
    job_id = create_job("imap")
    threading.Thread(target=_imap, args=(job_id,), daemon=True).start()
    return job_id


def _generate(job_id: str, scope: str) -> None:
    try:
        episode_id = generate_episode(get_settings(), scope)
        finish_job(job_id, status="done", episode_id=episode_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Brief generation failed.")
        finish_job(job_id, status="error", error=str(exc))


def _podcast(
    job_id: str,
    chain_id: str,
    question: str,
    style: str,
    length: str,
    voice_preset: str,
    scope: str = "changed",
    chain_ids: list[str] | None = None,
) -> None:
    from inbox_brief.pipeline import generate_podcast

    try:
        episode_id = generate_podcast(
            get_settings(),
            chain_id,
            question=question,
            style=style,
            length=length,
            voice_preset=voice_preset or None,
            scope=scope,
            chain_ids=chain_ids,
        )
        finish_job(job_id, status="done", episode_id=episode_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Podcast generation failed.")
        finish_job(job_id, status="error", error=str(exc))


def _overview(
    job_id: str,
    question: str,
    style: str,
    length: str,
    voice_preset: str,
    scope: str,
) -> None:
    from inbox_brief.pipeline import generate_overview

    try:
        episode_id = generate_overview(
            get_settings(),
            question=question,
            style=style,
            length=length,
            voice_preset=voice_preset or None,
            scope=scope,
        )
        finish_job(job_id, status="done", episode_id=episode_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Overview generation failed.")
        finish_job(job_id, status="error", error=str(exc))


def _imap(job_id: str) -> None:
    try:
        settings = get_settings()
        from datetime import timedelta

        since = now_in(settings["timezone"]) - timedelta(hours=int(settings["window_hours"]))
        messages = fetch_imap(
            host=settings["imap_host"],
            port=int(settings["imap_port"]),
            user=settings["imap_user"],
            password=settings["imap_password"],
            folder=settings["imap_folder"],
            use_ssl=bool(settings["imap_ssl"]),
            since=since,
        )
        counts = upsert_messages(messages, settings)
        from inbox_brief.store import rebuild_chains

        rebuild_chains(settings)
        finish_job(job_id, status="done", error=f"Imported {counts['inserted']} message(s).")
    except Exception as exc:  # noqa: BLE001
        logger.exception("IMAP pull failed.")
        finish_job(job_id, status="error", error=str(exc))
