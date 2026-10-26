"""HTTP API for PodcastBox."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from inbox_brief import __version__
from inbox_brief.config import seed_on_start
from inbox_brief.db import get_settings, init_db, save_settings
from inbox_brief.ingest.parse import parse_eml_bytes, parse_mbox_bytes
from inbox_brief.jobs import start_generate, start_imap_pull, start_podcast
from inbox_brief.privacy import assert_private_base_url
from inbox_brief.schedule import start_scheduler, stop_scheduler
from inbox_brief.seed import seed_if_empty
from inbox_brief.settings import public_settings
from inbox_brief.store import (
    delete_episode,
    episode_audio,
    get_chain,
    get_episode,
    get_job,
    get_message,
    latest_episode,
    list_chains,
    list_episodes,
    list_messages,
    rebuild_chains,
    restore_episode,
    upsert_messages,
)
from inbox_brief.tts.engines import dia_health, onnx_available, resolve_engine, speaches_health

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

MAX_UPLOAD = 50 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if seed_on_start():
        seed_if_empty()
        from inbox_brief.seed import sync_fixtures

        sync_fixtures()
    import os

    if os.environ.get("INBOX_BRIEF_SCHEDULE", "1") != "0":
        start_scheduler()
    yield
    stop_scheduler()


def create_app() -> FastAPI:
    init_db()
    app = FastAPI(title="PodcastBox", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


from fastapi import APIRouter  # noqa: E402

router = APIRouter()


@router.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@router.get("/api/system")
def system() -> dict:
    settings = get_settings()
    return {
        "version": __version__,
        "dia": dia_health(settings["dia_url"]) or {"ok": False, "device": None},
        "speaches": {"ok": speaches_health(settings["speaches_url"])},
        "kokoro_onnx": {"ok": onnx_available()},
        "ollama": _ollama(settings["ollama_url"]),
        "resolved_engine": resolve_engine(settings["tts_engine"], settings["dia_url"]),
        "script_backend": settings["script_backend"],
        "script_model": settings["script_model"],
    }


@router.get("/api/settings")
def read_settings() -> dict:
    return public_settings(get_settings())


@router.put("/api/settings")
def write_settings(payload: dict) -> dict:
    try:
        saved = save_settings(payload)
    except (TypeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    rebuild_chains(get_settings())
    return public_settings(saved)


_PREVIEWS = {
    "kokoro_british": "kokoro-british.mp3",
    "kokoro_american": "kokoro-ab.mp3",
    "dia": "dia-sample.mp3",
}


@router.get("/api/voices/preview/{preset}")
def voice_preview(preset: str) -> Response:
    from inbox_brief.config import demo_dir

    name = _PREVIEWS.get(preset)
    if name is None:
        raise HTTPException(404, "That voice has no preview.")
    path = demo_dir() / name
    if not path.is_file():
        raise HTTPException(404, "The preview clip is not on this machine.")
    mime = "audio/mpeg" if name.endswith(".mp3") else "audio/wav"
    return Response(path.read_bytes(), media_type=mime)


@router.get("/api/voice/mine")
def my_voice() -> dict:
    from inbox_brief.tts.voice_clip import empty_status, load_clip

    settings = get_settings()
    clip = load_clip()
    host = settings.get("my_voice_host") or "S1"
    if clip is None:
        return empty_status(host)
    status = clip.status()
    status["host"] = host
    return status


@router.post("/api/voice/mine")
async def save_my_voice(
    file: UploadFile = File(...),
    consent: str = Form("false"),
    host: str = Form("S1"),
) -> dict:
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "That clip is larger than 15 MB.")
    from inbox_brief.tts.voice_clip import VoiceClipError, save_clip

    try:
        clip = save_clip(data, file.filename or "clip.wav", consent=consent, host=host)
    except VoiceClipError as exc:
        raise HTTPException(400, str(exc)) from exc
    save_settings({"my_voice_host": clip.host})
    return clip.status()


@router.delete("/api/voice/mine")
def remove_my_voice() -> Response:
    from inbox_brief.tts.voice_clip import delete_clip

    delete_clip()
    return Response(status_code=204)


@router.get("/api/voice/mine/audio")
def my_voice_audio() -> Response:
    from inbox_brief.tts.voice_clip import load_clip

    clip = load_clip()
    if clip is None:
        raise HTTPException(404, "No voice clip is stored on this machine.")
    return Response(clip.wav, media_type="audio/wav")


@router.get("/api/messages")
def messages(include_noise: bool = True) -> dict:
    return {"messages": list_messages(include_noise=include_noise)}


@router.get("/api/messages/{message_id}")
def message(message_id: str) -> dict:
    found = get_message(message_id)
    if found is None:
        raise HTTPException(404, "That email is not in the library.")
    return found


@router.post("/api/ingest/upload")
async def upload(files: list[UploadFile] = File(...)) -> dict:
    settings = get_settings()
    parsed = []
    for upload_file in files:
        data = await upload_file.read()
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, f"{upload_file.filename} is larger than 50 MB.")
        parsed.extend(_parse_upload(upload_file.filename or "", data))
    if not parsed:
        raise HTTPException(400, "No messages were found in that file.")
    counts = upsert_messages(parsed, settings)
    counts["parsed"] = len(parsed)
    return counts


@router.post("/api/ingest/imap")
def imap_pull() -> dict:
    return {"job_id": start_imap_pull()}


@router.post("/api/ingest/graph")
def graph_pull() -> dict:
    return _sync_outlook()


@router.get("/api/connections")
def connections() -> dict:
    from inbox_brief.mail import gmail, outlook

    settings = get_settings()
    return {
        "gmail": {
            "configured": gmail.configured(),
            "connected": gmail.connected(),
            "account": gmail.account(),
            "redirect_uri": gmail.redirect_uri(),
            "scope": "gmail.readonly",
        },
        "outlook": {
            "configured": outlook.configured(),
            "connected": outlook.connected(),
            "account": outlook.account(),
            "redirect_uri": outlook.redirect_uri(),
            "scope": "Mail.Read",
        },
        "imap": {"configured": bool(settings.get("imap_host") and settings.get("imap_user"))},
        "mcp": {"urls": settings.get("mcp_mail_urls") or []},
        "upload": {"available": True},
    }


@router.get("/api/connect/gmail")
def connect_gmail():
    from inbox_brief.mail.gmail import authorization_url

    try:
        return RedirectResponse(authorization_url())
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/connect/gmail/callback")
def gmail_callback(code: str = "", state: str = ""):
    from inbox_brief.mail.gmail import exchange

    try:
        exchange(code, state)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Gmail did not connect. {exc}") from exc
    return RedirectResponse(_web("/?connected=gmail"))


@router.post("/api/connect/gmail/disconnect")
def gmail_disconnect() -> dict:
    from inbox_brief.mail.gmail import disconnect

    disconnect()
    return {"connected": False}


@router.post("/api/connect/gmail/sync")
def gmail_sync() -> dict:
    from datetime import timedelta

    from inbox_brief.mail.gmail import fetch_recent
    from inbox_brief.settings import now_in

    settings = get_settings()
    since = now_in(settings["timezone"]) - timedelta(days=_period_days(settings))
    try:
        messages = fetch_recent(since)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    counts = upsert_messages(messages, settings)
    return counts


@router.get("/api/connect/outlook")
def connect_outlook():
    from inbox_brief.mail.outlook import authorization_url

    try:
        return RedirectResponse(authorization_url())
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/api/connect/outlook/callback")
def outlook_callback(code: str = "", state: str = ""):
    from inbox_brief.mail.outlook import exchange

    try:
        exchange(code, state)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Outlook did not connect. {exc}") from exc
    return RedirectResponse(_web("/?connected=outlook"))


@router.post("/api/connect/outlook/disconnect")
def outlook_disconnect() -> dict:
    from inbox_brief.mail.outlook import disconnect

    disconnect()
    return {"connected": False}


@router.post("/api/connect/outlook/sync")
def outlook_sync() -> dict:
    return _sync_outlook()


@router.post("/api/connect/mcp/sync")
def mcp_sync() -> dict:
    from datetime import timedelta

    from inbox_brief.settings import now_in

    settings = get_settings()
    from inbox_brief.mail.external import fetch_target, targets_from_settings

    targets = targets_from_settings(settings)
    if not targets:
        raise HTTPException(400, "Add an MCP mail server URL in Settings.")
    since = now_in(settings["timezone"]) - timedelta(days=_period_days(settings))
    parsed = []
    try:
        for target in targets:
            parsed.extend(fetch_target(target, since))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    return upsert_messages(parsed, settings)


@router.get("/api/chains")
def chains(q: str = "") -> dict:
    from inbox_brief.store import home_chains

    found = home_chains(get_settings(), q)
    return {"chains": [_hide_search(chain) for chain in found], "query": q}


@router.get("/api/inbox")
def inbox(q: str = "") -> dict:
    from inbox_brief.store import inbox_chains

    found = inbox_chains(get_settings(), q)
    return {"chains": [_hide_search(chain) for chain in found], "query": q}


@router.post("/api/chains/refresh")
def refresh_chains() -> dict:
    found = rebuild_chains(get_settings(), use_model=True)
    return {"chains": [_hide_search(chain) for chain in found if chain.get("recommended")]}


@router.get("/api/overview")
def overview() -> dict:
    from inbox_brief.overview import overview_status

    return overview_status(get_settings())


@router.post("/api/podcasts")
def create_podcast(payload: dict) -> dict:
    if payload.get("overview"):
        from inbox_brief.jobs import start_overview

        style = payload.get("style") if payload.get("style") in {"quick", "deep", "action", "full"} else "full"
        length = "full" if style == "full" else payload.get("length") if payload.get("length") in {"short", "medium", "long"} else "short"
        scope = payload.get("scope") if payload.get("scope") in {"full", "changed"} else "full"
        voice = str(payload.get("voice_preset") or "")
        return {
            "job_id": start_overview(
                str(payload.get("question") or ""),
                style,
                length,
                voice,
                scope,
            )
        }
    raw_ids = payload.get("chain_ids") or []
    if isinstance(raw_ids, str):
        raw_ids = [raw_ids]
    chain_ids = [str(item) for item in raw_ids if str(item).strip()]
    if not chain_ids and payload.get("chain_id"):
        chain_ids = [str(payload.get("chain_id"))]
    if not chain_ids or any(get_chain(item) is None for item in chain_ids):
        raise HTTPException(404, "That chain is not in this review period.")
    style = payload.get("style") if payload.get("style") in {"quick", "deep", "action"} else "quick"
    length = payload.get("length") if payload.get("length") in {"short", "medium", "long"} else "short"
    scope = payload.get("scope") if payload.get("scope") in {"full", "changed"} else "changed"
    voice = str(payload.get("voice_preset") or "")
    return {
        "job_id": start_podcast(
            chain_ids[0],
            str(payload.get("question") or ""),
            style,
            length,
            voice,
            scope,
            chain_ids,
        )
    }


@router.get("/api/podcasts")
def podcasts() -> dict:
    from inbox_brief.store import podcast_index

    return podcast_index(get_settings())


@router.delete("/api/podcasts/{episode_id}")
def remove_podcast(episode_id: str) -> dict:
    if get_episode(episode_id) is None:
        raise HTTPException(404, "That podcast is not in the library.")
    if not delete_episode(episode_id):
        raise HTTPException(404, "That podcast is not in the library.")
    return {"id": episode_id, "deleted": True}


@router.post("/api/podcasts/{episode_id}/restore")
def undo_podcast(episode_id: str) -> dict:
    if not restore_episode(episode_id):
        raise HTTPException(404, "That podcast could not be restored.")
    return get_episode(episode_id)


@router.post("/mcp")
def mcp_endpoint(payload: dict) -> dict:
    from inbox_brief.mail.mcp import handle

    return handle(payload)


@router.get("/api/episodes")
def episodes() -> dict:
    return {"episodes": list_episodes()}


@router.get("/api/episodes/today")
def today() -> dict:
    episode = latest_episode()
    if episode is None:
        return {"episode": None}
    return {"episode": get_episode(episode["id"])}


@router.get("/api/episodes/{episode_id}")
def episode(episode_id: str) -> dict:
    found = get_episode(episode_id)
    if found is None:
        raise HTTPException(404, "That edition is not on this machine.")
    return found


@router.get("/api/episodes/{episode_id}/audio")
def audio(episode_id: str) -> Response:
    found = episode_audio(episode_id)
    if found is None:
        raise HTTPException(404, "This edition has no audio yet.")
    content, mime = found
    return Response(content, media_type=mime)


@router.post("/api/episodes/generate")
def generate(scope: str = "window") -> dict:
    if scope not in {"window", "all"}:
        raise HTTPException(400, "Scope must be window or all.")
    return {"job_id": start_generate(scope)}


@router.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    found = get_job(job_id)
    if found is None:
        raise HTTPException(404, "That job does not exist.")
    return found


def _sync_outlook() -> dict:
    from datetime import timedelta

    from inbox_brief.mail.outlook import fetch_recent
    from inbox_brief.settings import now_in

    settings = get_settings()
    since = now_in(settings["timezone"]) - timedelta(days=_period_days(settings))
    try:
        messages = fetch_recent(since)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc
    return upsert_messages(messages, settings)


def _period_days(settings: dict) -> int:
    return {"day": 1, "week": 7, "month": 31}.get(settings.get("review_period") or "week", 7)


def _web(path: str) -> str:
    import os

    root = os.environ.get("INBOX_BRIEF_WEB_URL", "http://127.0.0.1:43123").rstrip("/")
    return f"{root}{path}"


def _hide_search(chain: dict) -> dict:
    hidden = dict(chain)
    hidden.pop("search_text", None)
    hidden.pop("fresh_ids", None)
    hidden.pop("covered_ids", None)
    return hidden


def _parse_upload(filename: str, data: bytes):
    name = filename.lower()
    if name.endswith(".mbox") or data.lstrip().startswith(b"From "):
        return parse_mbox_bytes(data, source="upload")
    return [parse_eml_bytes(data, source="upload")]


def _ollama(base_url: str) -> dict:
    try:
        root = assert_private_base_url(base_url)
        response = httpx.get(f"{root}/api/tags", timeout=3)
        response.raise_for_status()
        models = [item.get("name") for item in response.json().get("models", [])]
        return {"ok": True, "models": models}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "models": [], "error": str(exc)}


app = create_app()
