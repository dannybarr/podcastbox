"""Chains are deduped, filtered, linked by topic, and searchable."""

from datetime import datetime, timezone
from pathlib import Path

from inbox_brief.curate import ask_chains, build_chains, suggest_links
from inbox_brief.domain import ParsedMessage
from inbox_brief.ingest.noise import noise_reason
from inbox_brief.ingest.parse import parse_path

NOW = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def _load(folder: Path) -> list:
    messages = []
    for path in sorted(folder.glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    return messages


def _chains(messages):
    return build_chains(messages, now=NOW, period="week")


def test_separate_atlas_threads_become_one_chain(fixtures: Path):
    chains = _chains(_load(fixtures))
    atlas = [chain for chain in chains if chain["project"] == "Atlas"]
    assert len(atlas) == 1
    chain = atlas[0]
    assert chain["message_count"] >= 8
    assert chain["recommended"] is True
    assert "Project Atlas" in chain["reason"]
    assert "people" in chain["reason"]
    assert "messages" in chain["reason"]
    names = {person["name"] for person in chain["participants"]}
    assert {"Sarah Chen", "Tom Adler", "Priya Shah", "Luis Ortega", "Mina Okonkwo", "David Cho"} <= names


def test_homepage_stays_a_separate_chain(fixtures: Path):
    chains = _chains(_load(fixtures))
    heroes = [chain for chain in chains if "homepage" in chain["title"].lower() or "hero" in chain["title"].lower()]
    assert len(heroes) == 1
    assert heroes[0]["project"] != "Atlas"
    assert heroes[0]["message_count"] >= 4
    assert {person["name"] for person in heroes[0]["participants"]} >= {
        "Priya Shah",
        "Luis Ortega",
        "Owen Blake",
        "Amina Yusuf",
    }


def test_low_value_mail_never_becomes_a_chain(fixtures: Path):
    messages = {message.message_id: message for message in _load(fixtures)}
    kwargs = {"drop_newsletters": True, "drop_noreply": True, "extra_patterns": []}
    assert noise_reason(messages["receipt-1@supplies.example"], **kwargs) == "receipt"
    assert noise_reason(messages["reminder-1@tasks.example"], **kwargs) == "reminder"
    assert noise_reason(messages["note-1@ci.example"], **kwargs) == "notification"
    assert noise_reason(messages["quick-1@northline.example"], **kwargs) == "quick note"
    assert noise_reason(messages["cal-accept-1@meet.example"], **kwargs) == "calendar"
    assert noise_reason(messages["news-1@digest.example"], **kwargs) == "list-unsubscribe header"
    chains = _chains(list(messages.values()))
    blob = " ".join(chain["title"] + chain["reason"] + chain["search_text"] for chain in chains).lower()
    for banned in ("receipt", "timesheet", "build 188", "unsubscribe", "friday review"):
        assert banned not in blob


def test_provider_thread_ids_join_messages_the_headers_do_not():
    left = ParsedMessage(
        id="p1",
        message_id="p1@example",
        from_name="Ada",
        from_addr="ada@example",
        to_addr="bo@example",
        subject="Zebra docking fee",
        date="2026-10-17T09:00:00+00:00",
        clean_body="The zebra docking fee is 40 pounds and Ada will pay it Friday.",
        raw_body="",
        provider_thread_id="gmail-thread-99",
    )
    right = ParsedMessage(
        id="p2",
        message_id="p2@example",
        from_name="Bo",
        from_addr="bo@example",
        to_addr="ada@example",
        subject="Paint for the south wall",
        date="2026-10-17T10:00:00+00:00",
        clean_body="Bo ordered grey paint for the south wall and it arrives Monday.",
        raw_body="",
        provider_thread_id="gmail-thread-99",
    )
    chains = _chains([left, right])
    assert len(chains) == 1
    assert chains[0]["message_count"] == 2


def test_ask_finds_a_topic_and_a_person(fixtures: Path):
    chains = _chains(_load(fixtures))
    atlas = ask_chains(chains, "update on Atlas")
    assert atlas
    assert atlas[0]["project"] == "Atlas"
    priya = ask_chains(chains, "my communications with Priya")
    assert priya
    assert all(
        any(person["name"] == "Priya Shah" for person in chain["participants"])
        for chain in priya
    )


def test_a_model_can_link_threads_the_embeddings_leave_apart():
    left = ParsedMessage(
        id="m1",
        message_id="m1@example",
        from_name="Ada",
        from_addr="ada@example",
        to_addr="bo@example",
        subject="Zebra docking fee",
        date="2026-10-17T09:00:00+00:00",
        clean_body="The zebra docking fee is 40 pounds and Ada will pay it Friday.",
        raw_body="",
    )
    right = ParsedMessage(
        id="m2",
        message_id="m2@example",
        from_name="Bo",
        from_addr="bo@example",
        to_addr="ada@example",
        subject="Paint for the south wall",
        date="2026-10-17T10:00:00+00:00",
        clean_body="Bo ordered grey paint for the south wall and it arrives Monday.",
        raw_body="",
    )
    alone = _chains([left, right])
    assert len(alone) == 2

    def linker(_threads):
        return [("m1", "m2")]

    linked = build_chains([left, right], now=NOW, period="week", linker=linker)
    assert len(linked) == 1
    assert suggest_links({left.id: [left], right.id: [right]}, {"llm_provider": "ollama", "ollama_url": "http://127.0.0.1:9"}) == []


def test_upload_dedupes_and_the_key_stays_on_the_server(client, fixtures: Path):
    path = fixtures / "07-atlas-ship.eml"
    payload = path.read_bytes()
    first = client.post("/api/ingest/upload", files={"files": ("07-atlas-ship.eml", payload, "message/rfc822")})
    second = client.post("/api/ingest/upload", files={"files": ("07-atlas-ship.eml", payload, "message/rfc822")})
    assert first.status_code == 200
    assert second.json()["duplicate"] == 1
    saved = client.put(
        "/api/settings",
        json={"llm_provider": "openai", "llm_model": "gpt-4o-mini", "llm_api_key": "sk-test-secret", "review_period": "week"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["llm_api_key"] == ""
    assert body["llm_api_key_set"] is True
    assert "sk-test-secret" not in saved.text
    again = client.get("/api/settings")
    assert again.json()["llm_api_key"] == ""
    assert again.json()["llm_provider"] == "openai"


def test_ask_and_podcast_and_mcp_round_trip(client, fixtures: Path, monkeypatch):
    for path in sorted(fixtures.glob("*.eml")):
        with path.open("rb") as handle:
            response = client.post("/api/ingest/upload", files={"files": (path.name, handle, "message/rfc822")})
        assert response.status_code == 200, response.text
    chains = client.get("/api/chains").json()["chains"]
    assert chains
    assert all(chain["recommended"] for chain in chains)
    assert any(chain["project"] == "Atlas" for chain in chains)
    asked = client.get("/api/chains", params={"q": "update on Atlas"}).json()["chains"]
    assert asked[0]["project"] == "Atlas"
    missing = client.get("/api/connect/gmail")
    assert missing.status_code == 400
    assert "CLIENT_ID" in missing.json()["detail"]
    outlook = client.post("/api/ingest/graph")
    assert outlook.status_code == 400
    assert "not connected" in outlook.json()["detail"].lower()

    from inbox_brief.audio.wav import concat, duration_ms, read_wav, write_wav
    from inbox_brief.domain import RenderResult
    from inbox_brief.tts.engines import tone_wav

    def fake_synthesize(engine, segments, settings):
        del engine, settings
        pieces, timings, cursor, rate = [], [], 0, 8000
        for index, _segment in enumerate(segments):
            _rate, samples = read_wav(tone_wav(0.2, rate=rate, frequency=440 + index * 30))
            span = duration_ms(len(samples), rate)
            timings.append((cursor, cursor + span))
            cursor += span
            pieces.append(samples)
        return RenderResult(audio=write_wav(concat(pieces), rate), mime="audio/wav", timings=timings, engine="kokoro", detail="test")

    monkeypatch.setattr("inbox_brief.pipeline.synthesize", fake_synthesize)
    monkeypatch.setattr("inbox_brief.pipeline.resolve_engine", lambda *_args, **_kwargs: "kokoro")
    client.put("/api/settings", json={"script_backend": "extractive", "voice_preset": "kokoro_british"})
    atlas = next(chain for chain in client.get("/api/chains").json()["chains"] if chain["project"] == "Atlas")
    from inbox_brief.db import get_settings
    from inbox_brief.pipeline import generate_podcast

    episode_id = generate_podcast(
        get_settings(),
        atlas["id"],
        question="What did they say about the ship date?",
        style="quick",
        length="short",
        voice_preset="kokoro_british",
    )
    episode = client.get(f"/api/episodes/{episode_id}").json()
    assert episode["chain_id"] == atlas["id"]
    assert episode["segments"]
    for segment in episode["segments"]:
        assert segment["source_ids"]
    listed = client.get("/api/podcasts").json()["podcasts"]
    assert any(item["id"] == episode_id for item in listed)
    removed = client.delete(f"/api/podcasts/{episode_id}")
    assert removed.status_code == 200
    assert all(item["id"] != episode_id for item in client.get("/api/podcasts").json()["podcasts"])
    restored = client.post(f"/api/podcasts/{episode_id}/restore")
    assert restored.status_code == 200
    assert any(item["id"] == episode_id for item in client.get("/api/podcasts").json()["podcasts"])

    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = [tool["name"] for tool in tools.json()["result"]["tools"]]
    assert "list_messages" in names
    assert "search_chains" in names
    found = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "search_chains", "arguments": {"query": "update on Atlas"}}},
    )
    import json

    payload = json.loads(found.json()["result"]["content"][0]["text"])
    assert payload["chains"][0]["project"] == "Atlas"
