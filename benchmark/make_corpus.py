"""Write the labelled benchmark mailbox. The gold chains are the intended topics."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / "corpus"
GOLD = ROOT / "labels" / "gold.json"

# chain, message_id, name, addr, to, subject, date, body, extra headers, in_reply_to, references, provider thread
LETTERS: list[dict] = []


def add(**kwargs) -> None:
    LETTERS.append(kwargs)


def thread(chain: str, prefix: str, people: list[tuple[str, str]], subject: str, bodies: list[str], start: str, provider: str = "") -> None:
    from datetime import datetime, timedelta

    ids = []
    base = datetime.fromisoformat(start)
    for index, body in enumerate(bodies):
        name, addr = people[index % len(people)]
        other = people[(index + 1) % len(people)]
        message_id = f"{prefix}-{index + 1}@bench.example"
        add(
            chain=chain,
            noise=False,
            message_id=message_id,
            name=name,
            addr=addr,
            to=other[1],
            subject=subject if index == 0 else f"Re: {subject}",
            date=(base + timedelta(minutes=index * 15)).isoformat(),
            body=body,
            in_reply_to="" if index == 0 else ids[-1],
            references=" ".join(ids),
            provider=provider,
            headers=[],
        )
        ids.append(message_id)


def main() -> None:
    LETTERS.clear()
    thread(
        "northquay",
        "north-a",
        [("Ada North", "ada.north@bench.example"), ("Ben Quay", "ben.quay@bench.example"), ("Chi Lo", "chi.lo@bench.example")],
        "Project Northquay crane",
        [
            "The Project Northquay crane is booked for Wednesday 21 October. Ada North asked the harbour master to hold berth 2.",
            "Ben Quay confirmed berth 2 for the Project Northquay crane. The lift plan is filed with the harbour master.",
            "Chi Lo sent the Project Northquay lift plan to the harbour master. Berth 2 stays Wednesday 21 October.",
            "Ada North said the Project Northquay crane crew arrives at berth 2 before 08:00.",
        ],
        "2026-10-16T09:00:00+00:00",
    )
    thread(
        "northquay",
        "north-b",
        [("Ben Quay", "ben.quay@bench.example"), ("Ada North", "ada.north@bench.example"), ("Chi Lo", "chi.lo@bench.example")],
        "Northquay berth window",
        [
            "A second note on Project Northquay: the crane still needs berth 2. Ben Quay copied the harbour master.",
            "Ada North repeated that the Project Northquay crane uses berth 2 on Wednesday 21 October.",
            "Chi Lo added the Project Northquay berth note for the crane crew at berth 2.",
        ],
        "2026-10-16T11:00:00+00:00",
    )
    add(
        chain="northquay",
        noise=False,
        message_id="northquay-8@bench.example",
        name="Ada North",
        addr="ada.north@bench.example",
        to="ben.quay@bench.example",
        subject="Re: Project Northquay crane",
        date="2026-10-18T09:12:00+00:00",
        body="The Project Northquay crane is now on berth 2. Ada North told the harbour master the lift is underway.",
        in_reply_to="north-a-4@bench.example",
        references="north-a-1@bench.example north-a-4@bench.example",
        provider="",
        headers=[],
    )
    thread(
        "birchkiln",
        "birch",
        [("Dana Birch", "dana.birch@bench.example"), ("Evan Kiln", "evan.kiln@bench.example")],
        "Project Birchkiln temperature",
        [
            "Project Birchkiln holds at 180 degrees. Dana Birch logged the kiln temperature at 07:40.",
            "Evan Kiln read 182 degrees on the Project Birchkiln gauge and wrote it in the log.",
            "Dana Birch said the Project Birchkiln firing ends Thursday 22 October if the gauge stays under 190.",
            "Evan Kiln replaced the Project Birchkiln thermocouple. The gauge now reads 181 degrees.",
            "Dana Birch confirmed the Project Birchkiln log has the new thermocouple serial K-19.",
            "Evan Kiln closed the Project Birchkiln log for Thursday 22 October at 181 degrees.",
        ],
        "2026-10-16T08:00:00+00:00",
    )
    thread(
        "colourpass",
        "colour",
        [("Farah Colour", "farah.colour@bench.example"), ("Gus Tint", "gus.tint@bench.example")],
        "Homepage colour pass",
        [
            "Farah Colour asked for a homepage colour pass on the hero. The swatch is sea glass, not navy.",
            "Gus Tint exported the homepage hero in sea glass and put it in the design folder.",
            "Farah Colour approved the sea glass hero for the homepage colour pass.",
            "Gus Tint saved the homepage hero export as colour-pass-4 and sent the folder link.",
            "Farah Colour said the homepage colour pass is ready for the Thursday review of sea glass.",
            "Gus Tint locked colour-pass-4. The homepage hero stays sea glass.",
        ],
        "2026-10-16T14:00:00+00:00",
    )
    thread(
        "lanyard",
        "lanyard",
        [("Nora Ellis", "nora.ellis@bench.example"), ("Ben Idris", "ben.idris@bench.example")],
        "Nylon badge reels",
        [
            "The spare nylon badge reels are in the lobby drawer.",
            "I moved the nylon badge reels into the lobby drawer.",
        ],
        "2026-10-16T15:10:00+00:00",
    )
    thread(
        "dock",
        "dock",
        [("Hana Dock", "hana.dock@bench.example"), ("Ivan Berth", "ivan.berth@bench.example")],
        "Fender inspection",
        [
            "Hana Dock booked the fender inspection for bollard 6 on Monday 19 October.",
            "Ivan Berth has the fender gauges for bollard 6. He will start at 09:30.",
            "Hana Dock said bollard 6 needs two fender gauges, not one.",
            "Ivan Berth packed two fender gauges for bollard 6.",
            "Hana Dock confirmed the fender inspection at bollard 6 is Monday 19 October at 09:30.",
        ],
        "2026-10-16T16:00:00+00:00",
    )
    thread(
        "payroll",
        "payroll",
        [("Jade Pension", "jade.pension@bench.example"), ("Omar Ledger", "omar.ledger@bench.example")],
        "Pension form",
        [
            "Jade Pension sent the pension form for the October payroll. The reference is PF-204.",
            "Omar Ledger filed pension form PF-204 with the October payroll.",
        ],
        "2026-10-17T10:00:00+00:00",
    )
    # Same provider thread, unrelated subjects. Headers do not connect them.
    add(
        chain="zebra",
        noise=False,
        message_id="zebra-1@bench.example",
        name="Ada Zebra",
        addr="ada.zebra@bench.example",
        to="bo.paint@bench.example",
        subject="Zebra docking fee",
        date="2026-10-17T09:00:00+00:00",
        body="The zebra docking fee is 40 pounds and Ada Zebra will pay it on Friday 23 October.",
        in_reply_to="",
        references="",
        provider="gmail-thread-bench-zebra",
        headers=[],
    )
    add(
        chain="zebra",
        noise=False,
        message_id="zebra-2@bench.example",
        name="Bo Paint",
        addr="bo.paint@bench.example",
        to="ada.zebra@bench.example",
        subject="Paint for the south wall",
        date="2026-10-17T10:00:00+00:00",
        body="Bo Paint ordered grey paint for the south wall and it arrives Monday 19 October.",
        in_reply_to="",
        references="",
        provider="gmail-thread-bench-zebra",
        headers=[],
    )
    add(
        chain="zebra",
        noise=False,
        message_id="zebra-3@bench.example",
        name="Cara Fee",
        addr="cara.fee@bench.example",
        to="ada.zebra@bench.example",
        subject="Receipts for the fee",
        date="2026-10-17T11:00:00+00:00",
        body="Cara Fee asked Ada Zebra to keep the zebra docking fee note with the grey paint order.",
        in_reply_to="",
        references="",
        provider="gmail-thread-bench-zebra",
        headers=[],
    )
    thread(
        "radio",
        "radio",
        [("Kim Radio", "kim.radio@bench.example"), ("Lee Channel", "lee.channel@bench.example"), ("Mo Squelch", "mo.squelch@bench.example")],
        "Handheld radio channel",
        [
            "Kim Radio set the handheld radio to channel 4. The squelch is at 2.",
            "Lee Channel confirmed handheld channel 4 and squelch 2 for the yard.",
            "Mo Squelch tested handheld channel 4 from the gate. The squelch held at 2.",
            "Kim Radio said the spare handheld stays on channel 4 in the gate cupboard.",
            "Lee Channel labelled the spare handheld with channel 4 and squelch 2.",
        ],
        "2026-10-16T12:00:00+00:00",
    )
    noises = [
        ("news-1@bench.example", "Digest", "news@digest.bench.example", "Weekly digest", "Our picks will crush your roadmap.", [("List-Unsubscribe", "<mailto:bye@digest.bench.example>"), ("Precedence", "bulk")]),
        ("cal-1@bench.example", "Calendar", "noreply@calendar.bench.example", "Reminder: standup", "This is an automatic reminder.", [("Auto-Submitted", "auto-generated")]),
        ("receipt-1@bench.example", "Supplies", "billing@supplies.bench.example", "Your receipt", "Payment received for order 441.", []),
        ("reminder-1@bench.example", "Tasks", "reminder@tasks.bench.example", "Reminder: timesheet", "Please send the timesheet.", []),
        ("note-1@bench.example", "CI", "notifications@ci.bench.example", "Notification: build 188", "Build 188 finished.", []),
        ("quick-1@bench.example", "Sam Quick", "sam.quick@bench.example", "Thanks", "Thanks!", []),
        ("cal-accept-1@bench.example", "Meet", "bot@meet.bench.example", "Accepted: Friday review", "The invite was accepted.", []),
        ("receipt-2@bench.example", "Supplies", "billing@supplies.bench.example", "Payment confirmation", "Payment confirmation for order 442.", []),
    ]
    for message_id, name, addr, subject, body, headers in noises:
        add(
            chain=None,
            noise=True,
            message_id=message_id,
            name=name,
            addr=addr,
            to="ada.north@bench.example",
            subject=subject,
            date="2026-10-16T18:00:00+00:00",
            body=body,
            in_reply_to="",
            references="",
            provider="",
            headers=headers,
        )

    CORPUS.mkdir(parents=True, exist_ok=True)
    for old in CORPUS.glob("*.eml"):
        old.unlink()
    messages = []
    for index, letter in enumerate(LETTERS, start=1):
        path = CORPUS / f"{index:02d}-{letter['message_id'].split('@')[0]}.eml"
        path.write_text(_eml(letter), encoding="utf-8")
        messages.append(
            {
                "message_id": letter["message_id"],
                "noise": letter["noise"],
                "chain": letter["chain"],
            }
        )
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    GOLD.write_text(
        json.dumps(
            {
                "messages": messages,
                "queries": [
                    {"query": "update on Northquay", "chains": ["northquay"]},
                    {"query": "update on Birchkiln", "chains": ["birchkiln"]},
                    {"query": "my communications with Farah Colour", "chains": ["colourpass"]},
                    {"query": "handheld radio channel", "chains": ["radio"]},
                    {"query": "zebra docking fee", "chains": ["zebra"]},
                    {"query": "nylon badge reels", "chains": ["lanyard"]},
                    {"query": "pension form PF-204", "chains": ["payroll"]},
                    {"query": "fender inspection bollard", "chains": ["dock"]},
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {len(LETTERS)} messages to {CORPUS}")


def _eml(letter: dict) -> str:
    lines = [
        f"From: {letter['name']} <{letter['addr']}>",
        f"To: <{letter['to']}>",
        f"Subject: {letter['subject']}",
        f"Date: {_rfc(letter['date'])}",
        f"Message-ID: <{letter['message_id']}>",
    ]
    if letter["in_reply_to"]:
        lines.append(f"In-Reply-To: <{letter['in_reply_to']}>")
    if letter["references"]:
        lines.append("References: " + " ".join(f"<{part}>" for part in letter["references"].split()))
    if letter["provider"]:
        lines.append(f"X-Provider-Thread: {letter['provider']}")
    for key, value in letter["headers"]:
        lines.append(f"{key}: {value}")
    lines.append("MIME-Version: 1.0")
    lines.append('Content-Type: text/plain; charset="utf-8"')
    lines.append("")
    lines.append(letter["body"])
    lines.append("")
    return "\n".join(lines)


def _rfc(value: str) -> str:
    from datetime import datetime

    when = datetime.fromisoformat(value)
    days = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{days[when.weekday()]}, {when.day:02d} {months[when.month - 1]} {when.year} {when.strftime('%H:%M:%S')} +0000"


if __name__ == "__main__":
    main()
