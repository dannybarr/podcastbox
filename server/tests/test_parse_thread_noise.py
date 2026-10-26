import mailbox
from pathlib import Path

from inbox_brief.ingest.noise import noise_reason
from inbox_brief.ingest.parse import parse_eml_bytes, parse_mbox_bytes, parse_path
from inbox_brief.ingest.thread import normalize_subject, thread_messages


def _load(fixtures: Path):
    messages = []
    for path in sorted(fixtures.glob("*.eml")):
        messages.extend(parse_path(str(path), source="fixture"))
    return messages


def test_plain_email_keeps_the_request_and_drops_the_signature(fixtures: Path):
    message = parse_path(str(fixtures / "01-launch.eml"))[0]
    assert message.from_name == "Sarah Chen"
    assert message.message_id == "launch-1@northline.example"
    assert "Thursday 22 October" in message.clean_body
    assert "Hi all" not in message.clean_body
    assert "Product Operations" not in message.clean_body
    assert "Thanks," not in message.clean_body


def test_quoted_reply_and_phone_signature_are_stripped(fixtures: Path):
    message = parse_path(str(fixtures / "02-launch-reply.eml"))[0]
    assert "loading dock" in message.clean_body
    assert "design review" in message.clean_body
    assert "Can we move the ship date" not in message.clean_body
    assert "Sent from my iPhone" not in message.clean_body
    assert message.in_reply_to == "launch-1@northline.example"


def test_footer_is_removed_from_multipart_mail(fixtures: Path):
    message = parse_path(str(fixtures / "03-design.eml"))[0]
    assert "homepage hero" in message.clean_body
    assert "revised stills" in message.clean_body
    assert "confidential" not in message.clean_body.lower()
    assert "Priya Shah" not in message.clean_body


def test_html_only_message_is_readable():
    raw = b"""From: Ada <ada@northline.example>\r
Subject: Notes\r
Content-Type: text/html; charset=utf-8\r
\r
<p>The mockups landed in the shared folder.</p>\r
<p>This email and any attachments are confidential.</p>\r
"""
    message = parse_eml_bytes(raw)
    assert "mockups landed" in message.clean_body
    assert "confidential" not in message.clean_body.lower()


def test_threads_follow_reply_headers_and_subjects(fixtures: Path):
    messages = _load(fixtures)
    threads = thread_messages(messages)
    groups = {tuple(message.message_id for message in members) for members in threads.values()}
    assert ("launch-1@northline.example", "launch-2@northline.example") in groups
    assert ("design-1@northline.example", "design-2@northline.example") in groups
    assert (
        "atlas-ship-1@northline.example",
        "atlas-ship-2@northline.example",
        "atlas-ship-3@northline.example",
        "atlas-ship-4@northline.example",
        "atlas-ship-5@northline.example",
        "atlas-ship-6@northline.example",
    ) in groups
    assert normalize_subject("Re: Homepage hero") == "homepage hero"
    assert len(threads) > 4


def test_subject_threads_messages_that_have_no_ids():
    first = parse_eml_bytes(
        b"From: A <a@northline.example>\nSubject: Dock booking\n\nThe dock is free at noon.\n"
    )
    second = parse_eml_bytes(
        b"From: B <b@northline.example>\nSubject: RE: Dock booking\n\nNoon still works.\n"
    )
    other = parse_eml_bytes(
        b"From: C <c@northline.example>\nSubject: Lunch\n\nSoup is in the kitchen.\n"
    )
    threads = thread_messages([first, second, other])
    assert len(threads) == 2
    dock = next(members for members in threads.values() if len(members) == 2)
    assert {message.subject for message in dock} == {"Dock booking", "RE: Dock booking"}


def test_newsletters_and_noreply_are_noise(fixtures: Path):
    messages = {message.message_id: message for message in _load(fixtures)}
    kwargs = {"drop_newsletters": True, "drop_noreply": True, "extra_patterns": []}
    assert noise_reason(messages["news-1@digest.example"], **kwargs) == "list-unsubscribe header"
    assert "auto-submitted" in (noise_reason(messages["cal-1@calendar.example"], **kwargs) or "")
    assert noise_reason(messages["launch-1@northline.example"], **kwargs) is None
    quiet = {"drop_newsletters": False, "drop_noreply": False, "extra_patterns": []}
    assert noise_reason(messages["news-1@digest.example"], **quiet) is None
    custom = {"drop_newsletters": False, "drop_noreply": False, "extra_patterns": ["northline.example"]}
    assert noise_reason(messages["launch-1@northline.example"], **custom)


def test_mbox_round_trip(fixtures: Path, tmp_path: Path):
    path = tmp_path / "sample.mbox"
    box = mailbox.mbox(path)
    try:
        for eml in sorted(fixtures.glob("*.eml")):
            box.add(eml.read_bytes())
    finally:
        box.close()
    parsed = parse_mbox_bytes(path.read_bytes())
    expected = {message.message_id for message in _load(fixtures)}
    assert {message.message_id for message in parsed} == expected
    assert "launch-1@northline.example" in expected
