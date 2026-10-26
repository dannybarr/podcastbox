"""Read mail from external MCP servers.

Streamable HTTP and stdio are both supported. Tool names are detected:

- list_messages: another PodcastBox server
- search_emails and read_email: GongRzhe Gmail MCP (@gongrzhe/server-gmail-autoauth-mcp)
- list-mail-messages and get-mail-message: Softeria Microsoft 365 MCP (@softeria/ms-365-mcp-server)
"""

from __future__ import annotations

import json
import shlex
import subprocess
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from inbox_brief.domain import ParsedMessage
from inbox_brief.mail.http_retry import MAX_PAGES, send
from inbox_brief.mail.mcp import _from_tool, _tool_json

PROTOCOL = "2024-11-05"


def targets_from_settings(settings: dict) -> list[dict]:
    targets = []
    for raw in settings.get("mcp_mail_urls") or []:
        text = str(raw).strip()
        if not text:
            continue
        if text.lower().startswith("stdio:"):
            targets.append({"transport": "stdio", "command": text.split(":", 1)[1].strip()})
        else:
            targets.append({"transport": "http", "url": text})
    return targets


def fetch_target(target: dict, since: datetime | None = None) -> list[ParsedMessage]:
    session = StdioSession(target["command"]) if target.get("transport") == "stdio" else HttpSession(target["url"])
    try:
        session.rpc(
            "initialize",
            {"protocolVersion": PROTOCOL, "capabilities": {}, "clientInfo": {"name": "inbox-brief", "version": "2"}},
        )
        listed = session.rpc("tools/list", {})
        names = {tool.get("name") for tool in (listed.get("tools") or [])}
        if "list_messages" in names:
            arguments = {}
            if since is not None:
                arguments["since"] = since.date().isoformat()
            result = session.rpc("tools/call", {"name": "list_messages", "arguments": arguments})
            payload = _tool_json(result)
            return [_from_tool(item, target.get("url") or target.get("command") or "mcp") for item in payload.get("messages") or []]
        if "search_emails" in names and "read_email" in names:
            return _gmail_mcp(session, since)
        if "list-mail-messages" in names and "get-mail-message" in names:
            return _outlook_mcp(session, since)
        found = ", ".join(sorted(str(name) for name in names if name)) or "none"
        raise RuntimeError(
            "That MCP server has no supported mail tool. "
            f"Expected list_messages, search_emails, or list-mail-messages. Found: {found}."
        )
    finally:
        session.close()


class HttpSession:
    def __init__(self, url: str) -> None:
        self.url = url
        self.session_id = ""

    def rpc(self, method: str, params: dict) -> dict:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        response = send(
            "POST",
            self.url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        if response.headers.get("Mcp-Session-Id"):
            self.session_id = response.headers["Mcp-Session-Id"]
        body = _decode_http(response)
        if body.get("error"):
            raise RuntimeError(body["error"].get("message") or "The MCP server returned an error.")
        return body.get("result") or {}

    def close(self) -> None:
        return None


class StdioSession:
    def __init__(self, command: str) -> None:
        args = _stdio_args(command)
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def rpc(self, method: str, params: dict) -> dict:
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("The stdio MCP process has no pipes.")
        payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        self.proc.stdin.write(payload + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            err = ""
            if self.proc.stderr is not None:
                err = self.proc.stderr.read()[:400]
            raise RuntimeError(f"The stdio MCP process closed. {err}".strip())
        body = json.loads(line)
        if body.get("error"):
            raise RuntimeError(body["error"].get("message") or "The MCP server returned an error.")
        return body.get("result") or {}

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()


def _stdio_args(command: str) -> list[str]:
    if any(token in command for token in ("|", ";", "&&", "`", "$(", "\n")):
        raise RuntimeError("The stdio command must be one program and its arguments, not a shell pipeline.")
    args = shlex.split(command)
    if not args:
        raise RuntimeError("The stdio command is empty.")
    return args


def _decode_http(response) -> dict:
    content_type = (response.headers.get("content-type") or "").lower()
    text = response.text or ""
    if "text/event-stream" in content_type or text.lstrip().startswith("data:") or text.lstrip().startswith("event:"):
        data = ""
        for line in text.splitlines():
            if line.startswith("data:"):
                data = line[5:].strip()
        if not data:
            return {}
        return json.loads(data)
    return response.json()


def _gmail_mcp(session, since: datetime | None) -> list[ParsedMessage]:
    query = "in:inbox"
    if since is not None:
        query = f"after:{since.strftime('%Y/%m/%d')}"
    found: list[dict] = []
    page = None
    for _page_number in range(MAX_PAGES):
        arguments = {"query": query, "maxResults": 50}
        if page:
            arguments["pageToken"] = page
        payload = _payload(session.rpc("tools/call", {"name": "search_emails", "arguments": arguments}))
        found.extend(payload.get("messages") or [])
        page = payload.get("nextPageToken") or ""
        if not page:
            break
    messages = []
    for item in found:
        if not item.get("body") and not item.get("snippet"):
            detail = _payload(session.rpc("tools/call", {"name": "read_email", "arguments": {"messageId": item.get("id")}}))
            richer = (detail.get("messages") or [{}])[0]
            item = {**richer, **{key: value for key, value in item.items() if value}}
        messages.append(_gmail_message(item))
    return messages


def _outlook_mcp(session, since: datetime | None) -> list[ParsedMessage]:
    from inbox_brief.mail.outlook import _to_message

    stamp = "1970-01-01T00:00:00Z"
    if since is not None:
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        stamp = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    skiptoken = None
    messages: list[ParsedMessage] = []
    for _page_number in range(MAX_PAGES):
        arguments = {
            "top": 50,
            "orderby": "receivedDateTime desc",
            "filter": f"receivedDateTime ge {stamp}",
            "select": "id,conversationId,subject,from,toRecipients,receivedDateTime,body,internetMessageId,isDraft",
        }
        if skiptoken:
            arguments["skiptoken"] = skiptoken
        payload = _payload(session.rpc("tools/call", {"name": "list-mail-messages", "arguments": arguments}))
        for item in payload.get("value") or payload.get("messages") or []:
            if item.get("isDraft"):
                continue
            if not ((item.get("body") or {}).get("content") or item.get("bodyPreview")):
                detail = _payload(
                    session.rpc("tools/call", {"name": "get-mail-message", "arguments": {"messageId": item.get("id")}})
                )
                fuller = (detail.get("value") or detail.get("messages") or [detail])[0]
                if isinstance(fuller, dict) and fuller.get("id"):
                    item = fuller
            parsed = _to_message(item)
            parsed.source = "mcp"
            messages.append(parsed)
        link = payload.get("@odata.nextLink") or ""
        if not link:
            break
        skiptoken = (parse_qs(urlparse(link).query).get("$skiptoken") or [""])[0]
        if not skiptoken:
            break
    return messages


def _payload(result: dict) -> dict:
    content = result.get("content") or []
    text = ""
    if content and isinstance(content[0], dict):
        text = str(content[0].get("text") or "")
    text = text.strip()
    if text.startswith("{") or text.startswith("["):
        data = json.loads(text)
        if isinstance(data, list):
            return {"messages": data}
        if isinstance(data, dict):
            if "value" in data or "messages" in data or "nextPageToken" in data:
                return data
            if data.get("id") or data.get("subject") or data.get("body"):
                return {"messages": [data]}
            return data
    if text:
        return _text_messages(text)
    return _tool_json(result)


def _text_messages(text: str) -> dict:
    blocks = []
    current: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False
    next_token = ""

    def finish() -> None:
        nonlocal current, body_lines, in_body
        if current:
            if body_lines:
                current["body"] = "\n".join(body_lines).strip()
            blocks.append(current)
        current = {}
        body_lines = []
        in_body = False

    for line in text.splitlines():
        if line.startswith("ID:") and current:
            finish()
        if line.lower().startswith("nextpagetoken:"):
            next_token = line.split(":", 1)[1].strip()
            continue
        label, _, value = line.partition(":")
        key = label.strip().lower()
        if key in {"id", "thread id", "subject", "from", "to", "date", "message-id", "message id"} and not in_body:
            current[{"thread id": "threadId", "message-id": "message_id", "message id": "message_id"}.get(key, key)] = value.strip()
            continue
        if line.strip() == "" and current and not in_body:
            in_body = True
            continue
        if in_body or (current and key not in {"id", "thread id", "subject", "from", "to", "date"}):
            in_body = True
            body_lines.append(line)
    finish()
    return {"messages": blocks, "nextPageToken": next_token}


def _gmail_message(item: dict) -> ParsedMessage:
    from email.utils import parseaddr, parsedate_to_datetime

    sender = str(item.get("from") or item.get("From") or "")
    name, addr = parseaddr(sender)
    to_name, to_addr = parseaddr(str(item.get("to") or ""))
    del to_name
    when = str(item.get("date") or "")
    if when and "T" not in when:
        try:
            when = parsedate_to_datetime(when).isoformat()
        except (TypeError, ValueError, IndexError):
            pass
    body = str(item.get("body") or item.get("snippet") or "")
    record = {
        "message_id": str(item.get("message_id") or item.get("messageId") or item.get("id") or ""),
        "from_name": name or str(item.get("from_name") or ""),
        "from_addr": addr or str(item.get("from_addr") or ""),
        "to_addr": to_addr or str(item.get("to_addr") or ""),
        "subject": str(item.get("subject") or ""),
        "date": when,
        "body": body,
        "thread_id": str(item.get("threadId") or item.get("thread_id") or ""),
    }
    return _from_tool(record, "gmail-mcp")
