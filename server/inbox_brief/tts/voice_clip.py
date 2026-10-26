"""A locally stored clip of the owner's own voice, used as a Dia audio prompt.

The file never leaves this machine except as a request to the local Dia
service, which itself must be a private address. The owner has to confirm
the clip is their own voice before it is kept.
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import wave
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from inbox_brief.config import data_dir
from inbox_brief.domain import HOSTS, SegmentDraft
from inbox_brief.tts.format import format_dia

# About eight seconds at a calm pace. The same words are shown in Settings
# and prepended to the Dia transcript so the audio prompt stays aligned.
VOICE_SCRIPT = (
    "This is my voice for PodcastBox. I recorded it myself, in a quiet room, for use as one host."
)

GUIDANCE = (
    "Use a quiet room.",
    "Record at 16 kHz or higher.",
    "No music and no other voices.",
    "Read the script once, for 5 to 10 seconds.",
)

MIN_SECONDS = 5.0
MAX_SECONDS = 10.0
MIN_SAMPLE_RATE = 16000
STORE_RATE = 44100


class VoiceClipError(ValueError):
    pass


@dataclass(frozen=True)
class VoiceClip:
    wav: bytes
    transcript: str
    host: str
    duration_s: float
    sample_rate: int
    original_sample_rate: int
    consented_at: str

    def status(self) -> dict:
        return {
            "script": self.transcript,
            "host": self.host,
            "has_clip": True,
            "duration_s": round(self.duration_s, 2),
            "sample_rate": self.sample_rate,
            "original_sample_rate": self.original_sample_rate,
            "consented_at": self.consented_at,
            "guidance": list(GUIDANCE),
        }


def empty_status(host: str = "S1") -> dict:
    return {
        "script": VOICE_SCRIPT,
        "host": host if host in HOSTS else "S1",
        "has_clip": False,
        "duration_s": None,
        "sample_rate": None,
        "original_sample_rate": None,
        "consented_at": None,
        "guidance": list(GUIDANCE),
    }


def clip_dir() -> Path:
    path = data_dir() / "voice"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wav_path() -> Path:
    return clip_dir() / "mine.wav"


def _meta_path() -> Path:
    return clip_dir() / "mine.json"


def load_clip() -> VoiceClip | None:
    wav_path = _wav_path()
    meta_path = _meta_path()
    if not wav_path.exists() or not meta_path.exists():
        return None
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if not meta.get("consent"):
        return None
    return VoiceClip(
        wav=wav_path.read_bytes(),
        transcript=str(meta.get("transcript") or VOICE_SCRIPT),
        host=meta.get("host") if meta.get("host") in HOSTS else "S1",
        duration_s=float(meta.get("duration_s") or 0),
        sample_rate=int(meta.get("sample_rate") or STORE_RATE),
        original_sample_rate=int(meta.get("original_sample_rate") or 0),
        consented_at=str(meta.get("consented_at") or ""),
    )


def delete_clip() -> None:
    _wav_path().unlink(missing_ok=True)
    _meta_path().unlink(missing_ok=True)


def consent_accepted(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def save_clip(data: bytes, filename: str, *, consent: object, host: str) -> VoiceClip:
    if not consent_accepted(consent):
        raise VoiceClipError("Confirm that this is your own voice before saving the clip.")
    if host not in HOSTS:
        raise VoiceClipError("Choose Mina or Owen as the host for this clip.")
    if not data:
        raise VoiceClipError("That file has no audio.")
    suffix = Path(filename or "clip.wav").suffix.lower() or ".wav"
    if suffix not in {".wav", ".mp3", ".m4a", ".ogg", ".webm", ".flac", ".aac"}:
        suffix = ".wav"
    original_rate, _duration = _probe(data, suffix)
    if original_rate < MIN_SAMPLE_RATE:
        raise VoiceClipError(
            f"The clip is {original_rate} Hz. Record at 16 kHz or higher, with no music."
        )
    wav = _to_wav(data, suffix)
    _rate, duration = _wav_info(wav)
    if duration < MIN_SECONDS or duration > MAX_SECONDS:
        raise VoiceClipError(
            f"The clip is {duration:.1f} seconds. Read the script for 5 to 10 seconds."
        )
    consented_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    meta = {
        "consent": True,
        "consented_at": consented_at,
        "host": host,
        "transcript": VOICE_SCRIPT,
        "sample_rate": STORE_RATE,
        "original_sample_rate": original_rate,
        "duration_s": round(duration, 3),
    }
    _wav_path().write_bytes(wav)
    _meta_path().write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    stored = load_clip()
    if stored is None:
        raise VoiceClipError("The clip could not be stored.")
    return stored


def dialogue_text(segments: list[SegmentDraft], *, host: str, transcript: str | None) -> str:
    """Map the chosen host onto Dia's [S1] and keep the other host as [S2].

    Dia's audio prompt is one speaker, and that speaker is [S1]. The lines
    stay in their original order. When the owner chose Owen, his lines are
    tagged [S1] and Mina's are tagged [S2], so her voice stays the stock one.
    """
    spoken = _retag(segments, host)
    body = format_dia(spoken)
    if not transcript:
        return body
    prefix = f"[S1] {transcript.strip()}"
    if body.startswith("[S1]"):
        return f"{prefix} {body[len('[S1]'):].lstrip()}"
    return f"{prefix} {body}"


def audio_prompt_b64(wav: bytes) -> str:
    return base64.b64encode(wav).decode("ascii")


def _retag(segments: list[SegmentDraft], host: str) -> list[SegmentDraft]:
    if host != "S2":
        return list(segments)
    swapped: list[SegmentDraft] = []
    for segment in segments:
        speaker = "S1" if segment.speaker == "S2" else "S2"
        swapped.append(replace(segment, speaker=speaker))
    return swapped


def _probe(data: bytes, suffix: str) -> tuple[int, float | None]:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "a:0",
                    "-show_entries",
                    "stream=sample_rate,duration",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    str(src),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VoiceClipError("ffmpeg is required to store a voice clip.") from exc
    if proc.returncode != 0:
        raise VoiceClipError("That file does not contain audio.")
    payload = json.loads(proc.stdout or "{}")
    streams = payload.get("streams") or []
    if not streams:
        raise VoiceClipError("That file does not contain audio.")
    rate = int(streams[0].get("sample_rate") or 0)
    duration = streams[0].get("duration") or (payload.get("format") or {}).get("duration")
    return rate, float(duration) if duration not in (None, "N/A", "") else None


def _to_wav(data: bytes, suffix: str) -> bytes:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        dest = Path(tmp) / "out.wav"
        src.write_bytes(data)
        try:
            proc = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", str(STORE_RATE), "-c:a", "pcm_s16le", str(dest)],
                capture_output=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise VoiceClipError("ffmpeg is required to store a voice clip.") from exc
        if proc.returncode != 0 or not dest.exists():
            raise VoiceClipError("That file could not be read as audio.")
        return dest.read_bytes()


def _wav_info(data: bytes) -> tuple[int, float]:
    with wave.open(io.BytesIO(data)) as handle:
        rate = handle.getframerate()
        frames = handle.getnframes()
    if rate <= 0 or frames <= 0:
        raise VoiceClipError("That file does not contain audio.")
    return rate, frames / rate
