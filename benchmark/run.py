#!/usr/bin/env python3
"""Score PodcastBox against benchmark/RUBRIC.md.

Criteria live in the rubric. This file measures them. It does not change them.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import wave
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
sys.path.insert(0, "/tmp/pydeps")
sys.path.insert(0, str(SERVER))

RUBRIC = ROOT / "benchmark" / "RUBRIC.md"
HISTORY = ROOT / "benchmark" / "history.json"
REPORT_MD = ROOT / "benchmark" / "REPORT.md"
REPORT_JSON = ROOT / "benchmark" / "report.json"
CORPUS = ROOT / "benchmark" / "corpus"
GOLD = ROOT / "benchmark" / "labels" / "gold.json"
PY = sys.executable
PY_ENV = {
    **os.environ,
    "PYTHONPATH": f"{SERVER}:/tmp/pydeps",
    "INBOX_BRIEF_SEED": "0",
    "INBOX_BRIEF_SCHEDULE": "0",
}
# Live checks and pytest use the project data dir, not the benchmark sandbox.
for _key in ("INBOX_BRIEF_DATA_DIR",):
    PY_ENV.pop(_key, None)

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=timezone.utc)
METRICS: list[dict] = []


def main() -> int:
    METRICS.clear()
    connectivity()
    chains, messages, gold = load_mailbox()
    threading(chains, messages, gold)
    noise(messages, gold)
    ask(chains, gold)
    podcast, by_message = faithfulness(messages, gold)
    neutrality(podcast, by_message)
    audio()
    ux()
    days()
    privacy()
    reliability()
    write_reports()
    total = sum(item["score"] for item in METRICS)
    print(f"Benchmark total {total}/120")
    for item in METRICS:
        print(f"  {item['score']:>2}/10  {item['name']}")
    return 0


def add(name: str, score: int, evidence: str, ceiling: str = "") -> None:
    METRICS.append(
        {
            "name": name,
            "score": max(0, min(10, int(score))),
            "evidence": evidence.strip(),
            "ceiling": ceiling.strip(),
        }
    )


def run(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=cwd or ROOT,
        env=env or PY_ENV,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def connectivity() -> None:
    names = [
        "test_gmail_oauth_refresh_pagination_thread_and_backoff",
        "test_outlook_oauth_refresh_pagination_thread_and_backoff",
        "test_mcp_gmail_streamable_http_and_stdio",
        "test_mcp_outlook_streamable_http_pages",
    ]
    nodeids = [f"server/tests/test_mail_contracts.py::{name}" for name in names]
    proc = run([PY, "-m", "pytest", "-q", "--tb=line", *nodeids], timeout=180)
    output = (proc.stdout or "") + (proc.stderr or "")
    source = (ROOT / "server" / "tests" / "test_mail_contracts.py").read_text(encoding="utf-8")
    points = 0
    lines = []
    for name in names:
        if proc.returncode == 0 and f"def {name}" in source:
            points += 2
            lines.append(f"{name}: pass (mocked Gmail, Graph, or MCP responses).")
        else:
            lines.append(f"{name}: fail. {output[-500:]}")
    verify = run([PY, str(ROOT / "scripts" / "verify-connections")], timeout=60)
    verify_out = ((verify.stdout or "") + (verify.stderr or "")).strip()
    if verify.returncode == 0:
        points += 2
        lines.append("scripts/verify-connections exited 0. A live mailbox passed auth, list, fetch thread, and local disconnect.")
        ceiling = ""
    else:
        lines.append(
            f"scripts/verify-connections exited {verify.returncode}. "
            "The last 2 points need a live Gmail or Outlook account on this machine. "
            "Exit 2 means nothing was configured. Exit 1 means a configured account failed."
        )
        lines.append(verify_out or "(no output)")
        ceiling = (
            "8/10 until scripts/verify-connections exits 0 against a real mailbox: "
            "set the Google or Microsoft client id and secret, connect the account, and run the script. "
            "A mock cannot award these 2 points."
        )
    add("Connectivity and MCP robustness", points, "\n".join(lines), ceiling if points < 10 else "")


def load_mailbox():
    from inbox_brief.curate import build_chains
    from inbox_brief.ingest.parse import parse_path

    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    messages = []
    for path in sorted(CORPUS.glob("*.eml")):
        messages.extend(parse_path(str(path), "benchmark"))
    chains = build_chains(messages, now=NOW, period="month")
    return chains, messages, gold


def _pairs(groups: dict[str, list[str]]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for members in groups.values():
        ordered = sorted(set(members))
        found.update(combinations(ordered, 2))
    return found


def _f1_score(precision: float, recall: float) -> int:
    if precision == 1 and recall == 1:
        return 10
    if precision + recall == 0:
        return 0
    f1 = 2 * precision * recall / (precision + recall)
    return min(9, round(10 * f1))


def threading(chains, messages, gold) -> None:
    labelled = gold["messages"]
    if len(labelled) < 40 or len(list(CORPUS.glob("*.eml"))) < 40:
        add("Thread consolidation", 0, f"Corpus has {len(labelled)} labelled messages. Fewer than 40 scores 0.")
        return
    by_header = {message.message_id: message for message in messages}
    gold_chain = {row["message_id"]: row["chain"] for row in labelled if not row["noise"]}
    predicted: dict[str, list[str]] = {}
    for chain in chains:
        headers = []
        internal = set(chain["message_ids"])
        for message in messages:
            if message.id in internal and message.message_id in gold_chain:
                headers.append(message.message_id)
        if headers:
            predicted[chain["id"]] = headers
    gold_groups: dict[str, list[str]] = {}
    for header, chain_name in gold_chain.items():
        gold_groups.setdefault(chain_name, []).append(header)
    gold_pairs = _pairs(gold_groups)
    pred_pairs = _pairs(predicted)
    # A non-noise message the curator dropped simply has no predicted pairs.
    overlap = gold_pairs & pred_pairs
    precision = len(overlap) / len(pred_pairs) if pred_pairs else 0.0
    recall = len(overlap) / len(gold_pairs) if gold_pairs else 0.0
    missing = sorted(gold_pairs - pred_pairs)[:8]
    extra = sorted(pred_pairs - gold_pairs)[:8]
    score = _f1_score(precision, recall)
    add(
        "Thread consolidation",
        score,
        (
            f"{len(labelled)} labelled messages, {len(gold_chain)} non-noise. "
            f"Pairwise precision {precision:.3f} ({len(overlap)}/{len(pred_pairs)}), "
            f"recall {recall:.3f} ({len(overlap)}/{len(gold_pairs)}). "
            f"Missed pairs sample: {missing or 'none'}. Extra pairs sample: {extra or 'none'}."
        ),
    )
    del by_header


def noise(messages, gold) -> None:
    from inbox_brief.ingest.noise import noise_reason

    by_header = {message.message_id: message for message in messages}
    gold_noise = {row["message_id"] for row in gold["messages"] if row["noise"]}
    gold_keep = {row["message_id"] for row in gold["messages"] if not row["noise"]}
    predicted = set()
    missing_parse = []
    for row in gold["messages"]:
        message = by_header.get(row["message_id"])
        if message is None:
            missing_parse.append(row["message_id"])
            continue
        if noise_reason(message, drop_newsletters=True, drop_noreply=True, extra_patterns=[]):
            predicted.add(row["message_id"])
    true_pos = gold_noise & predicted
    precision = len(true_pos) / len(predicted) if predicted else 0.0
    recall = len(true_pos) / len(gold_noise) if gold_noise else 0.0
    score = _f1_score(precision, recall)
    add(
        "Noise filtering",
        score,
        (
            f"Precision {precision:.3f}, recall {recall:.3f}. "
            f"False noise: {sorted(predicted - gold_noise) or 'none'}. "
            f"Missed noise: {sorted(gold_noise - predicted) or 'none'}. "
            f"Unparsed: {missing_parse or 'none'}. Kept sample size {len(gold_keep)}."
        ),
    )


def ask(chains, gold) -> None:
    from inbox_brief.curate import ask_chains

    header_of = {}
    # message internal id -> header, rebuilt from chains' members via a fresh parse map
    from inbox_brief.ingest.parse import parse_path

    for path in CORPUS.glob("*.eml"):
        for message in parse_path(str(path), "benchmark"):
            header_of[message.id] = message.message_id
    gold_of = {row["message_id"]: row["chain"] for row in gold["messages"]}
    queries = gold["queries"]
    passed = 0
    details = []
    for item in queries:
        returned = ask_chains(chains, item["query"])
        labels = []
        for chain in returned:
            votes = []
            for internal in chain["message_ids"]:
                header = header_of.get(internal)
                if header in gold_of and gold_of[header]:
                    votes.append(gold_of[header])
            if not votes:
                labels.append("?")
                continue
            labels.append(max(set(votes), key=votes.count))
        expected = list(item["chains"])
        ok = sorted(labels) == sorted(expected)
        passed += int(ok)
        details.append(f"{item['query']!r}: {'pass' if ok else 'fail'} got {labels} expected {expected}")
    if len(queries) != 8:
        score = 0
    elif passed == 8:
        score = 10
    else:
        score = min(9, round(10 * passed / 8))
    add("Suggestions and the ask box", score, f"{passed}/8 queries.\n" + "\n".join(details))


def faithfulness(messages, gold):
    sandbox = tempfile.mkdtemp(prefix="inbox-brief-bench-")
    os.environ["INBOX_BRIEF_DATA_DIR"] = sandbox
    os.environ["INBOX_BRIEF_SEED"] = "0"
    os.environ["INBOX_BRIEF_SCHEDULE"] = "0"
    import httpx

    from inbox_brief.db import init_db, save_settings
    from inbox_brief.domain import ParsedMessage, Script, SegmentDraft
    from inbox_brief.pipeline import generate_podcast
    from inbox_brief.script.guard import apply_guard
    from inbox_brief.store import get_chain, get_episode, rebuild_chains, upsert_messages

    init_db()
    save_settings(
        {
            "script_backend": "extractive",
            "review_period": "month",
            "schedule_enabled": False,
            "llm_provider": "ollama",
            "voice_preset": "kokoro_british",
        }
    )
    from inbox_brief.db import get_settings

    upsert_messages(messages, get_settings())
    rebuild_chains(get_settings(), use_model=False)
    header_of = {message.id: message.message_id for message in messages}
    by_header = {message.message_id: message for message in messages}
    gold_of = {row["message_id"]: row["chain"] for row in gold["messages"]}
    north = None
    for chain in rebuild_chains(get_settings(), use_model=False):
        votes = [gold_of.get(header_of.get(item, ""), "") for item in chain["message_ids"]]
        votes = [vote for vote in votes if vote]
        if votes and max(set(votes), key=votes.count) == "northquay":
            north = chain
            break
    points = 0
    notes: list[str] = []
    episode = None
    network_calls: list[str] = []

    def _explode(*_args, **_kwargs):
        network_calls.append("http")
        raise RuntimeError("extractive generation tried to use the network")

    real_request = httpx.request
    real_post = httpx.post
    httpx.request = _explode  # type: ignore[method-assign]
    httpx.post = _explode  # type: ignore[method-assign]
    import inbox_brief.pipeline as pipeline
    from inbox_brief.audio.wav import concat, duration_ms, read_wav, write_wav
    from inbox_brief.domain import RenderResult
    from inbox_brief.tts.engines import tone_wav

    def fake_synthesize(engine, segments, settings):
        del engine, settings
        pieces, timings, cursor, rate = [], [], 0, 8000
        for index, _segment in enumerate(segments):
            _rate, samples = read_wav(tone_wav(0.2, rate=rate, frequency=440 + index * 30))
            span = duration_ms(len(samples), rate)
            timings.append((cursor, cursor + span))
            cursor += span
            pieces.append(samples)
        return RenderResult(audio=write_wav(concat(pieces), rate), mime="audio/wav", timings=timings, engine="kokoro", detail="test-tone")

    pipeline.synthesize = fake_synthesize
    pipeline.resolve_engine = lambda *_args, **_kwargs: "kokoro"
    try:
        if north is None:
            notes.append("Northquay chain was not stored, so no podcast was generated.")
        else:
            episode_id = generate_podcast(get_settings(), north["id"], question="", style="quick", length="short", scope="full")
            episode = get_episode(episode_id)
            script_notes = episode.get("notes") or []
            sourced = all(segment.get("source_ids") for segment in episode["segments"])
            if sourced and not script_notes and episode["segments"]:
                points += 4
                notes.append(
                    f"Extractive Northquay podcast {episode_id}: {len(episode['segments'])} segments, each with a source id, guard notes empty. Speech was a test tone."
                )
            else:
                notes.append(
                    f"Source ids present: {sourced}. Guard notes: {script_notes or 'none'}. Segments: {len(episode['segments'])}."
                )
            if network_calls:
                notes.append("Extractive generation called HTTP. That fails the reliability network check.")
            else:
                notes.append("Extractive generation made no HTTP call.")
            token_ok = True
            problems = []
            stored = {message.id: message for message in messages}
            for segment in episode["segments"]:
                cited = " ".join(
                    " ".join([stored[sid].from_name, stored[sid].from_addr, stored[sid].subject, stored[sid].clean_body])
                    for sid in segment["source_ids"]
                    if sid in stored
                )
                for token in re.findall(r"\b[A-Z][A-Za-z0-9'-]*\b", segment["text"]):
                    if token.lower() not in cited.lower():
                        token_ok = False
                        problems.append(f"capital {token!r} in {segment['text'][:80]!r}")
                for number in re.findall(r"\d+", segment["text"]):
                    if number not in cited:
                        token_ok = False
                        problems.append(f"number {number} in {segment['text'][:80]!r}")
            if token_ok and episode["segments"]:
                points += 3
                notes.append("Every number and capitalised token in the spoken lines appears in the cited source.")
            else:
                notes.append("Token check failed: " + "; ".join(problems[:6]))
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Podcast generation failed: {exc}")
    finally:
        httpx.request = real_request  # type: ignore[method-assign]
        httpx.post = real_post  # type: ignore[method-assign]

    planted_source = next(message for message in messages if message.message_id == "north-a-1@bench.example")
    planted = Script(
        title="Plant",
        segments=[
            SegmentDraft(speaker="S1", text="This is a good idea.", source_ids=[planted_source.id]),
            SegmentDraft(
                speaker="S2",
                text=f"{planted_source.sender_label} wrote: {planted_source.clean_body}",
                source_ids=[planted_source.id],
            ),
        ],
    )
    checked, guard_notes = apply_guard(planted, {planted_source.id: planted_source})
    spoken = " ".join(segment.text for segment in checked.segments)
    if "good idea" not in spoken.lower() and any("good idea" in note.lower() or "good" in note.lower() for note in guard_notes):
        points += 3
        notes.append("Planted line 'This is a good idea' was removed. A sourced Northquay sentence stayed.")
    else:
        notes.append(f"Planted line was not removed as required. Notes: {guard_notes}. Kept: {spoken[:200]}")
    add("Script faithfulness", points, "\n".join(notes))
    # Stash network result for reliability via an attribute on the function.
    faithfulness.network_clean = not network_calls and episode is not None  # type: ignore[attr-defined]
    return episode, by_header


def neutrality(podcast, by_header) -> None:
    from inbox_brief.domain import Script, SegmentDraft
    from inbox_brief.script.guard import apply_guard

    points = 0
    notes = []
    spoken = " ".join(segment["text"] for segment in (podcast or {}).get("segments") or []).lower()
    banned = ("i think", "you should", "we should", "probably", "good idea")
    hits = [phrase for phrase in banned if phrase in spoken]
    if podcast and podcast.get("segments") and not hits:
        points += 5
        notes.append("Spoken Northquay podcast contains none of: i think, you should, we should, probably, good idea.")
    else:
        notes.append(f"Banned phrases in the podcast: {hits or 'podcast missing'}.")

    from inbox_brief.domain import ParsedMessage

    with_good = ParsedMessage(
        id="good-src",
        message_id="good@bench",
        from_name="Ada North",
        from_addr="ada.north@bench.example",
        to_addr="ben.quay@bench.example",
        subject="Project Northquay",
        date="2026-10-16T09:00:00+00:00",
        clean_body="The crane plan is good.",
        raw_body="The crane plan is good.",
    )
    without = ParsedMessage(
        id="plain-src",
        message_id="plain@bench",
        from_name="Ada North",
        from_addr="ada.north@bench.example",
        to_addr="ben.quay@bench.example",
        subject="Project Northquay",
        date="2026-10-16T09:00:00+00:00",
        clean_body="The crane plan is booked.",
        raw_body="The crane plan is booked.",
    )
    kept_good, notes_good = apply_guard(
        Script(title="g", segments=[SegmentDraft(speaker="S1", text="Ada North wrote: The crane plan is good.", source_ids=["good-src"])]),
        {"good-src": with_good},
    )
    dropped, notes_drop = apply_guard(
        Script(title="d", segments=[SegmentDraft(speaker="S1", text="This is a good idea.", source_ids=["plain-src"])]),
        {"plain-src": without},
    )
    kept_text = " ".join(segment.text.lower() for segment in kept_good.segments)
    dropped_text = " ".join(segment.text.lower() for segment in dropped.segments)
    if "good" in kept_text and not notes_good and "good" not in dropped_text and notes_drop:
        points += 5
        notes.append("The guard kept 'good' when the cited source says good, and dropped it when the source does not.")
    else:
        notes.append(f"Guard keep/drop failed. Kept {kept_text!r} notes {notes_good}. Dropped {dropped_text!r} notes {notes_drop}.")
    add("Neutrality", points, "\n".join(notes))


def audio() -> None:
    points = 0
    notes = []
    british = ROOT / "demo" / "kokoro-british.mp3"
    transcript_path = ROOT / "demo" / "transcript-british.json"
    if british.is_file() and british.stat().st_size > 10_000:
        head = british.read_bytes()[:3]
        if head == b"ID3" or head[0] == 0xFF:
            points += 1
            notes.append(f"kokoro-british.mp3 is {british.stat().st_size} bytes and starts with {head!r}.")
        else:
            notes.append(f"MP3 header missing, starts with {head!r}.")
    else:
        notes.append("demo/kokoro-british.mp3 is missing or under 10 KB.")
    transcript = {}
    if transcript_path.is_file():
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
        speakers = {segment.get("speaker") for segment in transcript.get("segments") or []}
        if "S1" in speakers and "S2" in speakers:
            points += 1
            notes.append("Transcript has S1 and S2.")
        else:
            notes.append(f"Transcript speakers: {speakers}.")
        ranges = [(int(segment["start_ms"]), int(segment["end_ms"])) for segment in transcript.get("segments") or []]
        monotonic = bool(ranges) and all(start < end for start, end in ranges) and all(
            ranges[index][1] <= ranges[index + 1][0] for index in range(len(ranges) - 1)
        )
        if monotonic:
            points += 1
            notes.append(f"{len(ranges)} timing ranges, monotonic, one per segment.")
        else:
            notes.append(f"Timings are not monotonic: {ranges}.")
    else:
        notes.append("demo/transcript-british.json is missing.")
    settings_text = (SERVER / "inbox_brief" / "settings.py").read_text(encoding="utf-8")
    if '"voice_preset": "kokoro_british"' in settings_text and '"bf_emma"' in settings_text and '"bm_george"' in settings_text:
        points += 1
        notes.append("Default voice preset is kokoro_british with bf_emma and bm_george.")
    else:
        notes.append("Default British Kokoro voices are not the settings default.")
    previews = [
        ROOT / "demo" / "kokoro-british.mp3",
        ROOT / "demo" / "kokoro-ab.mp3",
        ROOT / "demo" / "dia-sample.mp3",
    ]
    if all(path.is_file() and path.stat().st_size > 1000 for path in previews):
        points += 1
        notes.append("Preview files exist for Kokoro British, Kokoro American, and Dia.")
    else:
        notes.append("A preview file is missing: " + ", ".join(str(path.name) for path in previews if not path.is_file()))
    try:
        from inbox_brief.tts.voice_clip import VoiceClipError, save_clip

        try:
            save_clip(b"not-audio", "clip.wav", consent=False, host="S1")
            notes.append("save_clip without consent did not raise.")
        except VoiceClipError:
            points += 1
            notes.append("save_clip without consent raises VoiceClipError.")
    except Exception as exc:  # noqa: BLE001
        notes.append(f"Voice clip check failed: {exc}")
    if transcript.get("segments") and british.is_file():
        expected = max(int(segment["end_ms"]) for segment in transcript["segments"]) / 1000
        probed = _mp3_seconds(british)
        if probed is not None and abs(probed - expected) <= 2:
            points += 1
            notes.append(f"British clip is {probed:.2f}s. Transcript ends at {expected:.2f}s. Within 2 seconds.")
        else:
            notes.append(f"Duration mismatch. File {probed}, transcript {expected:.2f}s.")
    listening = ROOT / "benchmark" / "listening.json"
    if listening.is_file():
        sheet = json.loads(listening.read_text(encoding="utf-8"))
        listener = str(sheet.get("listener") or "").strip()
        natural = sheet.get("naturalness")
        emotion = sheet.get("emotion")
        if listener and natural == 10 and emotion == 10:
            points += 3
            notes.append(f"Listening sheet from {listener}: naturalness 10, emotion 10.")
        else:
            notes.append(f"Listening sheet did not award the 3 points: {sheet}.")
    else:
        notes.append("benchmark/listening.json is absent. The benchmark does not invent a listener.")
    ceiling = ""
    if points <= 7 and not listening.is_file():
        ceiling = (
            "7/10 until a person listens to demo/kokoro-british.mp3 against demo/transcript-british.json "
            "and writes benchmark/listening.json with their name, naturalness 10, and emotion 10. "
            "The automated proxy cannot award the last 3 points."
        )
    add("Audio naturalness and emotion", points, "\n".join(notes), ceiling if points < 10 else "")


def _mp3_seconds(path: Path) -> float | None:
    proc = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        timeout=30,
    )
    try:
        return float((proc.stdout or "").strip())
    except ValueError:
        return None


def ux() -> None:
    points = 0
    notes = []
    pages = list((ROOT / "web" / "src" / "app").rglob("page.tsx"))
    real = []
    redirects = []
    for path in pages:
        text = path.read_text(encoding="utf-8")
        if "redirect(" in text:
            redirects.append(str(path.relative_to(ROOT)))
        else:
            real.append(str(path.relative_to(ROOT)))
    if sorted(real) == ["web/src/app/page.tsx", "web/src/app/settings/page.tsx"]:
        points += 2
        notes.append(f"Two screens: Home and Settings. Redirects: {redirects}.")
    else:
        notes.append(f"Screens that are not redirects: {real}.")
    if _port_open(43123):
        click = _clicks()
        if click.get("ok"):
            points += 2
            notes.append("Browser: one click on Turn into podcast opened a dialog that contains Make the podcast.")
        else:
            notes.append(f"Click measurement failed: {click.get('error') or click}.")
    else:
        notes.append("http://127.0.0.1:43123 is down, so the click points are 0.")
    light = _lighthouse()
    points += light["a11y_points"] + light["perf_points"]
    notes.append(light["evidence"])
    ceiling = light.get("ceiling") or ""
    add("UX simplicity", points, "\n".join(notes), ceiling if points < 10 else "")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return True
    except OSError:
        return False


def _clicks() -> dict:
    script = r"""
const puppeteer = require("/tmp/node_modules/puppeteer-core");
(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME || "/usr/bin/google-chrome-stable",
    headless: "new",
    args: ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage();
  page.setDefaultTimeout(20000);
  await page.goto("http://127.0.0.1:43123/", { waitUntil: "networkidle0" });
  await page.waitForFunction(() => document.body.innerText.includes("Turn into podcast"));
  const clicked = await page.evaluate(() => {
    const button = [...document.querySelectorAll("button")].find((el) => (el.textContent || "").includes("Turn into podcast"));
    if (!button) return false;
    button.click();
    return true;
  });
  await page.waitForFunction(() => document.body.innerText.includes("Make the podcast"));
  console.log(JSON.stringify({ ok: clicked }));
  await browser.close();
})().catch((error) => {
  console.log(JSON.stringify({ ok: false, error: String(error) }));
  process.exit(0);
});
"""
    proc = run(["node", "-e", script], timeout=60, env={**os.environ, "CHROME": "/usr/bin/google-chrome-stable"})
    raw = (proc.stdout or "").strip().splitlines()
    if not raw:
        return {"ok": False, "error": (proc.stderr or "no output")[-400:]}
    try:
        return json.loads(raw[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": raw[-1][:400]}


def _lighthouse() -> dict:
    chrome = "/usr/bin/google-chrome-stable"
    if not Path(chrome).exists():
        return {
            "a11y_points": 0,
            "perf_points": 0,
            "evidence": "Lighthouse skipped: Chrome is not installed. Accessibility and performance points are 0.",
            "ceiling": "Install Chrome and rerun so the production build can be measured.",
        }
    cache_path = ROOT / "benchmark" / ".lighthouse.json"
    digest = _web_digest()
    if cache_path.is_file():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("digest") == digest and "accessibility" in cached and "performance" in cached:
            return _light_points(cached["accessibility"], cached["performance"], "cached production measurement for the current web sources")
    build_dir = Path("/tmp/inbox-brief-lighthouse")
    if build_dir.exists():
        shutil.rmtree(build_dir)
    shutil.copytree(ROOT / "web", build_dir, ignore=shutil.ignore_patterns("node_modules", ".next"))
    (build_dir / "node_modules").symlink_to(ROOT / "web" / "node_modules")
    build = run(["npx", "next", "build"], cwd=build_dir, env={**os.environ, "API_INTERNAL_URL": "http://127.0.0.1:8742"}, timeout=300)
    if build.returncode != 0:
        tail = ((build.stdout or "") + (build.stderr or ""))[-800:]
        return {
            "a11y_points": 0,
            "perf_points": 0,
            "evidence": f"Lighthouse skipped: production build failed.\n{tail}",
            "ceiling": "",
        }
    port = 43191
    server = subprocess.Popen(
        ["npx", "next", "start", "-p", str(port), "-H", "127.0.0.1"],
        cwd=build_dir,
        env={**os.environ, "API_INTERNAL_URL": "http://127.0.0.1:8742"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = False
        for _ in range(40):
            if _port_open(port):
                ready = True
                break
            if server.poll() is not None:
                break
            import time

            time.sleep(0.5)
        if not ready:
            return {
                "a11y_points": 0,
                "perf_points": 0,
                "evidence": "Lighthouse skipped: the production server did not open a port.",
                "ceiling": "",
            }
        out = Path("/tmp/inbox-brief-lh.json")
        proc = run(
            [
                "npx",
                "--yes",
                "lighthouse",
                f"http://127.0.0.1:{port}/",
                "--quiet",
                "--chrome-flags=--headless=new --no-sandbox --disable-gpu",
                "--only-categories=performance,accessibility",
                "--output=json",
                f"--output-path={out}",
            ],
            cwd=build_dir,
            timeout=180,
        )
        if not out.is_file():
            tail = ((proc.stdout or "") + (proc.stderr or ""))[-600:]
            return {
                "a11y_points": 0,
                "perf_points": 0,
                "evidence": f"Lighthouse skipped: no report was written.\n{tail}",
                "ceiling": "",
            }
        report = json.loads(out.read_text(encoding="utf-8"))
        a11y = round(float(report["categories"]["accessibility"]["score"]) * 100)
        perf = round(float(report["categories"]["performance"]["score"]) * 100)
        cache_path.write_text(json.dumps({"digest": digest, "accessibility": a11y, "performance": perf}), encoding="utf-8")
        return _light_points(a11y, perf, f"production build on port {port}")
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()


def _web_digest() -> str:
    import hashlib

    digest = hashlib.sha256()
    root = ROOT / "web" / "src"
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _light_points(a11y: int, perf: int, where: str) -> dict:
    if a11y >= 95:
        a_points = 3
    elif a11y >= 90:
        a_points = 2
    elif a11y >= 80:
        a_points = 1
    else:
        a_points = 0
    if perf >= 90:
        p_points = 3
    elif perf >= 75:
        p_points = 2
    elif perf >= 50:
        p_points = 1
    else:
        p_points = 0
    return {
        "a11y_points": a_points,
        "perf_points": p_points,
        "evidence": f"Lighthouse ({where}): accessibility {a11y}, performance {perf}.",
        "ceiling": "",
    }


def days() -> None:
    proc = run([PY, "-m", "pytest", "-q", "server/tests/test_days.py", "--tb=line"], timeout=180)
    output = (proc.stdout or "") + (proc.stderr or "")
    passed, total = _pytest_counts(output, "server/tests/test_days.py")
    if total == 0:
        score = 0
    elif passed == total and proc.returncode == 0:
        score = 10
    else:
        score = min(9, round(10 * passed / total))
    overview_names = (
        "test_overview_orders_significant_chains_first",
        "test_overview_covers_each_chain_once",
        "test_overview_skips_noise",
        "test_overview_refresh_reads_only_what_is_new",
        "test_overview_full_keeps_every_sentence_and_quick_is_the_shorter_choice",
    )
    suite = (ROOT / "server" / "tests" / "test_days.py").read_text(encoding="utf-8")
    present = [name for name in overview_names if f"def {name}" in suite]
    add(
        "Day, library, and re-surface",
        score,
        "server/tests/test_days.py: "
        f"{passed}/{total} passed, exit {proc.returncode}.\n"
        f"Overview checks in this file: {', '.join(present) or 'none'}.\n"
        f"{output.strip()[-500:]}",
    )


def privacy() -> None:
    sandbox = os.environ.get("INBOX_BRIEF_DATA_DIR") or tempfile.mkdtemp(prefix="inbox-brief-privacy-")
    os.environ["INBOX_BRIEF_DATA_DIR"] = sandbox
    os.environ["INBOX_BRIEF_SEED"] = "0"
    os.environ["INBOX_BRIEF_SCHEDULE"] = "0"
    points = 0
    notes = []
    from inbox_brief.db import connect, init_db, save_settings
    from inbox_brief.secrets import read_secret, write_secret

    init_db()
    key = "sk-benchmark-privacy-key"
    save_settings({"llm_provider": "openai", "llm_api_key": key})
    with connect() as connection:
        stored = connection.execute("SELECT json FROM settings WHERE id = 1").fetchone()["json"]
        secret_row = connection.execute("SELECT payload FROM secrets WHERE name = 'llm_api_key'").fetchone()
    settings_file = Path(sandbox) / "settings.json"
    file_text = settings_file.read_text(encoding="utf-8") if settings_file.exists() else ""
    cipher = secret_row["payload"] if secret_row else ""
    if key not in stored and key not in file_text and cipher and key not in cipher and read_secret("llm_api_key") == key:
        points += 2
        notes.append("API key is ciphertext in the secrets table. The settings JSON does not contain the key, and the ciphertext is not the key.")
    else:
        notes.append("API key leaked into the settings document or was not sealed.")
    write_secret("gmail_oauth", json.dumps({"refresh_token": "gmail-refresh-benchmark"}))
    write_secret("outlook_oauth", json.dumps({"refresh_token": "outlook-refresh-benchmark"}))
    with connect() as connection:
        stored = connection.execute("SELECT json FROM settings WHERE id = 1").fetchone()["json"]
        names = [row["name"] for row in connection.execute("SELECT name FROM secrets").fetchall()]
    if "gmail-refresh-benchmark" not in stored and "outlook-refresh-benchmark" not in stored and "gmail_oauth" in names and "outlook_oauth" in names:
        points += 2
        notes.append("Gmail and Outlook tokens are in the secrets table, not the settings JSON.")
    else:
        notes.append(f"Token storage check failed. Secret names: {names}.")
    from inbox_brief.tts.voice_clip import save_clip

    wav = _tone_wav()
    clip = save_clip(wav, "mine.wav", consent=True, host="S1")
    del clip
    voice = Path(sandbox) / "voice" / "mine.wav"
    outside = [str(path) for path in Path("/tmp").glob("mine.wav")]
    if voice.is_file() and voice.resolve().is_relative_to(Path(sandbox).resolve()) and not outside:
        points += 2
        notes.append(f"Voice clip stored at {voice}, under the data directory.")
    else:
        notes.append(f"Voice clip path check failed: {voice} exists={voice.is_file()}.")
    hits = _secret_scan()
    if not hits:
        points += 2
        notes.append("Secret scan of server/inbox_brief, web/src, fixtures, and benchmark/corpus found no live key patterns.")
    else:
        notes.append("Secret scan hits: " + "; ".join(hits[:8]))
    from inbox_brief.ai import chat
    from inbox_brief.privacy import ExternalServiceError, assert_private_base_url

    rejected = False
    try:
        assert_private_base_url("https://api.openai.com/v1")
    except ExternalServiceError:
        rejected = True
    silent = chat({"llm_provider": "openai", "llm_api_key": "", "llm_model": "gpt-4o-mini"}, "system", "user")
    if rejected and silent is None:
        points += 2
        notes.append("assert_private_base_url rejects https://api.openai.com. ai.chat returns nothing when no API key is saved.")
    else:
        notes.append(f"Privacy gate failed. Rejected public host: {rejected}. chat without a key: {silent!r}.")
    add("Privacy and security", points, "\n".join(notes))


def _tone_wav() -> bytes:
    import io

    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * 16000 * 6)
    return buffer.getvalue()


def _secret_scan() -> list[str]:
    patterns = [
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"ya29\."),
        re.compile(r"AKIA[A-Z0-9]{16}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"xoxb-"),
    ]
    roots = [ROOT / "server" / "inbox_brief", ROOT / "web" / "src", ROOT / "fixtures", ROOT / "benchmark" / "corpus"]
    hits = []
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".json", ".eml", ".md", ".txt", ".toml"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern in patterns:
                if pattern.search(text):
                    hits.append(f"{path.relative_to(ROOT)} matches {pattern.pattern}")
    return hits


def reliability() -> None:
    proc = run([PY, "-m", "pytest", "-q", "server/tests", "--tb=line"], timeout=300)
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    points = 4 if proc.returncode == 0 else 0
    notes = [f"python3 -m pytest -q server/tests exited {proc.returncode}.", output[-400:]]
    suite = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "server" / "tests").glob("test_*.py"))
    unknown = "/api/podcasts" in suite and "404" in suite and "review period" in suite
    gmail = "/api/connect/gmail" in suite and "400" in suite
    empty = "No mail in this window" in suite or 'status"] == "empty"' in suite or "status == \"empty\"" in suite
    if unknown and gmail and empty:
        points += 2
        notes.append("The suite covers an unknown chain (404), Gmail without credentials (400), and an empty extractive brief.")
    else:
        notes.append(f"Suite coverage missing. unknown chain 404: {unknown}. Gmail 400: {gmail}. empty extractive: {empty}.")
    contracts_ok = proc.returncode == 0 and "def test_gmail_oauth_refresh_pagination_thread_and_backoff" in (
        ROOT / "server" / "tests" / "test_mail_contracts.py"
    ).read_text(encoding="utf-8")
    network_clean = getattr(faithfulness, "network_clean", False)
    if contracts_ok and network_clean:
        points += 2
        notes.append("Extractive generation made no network call. The contract suite mocks HTTP and passed inside the full pytest run.")
    else:
        notes.append(f"Network row not met. contracts passed: {contracts_ok}. extractive stayed offline: {network_clean}.")
    job_ok = _failed_job()
    if job_ok:
        points += 2
        notes.append("A failed podcast job stores a non-empty error string.")
    else:
        notes.append("A failed podcast job did not store an error string.")
    add("Reliability", points, "\n".join(notes))


def _failed_job() -> bool:
    try:
        from inbox_brief.jobs import _podcast
        from inbox_brief.store import create_job, get_job

        import inbox_brief.pipeline as pipeline

        def explode(*_args, **_kwargs):
            raise RuntimeError("benchmark podcast failed on purpose")

        original = pipeline.generate_podcast
        pipeline.generate_podcast = explode
        try:
            job_id = create_job("podcast")
            _podcast(job_id, "missing", "", "quick", "short", "kokoro_british", "full", ["missing"])
        finally:
            pipeline.generate_podcast = original
        job = get_job(job_id)
        return bool(job and job.get("status") == "error" and "benchmark podcast failed on purpose" in (job.get("error") or ""))
    except Exception:
        return False


def _measure_docs() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    checks = [
        ("docker compose up or uvicorn", ("docker compose up" in text) or ("uvicorn" in text)),
        ("INBOX_BRIEF_GOOGLE_CLIENT_ID", "INBOX_BRIEF_GOOGLE_CLIENT_ID" in text),
        ("Mail.Read and offline_access", "Mail.Read" in text and "offline_access" in text),
        ("@gongrzhe/server-gmail-autoauth-mcp", "@gongrzhe/server-gmail-autoauth-mcp" in text),
        ("@softeria/ms-365-mcp-server", "@softeria/ms-365-mcp-server" in text),
        ("stdio: and streamable HTTP", "stdio:" in text and "streamable HTTP" in text),
        ("scripts/verify-connections", "scripts/verify-connections" in text),
        ("make benchmark", "make benchmark" in text),
        ("cloud model only with a saved key", "cloud model only with a saved key" in text),
        ("Europe/London", "Europe/London" in text),
    ]
    points = sum(1 for _name, ok in checks if ok)
    lines = [f"{'yes' if ok else 'no'}  {name}" for name, ok in checks]
    add("Docs and onboarding", points, "\n".join(lines))


def _pytest_counts(output: str, path: str) -> tuple[int, int]:
    passed = int(match.group(1)) if (match := re.search(r"(\d+) passed", output)) else 0
    failed = int(match.group(1)) if (match := re.search(r"(\d+) failed", output)) else 0
    errors = int(match.group(1)) if (match := re.search(r"(\d+) error", output)) else 0
    total = passed + failed + errors
    if total == 0:
        total = len(re.findall(r"^def test_", Path(path).read_text(encoding="utf-8"), re.M))
        passed = 0
    return passed, total


def write_reports() -> None:
    _measure_docs()
    history = {"iterations": []}
    if HISTORY.is_file():
        history = json.loads(HISTORY.read_text(encoding="utf-8"))
    iteration = len(history["iterations"]) + 1
    stamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    total = sum(item["score"] for item in METRICS)
    row = {
        "iteration": iteration,
        "at": stamp,
        "total": total,
        "scores": {item["name"]: item["score"] for item in METRICS},
    }
    history["iterations"].append(row)
    HISTORY.write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# PodcastBox benchmark",
        "",
        f"Iteration {iteration} at {stamp}. Total **{total} / 120**.",
        "",
        "Criteria are fixed in `benchmark/RUBRIC.md`. Scores are not rounded up.",
        "",
        "## Scores",
        "",
        "| Metric | Score |",
        "| --- | ---: |",
    ]
    for item in METRICS:
        lines.append(f"| {item['name']} | {item['score']} / 10 |")
    lines.append("")
    lines.append("## Evidence")
    lines.append("")
    for item in METRICS:
        lines.append(f"### {item['name']}: {item['score']} / 10")
        lines.append("")
        lines.append(item["evidence"])
        lines.append("")
        if item["ceiling"]:
            lines.append(f"Ceiling: {item['ceiling']}")
            lines.append("")
    lines.append("## Score history")
    lines.append("")
    header = "| Iteration | " + " | ".join(item["name"] for item in METRICS) + " | Total |"
    rule = "| --- | " + " | ".join("---:" for _ in METRICS) + " | ---: |"
    lines.extend([header, rule])
    for past in history["iterations"]:
        cells = " | ".join(str(past["scores"].get(item["name"], "")) for item in METRICS)
        lines.append(f"| {past['iteration']} | {cells} | {past['total']} |")
    lines.extend(
        [
            "",
            "## Live versus mocked",
            "",
            "Contract tests mock the Gmail API, Microsoft Graph, and the GongRzhe and Softeria MCP tool responses. They are not live calls.",
            "`scripts/verify-connections` is the only live check. On this run it did not receive a PASS from Google or Microsoft unless the connectivity evidence says exit 0.",
            "Thread, noise, ask, script, and privacy checks run on local fixtures and the benchmark corpus. No mail leaves the machine.",
            "",
            "## Ceilings",
            "",
        ]
    )
    ceilings = [item for item in METRICS if item["ceiling"]]
    if ceilings:
        for item in ceilings:
            lines.append(f"- **{item['name']}** ({item['score']}/10). {item['ceiling']}")
    else:
        lines.append("No metric is held under 10 by a measurement ceiling on this run.")
    lines.append("")
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")
    REPORT_JSON.write_text(
        json.dumps({"iteration": iteration, "at": stamp, "total": total, "metrics": METRICS, "history": history["iterations"]}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
