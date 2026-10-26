"""Write demo/transcript.json from the sample mailbox.

Audio is optional. Pass --audio after the Kokoro ONNX files are on disk.
Dia itself is rendered by the GPU service, not by this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from inbox_brief.config import fixtures_dir
from inbox_brief.domain import HOSTS
from inbox_brief.ingest.noise import noise_reason
from inbox_brief.ingest.parse import parse_path
from inbox_brief.ingest.thread import thread_messages
from inbox_brief.script.compose import compose_extractive, finish_script
from inbox_brief.tts.format import format_dia


def build_script():
    messages = []
    for path in sorted(fixtures_dir().glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    kept = [
        message
        for message in messages
        if noise_reason(message, drop_newsletters=True, drop_noreply=True, extra_patterns=[]) is None
        and message.clean_body.strip()
    ]
    threads = thread_messages(kept)
    script = compose_extractive(threads, title="Brief for 16 October")
    return finish_script(script, {message.id: message for message in kept}), {message.id: message for message in kept}


def write_transcript(
    demo: Path,
    timings: list[tuple[int, int]] | None,
    audio_file: str,
    engine: str,
    detail: str,
    transcript_name: str = "transcript.json",
) -> None:
    script, messages = build_script()
    demo.mkdir(parents=True, exist_ok=True)
    segments = []
    for index, segment in enumerate(script.segments):
        start, end = timings[index] if timings else (0, 0)
        segments.append(
            {
                "speaker": segment.speaker,
                "speaker_name": HOSTS[segment.speaker],
                "text": segment.text,
                "delivery": segment.delivery,
                "nonverbal": segment.nonverbal,
                "exaggeration": segment.exaggeration,
                "source_ids": segment.source_ids,
                "source_message_ids": [messages[source_id].message_id for source_id in segment.source_ids],
                "start_ms": start,
                "end_ms": end,
            }
        )
    payload = {
        "title": script.title,
        "brief_date": "2026-10-16",
        "engine": engine,
        "engine_detail": detail,
        "script_model": "extractive",
        "audio_file": audio_file,
        "notes": script.notes,
        "dia_prompt": format_dia(script.segments),
        "segments": segments,
    }
    (demo / transcript_name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    if transcript_name == "transcript.json":
        (demo / "dia-prompt.txt").write_text(payload["dia_prompt"] + "\n", encoding="utf-8")
    print(f"Wrote {demo / transcript_name} with {len(segments)} segments.")


def render_kokoro(demo: Path, *, american: bool = False) -> None:
    from inbox_brief.settings import DEFAULTS, kokoro_lang_code, kokoro_phoneme_lang
    from inbox_brief.audio.wav import concat, duration_ms, read_wav, silence, to_mp3, write_wav
    from inbox_brief.config import kokoro_model_path, kokoro_voices_path
    from inbox_brief.tts.engines import _float_to_wav
    from inbox_brief.tts.format import kokoro_speed, plain_text
    from kokoro_onnx import Kokoro

    model = kokoro_model_path()
    voices = kokoro_voices_path()
    if model is None or voices is None:
        raise SystemExit("Kokoro ONNX files are not in models/kokoro.")
    script, _messages = build_script()
    kokoro = Kokoro(str(model), str(voices))
    pieces = []
    timings = []
    cursor = 0
    rate = None
    if american:
        voice_for = {"S1": "af_bella", "S2": "am_michael"}
        lang = "en-us"
        stem = "kokoro-ab"
        transcript_name = "transcript.json"
    else:
        voice_for = {"S1": DEFAULTS["kokoro_voice_s1"], "S2": DEFAULTS["kokoro_voice_s2"]}
        lang = kokoro_phoneme_lang(DEFAULTS["kokoro_lang"])
        stem = "kokoro-british"
        transcript_name = "transcript-british.json"
    detail = f"kokoro-onnx {voice_for['S1']} + {voice_for['S2']} lang {kokoro_lang_code(lang)}"
    for index, segment in enumerate(script.segments):
        samples, sample_rate = kokoro.create(
            plain_text(segment),
            voice=voice_for[segment.speaker],
            speed=kokoro_speed(segment),
            lang=lang,
        )
        chunk_rate, pcm = read_wav(_float_to_wav(samples, sample_rate))
        if rate is None:
            rate = chunk_rate
        span = duration_ms(len(pcm), rate)
        timings.append((cursor, cursor + span))
        cursor += span
        pieces.append(pcm)
        if index != len(script.segments) - 1:
            gap = silence(180, rate)
            pieces.append(gap)
            cursor += duration_ms(len(gap), rate)
    assert rate is not None
    wav = write_wav(concat(pieces), rate)
    (demo / f"{stem}.wav").write_bytes(wav)
    mp3 = to_mp3(wav)
    audio_file = f"{stem}.wav"
    if mp3:
        (demo / f"{stem}.mp3").write_bytes(mp3)
        audio_file = f"{stem}.mp3"
    write_transcript(demo, timings, audio_file, "kokoro", detail, transcript_name)
    print(f"Rendered {audio_file} ({cursor} ms).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", default=str(Path(__file__).resolve().parents[3] / "demo"))
    parser.add_argument("--audio", action="store_true")
    parser.add_argument("--american", action="store_true", help="Render the American af_bella / am_michael take.")
    args = parser.parse_args()
    demo = Path(args.demo)
    if args.audio:
        render_kokoro(demo, american=args.american)
    else:
        write_transcript(demo, None, "", "kokoro", "script only")


if __name__ == "__main__":
    main()
