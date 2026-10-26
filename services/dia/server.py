"""Local Dia-1.6B dialogue server.

One request is one short exchange already marked with [S1] and [S2].
The process never calls a cloud model. Weights are read from the Hugging
Face cache, which is filled on first launch and then reused offline.
"""

from __future__ import annotations

import base64
import io
import os
import tempfile
import threading
from pathlib import Path

# Hugging Face's client phones home for telemetry unless this is set.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

MODEL_ID = os.environ.get("DIA_MODEL", "nari-labs/Dia-1.6B-0626")
app = FastAPI(title="PodcastBox Dia")
_model = None
_lock = threading.Lock()


class DialogueRequest(BaseModel):
    text: str = Field(min_length=1)
    seed: int = 42
    max_tokens: int | None = None
    # Optional clip of the owner's own voice. The API only sends this after
    # the owner confirms the recording is theirs. It is not written to disk
    # beyond a temp file for this request.
    audio_prompt_b64: str | None = None


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "loaded": _model is not None,
        "model": MODEL_ID,
    }


@app.post("/v1/dialogue")
def dialogue(request: DialogueRequest) -> Response:
    model = _load()
    torch.manual_seed(request.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(request.seed)
    max_tokens = request.max_tokens or min(2000, max(700, len(request.text) * 6))
    prompt_path = _write_prompt(request.audio_prompt_b64)
    if prompt_path is not None:
        # The prompt itself occupies part of the token budget. Leave room
        # for the brief that follows it.
        max_tokens = min(3072, max_tokens + 900)
    try:
        audio = model.generate(
            request.text,
            max_tokens=max_tokens,
            cfg_scale=float(os.environ.get("DIA_CFG", "3.0")),
            temperature=float(os.environ.get("DIA_TEMPERATURE", "1.5")),
            top_p=0.90,
            cfg_filter_top_k=50,
            use_torch_compile=False,
            verbose=False,
            audio_prompt=prompt_path,
        )
    finally:
        if prompt_path is not None:
            Path(prompt_path).unlink(missing_ok=True)
    if isinstance(audio, list):
        audio = audio[0]
    if audio is None or getattr(audio, "size", 1) == 0:
        raise HTTPException(500, "Dia produced no audio for that exchange.")
    buffer = io.BytesIO()
    import soundfile as sf

    sf.write(buffer, audio, 44100, format="WAV")
    return Response(buffer.getvalue(), media_type="audio/wav")


def _write_prompt(encoded: str | None) -> str | None:
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise HTTPException(400, "The voice clip could not be read.") from exc
    if not raw:
        raise HTTPException(400, "The voice clip could not be read.")
    handle = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    handle.write(raw)
    handle.close()
    return handle.name


def _load():
    global _model
    with _lock:
        if _model is None:
            from dia.model import Dia

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            dtype = "float16" if device.type == "cuda" else "float32"
            _model = Dia.from_pretrained(MODEL_ID, compute_dtype=dtype, device=device)
        return _model
