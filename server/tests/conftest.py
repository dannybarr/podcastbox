import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
# The sample mailbox is 16-18 October 2026. The review window is the last seven
# days, so API tests read that week instead of the clock on the machine.
SAMPLE_WEEK = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)


class FrozenDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return SAMPLE_WEEK.replace(tzinfo=None)
        return SAMPLE_WEEK.astimezone(tz)


@pytest.fixture()
def fixtures() -> Path:
    return FIXTURES


@pytest.fixture()
def client(tmp_path, monkeypatch, fixtures):
    monkeypatch.setenv("INBOX_BRIEF_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("INBOX_BRIEF_FIXTURES_DIR", str(fixtures))
    monkeypatch.setenv("INBOX_BRIEF_DEMO_DIR", str(tmp_path / "demo"))
    monkeypatch.setenv("INBOX_BRIEF_SEED", "0")
    monkeypatch.setenv("INBOX_BRIEF_SCHEDULE", "0")
    monkeypatch.setattr("inbox_brief.settings.datetime", FrozenDateTime)
    monkeypatch.setattr("inbox_brief.db.datetime", FrozenDateTime)
    os.environ["INBOX_BRIEF_DATA_DIR"] = str(tmp_path)
    from inbox_brief.main import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app()) as test_client:
        yield test_client
