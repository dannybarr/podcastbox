"""My voice: consent, duration, sample rate, and the Dia prompt."""

import base64
import io
import math
import wave

import httpx
from fastapi.testclient import TestClient

from inbox_brief.domain import SegmentDraft
from inbox_brief.settings import effective_settings
from inbox_brief.tts.engines import synthesize
from inbox_brief.tts.voice_clip import VOICE_SCRIPT, VoiceClipError, dialogue_text, save_clip


def _wav(seconds: float, rate: int = 16000, frequency: float = 180.0) -> bytes:
    frames = int(seconds * rate)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        samples = bytearray()
        for index in range(frames):
            value = int(8000 * math.sin(2 * math.pi * frequency * index / rate))
            samples += int(value).to_bytes(2, "little", signed=True)
        handle.writeframes(samples)
    return buffer.getvalue()


def _lines() -> list[SegmentDraft]:
    return [
        SegmentDraft(speaker="S1", text="Sarah Chen wrote: Thursday 22 October.", source_ids=["a"]),
        SegmentDraft(speaker="S2", text="Tom Adler replied: The dock is booked from 7am.", source_ids=["b"], nonverbal="chuckle"),
    ]


def test_a_clip_is_refused_without_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    try:
        save_clip(_wav(7), "mine.wav", consent=False, host="S1")
    except VoiceClipError as exc:
        assert "own voice" in str(exc)
    else:
        raise AssertionError("consent was not required")
    assert not (tmp_path / "voice" / "mine.wav").exists()


def test_short_and_low_rate_clips_are_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    try:
        save_clip(_wav(3), "short.wav", consent=True, host="S1")
    except VoiceClipError as exc:
        assert "5 to 10" in str(exc)
    else:
        raise AssertionError("short clip was stored")
    try:
        save_clip(_wav(7, rate=8000), "low.wav", consent=True, host="S1")
    except VoiceClipError as exc:
        assert "16 kHz" in str(exc)
    else:
        raise AssertionError("8 kHz clip was stored")


def test_a_placeholder_clip_is_stored_and_deleted(tmp_path, monkeypatch, fixtures):
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INBOX_BRIEF_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("INBOX_BRIEF_DEMO_DIR", str(tmp_path / "demo"))
    monkeypatch.setenv("INBOX_BRIEF_SEED", "0")
    monkeypatch.setenv("INBOX_BRIEF_SCHEDULE", "0")
    from inbox_brief.main import create_app

    client = TestClient(create_app())
    refused = client.post(
        "/api/voice/mine",
        files={"file": ("mine.wav", _wav(7), "audio/wav")},
        data={"consent": "false", "host": "S1"},
    )
    assert refused.status_code == 400
    saved = client.post(
        "/api/voice/mine",
        files={"file": ("mine.wav", _wav(7, rate=22050), "audio/wav")},
        data={"consent": "true", "host": "S2"},
    )
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["has_clip"] is True
    assert body["host"] == "S2"
    assert body["script"] == VOICE_SCRIPT
    assert 5 <= body["duration_s"] <= 10
    assert body["original_sample_rate"] == 22050
    assert body["consented_at"]
    audio = client.get("/api/voice/mine/audio")
    assert audio.status_code == 200
    assert audio.headers["content-type"].startswith("audio/wav")
    assert (tmp_path / "voice" / "mine.wav").exists()
    assert client.delete("/api/voice/mine").status_code == 204
    assert client.get("/api/voice/mine/audio").status_code == 404
    assert not (tmp_path / "voice" / "mine.wav").exists()


def test_saved_voice_choice_selects_the_engine():
    british = effective_settings({"voice_preset": "kokoro_british"})
    assert british["tts_engine"] == "kokoro"
    assert british["kokoro_voice_s1"] == "bf_emma"
    assert british["kokoro_voice_s2"] == "bm_george"
    american = effective_settings({"voice_preset": "kokoro_american", "kokoro_voice_s1": "bf_emma"})
    assert american["tts_engine"] == "kokoro"
    assert american["kokoro_lang"] == "en-us"
    assert american["kokoro_voice_s1"] == "af_bella"
    assert american["kokoro_voice_s2"] == "am_michael"
    dia = effective_settings({"voice_preset": "dia"})
    assert dia["tts_engine"] == "dia"
    mine = effective_settings({"voice_preset": "my_voice", "my_voice_host": "S2"})
    assert mine["tts_engine"] == "dia"
    assert mine["my_voice_host"] == "S2"


def test_owen_uses_the_prompt_and_mina_stays_stock():
    text = dialogue_text(_lines(), host="S2", transcript=VOICE_SCRIPT)
    assert text.startswith(f"[S1] {VOICE_SCRIPT}")
    assert "[S2] Sarah Chen wrote" in text
    assert "[S1] (chuckle) Tom Adler replied" in text
    mina = dialogue_text(_lines(), host="S1", transcript=VOICE_SCRIPT)
    assert mina.startswith(f"[S1] {VOICE_SCRIPT} Sarah Chen wrote")
    assert "[S2] (chuckle) Tom Adler replied" in mina


def test_generation_sends_the_clip_as_the_dia_audio_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    save_clip(_wav(7), "mine.wav", consent="true", host="S1")
    captured: dict = {}

    class _Response:
        content = _wav(0.4, rate=8000)

        def raise_for_status(self) -> None:
            return None

    def fake_post(url, json, timeout):
        del timeout
        captured["url"] = url
        captured["json"] = json
        return _Response()

    monkeypatch.setattr(httpx, "post", fake_post)
    settings = effective_settings({"voice_preset": "my_voice", "my_voice_host": "S1", "dia_url": "http://127.0.0.1:8871"})
    result = synthesize("dia", _lines(), settings)
    assert result.engine == "dia"
    assert "Mina" in result.detail
    assert captured["url"] == "http://127.0.0.1:8871/v1/dialogue"
    assert captured["json"]["text"].startswith(f"[S1] {VOICE_SCRIPT}")
    assert base64.b64decode(captured["json"]["audio_prompt_b64"]).startswith(b"RIFF")


def test_preview_serves_the_bundled_clip(tmp_path, monkeypatch, fixtures):
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "kokoro-british.mp3").write_bytes(b"preview-bytes")
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INBOX_BRIEF_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("INBOX_BRIEF_DEMO_DIR", str(demo))
    monkeypatch.setenv("INBOX_BRIEF_SEED", "0")
    monkeypatch.setenv("INBOX_BRIEF_SCHEDULE", "0")
    from inbox_brief.main import create_app

    client = TestClient(create_app())
    response = client.get("/api/voices/preview/kokoro_british")
    assert response.status_code == 200
    assert response.content == b"preview-bytes"
    assert client.get("/api/voices/preview/nope").status_code == 404
