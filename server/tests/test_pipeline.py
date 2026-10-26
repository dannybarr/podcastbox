import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from inbox_brief.audio.wav import concat, duration_ms, read_wav, silence, write_wav
from inbox_brief.domain import RenderResult
from inbox_brief.tts.engines import tone_wav


@pytest.fixture()
def client(tmp_path, monkeypatch, fixtures):
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INBOX_BRIEF_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("INBOX_BRIEF_DEMO_DIR", str(tmp_path / "demo"))
    monkeypatch.setenv("INBOX_BRIEF_SEED", "0")
    monkeypatch.setenv("INBOX_BRIEF_SCHEDULE", "0")
    os.environ["INBOX_BRIEF_DATA_DIR"] = str(tmp_path)
    from inbox_brief.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_upload_threads_and_generate_a_playable_episode(client, fixtures, monkeypatch):
    def fake_synthesize(engine, segments, settings):
        del engine, settings
        pieces = []
        timings = []
        cursor = 0
        rate = 8000
        for index, _segment in enumerate(segments):
            _rate, samples = read_wav(tone_wav(0.25, rate=rate, frequency=440 + index * 40))
            span = duration_ms(len(samples), rate)
            timings.append((cursor, cursor + span))
            cursor += span
            pieces.append(samples)
            if index != len(segments) - 1:
                gap = silence(40, rate)
                pieces.append(gap)
                cursor += duration_ms(len(gap), rate)
        wav = write_wav(concat(pieces), rate)
        return RenderResult(audio=wav, mime="audio/wav", timings=timings, engine="kokoro", detail="test-tone")

    monkeypatch.setattr("inbox_brief.pipeline.synthesize", fake_synthesize)
    monkeypatch.setattr("inbox_brief.pipeline.resolve_engine", lambda *_args, **_kwargs: "kokoro")

    for path in sorted(fixtures.glob("*.eml")):
        with path.open("rb") as handle:
            response = client.post(
                "/api/ingest/upload",
                files={"files": (path.name, handle, "message/rfc822")},
            )
        assert response.status_code == 200, response.text

    saved = client.put("/api/settings", json={"script_backend": "extractive", "schedule_enabled": False})
    assert saved.status_code == 200, saved.text
    from inbox_brief.db import get_settings
    from inbox_brief.pipeline import generate_episode

    episode_id = generate_episode(get_settings(), "all")
    episode = client.get(f"/api/episodes/{episode_id}").json()
    assert episode["status"] == "ready"
    assert episode["segments"]
    for segment in episode["segments"]:
        assert segment["source_ids"]
        for source_id in segment["source_ids"]:
            mail = client.get(f"/api/messages/{source_id}")
            assert mail.status_code == 200
            assert mail.json()["clean_body"]
    audio = client.get(f"/api/episodes/{episode['id']}/audio")
    assert audio.status_code == 200
    assert audio.content[:4] == b"RIFF"
    spoken = " ".join(segment["text"] for segment in episode["segments"])
    assert "Sarah Chen" in spoken
    assert "crush your roadmap" not in spoken
    graph = client.post("/api/ingest/graph")
    assert graph.status_code == 400
    assert "not connected" in graph.json()["detail"].lower()


def test_clock_helper_uses_a_real_zone():
    assert datetime(2026, 10, 18, 8, 0, tzinfo=ZoneInfo("Europe/London"))
