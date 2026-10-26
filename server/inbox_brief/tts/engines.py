"""Pluggable local voices.

Dia-1.6B is the default when it reports a CUDA device. Kokoro, via Speaches
or an in-process ONNX file, is the CPU fallback. Chatterbox is an optional
adapter: Resemble's package watermarks every file, so it is not installed
or selected unless someone opts in.
"""

from __future__ import annotations

import array
import io
import wave

import httpx

from inbox_brief.audio.wav import concat, duration_ms, read_wav, silence, to_mp3, write_wav
from inbox_brief.config import kokoro_model_path, kokoro_voices_path
from inbox_brief.domain import HOSTS, RenderResult, SegmentDraft
from inbox_brief.privacy import assert_private_base_url
from inbox_brief.settings import kokoro_lang_code, kokoro_phoneme_lang
from inbox_brief.tts.format import dia_chunks, format_chatterbox, kokoro_speed, plain_text
from inbox_brief.tts.voice_clip import VoiceClip, audio_prompt_b64, dialogue_text, load_clip


class SpeechError(RuntimeError):
    pass


def dia_health(base_url: str) -> dict | None:
    try:
        root = assert_private_base_url(base_url)
        response = httpx.get(f"{root}/health", timeout=3)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def speaches_health(base_url: str) -> bool:
    try:
        root = assert_private_base_url(base_url)
        response = httpx.get(f"{root}/v1/models", timeout=3)
        return response.status_code < 500
    except Exception:
        return False


def onnx_available() -> bool:
    return kokoro_model_path() is not None and kokoro_voices_path() is not None


def resolve_engine(engine: str, dia_url: str) -> str:
    if engine == "kokoro":
        return "kokoro"
    if engine == "chatterbox":
        return "chatterbox"
    if engine == "dia":
        return "dia"
    health = dia_health(dia_url)
    if health and health.get("device") == "cuda":
        return "dia"
    return "kokoro"


class DiaEngine:
    name = "dia"

    def __init__(self, base_url: str, seed: int, clip: VoiceClip | None = None) -> None:
        self.base_url = assert_private_base_url(base_url)
        self.seed = seed
        self.clip = clip

    def synthesize(self, segments: list[SegmentDraft]) -> RenderResult:
        chunks = dia_chunks(segments)
        if not chunks:
            raise SpeechError("There is nothing to read.")
        pieces: list[array.array] = []
        timings: list[tuple[int, int]] = []
        rate: int | None = None
        cursor = 0
        for index, chunk in enumerate(chunks):
            wav = self._speak(chunk)
            chunk_rate, samples = read_wav(wav)
            if rate is None:
                rate = chunk_rate
            elif chunk_rate != rate:
                raise SpeechError("Dia returned mixed sample rates.")
            weights = [max(len(plain_text(segment)), 1) for segment in chunk]
            total = sum(weights)
            chunk_ms = duration_ms(len(samples), rate)
            used = 0
            for offset, (segment, weight) in enumerate(zip(chunk, weights)):
                del segment
                if offset == len(chunk) - 1:
                    span = chunk_ms - used
                else:
                    span = int(chunk_ms * weight / total)
                    used += span
                timings.append((cursor, cursor + max(span, 1)))
                cursor += max(span, 1)
            pieces.append(samples)
            if index != len(chunks) - 1:
                gap = silence(220, rate)
                pieces.append(gap)
                cursor += duration_ms(len(gap), rate)
        assert rate is not None
        wav_bytes = write_wav(concat(pieces), rate)
        detail = "nari-labs/Dia-1.6B-0626"
        if self.clip is not None:
            detail = f"{detail} audio-prompt {HOSTS[self.clip.host]}"
        return _package(wav_bytes, timings, self.name, detail)

    def _speak(self, chunk: list[SegmentDraft]) -> bytes:
        if self.clip is None:
            text = dialogue_text(chunk, host="S1", transcript=None)
            payload: dict = {"text": text, "seed": self.seed}
        else:
            text = dialogue_text(chunk, host=self.clip.host, transcript=self.clip.transcript)
            payload = {
                "text": text,
                "seed": self.seed,
                "audio_prompt_b64": audio_prompt_b64(self.clip.wav),
            }
        try:
            response = httpx.post(
                f"{self.base_url}/v1/dialogue",
                json=payload,
                timeout=1800,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechError(f"Dia did not render this exchange. {exc}") from exc
        if not response.content:
            raise SpeechError("Dia returned empty audio.")
        return response.content


class KokoroEngine:
    name = "kokoro"

    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def synthesize(self, segments: list[SegmentDraft]) -> RenderResult:
        if speaches_health(self.settings["speaches_url"]):
            return self._via_speaches(segments)
        if onnx_available():
            return self._via_onnx(segments)
        raise SpeechError(
            "Kokoro is not available. Start Speaches, or download the Kokoro ONNX "
            "files into models/kokoro. See the README."
        )

    def _via_speaches(self, segments: list[SegmentDraft]) -> RenderResult:
        root = assert_private_base_url(self.settings["speaches_url"])
        # Speaches has no accent field. It phonemises from the voice id:
        # bf_emma and bm_george are en-gb (Kokoro lang code b).
        return self._stitch(
            segments,
            lambda segment: self._speaches_line(root, segment),
            self._detail("speaches kokoro"),
        )

    def _speaches_line(self, root: str, segment: SegmentDraft) -> bytes:
        voice = self.settings["kokoro_voice_s1"] if segment.speaker == "S1" else self.settings["kokoro_voice_s2"]
        response = httpx.post(
            f"{root}/v1/audio/speech",
            json={
                "model": self.settings["kokoro_model"],
                "voice": voice,
                "input": plain_text(segment),
                "response_format": "wav",
                "speed": kokoro_speed(segment),
            },
            timeout=300,
        )
        response.raise_for_status()
        return response.content

    def _via_onnx(self, segments: list[SegmentDraft]) -> RenderResult:
        from kokoro_onnx import Kokoro

        model = kokoro_model_path()
        voices = kokoro_voices_path()
        assert model is not None and voices is not None
        kokoro = Kokoro(str(model), str(voices))

        lang = kokoro_phoneme_lang(self.settings.get("kokoro_lang", "en-gb"))

        def line(segment: SegmentDraft) -> bytes:
            voice = self.settings["kokoro_voice_s1"] if segment.speaker == "S1" else self.settings["kokoro_voice_s2"]
            samples, rate = kokoro.create(
                plain_text(segment),
                voice=voice,
                speed=kokoro_speed(segment),
                lang=lang,
            )
            return _float_to_wav(samples, rate)

        return self._stitch(segments, line, self._detail("kokoro-onnx"))

    def _detail(self, via: str) -> str:
        code = kokoro_lang_code(self.settings.get("kokoro_lang", "en-gb"))
        return (
            f"{via} {self.settings['kokoro_voice_s1']} + {self.settings['kokoro_voice_s2']} "
            f"lang {code}"
        )

    def _stitch(self, segments, line, detail: str) -> RenderResult:
        pieces: list[array.array] = []
        timings: list[tuple[int, int]] = []
        rate: int | None = None
        cursor = 0
        for index, segment in enumerate(segments):
            chunk_rate, samples = read_wav(line(segment))
            if rate is None:
                rate = chunk_rate
            elif chunk_rate != rate:
                raise SpeechError("Kokoro returned mixed sample rates.")
            span = duration_ms(len(samples), rate)
            timings.append((cursor, cursor + max(span, 1)))
            cursor += max(span, 1)
            pieces.append(samples)
            if index != len(segments) - 1:
                gap = silence(160, rate)
                pieces.append(gap)
                cursor += duration_ms(len(gap), rate)
        assert rate is not None
        return _package(write_wav(concat(pieces), rate), timings, self.name, detail)


class ChatterboxEngine:
    """Optional single-speaker engine with an exaggeration control.

    Not the default. The published Resemble package adds a PerTh watermark,
    and the model needs a reference clip per host, which is voice cloning.
    """

    name = "chatterbox"

    def __init__(self, settings: dict) -> None:
        self.settings = settings

    def synthesize(self, segments: list[SegmentDraft]) -> RenderResult:
        try:
            import torch
            from chatterbox.tts import ChatterboxTTS
        except ImportError as exc:
            raise SpeechError(
                "Chatterbox is not installed. Dia is the default dialogue engine. "
                "To opt in, install chatterbox-tts in the API image and set the "
                "voice engine to chatterbox. Its package watermarks output."
            ) from exc
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = ChatterboxTTS.from_pretrained(device=device)
        pieces: list[array.array] = []
        timings: list[tuple[int, int]] = []
        rate = int(getattr(model, "sr", 24000))
        cursor = 0
        for index, segment in enumerate(segments):
            text, exaggeration = format_chatterbox(segment)
            ref = self.settings.get("chatterbox_ref_s1") if segment.speaker == "S1" else self.settings.get("chatterbox_ref_s2")
            kwargs = {"exaggeration": exaggeration}
            if ref:
                kwargs["audio_prompt_path"] = ref
            wav = model.generate(text, **kwargs)
            samples = _tensor_to_samples(wav)
            span = duration_ms(len(samples), rate)
            timings.append((cursor, cursor + max(span, 1)))
            cursor += max(span, 1)
            pieces.append(samples)
            if index != len(segments) - 1:
                gap = silence(160, rate)
                pieces.append(gap)
                cursor += duration_ms(len(gap), rate)
        return _package(write_wav(concat(pieces), rate), timings, self.name, f"chatterbox {device}")


def synthesize(engine: str, segments: list[SegmentDraft], settings: dict) -> RenderResult:
    if engine == "dia":
        clip = None
        if settings.get("voice_preset") == "my_voice":
            clip = load_clip()
            if clip is None:
                raise SpeechError("Record your own voice in Settings, and confirm it is yours, before generating.")
            host = settings.get("my_voice_host") or clip.host
            if host in HOSTS and host != clip.host:
                clip = VoiceClip(
                    wav=clip.wav,
                    transcript=clip.transcript,
                    host=host,
                    duration_s=clip.duration_s,
                    sample_rate=clip.sample_rate,
                    original_sample_rate=clip.original_sample_rate,
                    consented_at=clip.consented_at,
                )
        return DiaEngine(settings["dia_url"], int(settings["dia_seed"]), clip).synthesize(segments)
    if engine == "chatterbox":
        return ChatterboxEngine(settings).synthesize(segments)
    if engine == "kokoro":
        return KokoroEngine(settings).synthesize(segments)
    raise SpeechError(f"Unknown voice engine {engine!r}.")


def _package(wav_bytes: bytes, timings: list[tuple[int, int]], engine: str, detail: str) -> RenderResult:
    mp3 = to_mp3(wav_bytes)
    if mp3:
        return RenderResult(audio=mp3, mime="audio/mpeg", timings=timings, engine=engine, detail=detail)
    return RenderResult(audio=wav_bytes, mime="audio/wav", timings=timings, engine=engine, detail=detail)


def _float_to_wav(samples, rate: int) -> bytes:
    pcm = array.array("h", (max(-32767, min(32767, int(float(sample) * 32767))) for sample in samples))
    return write_wav(pcm, int(rate))


def _tensor_to_samples(wav) -> array.array:
    if hasattr(wav, "detach"):
        wav = wav.detach().cpu().float().numpy()
    data = wav.reshape(-1)
    return array.array("h", (max(-32767, min(32767, int(float(sample) * 32767))) for sample in data))


def tone_wav(seconds: float = 0.2, rate: int = 8000, frequency: float = 440.0) -> bytes:
    """A tiny audible tone used by tests, not by the product."""
    import math

    count = int(rate * seconds)
    samples = array.array(
        "h",
        (int(0.2 * 32767 * math.sin(2 * math.pi * frequency * index / rate)) for index in range(count)),
    )
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return buffer.getvalue()
