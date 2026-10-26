"""Editorial settings stored in SQLite, with service URLs from the environment."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, available_timezones

from inbox_brief.config import service_urls

# Kokoro's own lang codes: b is British English, a is American English.
# espeak, and kokoro-onnx, spell those "en-gb" and "en-us".
KOKORO_LANG_CODES = {
    "en-gb": "b",
    "en-us": "a",
}
KOKORO_LANG_ALIASES = {
    "en-gb": "en-gb",
    "b": "en-gb",
    "en-us": "en-us",
    "a": "en-us",
}

DEFAULTS: dict = {
    "timezone": "Europe/London",
    "tz_chosen": False,
    "schedule_enabled": True,
    "schedule_time": "07:30",
    "window_hours": 36,
    "tts_engine": "auto",
    "tts_fallback": "kokoro",
    "dia_seed": 42,
    "kokoro_model": "speaches-ai/Kokoro-82M-v1.0-ONNX",
    "kokoro_lang": "en-gb",
    "kokoro_voice_s1": "bf_emma",
    "kokoro_voice_s2": "bm_george",
    "voice_preset": "kokoro_british",
    "my_voice_host": "S1",
    "script_backend": "ollama",
    "script_model": "qwen3:8b",
    "script_model_fallback": "llama3.2",
    "drop_newsletters": True,
    "drop_noreply": True,
    "extra_noise_patterns": [],
    "imap_host": "",
    "imap_port": 993,
    "imap_user": "",
    "imap_password": "",
    "imap_folder": "INBOX",
    "imap_ssl": True,
    "chatterbox_ref_s1": "",
    "chatterbox_ref_s2": "",
    "llm_provider": "ollama",
    "llm_base_url": "",
    "llm_model": "",
    "llm_api_key": "",
    "review_period": "week",
    "mcp_mail_urls": [],
}

_ENGINES = {"auto", "dia", "kokoro", "chatterbox"}
_BACKENDS = {"ollama", "extractive"}
_LLM_PROVIDERS = {"ollama", "openai", "anthropic", "compatible"}
_PERIODS = {"day", "week", "month"}
_PRESETS = {
    "kokoro_british": ("kokoro", "en-gb", "bf_emma", "bm_george"),
    "kokoro_american": ("kokoro", "en-us", "af_bella", "am_michael"),
    "dia": ("dia", None, None, None),
    "my_voice": ("dia", None, None, None),
}


def kokoro_phoneme_lang(value: str) -> str:
    """Return the espeak lang kokoro-onnx expects. Unknown values stay British."""
    return KOKORO_LANG_ALIASES.get(str(value).strip().lower(), "en-gb")


def kokoro_lang_code(value: str) -> str:
    """Kokoro's single-letter code: b British, a American."""
    return KOKORO_LANG_CODES[kokoro_phoneme_lang(value)]


def migrate_stored_settings(stored: dict | None) -> dict:
    """Move an untouched American default onto the British voices.

    A database saved before the accent setting existed has no kokoro_lang.
    The old shipped pair was af_bella and am_michael. Those rows pick up
    bf_emma and bm_george. Any other saved pair is left alone, and the
    accent is inferred from the first voice id.
    """
    raw = dict(stored or {})
    if "kokoro_lang" not in raw:
        first = raw.get("kokoro_voice_s1", "af_bella")
        second = raw.get("kokoro_voice_s2", "am_michael")
        if first == "af_bella" and second == "am_michael":
            raw["kokoro_voice_s1"] = DEFAULTS["kokoro_voice_s1"]
            raw["kokoro_voice_s2"] = DEFAULTS["kokoro_voice_s2"]
            raw["kokoro_lang"] = "en-gb"
        else:
            raw["kokoro_lang"] = "en-gb" if str(first).startswith("b") else "en-us"
    if "voice_preset" not in raw:
        engine = raw.get("tts_engine", "auto")
        lang = kokoro_phoneme_lang(str(raw.get("kokoro_lang", "en-gb")))
        if engine == "dia":
            raw["voice_preset"] = "dia"
        elif lang == "en-us" or raw.get("kokoro_voice_s1") == "af_bella":
            raw["voice_preset"] = "kokoro_american"
        else:
            raw["voice_preset"] = "kokoro_british"
    # The first shipped default was UTC, and Settings did not offer a timezone.
    # Move that untouched value to Europe/London. A later explicit save sets
    # tz_chosen so a chosen UTC stays UTC.
    if not raw.get("tz_chosen") and raw.get("timezone") in (None, "", "UTC"):
        raw["timezone"] = "Europe/London"
    return raw


def effective_settings(stored: dict | None) -> dict:
    merged = dict(DEFAULTS)
    if stored:
        merged.update(migrate_stored_settings(stored))
    merged.update(service_urls())
    return validate_settings(merged)


def validate_settings(raw: dict) -> dict:
    settings = dict(DEFAULTS)
    settings.update({key: raw[key] for key in raw if key in DEFAULTS or key in service_urls()})
    settings.update(service_urls())
    if settings["timezone"] not in available_timezones():
        settings["timezone"] = "Europe/London"
    settings["tz_chosen"] = bool(settings.get("tz_chosen"))
    settings["schedule_time"] = _clock(str(settings["schedule_time"]))
    settings["schedule_enabled"] = bool(settings["schedule_enabled"])
    settings["window_hours"] = min(168, max(1, int(settings["window_hours"])))
    if settings["tts_engine"] not in _ENGINES:
        settings["tts_engine"] = "auto"
    if settings["tts_fallback"] not in {"kokoro", "none"}:
        settings["tts_fallback"] = "kokoro"
    settings["dia_seed"] = int(settings["dia_seed"])
    settings["kokoro_lang"] = kokoro_phoneme_lang(str(settings.get("kokoro_lang", "en-gb")))
    settings["kokoro_voice_s1"] = str(settings.get("kokoro_voice_s1") or DEFAULTS["kokoro_voice_s1"]).strip()
    settings["kokoro_voice_s2"] = str(settings.get("kokoro_voice_s2") or DEFAULTS["kokoro_voice_s2"]).strip()
    if settings["script_backend"] not in _BACKENDS:
        settings["script_backend"] = "ollama"
    settings["drop_newsletters"] = bool(settings["drop_newsletters"])
    settings["drop_noreply"] = bool(settings["drop_noreply"])
    patterns = settings["extra_noise_patterns"]
    if isinstance(patterns, str):
        patterns = [part.strip() for part in patterns.split(",") if part.strip()]
    if not isinstance(patterns, list):
        patterns = []
    settings["extra_noise_patterns"] = [str(item).strip() for item in patterns if str(item).strip()]
    settings["imap_port"] = int(settings["imap_port"])
    settings["imap_ssl"] = bool(settings["imap_ssl"])
    settings["imap_folder"] = settings["imap_folder"] or "INBOX"
    if settings.get("llm_provider") not in _LLM_PROVIDERS:
        settings["llm_provider"] = "ollama"
    settings["llm_base_url"] = str(settings.get("llm_base_url") or "").strip().rstrip("/")
    settings["llm_model"] = str(settings.get("llm_model") or "").strip()
    settings["llm_api_key"] = str(settings.get("llm_api_key") or "")
    if settings.get("review_period") not in _PERIODS:
        settings["review_period"] = "week"
    urls = settings.get("mcp_mail_urls") or []
    if isinstance(urls, str):
        urls = [part.strip() for part in urls.split(",") if part.strip()]
    if not isinstance(urls, list):
        urls = []
    settings["mcp_mail_urls"] = [str(item).strip() for item in urls if str(item).strip()][:8]
    return apply_voice_preset(settings)


def apply_voice_preset(settings: dict) -> dict:
    """The saved voice choice decides the engine and the Kokoro pair."""
    preset = str(settings.get("voice_preset") or "")
    if preset not in _PRESETS:
        preset = "kokoro_british"
    settings["voice_preset"] = preset
    engine, lang, first, second = _PRESETS[preset]
    settings["tts_engine"] = engine
    if lang is not None:
        settings["kokoro_lang"] = lang
        settings["kokoro_voice_s1"] = first
        settings["kokoro_voice_s2"] = second
    host = str(settings.get("my_voice_host") or "S1")
    settings["my_voice_host"] = host if host in {"S1", "S2"} else "S1"
    return settings


def public_settings(settings: dict) -> dict:
    hidden = dict(settings)
    hidden["imap_password_set"] = bool(settings.get("imap_password"))
    hidden["imap_password"] = ""
    hidden["llm_api_key_set"] = bool(settings.get("llm_api_key"))
    hidden["llm_api_key"] = ""
    return hidden


def should_run(now: datetime, schedule_time: str, last_date: str | None, enabled: bool) -> bool:
    if not enabled:
        return False
    hour, minute = (int(part) for part in schedule_time.split(":"))
    return now.hour == hour and now.minute == minute and last_date != now.date().isoformat()


def now_in(timezone_name: str) -> datetime:
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = ZoneInfo("Europe/London")
    return datetime.now(zone)


def _clock(value: str) -> str:
    parts = value.strip().split(":")
    if len(parts) != 2:
        return "07:30"
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return "07:30"
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return "07:30"
    return f"{hour:02d}:{minute:02d}"
