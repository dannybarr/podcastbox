from inbox_brief.domain import ParsedMessage, Script, SegmentDraft
from inbox_brief.ingest.parse import parse_path
from inbox_brief.ingest.thread import thread_messages
from inbox_brief.privacy import ExternalServiceError, assert_private_base_url
from inbox_brief.script.compose import compose_extractive, finish_script
from inbox_brief.script.guard import apply_guard, repair_speakers
from inbox_brief.settings import effective_settings, kokoro_lang_code, migrate_stored_settings, should_run
from inbox_brief.tts.format import dia_chunks, format_chatterbox, format_dia, plain_text
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest


def _message(body: str, message_id: str = "m1") -> ParsedMessage:
    return ParsedMessage(
        id=message_id,
        message_id=message_id,
        from_name="Sarah Chen",
        from_addr="sarah.chen@northline.example",
        to_addr="launch@northline.example",
        subject="Thursday ship date",
        date="2026-10-16T08:14:00+00:00",
        clean_body=body,
        raw_body=body,
    )


def test_guard_removes_judgement_that_is_not_in_the_email():
    source = _message("Can we move the ship date to Thursday 22 October?")
    script = Script(
        title="Brief",
        segments=[
            SegmentDraft(
                speaker="S1",
                text="Sarah Chen wrote: Can we move the ship date to Thursday 22 October? This is a great idea.",
                source_ids=["m1"],
                delivery="curious",
                nonverbal="chuckle",
            )
        ],
    )
    checked, notes = apply_guard(script, {"m1": source})
    assert len(checked.segments) == 1
    assert "great" not in checked.segments[0].text.lower()
    assert "Thursday 22 October" in checked.segments[0].text
    assert checked.segments[0].nonverbal == "chuckle"
    assert notes


def test_guard_keeps_a_word_when_the_sender_used_it():
    source = _message("We should delay the crates until Wednesday.")
    script = Script(
        title="Brief",
        segments=[
            SegmentDraft(
                speaker="S1",
                text="Sarah Chen wrote: We should delay the crates until Wednesday.",
                source_ids=["m1"],
            )
        ],
    )
    checked, notes = apply_guard(script, {"m1": source})
    assert checked.segments[0].text.startswith("Sarah Chen wrote")
    assert "should" in checked.segments[0].text
    assert notes == []


def test_guard_drops_advice_and_unsupported_claims():
    source = _message("The crates arrive Wednesday.")
    script = Script(
        title="Brief",
        segments=[
            SegmentDraft(
                speaker="S1",
                text="You should tell the vendor to hurry. The cafeteria is closed today.",
                source_ids=["m1"],
            ),
            SegmentDraft(speaker="S2", text="Owen thinks the plan is exciting.", source_ids=[]),
        ],
    )
    checked, _notes = apply_guard(script, {"m1": source})
    assert checked.segments == []


def test_speakers_alternate_from_s1():
    segments = repair_speakers(
        [
            SegmentDraft(speaker="S2", text="One.", source_ids=["m1"]),
            SegmentDraft(speaker="S2", text="Two.", source_ids=["m1"]),
        ]
    )
    assert [segment.speaker for segment in segments] == ["S1", "S2"]


def test_dia_prompt_carries_emotion_cues_without_changing_the_words():
    segments = [
        SegmentDraft(
            speaker="S1",
            text="Sarah Chen wrote: Can we move the ship date to Thursday?",
            source_ids=["m1"],
            delivery="curious",
            nonverbal=None,
            exaggeration=0.4,
        ),
        SegmentDraft(
            speaker="S2",
            text="Tom Adler replied: The loading dock is booked from 7am.",
            source_ids=["m2"],
            nonverbal="chuckle",
            exaggeration=0.42,
        ),
    ]
    prompt = format_dia(segments)
    assert prompt.startswith("[S1] ")
    assert "[S2] (chuckle) " in prompt
    assert prompt.endswith("[S1]")
    assert "great idea" not in prompt
    spoken, exaggeration = format_chatterbox(segments[1])
    assert spoken.startswith("[chuckle] ")
    assert exaggeration == pytest.approx(0.42)
    assert "(chuckle)" not in plain_text(segments[1])
    assert len(dia_chunks(segments)) == 1


def test_extractive_brief_stays_sourced_and_neutral(fixtures):
    messages = []
    for path in sorted(fixtures.glob("*.eml")):
        messages.extend(parse_path(str(path)))
    from inbox_brief.ingest.noise import noise_reason

    kept = [
        message
        for message in messages
        if noise_reason(message, drop_newsletters=True, drop_noreply=True, extra_patterns=[]) is None
    ]
    threads = thread_messages(kept)
    script = compose_extractive(threads, title="Brief for 16 October")
    checked = finish_script(script, {message.id: message for message in kept})
    assert checked.segments
    blob = " ".join(segment.text for segment in checked.segments)
    assert "crush your roadmap" not in blob
    assert "standup" not in blob.lower()
    assert "Can we move the ship date" not in blob or "Sarah Chen" in blob
    for segment in checked.segments:
        assert segment.source_ids
        assert "great" not in segment.text.lower()
        assert "should" not in segment.text.lower() or "should" in " ".join(
            checked_source(kept, segment.source_ids)
        )


def checked_source(messages, ids: list[str]) -> str:
    return " ".join(message.clean_body for message in messages if message.id in ids).lower()


def test_model_urls_must_stay_on_the_machine():
    assert assert_private_base_url("http://ollama:11434").startswith("http://ollama:11434")
    assert assert_private_base_url("http://127.0.0.1:8871")
    with pytest.raises(ExternalServiceError):
        assert_private_base_url("https://api.openai.com/v1")
    with pytest.raises(ExternalServiceError):
        assert_private_base_url("https://api.elevenlabs.io")


def test_daily_clock_fires_once_per_local_day():
    morning = datetime(2026, 10, 18, 7, 30, tzinfo=ZoneInfo("UTC"))
    assert should_run(morning, "07:30", None, True)
    assert not should_run(morning, "07:30", "2026-10-18", True)
    assert not should_run(morning, "07:30", None, False)
    assert not should_run(morning.replace(minute=31), "07:30", None, True)


def test_kokoro_defaults_to_british_english():
    settings = effective_settings({})
    assert settings["voice_preset"] == "kokoro_british"
    assert settings["tts_engine"] == "kokoro"
    assert settings["kokoro_lang"] == "en-gb"
    assert kokoro_lang_code(settings["kokoro_lang"]) == "b"
    assert settings["kokoro_voice_s1"] == "bf_emma"
    assert settings["kokoro_voice_s2"] == "bm_george"


def test_kokoro_lang_code_a_stays_american_when_chosen():
    settings = effective_settings(
        {"kokoro_lang": "a", "kokoro_voice_s1": "af_bella", "kokoro_voice_s2": "am_michael"}
    )
    assert settings["kokoro_lang"] == "en-us"
    assert kokoro_lang_code("en-us") == "a"
    assert settings["kokoro_voice_s1"] == "af_bella"


def test_untouched_american_voices_migrate_to_british():
    migrated = migrate_stored_settings({"kokoro_voice_s1": "af_bella", "kokoro_voice_s2": "am_michael"})
    assert migrated["kokoro_lang"] == "en-gb"
    assert migrated["kokoro_voice_s1"] == "bf_emma"
    assert migrated["kokoro_voice_s2"] == "bm_george"
    custom = migrate_stored_settings({"kokoro_voice_s1": "af_heart", "kokoro_voice_s2": "am_adam"})
    assert custom["kokoro_voice_s1"] == "af_heart"
    assert custom["kokoro_lang"] == "en-us"
