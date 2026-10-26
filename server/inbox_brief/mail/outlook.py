"""Read-only Outlook and Microsoft 365 mail via Microsoft Graph OAuth."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from urllib.parse import urlencode

from inbox_brief.db import remember_oauth_state, take_oauth_state
from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.clean import clean_body
from inbox_brief.mail.http_retry import MAX_PAGES, send
from inbox_brief.secrets import delete_secret, read_secret, write_secret

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "offline_access User.Read Mail.Read"
_SECRET = "outlook_oauth"


def configured() -> bool:
    return bool(client_id() and client_secret())


def client_id() -> str:
    return os.environ.get("INBOX_BRIEF_MICROSOFT_CLIENT_ID", "").strip()


def client_secret() -> str:
    return os.environ.get("INBOX_BRIEF_MICROSOFT_CLIENT_SECRET", "").strip()


def tenant() -> str:
    return os.environ.get("INBOX_BRIEF_MICROSOFT_TENANT", "common").strip() or "common"


def redirect_uri() -> str:
    return os.environ.get(
        "INBOX_BRIEF_MICROSOFT_REDIRECT_URI",
        "http://127.0.0.1:8742/api/connect/outlook/callback",
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
            "Outlook is not configured. Set INBOX_BRIEF_MICROSOFT_CLIENT_ID and "
            "INBOX_BRIEF_MICROSOFT_CLIENT_SECRET."
        )
    import secrets

    state = secrets.token_urlsafe(24)
    remember_oauth_state(state, "outlook")
    query = urlencode(
        {
            "client_id": client_id(),
            "response_type": "code",
            "redirect_uri": redirect_uri(),
            "response_mode": "query",
            "scope": SCOPE,
            "state": state,
        }
    )
    return f"https://login.microsoftonline.com/{tenant()}/oauth2/v2.0/authorize?{query}"


def exchange(code: str, state: str) -> str:
    if take_oauth_state(state) != "outlook":
        raise RuntimeError("The Outlook sign-in expired. Start it again from Settings.")
    token = _token(
        {
            "client_id": client_id(),
            "client_secret": client_secret(),
            "code": code,
            "redirect_uri": redirect_uri(),
            "grant_type": "authorization_code",
            "scope": SCOPE,
        }
    )
    me = send(
        "GET",
        f"{GRAPH}/me",
        headers={"Authorization": f"Bearer {token['access_token']}"},
        params={"$select": "mail,userPrincipalName"},
        timeout=30,
    )
    me.raise_for_status()
    email = me.json().get("mail") or me.json().get("userPrincipalName") or ""
    _store(token, email)
    return email


def fetch_recent(since: datetime) -> list[ParsedMessage]:
    token = _access_token()
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{GRAPH}/me/messages"
    params: dict | None = {
        "$top": 50,
        "$orderby": "receivedDateTime desc",
        "$filter": f"receivedDateTime ge {stamp}",
        "$select": "id,conversationId,subject,from,toRecipients,receivedDateTime,body,internetMessageId,isDraft",
    }
    messages: list[ParsedMessage] = []
    for _page_number in range(MAX_PAGES):
        response = send("GET", url, headers=headers, params=params, timeout=45)
        response.raise_for_status()
        body = response.json()
        page_items = body.get("value") or []
        older = 0
        for item in page_items:
            if item.get("isDraft"):
                continue
            parsed = _to_message(item)
            if _before(parsed.date, since):
                older += 1
                continue
            messages.append(parsed)
        nxt = body.get("@odata.nextLink")
        if not nxt or (page_items and older == len(page_items)):
            break
        url = nxt
        params = None
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


def _to_message(item: dict) -> ParsedMessage:
    import hashlib

    sender = ((item.get("from") or {}).get("emailAddress") or {})
    recipients = item.get("toRecipients") or []
    to_addr = ""
    if recipients:
        to_addr = (recipients[0].get("emailAddress") or {}).get("address") or ""
    body = item.get("body") or {}
    content = body.get("content") or ""
    if (body.get("contentType") or "").lower() == "html":
        from inbox_brief.ingest.clean import html_to_text

        raw = html_to_text(content)
    else:
        raw = content
    message_id = (item.get("internetMessageId") or "").strip().strip("<>")
    received = item.get("receivedDateTime") or ""
    try:
        when = datetime.fromisoformat(received.replace("Z", "+00:00")).isoformat()
    except ValueError:
        when = received
    identity = message_id or f"{sender.get('address')}|{when}|{item.get('subject')}|{raw[:400]}"
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    return ParsedMessage(
        id=digest,
        message_id=message_id,
        from_name=sender.get("name") or "",
        from_addr=sender.get("address") or "",
        to_addr=to_addr,
        subject=item.get("subject") or "",
        date=when,
        clean_body=clean_body(raw),
        raw_body=raw.strip(),
        source="outlook",
        provider_thread_id=str(item.get("conversationId") or ""),
    )


def _access_token() -> str:
    saved = _load()
    if not saved.get("refresh_token") and not saved.get("access_token"):
        raise RuntimeError("Outlook is not connected.")
    expires = float(saved.get("expires_at") or 0)
    if saved.get("access_token") and expires > datetime.now(timezone.utc).timestamp() + 30:
        return saved["access_token"]
    if not saved.get("refresh_token"):
        raise RuntimeError("Outlook needs to be connected again.")
    token = _token(
        {
            "client_id": client_id(),
            "client_secret": client_secret(),
            "refresh_token": saved["refresh_token"],
            "grant_type": "refresh_token",
            "scope": SCOPE,
        }
    )
    token.setdefault("refresh_token", saved["refresh_token"])
    _store(token, saved.get("account") or "")
    return token["access_token"]


def _token(data: dict) -> dict:
    response = send(
        "POST",
        f"https://login.microsoftonline.com/{tenant()}/oauth2/v2.0/token",
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


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

