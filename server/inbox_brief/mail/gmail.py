"""Read-only Gmail via Google OAuth and the Gmail API."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from inbox_brief.db import remember_oauth_state, take_oauth_state
from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.parse import parse_eml_bytes
from inbox_brief.mail.http_retry import MAX_PAGES, send
from inbox_brief.secrets import delete_secret, read_secret, write_secret

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
_SECRET = "gmail_oauth"


def configured() -> bool:
    return bool(client_id() and client_secret())


def client_id() -> str:
    return os.environ.get("INBOX_BRIEF_GOOGLE_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("INBOX_BRIEF_GOOGLE_CLIENT_SECRET", "").strip()


def redirect_uri() -> str:
    return os.environ.get(
        "INBOX_BRIEF_GOOGLE_REDIRECT_URI",
        "http://127.0.0.1:8742/api/connect/gmail/callback",
    ).strip()


def account() -> str:
    return _load().get("account") or ""


def connected() -> bool:
    return bool(_load().get("refresh_token") or _load().get("access_token"))


def disconnect() -> None:
    delete_secret(_SECRET)


def authorization_url() -> str:
    if not configured():
        raise RuntimeError(
            "Gmail is not configured. Set INBOX_BRIEF_GOOGLE_CLIENT_ID and INBOX_BRIEF_GOOGLE_CLIENT_SECRET."
        )
    import secrets

    state = secrets.token_urlsafe(24)
    remember_oauth_state(state, "gmail")
    query = urlencode(
        {
            "client_id": client_id(),
            "redirect_uri": redirect_uri(),
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
    )
    return f"{AUTH}?{query}"


def exchange(code: str, state: str) -> str:
    if take_oauth_state(state) != "gmail":
        raise RuntimeError("The Gmail sign-in expired. Start it again from Settings.")
    response = send(
        "POST",
        TOKEN,
        data={
            "code": code,
            "client_id": client_id(),
            "client_secret": client_secret(),
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    profile = send(
        "GET",
        f"{API}/profile",
        headers={"Authorization": f"Bearer {token['access_token']}"},
        timeout=30,
    )
    profile.raise_for_status()
    _store(token, profile.json().get("emailAddress") or "")
    return profile.json().get("emailAddress") or ""


def fetch_recent(since: datetime) -> list[ParsedMessage]:
    token = _access_token()
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    query = f"after:{since.strftime('%Y/%m/%d')}"
    headers = {"Authorization": f"Bearer {token}"}
    messages: list[ParsedMessage] = []
    page = None
    for _page_number in range(MAX_PAGES):
        params = {"q": query, "maxResults": 50}
        if page:
            params["pageToken"] = page
        listed = send("GET", f"{API}/messages", headers=headers, params=params, timeout=30)
        listed.raise_for_status()
        body = listed.json()
        for item in body.get("messages") or []:
            raw = send(
                "GET",
                f"{API}/messages/{item['id']}",
                headers=headers,
                params={"format": "raw"},
                timeout=30,
            )
            raw.raise_for_status()
            payload = raw.json()
            import base64

            data = payload.get("raw") or ""
            padded = data + "=" * (-len(data) % 4)
            parsed = parse_eml_bytes(base64.urlsafe_b64decode(padded), source="gmail")
            parsed.provider_thread_id = str(payload.get("threadId") or item.get("threadId") or "")
            if _before(parsed.date, since):
                continue
            messages.append(parsed)
        page = body.get("nextPageToken")
        if not page:
            break
    return messages


def _before(value: str, since: datetime) -> bool:
    if not value:
        return False
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when < since


def _access_token() -> str:
    saved = _load()
    if not saved.get("refresh_token") and not saved.get("access_token"):
        raise RuntimeError("Gmail is not connected.")
    expires = float(saved.get("expires_at") or 0)
    if saved.get("access_token") and expires > datetime.now(timezone.utc).timestamp() + 30:
        return saved["access_token"]
    if not saved.get("refresh_token"):
        raise RuntimeError("Gmail needs to be connected again.")
    response = send(
        "POST",
        TOKEN,
        data={
            "client_id": client_id(),
            "client_secret": client_secret(),
            "refresh_token": saved["refresh_token"],
            "grant_type": "refresh_token",
        },
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()
    token.setdefault("refresh_token", saved["refresh_token"])
    _store(token, saved.get("account") or "")
    return token["access_token"]


def _load() -> dict:
    import json

    raw = read_secret(_SECRET)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _store(token: dict, account_email: str) -> None:
    import json

    expires = datetime.now(timezone.utc).timestamp() + float(token.get("expires_in") or 3600)
    write_secret(
        _SECRET,
        json.dumps(
            {
                "access_token": token.get("access_token") or "",
                "refresh_token": token.get("refresh_token") or "",
                "expires_at": expires,
                "account": account_email,
            }
        ),
    )
