"""Live connection check for Gmail, Outlook, and configured MCP servers.

Nothing here is mocked. Missing credentials are SKIP, not a pass.
A full PASS deletes the local OAuth token after a thread was fetched.
Google and Microsoft are not asked to revoke the grant.
"""

from __future__ import annotations

from datetime import timedelta


def main() -> int:
    rows = [check_gmail(), check_outlook(), check_mcp()]
    print("PodcastBox connection check")
    print("Live services only. A skip is not a pass.")
    print()
    for row in rows:
        print(f"{row['name']}: {row['status']}")
        for step in row["steps"]:
            print(f"  {step['step']}: {step['status']}  {step['detail']}")
        print()
    if any(row["status"] == "FAIL" for row in rows):
        print("Result: FAIL")
        return 1
    if any(row["status"] == "PASS" for row in rows):
        print("Result: PASS")
        return 0
    print("Result: SKIP  No live mailbox could be checked.")
    return 2


def check_gmail() -> dict:
    from inbox_brief.mail import gmail

    return _check_native(
        "Gmail",
        gmail,
        "INBOX_BRIEF_GOOGLE_CLIENT_ID and INBOX_BRIEF_GOOGLE_CLIENT_SECRET",
    )


def check_outlook() -> dict:
    from inbox_brief.mail import outlook

    return _check_native(
        "Outlook",
        outlook,
        "INBOX_BRIEF_MICROSOFT_CLIENT_ID and INBOX_BRIEF_MICROSOFT_CLIENT_SECRET",
    )


def _check_native(name: str, module, env_hint: str) -> dict:
    from inbox_brief.db import get_settings
    from inbox_brief.settings import now_in

    steps = []
    if not module.configured():
        steps.append({"step": "auth", "status": "SKIP", "detail": f"Set {env_hint}."})
        steps.append({"step": "list", "status": "SKIP", "detail": "No credentials."})
        steps.append({"step": "fetch thread", "status": "SKIP", "detail": "No credentials."})
        steps.append({"step": "disconnect", "status": "SKIP", "detail": "Nothing was stored."})
        return {"name": name, "status": "SKIP", "steps": steps}
    if not module.connected():
        steps.append({"step": "auth", "status": "FAIL", "detail": "The app is configured but the account is not connected."})
        steps.append({"step": "list", "status": "SKIP", "detail": "Connect the account in Settings first."})
        steps.append({"step": "fetch thread", "status": "SKIP", "detail": "No account."})
        steps.append({"step": "disconnect", "status": "SKIP", "detail": "No token to delete."})
        return {"name": name, "status": "FAIL", "steps": steps}
    try:
        module._access_token()
    except Exception as exc:  # noqa: BLE001
        steps.append({"step": "auth", "status": "FAIL", "detail": str(exc)})
        steps.append({"step": "list", "status": "SKIP", "detail": "Auth failed."})
        steps.append({"step": "fetch thread", "status": "SKIP", "detail": "Auth failed."})
        steps.append({"step": "disconnect", "status": "SKIP", "detail": "Left the token in place because auth failed."})
        return {"name": name, "status": "FAIL", "steps": steps}
    steps.append({"step": "auth", "status": "PASS", "detail": module.account() or "token accepted"})
    settings = get_settings()
    since = now_in(settings["timezone"]) - timedelta(days=31)
    try:
        messages = module.fetch_recent(since)
    except Exception as exc:  # noqa: BLE001
        steps.append({"step": "list", "status": "FAIL", "detail": str(exc)})
        steps.append({"step": "fetch thread", "status": "SKIP", "detail": "List failed."})
        steps.append({"step": "disconnect", "status": "SKIP", "detail": "Left the token in place because list failed."})
        return {"name": name, "status": "FAIL", "steps": steps}
    steps.append({"step": "list", "status": "PASS", "detail": f"{len(messages)} message(s) in the last 31 days."})
    threaded = [item for item in messages if item.provider_thread_id]
    if not messages:
        steps.append({"step": "fetch thread", "status": "SKIP", "detail": "The mailbox returned no messages, so no thread id was checked."})
        steps.append({"step": "disconnect", "status": "SKIP", "detail": "Left the token in place."})
        return {"name": name, "status": "SKIP", "steps": steps}
    if not threaded:
        steps.append({"step": "fetch thread", "status": "FAIL", "detail": "Messages came back without a provider thread id."})
        steps.append({"step": "disconnect", "status": "SKIP", "detail": "Left the token in place."})
        return {"name": name, "status": "FAIL", "steps": steps}
    steps.append({"step": "fetch thread", "status": "PASS", "detail": f"thread {threaded[0].provider_thread_id}"})
    module.disconnect()
    if module.connected():
        steps.append({"step": "disconnect", "status": "FAIL", "detail": "The local token is still stored."})
        return {"name": name, "status": "FAIL", "steps": steps}
    steps.append({"step": "disconnect", "status": "PASS", "detail": "Local token deleted. The provider grant was not revoked."})
    return {"name": name, "status": "PASS", "steps": steps}


def check_mcp() -> dict:
    from datetime import timedelta

    from inbox_brief.db import get_settings
    from inbox_brief.mail.external import fetch_target, targets_from_settings
    from inbox_brief.settings import now_in

    settings = get_settings()
    targets = targets_from_settings(settings)
    if not targets:
        return {
            "name": "MCP",
            "status": "SKIP",
            "steps": [
                {"step": "auth", "status": "SKIP", "detail": "No MCP server is saved in Settings."},
                {"step": "list", "status": "SKIP", "detail": "Add an http URL or a stdio: command."},
                {"step": "fetch thread", "status": "SKIP", "detail": "No server."},
                {"step": "disconnect", "status": "SKIP", "detail": "MCP servers keep their own login."},
            ],
        }
    since = now_in(settings["timezone"]) - timedelta(days=31)
    messages = []
    try:
        for target in targets:
            messages.extend(fetch_target(target, since))
    except Exception as exc:  # noqa: BLE001
        return {
            "name": "MCP",
            "status": "FAIL",
            "steps": [
                {"step": "auth", "status": "FAIL", "detail": str(exc)},
                {"step": "list", "status": "SKIP", "detail": "The server did not answer."},
                {"step": "fetch thread", "status": "SKIP", "detail": "The server did not answer."},
                {"step": "disconnect", "status": "SKIP", "detail": "No local MCP token is stored by PodcastBox."},
            ],
        }
    threaded = [item for item in messages if item.provider_thread_id]
    thread_status = "PASS" if threaded else ("SKIP" if not messages else "FAIL")
    thread_detail = (
        f"thread {threaded[0].provider_thread_id}"
        if threaded
        else ("No messages in the window." if not messages else "Messages came back without a thread id.")
    )
    status = "PASS" if threaded else "SKIP"
    return {
        "name": "MCP",
        "status": status,
        "steps": [
            {"step": "auth", "status": "PASS", "detail": f"{len(targets)} server(s) answered."},
            {"step": "list", "status": "PASS", "detail": f"{len(messages)} message(s)."},
            {"step": "fetch thread", "status": thread_status, "detail": thread_detail},
            {"step": "disconnect", "status": "SKIP", "detail": "External MCP logins are not cleared by this app."},
        ],
    }
