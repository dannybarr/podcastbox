"""Unknown chains, a mailbox with nothing to read, and Gmail before it is configured."""

from inbox_brief.db import get_settings
from inbox_brief.pipeline import generate_episode


def test_unknown_chain_is_404_gmail_needs_credentials_and_empty_extractive_brief(client):
    missing = client.post("/api/podcasts", json={"chain_id": "missing-chain"})
    assert missing.status_code == 404
    assert "review period" in missing.json()["detail"]

    gmail = client.get("/api/connect/gmail")
    assert gmail.status_code == 400

    client.put("/api/settings", json={"script_backend": "extractive", "schedule_enabled": False})
    episode_id = generate_episode(get_settings(), "all")
    episode = client.get(f"/api/episodes/{episode_id}").json()
    assert episode["status"] == "empty"
    assert "No mail in this window" in episode["error"]
