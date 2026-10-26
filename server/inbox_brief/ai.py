"""Script and embedding calls for Ollama, OpenAI, Anthropic, or a compatible server.

Ollama stays on a private address. A cloud provider is used only after the
owner saves a key in Settings. Mail text is sent to that provider and nowhere else.
"""

from __future__ import annotations

import httpx

from inbox_brief.privacy import assert_private_base_url

_OPENAI = "https://api.openai.com/v1"
_ANTHROPIC = "https://api.anthropic.com"
_DEFAULT_MODEL = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "compatible": "gpt-4o-mini",
}


def chat(settings: dict, system: str, user: str, *, timeout: float = 60) -> str | None:
    """Return the model's text, or None when no provider is reachable."""
    provider = settings.get("llm_provider") or "ollama"
    try:
        if provider == "ollama":
            return _ollama_chat(settings, system, user, timeout)
        if not settings.get("llm_api_key"):
            return None
        if provider == "anthropic":
            return _anthropic_chat(settings, system, user, timeout)
        return _openai_chat(settings, system, user, timeout)
    except Exception:
        return None


def model_name(settings: dict) -> str:
    provider = settings.get("llm_provider") or "ollama"
    if settings.get("llm_model"):
        return str(settings["llm_model"])
    if provider == "ollama":
        return str(settings.get("script_model") or "qwen3:8b")
    return _DEFAULT_MODEL.get(provider, "gpt-4o-mini")


def _ollama_chat(settings: dict, system: str, user: str, timeout: float) -> str:
    root = assert_private_base_url(settings["ollama_url"])
    response = httpx.post(
        f"{root}/api/chat",
        json={
            "model": model_name(settings),
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json().get("message", {}).get("content") or "")


def _openai_chat(settings: dict, system: str, user: str, timeout: float) -> str:
    base = _openai_base(settings)
    response = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {settings['llm_api_key']}"},
        json={
            "model": model_name(settings),
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return str(response.json()["choices"][0]["message"]["content"])


def _anthropic_chat(settings: dict, system: str, user: str, timeout: float) -> str:
    response = httpx.post(
        f"{_ANTHROPIC}/v1/messages",
        headers={
            "x-api-key": settings["llm_api_key"],
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": model_name(settings),
            "max_tokens": 1800,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    blocks = response.json().get("content") or []
    return "".join(block.get("text", "") for block in blocks if block.get("type") == "text")


def _openai_base(settings: dict) -> str:
    provider = settings.get("llm_provider")
    if provider == "compatible":
        base = str(settings.get("llm_base_url") or "").rstrip("/")
        if not base:
            raise ValueError("Add the OpenAI-compatible base URL in Settings.")
        return base
    custom = str(settings.get("llm_base_url") or "").rstrip("/")
    return custom or _OPENAI
