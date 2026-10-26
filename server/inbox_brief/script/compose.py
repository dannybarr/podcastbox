"""Build a two-host script from threads, with or without a local model."""

from __future__ import annotations

import json
import re
from datetime import datetime

import httpx

from inbox_brief.domain import ParsedMessage, Script, SegmentDraft
from inbox_brief.privacy import assert_private_base_url
from inbox_brief.script.guard import apply_guard

_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def compose_script(
    threads: dict[str, list[ParsedMessage]],
    *,
    backend: str,
    ollama_url: str,
    model: str,
    fallback_model: str,
    title: str | None = None,
) -> tuple[Script, str]:
    messages = [message for group in _ordered(threads) for message in group if message.clean_body.strip()]
    if not messages:
        return Script(title=title or "Brief", segments=[]), backend
    heading = title or _title_for(messages)
    if backend == "extractive":
        script = compose_extractive(threads, title=heading)
        return script, "extractive"
    script, used = compose_with_ollama(
        threads,
        title=heading,
        ollama_url=ollama_url,
        model=model,
        fallback_model=fallback_model,
    )
    return script, used


def compose_extractive(threads: dict[str, list[ParsedMessage]], *, title: str, max_segments: int = 12) -> Script:
    segments: list[SegmentDraft] = []
    chuckled = False
    index = 0
    for group in _ordered(threads):
        spoken_messages = [message for message in group if message.clean_body.strip()]
        for position, message in enumerate(spoken_messages):
            text = _spoken(message, reply=position > 0)
            if not text:
                continue
            delivery = _delivery(text)
            nonverbal = None
            exaggeration = 0.28
            if delivery == "curious":
                exaggeration = 0.4
            elif delivery == "emphasis":
                exaggeration = 0.45
            elif delivery == "warm":
                exaggeration = 0.35
            if not chuckled and index == 1 and "?" not in text:
                nonverbal = "chuckle"
                chuckled = True
                exaggeration = max(exaggeration, 0.4)
            speaker = "S1" if index % 2 == 0 else "S2"
            segments.append(
                SegmentDraft(
                    speaker=speaker,  # type: ignore[arg-type]
                    text=text,
                    source_ids=[message.id],
                    delivery=delivery,  # type: ignore[arg-type]
                    nonverbal=nonverbal,
                    exaggeration=exaggeration,
                )
            )
            index += 1
            if index >= max_segments:
                return Script(title=title, segments=segments)
    return Script(title=title, segments=segments)


def compose_with_ollama(
    threads: dict[str, list[ParsedMessage]],
    *,
    title: str,
    ollama_url: str,
    model: str,
    fallback_model: str,
) -> tuple[Script, str]:
    catalog = _catalog(threads)
    prompt = _prompt(catalog)
    errors: list[str] = []
    tried: set[str] = set()
    for candidate in (model, fallback_model):
        if not candidate or candidate in tried:
            continue
        tried.add(candidate)
        try:
            raw = _chat(ollama_url, candidate, prompt)
            segments = _parse_model_json(raw, catalog)
            return Script(title=title, segments=segments), candidate
        except Exception as exc:  # noqa: BLE001 - surface every model failure
            errors.append(f"{candidate}: {exc}")
    raise RuntimeError(
        "The local script model did not return a usable brief. " + " ".join(errors)
    )


def finish_script(script: Script, messages: dict[str, ParsedMessage]) -> Script:
    checked, _notes = apply_guard(script, messages)
    return checked


def _ordered(threads: dict[str, list[ParsedMessage]]) -> list[list[ParsedMessage]]:
    groups = list(threads.values())
    groups.sort(key=lambda group: (group[0].date or "9999", group[0].id))
    return groups


def _title_for(messages: list[ParsedMessage]) -> str:
    dated = [message.date for message in messages if message.date]
    if not dated:
        return "Today's brief"
    try:
        when = datetime.fromisoformat(max(dated).replace("Z", "+00:00"))
    except ValueError:
        return "Today's brief"
    return f"Brief for {when.day} {when.strftime('%B')}"


def _spoken(message: ParsedMessage, *, reply: bool) -> str:
    sentences = [part.strip() for part in _SENTENCE.split(message.clean_body.strip()) if part.strip()]
    if not sentences:
        snippet = message.clean_body.strip()
        if not snippet:
            return ""
        sentences = [snippet]
    chosen = re.sub(r"\s+", " ", " ".join(sentences[:2])).strip()
    if len(chosen) > 320:
        chosen = chosen[:317].rsplit(" ", 1)[0] + "."
    verb = "replied" if reply else "wrote"
    return f"{message.sender_label} {verb}: {chosen}"


def _delivery(text: str) -> str:
    if "?" in text:
        return "curious"
    if re.search(r"\d", text):
        return "emphasis"
    if re.search(r"\bthanks\b", text, re.IGNORECASE):
        return "warm"
    return "steady"


def _catalog(threads: dict[str, list[ParsedMessage]]) -> dict[str, ParsedMessage]:
    catalog: dict[str, ParsedMessage] = {}
    count = 0
    for group in _ordered(threads):
        for message in group:
            if not message.clean_body.strip():
                continue
            catalog[message.id] = message
            count += 1
            if count >= 12:
                return catalog
    return catalog


def _prompt(catalog: dict[str, ParsedMessage]) -> str:
    blocks = []
    for message in catalog.values():
        blocks.append(
            "\n".join(
                [
                    f"ID: {message.id}",
                    f"From: {message.sender_label} <{message.from_addr}>",
                    f"Subject: {message.subject}",
                    f"Date: {message.date}",
                    "Body:",
                    message.clean_body[:1800],
                ]
            )
        )
    sources = "\n\n---\n\n".join(blocks)
    return f"""You write the spoken script for a two-host daily email brief.
Hosts: Mina is S1, Owen is S2. They read the mail aloud. They do not judge it.

Hard rules:
- Attribute every fact to the person who wrote it. Example: "Sarah Chen wrote that the crates arrive Wednesday."
- Use only facts that appear in the emails below. Do not add dates, names, decisions, or reasons.
- No evaluation, advice, or speculation. Do not say good, bad, should, important, probably, seems, or I think.
- Do not address the listener with suggestions.
- Alternate speakers, starting with S1. Six to twelve segments.
- Each segment is one or two short spoken sentences.
- Every segment's source_ids must be IDs from the emails it actually uses.
- delivery is one of: warm, steady, curious, emphasis. This is how the line is spoken, not an opinion.
- nonverbal is null, or one of: laughs, chuckle, sighs, inhales. Use at most two in the whole script. Never use one to react to bad news. A chuckle is warmth in the voice, not a comment on the email.
- exaggeration is a number from 0.25 to 0.5. Use the higher end only for emphasis.

Emails:

{sources}

Return JSON only:
{{"segments":[{{"speaker":"S1","text":"...","delivery":"steady","nonverbal":null,"exaggeration":0.3,"source_ids":["..."]}}]}}
"""


def _chat(base_url: str, model: str, prompt: str) -> str:
    root = assert_private_base_url(base_url)
    response = httpx.post(
        f"{root}/api/chat",
        json={
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You output JSON only. You never invent facts about email.",
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0.2},
        },
        timeout=600,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload.get("message", {}).get("content", "")
    if not content:
        raise RuntimeError("The model returned an empty script.")
    return content


def _parse_model_json(raw: str, catalog: dict[str, ParsedMessage]) -> list[SegmentDraft]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    data = json.loads(text)
    rows = data.get("segments", data if isinstance(data, list) else [])
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("The model JSON had no segments.")
    segments: list[SegmentDraft] = []
    allowed_nonverbal = {"laughs", "chuckle", "sighs", "inhales", "exhales", "clears throat", "mumbles"}
    for row in rows:
        if not isinstance(row, dict):
            continue
        speaker = row.get("speaker")
        if speaker not in {"S1", "S2"}:
            speaker = "S1" if len(segments) % 2 == 0 else "S2"
        source_ids = [str(item) for item in row.get("source_ids") or [] if str(item) in catalog]
        spoken = str(row.get("text") or "").strip()
        if not spoken or not source_ids:
            continue
        delivery = row.get("delivery") if row.get("delivery") in {"warm", "steady", "curious", "emphasis"} else "steady"
        nonverbal = row.get("nonverbal")
        if isinstance(nonverbal, str):
            nonverbal = nonverbal.strip().lower() or None
        else:
            nonverbal = None
        if nonverbal not in allowed_nonverbal:
            nonverbal = None
        try:
            exaggeration = float(row.get("exaggeration", 0.3))
        except (TypeError, ValueError):
            exaggeration = 0.3
        segments.append(
            SegmentDraft(
                speaker=speaker,
                text=spoken,
                source_ids=source_ids,
                delivery=delivery,
                nonverbal=nonverbal,
                exaggeration=exaggeration,
            )
        )
    if not segments:
        raise RuntimeError("No segment cited a real source id.")
    return segments
