"""From stored mail to a guarded script and a local audio file."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from inbox_brief.domain import HOSTS
from inbox_brief.ingest.thread import thread_messages
from inbox_brief.script.compose import compose_script, finish_script
from inbox_brief.settings import now_in
from inbox_brief.store import message_map, messages_for_brief, save_episode
from inbox_brief.tts.engines import SpeechError, resolve_engine, synthesize
from inbox_brief.tts.format import format_dia

logger = logging.getLogger(__name__)


def generate_episode(settings: dict, scope: str = "window") -> str:
    if scope not in {"window", "all"}:
        scope = "window"
    messages = messages_for_brief(settings, scope)
    today = now_in(settings["timezone"]).date().isoformat()
    if not messages:
        return save_episode(
            title=f"Brief for {today}",
            brief_date=today,
            status="empty",
            error="No mail in this window. Upload a mailbox, pull from IMAP, or generate from the whole library.",
            engine=None,
            script_model=None,
            script=None,
            audio=None,
            mime=None,
            segments=[],
        )
    threads = thread_messages(messages)
    by_id = {message.id: message for message in messages}
    script, model_name = compose_script(
        threads,
        backend=settings["script_backend"],
        ollama_url=settings["ollama_url"],
        model=settings["script_model"],
        fallback_model=settings["script_model_fallback"],
    )
    script = finish_script(script, by_id)
    if not script.segments:
        raise RuntimeError("The neutrality guard removed every line. Nothing unsupported was left to read.")
    for segment in script.segments:
        if not segment.source_ids:
            raise RuntimeError("A transcript line lost its source email.")
    engine = resolve_engine(settings["tts_engine"], settings["dia_url"])
    try:
        rendered = synthesize(engine, script.segments, settings)
    except SpeechError as exc:
        if (
            engine != "kokoro"
            and settings["tts_fallback"] == "kokoro"
            and settings.get("voice_preset") != "my_voice"
        ):
            logger.warning("Voice engine %s failed (%s). Falling back to Kokoro.", engine, exc)
            rendered = synthesize("kokoro", script.segments, settings)
            engine = "kokoro"
        else:
            raise
    if len(rendered.timings) != len(script.segments):
        raise RuntimeError("The audio timings do not match the transcript.")
    payload = script.to_dict()
    payload["dia_prompt"] = format_dia(script.segments)
    payload["engine_detail"] = rendered.detail
    segments = []
    for segment, (start, end) in zip(script.segments, rendered.timings):
        item = segment.to_dict()
        item["speaker_name"] = HOSTS[segment.speaker]
        item["start_ms"] = start
        item["end_ms"] = end
        segments.append(item)
    brief_date = _brief_date(messages, today)
    return save_episode(
        title=script.title,
        brief_date=brief_date,
        status="ready",
        error=None,
        engine=engine,
        script_model=model_name,
        script=payload,
        audio=rendered.audio,
        mime=rendered.mime,
        segments=segments,
    )


def generate_podcast(
    settings: dict,
    chain_id: str,
    *,
    question: str = "",
    style: str = "quick",
    length: str = "short",
    voice_preset: str | None = None,
    scope: str = "changed",
    chain_ids: list[str] | None = None,
) -> str:
    from inbox_brief.days import annotate_chain
    from inbox_brief.settings import apply_voice_preset
    from inbox_brief.store import chain_messages, coverage_records, get_chain

    chosen_ids = [item for item in (chain_ids or [chain_id]) if item]
    chains = []
    for item in chosen_ids:
        chain = get_chain(item)
        if chain is None:
            raise RuntimeError("That chain is not in this review period.")
        chains.append(chain)
    if not chains:
        raise RuntimeError("That chain is not in this review period.")
    primary = chains[0]
    messages = []
    seen: set[str] = set()
    for chain in chains:
        for message in chain_messages(chain["id"]):
            if message.id not in seen:
                seen.add(message.id)
                messages.append(message)
    if not messages:
        raise RuntimeError("That chain has no mail left to read.")
    messages.sort(key=lambda item: (item.date or "", item.id))
    working = dict(settings)
    if voice_preset:
        working["voice_preset"] = voice_preset
        working = apply_voice_preset(working)
    zone = working.get("timezone") or "Europe/London"
    dates = {message.id: message.date for message in messages}
    records = coverage_records()
    covered: set[str] = set()
    fresh_ids: list[str] = []
    for chain in chains:
        note = annotate_chain(chain, records, dates, zone)
        if note.get("covered"):
            fresh_ids.extend(note.get("fresh_ids") or [])
            covered.update(note.get("covered_ids") or [])
    fresh_ids = [item for item in dict.fromkeys(fresh_ids) if item in seen]
    use_changed = scope != "full" and bool(covered)
    if use_changed and not fresh_ids:
        raise RuntimeError("Nothing new since the last podcast.")
    selected = [message for message in messages if message.id in set(fresh_ids)] if use_changed else messages
    prior = None
    if use_changed:
        heard = [message for message in messages if message.id in covered]
        prior = max(heard, key=lambda item: item.date or "") if heard else None
    limit = {"quick": 4, "action": 6, "deep": 10}.get(style, 4)
    if length == "long":
        limit += 2
    ordered = _focus(selected, question, style)
    title = primary["title"] if len(chains) == 1 else "Selected chains"
    threads = {primary["id"]: ordered}
    by_id = {message.id: message for message in messages}
    script, model_name = _compose_podcast(working, threads, title, question, style, limit)
    if prior is not None:
        script.segments.insert(0, _recap(prior))
    script = finish_script(script, by_id)
    if not script.segments:
        raise RuntimeError("The neutrality guard removed every line. Nothing unsupported was left to read.")
    for segment in script.segments:
        if not segment.source_ids:
            raise RuntimeError("A transcript line lost its source email.")
    engine = resolve_engine(working["tts_engine"], working["dia_url"])
    try:
        rendered = synthesize(engine, script.segments, working)
    except SpeechError as exc:
        if engine != "kokoro" and working["tts_fallback"] == "kokoro" and working.get("voice_preset") != "my_voice":
            logger.warning("Voice engine %s failed (%s). Falling back to Kokoro.", engine, exc)
            rendered = synthesize("kokoro", script.segments, working)
            engine = "kokoro"
        else:
            raise
    payload = script.to_dict()
    payload["dia_prompt"] = format_dia(script.segments)
    payload["engine_detail"] = rendered.detail
    payload["question"] = question
    payload["style"] = style
    segments = []
    for segment, (start, end) in zip(script.segments, rendered.timings):
        item = segment.to_dict()
        item["speaker_name"] = HOSTS[segment.speaker]
        item["start_ms"] = start
        item["end_ms"] = end
        segments.append(item)
    stored = selected
    through = max((message.date for message in stored if message.date), default="")
    return save_episode(
        title=script.title or title,
        brief_date=_brief_date(ordered, now_in(working["timezone"]).date().isoformat()),
        status="ready",
        error=None,
        engine=engine,
        script_model=model_name,
        script=payload,
        audio=rendered.audio,
        mime=rendered.mime,
        segments=segments,
        chain_id=primary["id"],
        question=question,
        style=style,
        length=length,
        covered_ids=[message.id for message in stored],
        covered_through=through,
    )


def _recap(message):
    """One neutral line of earlier context, sourced to the last covered email."""
    import re

    from inbox_brief.domain import SegmentDraft

    body = re.sub(r"\s+", " ", (message.clean_body or "").strip())
    sentence = re.split(r"(?<=[.!?])\s+", body)[0] if body else ""
    sentence = sentence.rstrip(".")
    if sentence and sentence[0].isalpha() and sentence[0].isupper():
        first = sentence.split(" ", 1)[0]
        names = {part.lower() for part in message.sender_label.split()}
        if first.lower() not in names:
            sentence = sentence[0].lower() + sentence[1:]
    text = f"Earlier, {message.sender_label} wrote that {sentence}."
    return SegmentDraft(speaker="S1", text=text, source_ids=[message.id], delivery="steady", exaggeration=0.3)


def _compose_podcast(settings, threads, title, question, style, limit):
    from inbox_brief.ai import chat, model_name
    from inbox_brief.script.compose import _catalog, _parse_model_json

    if settings.get("script_backend") != "extractive" and settings.get("llm_provider") in {"openai", "anthropic", "compatible"}:
        raw = chat(
            settings,
            "You write a two-host podcast from email. Speakers are S1 (Mina) and S2 (Owen). "
            "Use only facts that appear in the emails. Name the person who wrote each fact. "
            "No advice, no judgement, no guesses. Every segment needs a source_ids value copied from the catalog. "
            'Reply with JSON: {"title":"...","segments":[{"speaker":"S1","text":"...","source_ids":["id"],"delivery":"steady"}]}',
            _podcast_prompt(threads, title, question, style, limit),
        )
        if raw:
            try:
                from inbox_brief.domain import Script

                catalog = _catalog(threads)
                segments = _parse_model_json(raw, catalog)[:limit]
                if segments:
                    return Script(title=title, segments=segments), model_name(settings)
            except Exception:
                logger.info("Cloud script was not usable. Reading the mail directly.")
    if settings.get("script_backend") != "extractive" and settings.get("llm_provider") == "ollama":
        try:
            return compose_script(
                threads,
                backend="ollama",
                ollama_url=settings["ollama_url"],
                model=settings["script_model"],
                fallback_model=settings["script_model_fallback"],
                title=title,
            )
        except Exception:
            logger.info("Ollama did not return a script. Reading the mail directly.")
    from inbox_brief.script.compose import compose_extractive

    return compose_extractive(threads, title=title, max_segments=limit), "extractive"


def _podcast_prompt(threads, title, question, style, limit) -> str:
    from inbox_brief.script.compose import _catalog

    style_line = {
        "quick": "Keep it to a short brief.",
        "deep": "Cover the chain in more turns, still without adding anything.",
        "action": "Lead with dates, requests, and what people said they would do.",
    }.get(style, "Keep it to a short brief.")
    question_line = f"The listener asked: {question}" if question.strip() else "The listener asked for the chain as it stands."
    return f"Title: {title}\n{question_line}\n{style_line}\nAt most {limit} segments.\n\n{_catalog(threads)}"


def _focus(messages, question: str, style: str):
    tokens = {token.lower() for token in question.split() if len(token) > 2}

    def score(message):
        text = f"{message.subject} {message.clean_body}".lower()
        overlap = sum(1 for token in tokens if token in text)
        action = 1 if style == "action" and any(word in text for word in ("wednesday", "thursday", "friday", "monday", "asked", "confirmed", "arrive", "will")) else 0
        return (overlap, action, message.date or "")

    return sorted(messages, key=score, reverse=True)


def generate_overview(
    settings: dict,
    *,
    question: str = "",
    style: str = "full",
    length: str = "full",
    voice_preset: str | None = None,
    scope: str = "full",
) -> str:
    """Read every non-noise email in the review period, in full, most significant chain first."""
    from inbox_brief.overview import (
        OVERVIEW_CHAIN_ID,
        compose_overview,
        covered_overview_ids,
        overview_selection,
        period_label,
    )
    from inbox_brief.settings import apply_voice_preset
    from inbox_brief.store import inbox_chains

    if style not in {"quick", "deep", "action", "full"}:
        style = "full"
    if style == "full":
        length = "full"
    elif length not in {"short", "medium", "long"}:
        length = "short"
    if scope not in {"full", "changed"}:
        scope = "full"
    working = dict(settings)
    if voice_preset:
        working["voice_preset"] = voice_preset
        working = apply_voice_preset(working)
    chains = inbox_chains(working, "")
    covered = covered_overview_ids() if scope == "changed" else set()
    selected = overview_selection(chains, covered_ids=covered, scope=scope, question=question)
    if scope == "changed" and covered and not selected:
        raise RuntimeError("Nothing new since the last overview.")
    if not selected:
        raise RuntimeError("No mail in this review period.")
    needed = [message_id for chain in selected for message_id in chain["message_ids"]]
    by_id = message_map(needed)
    email_count = len({message_id for message_id in needed if message_id in by_id})
    script = compose_overview(
        selected,
        by_id,
        email_count=email_count,
        period=working.get("review_period") or "week",
        style=style,
        fresh=scope == "changed" and bool(covered),
    )
    script = finish_script(script, by_id)
    if not script.segments:
        raise RuntimeError("The neutrality guard removed every line. Nothing unsupported was left to read.")
    for segment in script.segments:
        if not segment.source_ids:
            raise RuntimeError("A transcript line lost its source email.")
    engine = resolve_engine(working["tts_engine"], working["dia_url"])
    try:
        rendered = synthesize(engine, script.segments, working)
    except SpeechError as exc:
        if engine != "kokoro" and working["tts_fallback"] == "kokoro" and working.get("voice_preset") != "my_voice":
            logger.warning("Voice engine %s failed (%s). Falling back to Kokoro.", engine, exc)
            rendered = synthesize("kokoro", script.segments, working)
            engine = "kokoro"
        else:
            raise
    payload = script.to_dict()
    payload["dia_prompt"] = format_dia(script.segments)
    payload["engine_detail"] = rendered.detail
    payload["question"] = question
    payload["style"] = style
    payload["overview"] = True
    payload["period_label"] = period_label(working.get("review_period") or "week")
    segments = []
    for segment, (start, end) in zip(script.segments, rendered.timings):
        item = segment.to_dict()
        item["speaker_name"] = HOSTS[segment.speaker]
        item["start_ms"] = start
        item["end_ms"] = end
        segments.append(item)
    spoken = [by_id[message_id] for message_id in needed if message_id in by_id]
    through = max((message.date for message in spoken if message.date), default="")
    title = script.title or "Full inbox overview"
    return save_episode(
        title=title,
        brief_date=_brief_date(spoken, now_in(working["timezone"]).date().isoformat()),
        status="ready",
        error=None,
        engine=engine,
        script_model="extractive",
        script=payload,
        audio=rendered.audio,
        mime=rendered.mime,
        segments=segments,
        chain_id=OVERVIEW_CHAIN_ID,
        question=question,
        style=style,
        length=length,
        covered_ids=[message.id for message in spoken],
        covered_through=through,
    )


def _brief_date(messages, fallback: str) -> str:
    dates = [message.date for message in messages if message.date]
    if not dates:
        return fallback
    try:
        when = datetime.fromisoformat(max(dates).replace("Z", "+00:00"))
    except ValueError:
        return fallback
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.date().isoformat()
