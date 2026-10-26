"""Contract tests for native Gmail, native Outlook, and external mail MCP servers.

Responses follow the public Gmail API and Microsoft Graph shapes.
No live Google or Microsoft call is made.
"""

from __future__ import annotations

import base64
import json
import textwrap
from datetime import datetime, timezone

import httpx

SINCE = datetime(2026, 10, 1, tzinfo=timezone.utc)


def _json(status: int, payload: dict, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        json=payload,
        headers=headers or {},
        request=httpx.Request("GET", "https://contract.example"),
    )


def _install(monkeypatch, handler):
    def request(method, url, **kwargs):
        return handler(method, str(url), **kwargs)

    monkeypatch.setattr("inbox_brief.mail.http_retry.httpx.request", request)
    monkeypatch.setattr("inbox_brief.mail.http_retry.time.sleep", lambda _seconds: None)


def _raw(message_id: str, subject: str, body: str) -> str:
    eml = (
        f"From: Ada North <ada@example.com>\r\n"
        f"To: Ben Quay <ben@example.com>\r\n"
        f"Subject: {subject}\r\n"
        f"Date: Fri, 16 Oct 2026 09:00:00 +0000\r\n"
        f"Message-ID: <{message_id}@example.com>\r\n"
        f"\r\n{body}\r\n"
    )
    return base64.urlsafe_b64encode(eml.encode()).decode().rstrip("=")


def _graph_message(index: int, conversation: str) -> dict:
    return {
        "@odata.etag": f"W/\"{index}\"",
        "id": f"AAMkAG{index}",
        "conversationId": conversation,
        "subject": "Project Northquay",
        "from": {"emailAddress": {"name": "Ada North", "address": "ada@contoso.com"}},
        "toRecipients": [{"emailAddress": {"name": "Ben Quay", "address": "ben@contoso.com"}}],
        "receivedDateTime": "2026-10-16T09:05:00Z",
        "body": {"contentType": "text", "content": f"The Project Northquay crane is item {index}."},
        "internetMessageId": f"<north-{index}@contoso.com>",
        "isDraft": False,
    }


def test_gmail_oauth_refresh_pagination_thread_and_backoff(client, monkeypatch):
    monkeypatch.setenv("INBOX_BRIEF_GOOGLE_CLIENT_ID", "google-client")
    monkeypatch.setenv("INBOX_BRIEF_GOOGLE_CLIENT_SECRET", "google-secret")
    from inbox_brief.db import remember_oauth_state
    from inbox_brief.mail import gmail
    from inbox_brief.mail.http_retry import MAX_PAGES

    assert MAX_PAGES >= 40
    remember_oauth_state("state-gmail", "gmail")
    calls = []
    pages = {"n": 0}
    limited = {"once": True}

    def handler(method, url, **kwargs):
        calls.append((method, url, kwargs.get("data"), kwargs.get("params")))
        if method == "POST" and url.endswith("/token"):
            return _json(
                200,
                {
                    "access_token": "ya29.access",
                    "expires_in": 3600,
                    "refresh_token": "1//refresh",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_type": "Bearer",
                },
            )
        if url.endswith("/profile"):
            return _json(200, {"emailAddress": "ada@gmail.com", "messagesTotal": 4, "threadsTotal": 1, "historyId": "9"})
        if limited["once"] and url.endswith("/messages"):
            limited["once"] = False
            return _json(
                429,
                {"error": {"code": 429, "message": "Rate Limit Exceeded", "errors": [{"domain": "usageLimits", "reason": "rateLimitExceeded"}]}},
                headers={"Retry-After": "0"},
            )
        if url.endswith("/messages"):
            pages["n"] += 1
            token = None if pages["n"] == 4 else f"page-{pages['n'] + 1}"
            body = {
                "messages": [{"id": f"g{pages['n']}", "threadId": "thread-north"}],
                "resultSizeEstimate": 4,
            }
            if token:
                body["nextPageToken"] = token
            assert kwargs["params"]["maxResults"] == 50
            assert "after:" in kwargs["params"]["q"]
            return _json(200, body)
        assert kwargs["params"]["format"] == "raw"
        message_id = url.rsplit("/", 1)[-1]
        return _json(
            200,
            {
                "id": message_id,
                "threadId": "thread-north",
                "labelIds": ["INBOX"],
                "snippet": "crane",
                "historyId": "9",
                "internalDate": "1760600000000",
                "sizeEstimate": 120,
                "raw": _raw(message_id, "Project Northquay", "The crane arrives Wednesday."),
            },
        )

    _install(monkeypatch, handler)
    assert gmail.exchange("auth-code", "state-gmail") == "ada@gmail.com"
    assert calls[0][2]["grant_type"] == "authorization_code"
    saved = gmail._load()
    saved["expires_at"] = 0
    from inbox_brief.secrets import write_secret

    write_secret("gmail_oauth", json.dumps(saved))
    messages = gmail.fetch_recent(SINCE)
    assert len(messages) == 4
    assert {item.provider_thread_id for item in messages} == {"thread-north"}
    assert any(item[2] and item[2].get("grant_type") == "refresh_token" for item in calls)
    assert pages["n"] == 4
    gmail.disconnect()
    assert gmail.connected() is False


def test_outlook_oauth_refresh_pagination_thread_and_backoff(client, monkeypatch):
    monkeypatch.setenv("INBOX_BRIEF_MICROSOFT_CLIENT_ID", "ms-client")
    monkeypatch.setenv("INBOX_BRIEF_MICROSOFT_CLIENT_SECRET", "ms-secret")
    monkeypatch.setenv("INBOX_BRIEF_MICROSOFT_TENANT", "common")
    from inbox_brief.db import remember_oauth_state
    from inbox_brief.mail import outlook
    from inbox_brief.secrets import write_secret

    remember_oauth_state("state-outlook", "outlook")
    calls = []
    limited = {"once": True}
    page = {"n": 0}

    def handler(method, url, **kwargs):
        calls.append((method, url, kwargs.get("data"), kwargs.get("params")))
        if method == "POST" and "/oauth2/v2.0/token" in url:
            assert "login.microsoftonline.com/common/" in url
            return _json(
                200,
                {
                    "access_token": "ey.access",
                    "expires_in": 3600,
                    "refresh_token": "0.refresh",
                    "scope": "offline_access User.Read Mail.Read",
                    "token_type": "Bearer",
                },
            )
        if url.endswith("/me"):
            return _json(200, {"mail": "ada@contoso.com", "userPrincipalName": "ada@contoso.com"})
        if limited["once"]:
            limited["once"] = False
            return _json(
                429,
                {"error": {"code": "TooManyRequests", "message": "Application is over its MailboxConcurrency limit."}},
                headers={"Retry-After": "0"},
            )
        page["n"] += 1
        if page["n"] == 1:
            assert kwargs["params"]["$top"] == 50
            assert kwargs["params"]["$orderby"] == "receivedDateTime desc"
            assert "receivedDateTime ge" in kwargs["params"]["$filter"]
            values = [_graph_message(index, "AAQkAG-north") for index in range(50)]
            return _json(
                200,
                {
                    "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#users('me')/messages",
                    "value": values,
                    "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=page2",
                },
            )
        assert kwargs.get("params") is None
        assert "$skiptoken=page2" in url
        values = [_graph_message(index, "AAQkAG-north") for index in range(50, 60)]
        return _json(
            200,
            {
                "@odata.context": "https://graph.microsoft.com/v1.0/$metadata#users('me')/messages",
                "value": values,
            },
        )

    _install(monkeypatch, handler)
    assert outlook.exchange("auth-code", "state-outlook") == "ada@contoso.com"
    assert calls[0][2]["grant_type"] == "authorization_code"
    assert calls[0][2]["scope"] == "offline_access User.Read Mail.Read"
    saved = outlook._load()
    saved["expires_at"] = 0
    write_secret("outlook_oauth", json.dumps(saved))
    messages = outlook.fetch_recent(SINCE)
    assert len(messages) == 60
    assert {item.provider_thread_id for item in messages} == {"AAQkAG-north"}
    assert any(item[2] and item[2].get("grant_type") == "refresh_token" for item in calls)
    outlook.disconnect()
    assert outlook.connected() is False


def test_mcp_gmail_streamable_http_and_stdio(tmp_path, monkeypatch):
    from inbox_brief.mail.external import fetch_target

    seen = {"session": []}

    def handler(method, url, **kwargs):
        headers = kwargs.get("headers") or {}
        if headers.get("Mcp-Session-Id"):
            seen["session"].append(headers["Mcp-Session-Id"])
        body = kwargs["json"]
        name = (body.get("params") or {}).get("name")
        if body["method"] == "initialize":
            payload = {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "gmail", "version": "1"}}}
            return httpx.Response(
                200,
                text="event: message\ndata: " + json.dumps(payload) + "\n\n",
                headers={"Content-Type": "text/event-stream", "Mcp-Session-Id": "sess-gmail"},
                request=httpx.Request("POST", "http://127.0.0.1:3000/mcp"),
            )
        if body["method"] == "tools/list":
            result = {"tools": [{"name": "search_emails"}, {"name": "read_email"}]}
        else:
            arguments = body["params"]["arguments"]
            if name == "search_emails":
                if arguments.get("pageToken") == "p2":
                    text = json.dumps({"messages": [{"id": "g2", "threadId": "t-north"}], "nextPageToken": ""})
                else:
                    text = json.dumps({"messages": [{"id": "g1", "threadId": "t-north"}], "nextPageToken": "p2"})
            else:
                mid = arguments["messageId"]
                text = (
                    f"ID: {mid}\nThread ID: t-north\nSubject: Project Northquay\n"
                    "From: Ada North <ada@example.com>\nTo: Ben Quay <ben@example.com>\n"
                    "Date: Fri, 16 Oct 2026 09:00:00 +0000\n\nThe crane arrives Wednesday.\n"
                )
            result = {"content": [{"type": "text", "text": text}]}
        return _json(200, {"jsonrpc": "2.0", "id": 1, "result": result})

    _install(monkeypatch, handler)
    http_messages = fetch_target({"transport": "http", "url": "http://127.0.0.1:3000/mcp"}, SINCE)
    assert len(http_messages) == 2
    assert {item.provider_thread_id for item in http_messages} == {"t-north"}
    assert seen["session"]
    assert "crane" in http_messages[0].clean_body or "crane" in http_messages[1].clean_body

    script = tmp_path / "gmail_mcp.py"
    script.write_text(
        textwrap.dedent(
            """
            import json, sys
            for line in sys.stdin:
                req = json.loads(line)
                method = req["method"]
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {}, "serverInfo": {"name": "gmail", "version": "1"}}
                elif method == "tools/list":
                    result = {"tools": [{"name": "search_emails"}, {"name": "read_email"}]}
                else:
                    name = req["params"]["name"]
                    args = req["params"]["arguments"]
                    if name == "search_emails":
                        if args.get("pageToken") == "p2":
                            text = json.dumps({"messages": [{"id": "g2", "threadId": "t9"}]})
                        else:
                            text = json.dumps({"messages": [{"id": "g1", "threadId": "t9"}], "nextPageToken": "p2"})
                    else:
                        text = "ID: " + args["messageId"] + "\\nThread ID: t9\\nSubject: Hello\\nFrom: Ada <ada@example.com>\\nDate: Fri, 16 Oct 2026 09:00:00 +0000\\n\\nBody line.\\n"
                    result = {"content": [{"type": "text", "text": text}]}
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}) + "\\n")
                sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    import sys

    stdio_messages = fetch_target({"transport": "stdio", "command": f"{sys.executable} {script}"}, SINCE)
    assert len(stdio_messages) == 2
    assert {item.provider_thread_id for item in stdio_messages} == {"t9"}


def test_mcp_outlook_streamable_http_pages(monkeypatch):
    from inbox_brief.mail.external import fetch_target

    def handler(method, url, **kwargs):
        del method, url
        body = kwargs["json"]
        if body["method"] == "initialize":
            return _json(200, {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}}, "serverInfo": {"name": "ms365", "version": "1"}}})
        if body["method"] == "tools/list":
            result = {"tools": [{"name": "list-mail-messages"}, {"name": "get-mail-message"}]}
        else:
            name = body["params"]["name"]
            args = body["params"]["arguments"]
            if name == "list-mail-messages":
                def listing(index: int) -> dict:
                    item = _graph_message(index, "AAQkAG-page")
                    item = {key: value for key, value in item.items() if key != "body"}
                    item["bodyPreview"] = ""
                    return item

                if args.get("skiptoken") == "page2":
                    graph = {"value": [listing(2)]}
                else:
                    assert "receivedDateTime ge" in args["filter"]
                    graph = {
                        "value": [listing(1)],
                        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skiptoken=page2",
                    }
                result = {"content": [{"type": "text", "text": json.dumps(graph)}]}
            else:
                assert args["messageId"]
                result = {"content": [{"type": "text", "text": json.dumps(_graph_message(int(args["messageId"][-1]), "AAQkAG-page"))}]}
        return _json(200, {"jsonrpc": "2.0", "id": 1, "result": result})

    _install(monkeypatch, handler)
    messages = fetch_target({"transport": "http", "url": "http://127.0.0.1:3000/mcp"}, SINCE)
    assert len(messages) == 2
    assert {item.provider_thread_id for item in messages} == {"AAQkAG-page"}
    assert all(item.source == "mcp" for item in messages)


def test_stdio_command_rejects_a_shell_pipeline():
    from inbox_brief.mail.external import fetch_target

    try:
        fetch_target({"transport": "stdio", "command": "echo hi | cat"}, SINCE)
    except RuntimeError as exc:
        assert "pipeline" in str(exc)
    else:
        raise AssertionError("A shell pipeline was accepted.")
