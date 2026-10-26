"""Concatenate 16-bit PCM waves without an audio library."""

from __future__ import annotations

import array
import io
import shutil
import subprocess
import wave


def read_wav(data: bytes) -> tuple[int, array.array]:
    with wave.open(io.BytesIO(data), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError("Only 16-bit WAV files can be stitched.")
    samples = array.array("h")
    samples.frombytes(frames)
    if samples.itemsize != 2:
        raise ValueError("Unexpected PCM width.")
    # wave returns native endian. array.frombytes uses native endian too.
    if channels == 2:
        mixed = array.array("h", ((samples[index] + samples[index + 1]) // 2 for index in range(0, len(samples) - 1, 2)))
        samples = mixed
    elif channels != 1:
        raise ValueError(f"Unsupported channel count {channels}.")
    return rate, samples


def write_wav(samples: array.array, rate: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()


def silence(milliseconds: int, rate: int) -> array.array:
    count = int(rate * max(milliseconds, 0) / 1000)
    return array.array("h", [0] * count)


def concat(parts: list[array.array]) -> array.array:
    output = array.array("h")
    for part in parts:
        output.extend(part)
    return output


def to_mp3(wav_bytes: bytes) -> bytes | None:
    if shutil.which("ffmpeg") is None:
        return None
    completed = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-codec:a",
            "libmp3lame",
            "-qscale:a",
            "4",
            "-f",
            "mp3",
            "pipe:1",
        ],
        input=wav_bytes,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout:
        return None
    return completed.stdout


def duration_ms(sample_count: int, rate: int) -> int:
    if rate <= 0:
        return 0
    return int(sample_count * 1000 / rate)
