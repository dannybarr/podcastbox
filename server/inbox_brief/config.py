"""Runtime configuration.

Infrastructure URLs come from the environment so Docker can point at
sibling services. Editorial settings live in the database and are layered
on top of these defaults by the settings store.
"""

from __future__ import annotations

import os
from pathlib import Path


def _path(name: str, default: str) -> Path:
    return Path(os.environ.get(name, default)).expanduser().resolve()


def data_dir() -> Path:
    path = _path("INBOX_BRIEF_DATA_DIR", "./data")
    path.mkdir(parents=True, exist_ok=True)
    return path


def fixtures_dir() -> Path:
    return _path("INBOX_BRIEF_FIXTURES_DIR", str(Path(__file__).resolve().parents[2] / "fixtures"))


def demo_dir() -> Path:
    return _path("INBOX_BRIEF_DEMO_DIR", str(Path(__file__).resolve().parents[2] / "demo"))


def kokoro_model_path() -> Path | None:
    raw = os.environ.get("INBOX_BRIEF_KOKORO_MODEL", "")
    if raw:
        return Path(raw)
    candidate = Path(__file__).resolve().parents[2] / "models" / "kokoro" / "kokoro-v1.0.onnx"
    return candidate if candidate.exists() else None


def kokoro_voices_path() -> Path | None:
    raw = os.environ.get("INBOX_BRIEF_KOKORO_VOICES", "")
    if raw:
        return Path(raw)
    candidate = Path(__file__).resolve().parents[2] / "models" / "kokoro" / "voices-v1.0.bin"
    return candidate if candidate.exists() else None


def seed_on_start() -> bool:
    return os.environ.get("INBOX_BRIEF_SEED", "1") != "0"


def service_urls() -> dict[str, str]:
    return {
        "ollama_url": os.environ.get("INBOX_BRIEF_OLLAMA_URL", "http://127.0.0.1:11434"),
        "dia_url": os.environ.get("INBOX_BRIEF_DIA_URL", "http://127.0.0.1:8871"),
        "speaches_url": os.environ.get("INBOX_BRIEF_SPEACHES_URL", "http://127.0.0.1:8969"),
    }
