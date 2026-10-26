"""MCP mail: this app speaks MCP, and it can read other MCP mail servers.

A plugged-in server must expose a tool named list_messages. The tool returns
JSON text: {"messages": [{"message_id", "from_name", "from_addr", "to_addr",
"subject", "date", "body", "in_reply_to", "references", "thread_id"}]}.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

import httpx

from inbox_brief.curate import ask_chains, public_chain
from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.clean import clean_body
from inbox_brief.store import get_chain, list_chains, list_messages

PROTOCOL = "2024-11-05"


def fetch_messages(url: str, since: datetime | None = None) -> list[ParsedMessage]:
    from inbox_brief.mail.external import fetch_target

    return fetch_target({"transport": "http", "url": url}, since)


def handle(request: dict) -> dict:
    method = request.get("method")
    rpc_id = request.get("id")
    if method == "initialize":
        return _ok(
            rpc_id,
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "inbox-brief", "version": "2"},
            },
        )
    if method == "tools/list":
        return _ok(rpc_id, {"tools": _tools()})
    if method == "tools/call":
        params = request.get("params") or {}
        return _ok(rpc_id, _call(params.get("name") or "", params.get("arguments") or {}))
    if method == "notifications/initialized":
        return _ok(rpc_id, {})
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": -32601, "message": "Method not found"}}


def _tools() -> list[dict]:
    return [
        {
            "name": "list_chains",
            "description": "Recommended email chains for the current review period. Each topic appears once.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "search_chains",
            "description": "Find chains with a plain-language question, such as 'update on Atlas'.",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
        {
            "name": "get_chain",
            "description": "One chain, including the message ids it was built from.",
            "inputSchema": {
                "type": "object",
                "properties": {"chain_id": {"type": "string"}},
                "required": ["chain_id"],
            },
        },
        {
            "name": "list_messages",
            "description": "Messages kept after filtering. Other PodcastBox servers can ingest these.",
            "inputSchema": {"type": "object", "properties": {"since": {"type": "string"}}},
        },
    ]


def _call(name: str, arguments: dict) -> dict:
    if name == "list_chains":
        chains = [public_chain(chain) for chain in list_chains() if chain.get("recommended")]
        return _text({"chains": chains})
    if name == "search_chains":
        found = ask_chains(list_chains(), str(arguments.get("query") or ""))
        return _text({"chains": [public_chain(chain) for chain in found]})
    if name == "get_chain":
        chain = get_chain(str(arguments.get("chain_id") or ""))
        if chain is None:
            return _text({"error": "That chain is not in this review period."})
        return _text({"chain": public_chain(chain)})
    if name == "list_messages":
        since = str(arguments.get("since") or "")
        rows = []
        for item in list_messages(include_noise=False):
            if since and item.get("date") and item["date"] < since:
                continue
            rows.append(
                {
                    "id": item["id"],
                    "message_id": item.get("message_id") or "",
                    "from_name": item.get("from_name") or "",
                    "from_addr": item.get("from_addr") or "",
                    "to_addr": item.get("to_addr") or "",
                    "subject": item.get("subject") or "",
                    "date": item.get("date") or "",
                    "body": item.get("clean_body") or "",
                    "thread_id": item.get("thread_id") or "",
                }
            )
        return _text({"messages": rows})
    return _text({"error": f"Unknown tool {name}."})


def _from_tool(item: dict, url: str) -> ParsedMessage:
    message_id = str(item.get("message_id") or item.get("id") or "")
    body = str(item.get("body") or item.get("clean_body") or "")
    identity = message_id or f"{item.get('from_addr')}|{item.get('date')}|{item.get('subject')}|{body[:400]}"
    digest = hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    references = item.get("references") or []
    if isinstance(references, str):
        references = references.split()
    return ParsedMessage(
        id=digest,
        message_id=message_id,
        from_name=str(item.get("from_name") or ""),
        from_addr=str(item.get("from_addr") or ""),
        to_addr=str(item.get("to_addr") or ""),
        subject=str(item.get("subject") or ""),
        date=str(item.get("date") or ""),
        clean_body=clean_body(body),
        raw_body=body,
        in_reply_to=str(item.get("in_reply_to") or ""),
        references=[str(part) for part in references],
        source="mcp",
        provider_thread_id=str(item.get("thread_id") or ""),
    )


def _rpc(url: str, method: str, params: dict) -> dict:
    response = httpx.post(
        url,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        timeout=30,
    )
    response.raise_for_status()
    body = response.json()
    if body.get("error"):
        raise RuntimeError(body["error"].get("message") or "The MCP server returned an error.")
    return body.get("result") or {}


def _tool_json(result: dict) -> dict:
    content = result.get("content") or []
    if content and isinstance(content[0], dict) and content[0].get("text"):
        return json.loads(content[0]["text"])
    if "messages" in result:
        return result
    return {"messages": []}


def _text(payload: dict) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


def _ok(rpc_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}
