"""Day boundaries, library movement, chain deltas, and the all-mail list."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from inbox_brief.days import annotate_chain, bucket_podcasts, day_label
from inbox_brief.settings import effective_settings, migrate_stored_settings

LONDON = ZoneInfo("Europe/London")
NOW = datetime(2026, 10, 18, 10, 0, tzinfo=LONDON)


def _episode(created_at: str, title: str) -> dict:
    return {"id": title, "title": title, "created_at": created_at, "status": "ready"}


def test_london_midnight_splits_today_from_the_library():
    episodes = [
        _episode("2026-10-17T22:30:00+00:00", "still Saturday"),
        _episode("2026-10-17T23:30:00+00:00", "just after midnight"),
    ]
    buckets = bucket_podcasts(episodes, "Europe/London", now=NOW)
    assert [item["title"] for item in buckets["today"]] == ["just after midnight"]
    assert buckets["library"][0]["date"] == "2026-10-17"
    assert buckets["library"][0]["label"] == "Sat 17 Oct 2026"
    assert buckets["library"][0]["count"] == 1
    assert day_label(datetime(2026, 10, 17).date()) == "Sat 17 Oct 2026"

    rollover = datetime(2026, 10, 18, 0, 30, tzinfo=LONDON)
    edge = bucket_podcasts(
        [
            _episode("2026-10-17T22:00:00+00:00", "before"),
            _episode("2026-10-17T23:45:00+00:00", "after"),
        ],
        "Europe/London",
        now=rollover,
    )
    assert [item["title"] for item in edge["today"]] == ["after"]
    assert edge["library"][0]["podcasts"][0]["title"] == "before"
    assert edge["library"][0]["label"] == "Sat 17 Oct 2026"


def test_untouched_utc_moves_to_london_and_a_chosen_zone_stays():
    assert migrate_stored_settings({"timezone": "UTC"})["timezone"] == "Europe/London"
    assert migrate_stored_settings({"timezone": "UTC", "tz_chosen": True})["timezone"] == "UTC"
    assert migrate_stored_settings({"timezone": "America/New_York"})["timezone"] == "America/New_York"
    assert effective_settings({"timezone": "Not/AZone"})["timezone"] == "Europe/London"
    assert effective_settings({})["timezone"] == "Europe/London"


def test_same_day_mail_does_not_resurface_and_a_later_day_does():
    chain = {"id": "c1", "message_ids": ["a", "b"], "recommended": True}
    records = [{"chain_id": "c1", "message_ids": ["a"]}]
    same = annotate_chain(
        chain,
        records,
        {"a": "2026-10-18T09:00:00+00:00", "b": "2026-10-18T15:00:00+00:00"},
        "Europe/London",
    )
    assert same["covered"] is True
    assert same["new_count"] == 0
    assert same["new_label"] == ""

    later = annotate_chain(
        chain,
        records,
        {"a": "2026-10-17T22:30:00+00:00", "b": "2026-10-17T23:30:00+00:00"},
        "Europe/London",
    )
    assert later["new_count"] == 1
    assert later["new_label"] == "New since 17 Oct 2026: 1 message"


def test_api_keeps_today_on_home_and_older_days_in_the_library(client, monkeypatch):
    monkeypatch.setattr(
        "inbox_brief.days.now_in",
        lambda _tz: datetime(2026, 10, 18, 10, 0, tzinfo=LONDON),
    )
    from inbox_brief.store import save_episode

    older = save_episode(
        title="Saturday brief",
        brief_date="2026-10-16",
        status="ready",
        error=None,
        engine="kokoro",
        script_model="extractive",
        script=None,
        audio=None,
        mime=None,
        segments=[],
        created_at="2026-10-17T15:00:00+00:00",
    )
    current = save_episode(
        title="Sunday brief",
        brief_date="2026-10-18",
        status="ready",
        error=None,
        engine="kokoro",
        script_model="extractive",
        script=None,
        audio=None,
        mime=None,
        segments=[],
        created_at="2026-10-17T23:30:00+00:00",
    )
    payload = client.get("/api/podcasts").json()
    assert "podcasts" in payload
    assert {item["id"] for item in payload["podcasts"]} >= {older, current}
    assert [item["id"] for item in payload["today"]] == [current]
    assert payload["library"][0]["label"] == "Sat 17 Oct 2026"
    assert payload["library"][0]["count"] == 1
    assert payload["library"][0]["podcasts"][0]["id"] == older
    assert payload["timezone"] == "Europe/London"
    assert all(item["id"] != current for day in payload["library"] for item in day["podcasts"])


def test_continuing_chain_keeps_its_id_and_reports_the_delta(fixtures):
    from inbox_brief.curate import build_chains
    from inbox_brief.ingest.parse import parse_path

    messages = []
    for path in sorted(fixtures.glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    earlier = [item for item in messages if item.message_id not in {"atlas-ship-5@northline.example", "atlas-ship-6@northline.example"}]
    moment = datetime(2026, 10, 18, 12, tzinfo=ZoneInfo("UTC"))
    before = next(chain for chain in build_chains(earlier, now=moment, period="week") if chain["project"] == "Atlas")
    after = next(chain for chain in build_chains(messages, now=moment, period="week") if chain["project"] == "Atlas")
    assert after["id"] == before["id"]
    assert after["message_count"] == before["message_count"] + 2
    dates = {item.id: item.date for item in messages}
    old_ids = set(before["message_ids"])
    note = annotate_chain(after, [{"chain_id": after["id"], "message_ids": sorted(old_ids)}], dates, "Europe/London")
    assert note["new_count"] == 2
    assert note["new_label"] == "New since 16 Oct 2026: 2 messages"


def _fake_voice(monkeypatch):
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


def test_changed_scope_reads_the_delta_and_full_scope_reads_the_chain(client, fixtures, monkeypatch):
    _fake_voice(monkeypatch)
    for path in sorted(fixtures.glob("*.eml")):
        with path.open("rb") as handle:
            response = client.post("/api/ingest/upload", files={"files": (path.name, handle, "message/rfc822")})
        assert response.status_code == 200, response.text
    client.put("/api/settings", json={"script_backend": "extractive", "timezone": "Europe/London"})
    atlas = next(chain for chain in client.get("/api/chains").json()["chains"] if chain["project"] == "Atlas")
    messages = {item["id"]: item for item in client.get("/api/messages").json()["messages"]}
    old_ids = [
        item
        for item in atlas["message_ids"]
        if messages[item]["date"].startswith("2026-10-16")
    ]
    new_ids = set(atlas["message_ids"]) - set(old_ids)
    assert new_ids
    from inbox_brief.store import save_episode

    save_episode(
        title="Atlas on Saturday",
        brief_date="2026-10-16",
        status="ready",
        error=None,
        engine="kokoro",
        script_model="extractive",
        script=None,
        audio=None,
        mime=None,
        segments=[{"speaker": "S1", "text": "Held.", "source_ids": [old_ids[0]], "delivery": "steady"}],
        chain_id=atlas["id"],
        covered_ids=old_ids,
        covered_through="2026-10-16T13:20:00+00:00",
        created_at="2026-10-17T15:00:00+00:00",
    )
    home = client.get("/api/chains").json()["chains"]
    surfaced = next(chain for chain in home if chain["project"] == "Atlas")
    assert surfaced["new_label"] == "New since 16 Oct 2026: 2 messages"
    assert any(chain["project"] != "Atlas" for chain in home)

    from inbox_brief.db import get_settings
    from inbox_brief.pipeline import generate_podcast

    changed_id = generate_podcast(get_settings(), atlas["id"], style="quick", length="short", scope="changed")
    changed = client.get(f"/api/episodes/{changed_id}").json()
    assert changed["segments"][0]["text"].startswith("Earlier,")
    assert set(changed["segments"][0]["source_ids"]) <= set(old_ids)
    body = {source for segment in changed["segments"][1:] for source in segment["source_ids"]}
    assert body
    assert body <= new_ids
    spoken = " ".join(segment["text"] for segment in changed["segments"]).lower()
    for banned in ("i think", "you should", "we should", "probably", "good idea"):
        assert banned not in spoken

    full_id = generate_podcast(get_settings(), atlas["id"], style="deep", length="long", scope="full")
    full = client.get(f"/api/episodes/{full_id}").json()
    full_sources = {source for segment in full["segments"] for source in segment["source_ids"]}
    assert full_sources & set(old_ids)
    assert not full["segments"][0]["text"].startswith("Earlier,")

    with pytest.raises(RuntimeError, match="Nothing new since the last podcast"):
        generate_podcast(get_settings(), atlas["id"], scope="changed")


def test_all_emails_keeps_quiet_chains_and_drops_noise(client, fixtures):
    for path in sorted(fixtures.glob("*.eml")):
        with path.open("rb") as handle:
            response = client.post("/api/ingest/upload", files={"files": (path.name, handle, "message/rfc822")})
        assert response.status_code == 200, response.text
    suggested = client.get("/api/chains").json()["chains"]
    inbox = client.get("/api/inbox").json()["chains"]
    assert len(inbox) > len(suggested)
    assert all(chain["recommended"] for chain in suggested)
    quiet = [chain for chain in inbox if not chain["recommended"]]
    assert quiet
    assert any(chain["message_count"] == 2 for chain in quiet)
    blob = " ".join(f"{chain['title']} {chain['reason']}" for chain in inbox).lower()
    for banned in ("receipt", "reminder", "notification", "unsubscribe", "no-reply", "noreply"):
        assert banned not in blob
    found = client.get("/api/inbox", params={"q": "homepage hero"}).json()["chains"]
    assert found
    assert all("hero" in chain["title"].lower() or "homepage" in chain["title"].lower() for chain in found)
    assert all(chain["project"] != "Atlas" or "hero" in chain["title"].lower() for chain in found)


def test_overview_orders_significant_chains_first(fixtures):
    from inbox_brief.ingest.parse import parse_path
    from inbox_brief.overview import overview_chains

    messages = []
    for path in sorted(fixtures.glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    moment = datetime(2026, 10, 18, 12, tzinfo=ZoneInfo("UTC"))
    chains = overview_chains(messages, now=moment, period="week")
    assert chains
    assert chains[0]["recommended"] is True
    assert chains[0]["project"] == "Atlas"
    recommended = [chain["message_count"] for chain in chains if chain["recommended"]]
    assert recommended == sorted(recommended, reverse=True)
    quiet_at = next(index for index, chain in enumerate(chains) if not chain["recommended"])
    assert all(chain["recommended"] for chain in chains[:quiet_at])
    assert quiet_at < len(chains) - 1 or not chains[quiet_at]["recommended"]


def test_overview_covers_each_chain_once():
    from inbox_brief.overview import order_overview

    chains = [
        {
            "id": "big",
            "recommended": True,
            "message_count": 4,
            "participants": [{}, {}, {}],
            "date_end": "2026-10-16",
            "message_ids": ["a", "b", "c"],
        },
        {
            "id": "big",
            "recommended": True,
            "message_count": 4,
            "participants": [{}, {}, {}],
            "date_end": "2026-10-16",
            "message_ids": ["a", "b", "c"],
        },
        {
            "id": "quiet",
            "recommended": False,
            "message_count": 2,
            "participants": [{}],
            "date_end": "2026-10-18",
            "message_ids": ["c", "d"],
        },
        {
            "id": "echo",
            "recommended": False,
            "message_count": 1,
            "participants": [{}],
            "date_end": "2026-10-18",
            "message_ids": ["a"],
        },
    ]
    ordered = order_overview(chains)
    assert [chain["id"] for chain in ordered] == ["big", "quiet"]
    assert ordered[0]["message_ids"] == ["a", "b", "c"]
    assert ordered[1]["message_ids"] == ["d"]


def test_overview_skips_noise(fixtures):
    from inbox_brief.ingest.noise import noise_reason
    from inbox_brief.ingest.parse import parse_path
    from inbox_brief.overview import overview_chains

    messages = []
    for path in sorted(fixtures.glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    moment = datetime(2026, 10, 18, 12, tzinfo=ZoneInfo("UTC"))
    chains = overview_chains(messages, now=moment, period="week")
    covered = {message_id for chain in chains for message_id in chain["message_ids"]}
    noisy = [
        message
        for message in messages
        if noise_reason(message, drop_newsletters=True, drop_noreply=True, extra_patterns=[])
    ]
    assert noisy
    assert covered.isdisjoint({message.id for message in noisy})
    blob = " ".join(chain["title"] for chain in chains).lower()
    for banned in ("receipt", "reminder", "notification", "unsubscribe", "noreply"):
        assert banned not in blob


def test_overview_full_keeps_every_sentence_and_quick_is_the_shorter_choice(fixtures):
    from inbox_brief.domain import ParsedMessage
    from inbox_brief.ingest.parse import parse_path
    from inbox_brief.overview import compose_overview, overview_chains

    messages = []
    for path in sorted(fixtures.glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    moment = datetime(2026, 10, 18, 12, tzinfo=ZoneInfo("UTC"))
    chains = overview_chains(messages, now=moment, period="week")
    by_id = {message.id: message for message in messages}
    email_count = sum(len(chain["message_ids"]) for chain in chains)
    full = compose_overview(chains, by_id, email_count=email_count, period="week", style="full")
    quick = compose_overview(chains, by_id, email_count=email_count, period="week", style="quick")
    full_text = " ".join(segment.text for segment in full.segments)
    quick_text = " ".join(segment.text for segment in quick.segments)
    assert "loading dock is booked from 7am" in full_text
    assert "Wednesday still works for the design review if we ship on Thursday" in full_text
    assert "crates arrive Wednesday" in full_text
    assert len(full_text) > len(quick_text)
    assert "Wednesday still works for the design review if we ship on Thursday" not in quick_text
    long_sentence = "The warehouse counted " + " ".join(["forty"] * 80) + " crates on Wednesday."
    long_message = ParsedMessage(
        id="long-overview",
        message_id="long-overview@northline.example",
        from_name="Mina Okonkwo",
        from_addr="mina.okonkwo@northline.example",
        to_addr="atlas@northline.example",
        subject="Crate count",
        date="2026-10-18T11:00:00+00:00",
        clean_body=long_sentence,
        raw_body=long_sentence,
    )
    script = compose_overview(
        [
            {
                "id": "long-chain",
                "title": "Crate count",
                "recommended": True,
                "message_count": 1,
                "participants": [{"name": "Mina Okonkwo", "addr": "mina.okonkwo@northline.example"}],
                "date_end": long_message.date,
                "message_ids": [long_message.id],
            }
        ],
        {long_message.id: long_message},
        email_count=1,
        period="day",
        style="full",
    )
    assert script.segments[0].text.count("forty") == 80
    assert len(script.segments[0].text) > 400


def test_overview_refresh_reads_only_what_is_new(client, fixtures, monkeypatch):
    _fake_voice(monkeypatch)
    for path in sorted(fixtures.glob("*.eml")):
        with path.open("rb") as handle:
            response = client.post("/api/ingest/upload", files={"files": (path.name, handle, "message/rfc822")})
        assert response.status_code == 200, response.text
    client.put("/api/settings", json={"script_backend": "extractive", "timezone": "Europe/London", "review_period": "week"})

    from inbox_brief.db import get_settings
    from inbox_brief.domain import ParsedMessage
    from inbox_brief.overview import overview_selection
    from inbox_brief.pipeline import generate_overview
    from inbox_brief.store import inbox_chains, upsert_messages

    settings = get_settings()
    chains = inbox_chains(settings, "")
    full = overview_selection(chains, scope="full")
    lead = full[0]
    assert lead["project"] == "Atlas"
    held = set(lead["message_ids"])
    delta = overview_selection(chains, covered_ids=held, scope="changed")
    assert lead["id"] not in {chain["id"] for chain in delta}
    assert held.isdisjoint({message_id for chain in delta for message_id in chain["message_ids"]})
    reread = overview_selection(chains, covered_ids=held, scope="full")
    assert lead["id"] in {chain["id"] for chain in reread}

    episode_id = generate_overview(settings, scope="full")
    episode = client.get(f"/api/episodes/{episode_id}").json()
    assert episode["title"] == "Full inbox overview"
    assert episode["chain_id"] == "overview"
    assert episode["style"] == "full"
    assert episode["length"] == "full"
    spoken = " ".join(segment["text"] for segment in episode["segments"])
    assert spoken.startswith(f"{client.get('/api/overview').json()['email_count']} emails this week")
    assert "first from" in episode["segments"][0]["text"]
    assert any(segment["text"].startswith("Next, from") for segment in episode["segments"][1:])
    flat = [message_id for segment in episode["segments"] for message_id in segment["source_ids"]]
    assert flat
    assert len(flat) == len(set(flat))
    assert all(segment["source_ids"] == [segment["source_ids"][0]] for segment in episode["segments"])
    mail = {item["id"]: item for item in client.get("/api/messages").json()["messages"]}
    dock = next(item for item in mail.values() if "booked from 7am" in item["clean_body"])
    dock_line = next(segment for segment in episode["segments"] if segment["source_ids"] == [dock["id"]])
    assert "Tom Adler wrote:" in dock_line["text"]
    assert "Wednesday still works for the design review" in dock_line["text"]
    assert "loading dock is booked from 7am" in dock_line["text"]
    assert "Thursday 22 October" not in dock_line["text"]
    vendor = next(
        item
        for item in mail.values()
        if "vendor confirmed the crates arrive Wednesday" in item["clean_body"] and "Project Atlas" not in item["subject"]
    )
    vendor_line = next(segment for segment in episode["segments"] if segment["source_ids"] == [vendor["id"]])
    assert "Thursday 22 October" in vendor_line["text"]
    assert "crates arrive Wednesday" in vendor_line["text"]
    hero = next(item for item in mail.values() if "cropped on the left at 1440" in item["clean_body"])
    hero_line = next(segment for segment in episode["segments"] if segment["source_ids"] == [hero["id"]])
    assert "1440" in hero_line["text"]
    assert "before Friday" in hero_line["text"]
    assert "Priya Shah wrote:" in hero_line["text"]
    for banned in ("Hi all", "Product Operations", "iPhone", "confidential"):
        assert banned not in spoken
    assert spoken.count("Can we move the ship date to Thursday 22 October") == 1

    status = client.get("/api/overview").json()
    assert status["generated"] is True
    assert status["new_count"] == 0
    assert status["episode_id"] == episode_id
    today = client.get("/api/podcasts").json()["today"]
    assert any(item["id"] == episode_id for item in today)
    home = client.get("/api/chains").json()["chains"]
    assert any(chain.get("project") == "Atlas" for chain in home)

    fresh = ParsedMessage(
        id="fresh-overview",
        message_id="fresh-overview@northline.example",
        from_name="Priya Shah",
        from_addr="priya.shah@northline.example",
        to_addr="design@northline.example",
        subject="Homepage hero follow up",
        date="2026-10-18T09:00:00+00:00",
        clean_body="Please send the full product photo before Friday.",
        raw_body="Please send the full product photo before Friday.",
    )
    robot = ParsedMessage(
        id="robot-overview",
        message_id="robot-overview@northline.example",
        from_name="Notifications",
        from_addr="noreply@northline.example",
        to_addr="design@northline.example",
        subject="Notification: build finished",
        date="2026-10-18T09:05:00+00:00",
        clean_body="Your notification is ready.",
        raw_body="Your notification is ready.",
        auto_submitted="auto-generated",
    )
    upsert_messages([fresh, robot], get_settings())
    refreshed = client.get("/api/overview").json()
    assert refreshed["generated"] is True
    assert refreshed["new_count"] >= 1
    changed_id = generate_overview(get_settings(), scope="changed")
    changed = client.get(f"/api/episodes/{changed_id}").json()
    changed_ids = {message_id for segment in changed["segments"] for message_id in segment["source_ids"]}
    assert "fresh-overview" in changed_ids
    assert "robot-overview" not in changed_ids
    assert changed_ids.isdisjoint(set(flat))
    assert "new email" in changed["segments"][0]["text"]
    caught_up = client.get("/api/overview").json()
    assert caught_up["new_count"] == 0

    with pytest.raises(RuntimeError, match="Nothing new since the last overview"):
        generate_overview(get_settings(), scope="changed")

    assert client.delete(f"/api/podcasts/{episode_id}").status_code == 200
    assert client.delete(f"/api/podcasts/{changed_id}").status_code == 200
    cleared = client.get("/api/overview").json()
    assert cleared["generated"] is False
    assert cleared["has_prior"] is False
    library = client.get("/api/podcasts").json()
    assert episode_id not in {item["id"] for item in library["today"]}
    assert all(item["id"] != episode_id for day in library["library"] for item in day["podcasts"])
