# PodcastBox benchmark

Iteration 5 at 2026-10-18T19:58:23+00:00. Total **115 / 120**.

Criteria are fixed in `benchmark/RUBRIC.md`. Scores are not rounded up.

## Scores

| Metric | Score |
| --- | ---: |
| Connectivity and MCP robustness | 8 / 10 |
| Thread consolidation | 10 / 10 |
| Noise filtering | 10 / 10 |
| Suggestions and the ask box | 10 / 10 |
| Script faithfulness | 10 / 10 |
| Neutrality | 10 / 10 |
| Audio naturalness and emotion | 7 / 10 |
| UX simplicity | 10 / 10 |
| Day, library, and re-surface | 10 / 10 |
| Privacy and security | 10 / 10 |
| Reliability | 10 / 10 |
| Docs and onboarding | 10 / 10 |

## Evidence

### Connectivity and MCP robustness: 8 / 10

test_gmail_oauth_refresh_pagination_thread_and_backoff: pass (mocked Gmail, Graph, or MCP responses).
test_outlook_oauth_refresh_pagination_thread_and_backoff: pass (mocked Gmail, Graph, or MCP responses).
test_mcp_gmail_streamable_http_and_stdio: pass (mocked Gmail, Graph, or MCP responses).
test_mcp_outlook_streamable_http_pages: pass (mocked Gmail, Graph, or MCP responses).
scripts/verify-connections exited 2. The last 2 points need a live Gmail or Outlook account on this machine. Exit 2 means nothing was configured. Exit 1 means a configured account failed.
PodcastBox connection check
Live services only. A skip is not a pass.

Gmail: SKIP
  auth: SKIP  Set INBOX_BRIEF_GOOGLE_CLIENT_ID and INBOX_BRIEF_GOOGLE_CLIENT_SECRET.
  list: SKIP  No credentials.
  fetch thread: SKIP  No credentials.
  disconnect: SKIP  Nothing was stored.

Outlook: SKIP
  auth: SKIP  Set INBOX_BRIEF_MICROSOFT_CLIENT_ID and INBOX_BRIEF_MICROSOFT_CLIENT_SECRET.
  list: SKIP  No credentials.
  fetch thread: SKIP  No credentials.
  disconnect: SKIP  Nothing was stored.

MCP: SKIP
  auth: SKIP  No MCP server is saved in Settings.
  list: SKIP  Add an http URL or a stdio: command.
  fetch thread: SKIP  No server.
  disconnect: SKIP  MCP servers keep their own login.

Result: SKIP  No live mailbox could be checked.

Ceiling: 8/10 until scripts/verify-connections exits 0 against a real mailbox: set the Google or Microsoft client id and secret, connect the account, and run the script. A mock cannot award these 2 points.

### Thread consolidation: 10 / 10

45 labelled messages, 37 non-noise. Pairwise precision 1.000 (83/83), recall 1.000 (83/83). Missed pairs sample: none. Extra pairs sample: none.

### Noise filtering: 10 / 10

Precision 1.000, recall 1.000. False noise: none. Missed noise: none. Unparsed: none. Kept sample size 37.

### Suggestions and the ask box: 10 / 10

8/8 queries.
'update on Northquay': pass got ['northquay'] expected ['northquay']
'update on Birchkiln': pass got ['birchkiln'] expected ['birchkiln']
'my communications with Farah Colour': pass got ['colourpass'] expected ['colourpass']
'handheld radio channel': pass got ['radio'] expected ['radio']
'zebra docking fee': pass got ['zebra'] expected ['zebra']
'nylon badge reels': pass got ['lanyard'] expected ['lanyard']
'pension form PF-204': pass got ['payroll'] expected ['payroll']
'fender inspection bollard': pass got ['dock'] expected ['dock']

### Script faithfulness: 10 / 10

Extractive Northquay podcast 4aacaa71ebe7: 4 segments, each with a source id, guard notes empty. Speech was a test tone.
Extractive generation made no HTTP call.
Every number and capitalised token in the spoken lines appears in the cited source.
Planted line 'This is a good idea' was removed. A sourced Northquay sentence stayed.

### Neutrality: 10 / 10

Spoken Northquay podcast contains none of: i think, you should, we should, probably, good idea.
The guard kept 'good' when the cited source says good, and dropped it when the source does not.

### Audio naturalness and emotion: 7 / 10

kokoro-british.mp3 is 216021 bytes and starts with b'ID3'.
Transcript has S1 and S2.
4 timing ranges, monotonic, one per segment.
Default voice preset is kokoro_british with bf_emma and bm_george.
Preview files exist for Kokoro British, Kokoro American, and Dia.
save_clip without consent raises VoiceClipError.
British clip is 29.63s. Transcript ends at 30.79s. Within 2 seconds.
benchmark/listening.json is absent. The benchmark does not invent a listener.

Ceiling: 7/10 until a person listens to demo/kokoro-british.mp3 against demo/transcript-british.json and writes benchmark/listening.json with their name, naturalness 10, and emotion 10. The automated proxy cannot award the last 3 points.

### UX simplicity: 10 / 10

Two screens: Home and Settings. Redirects: ['web/src/app/sources/page.tsx', 'web/src/app/history/page.tsx', 'web/src/app/sources/[id]/page.tsx', 'web/src/app/editions/[id]/page.tsx'].
Browser: one click on Turn into podcast opened a dialog that contains Make the podcast.
Lighthouse (production build on port 43191): accessibility 100, performance 100.

### Day, library, and re-surface: 10 / 10

server/tests/test_days.py: 12/12 passed, exit 0.
Overview checks in this file: test_overview_orders_significant_chains_first, test_overview_covers_each_chain_once, test_overview_skips_noise, test_overview_refresh_reads_only_what_is_new, test_overview_full_keeps_every_sentence_and_quick_is_the_shorter_choice.
          [100%]
=============================== warnings summary ===============================
tests/test_days.py::test_api_keeps_today_on_home_and_older_days_in_the_library
  /tmp/pydeps/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
12 passed, 1 warning in 1.87s

### Privacy and security: 10 / 10

API key is ciphertext in the secrets table. The settings JSON does not contain the key, and the ciphertext is not the key.
Gmail and Outlook tokens are in the secrets table, not the settings JSON.
Voice clip stored at /tmp/inbox-brief-bench-jpg5oz3m/voice/mine.wav, under the data directory.
Secret scan of server/inbox_brief, web/src, fixtures, and benchmark/corpus found no live key patterns.
assert_private_base_url rejects https://api.openai.com. ai.chat returns nothing when no API key is saved.

### Reliability: 10 / 10

python3 -m pytest -q server/tests exited 0.
ummary ===============================
../tmp/pydeps/fastapi/testclient.py:1
  /tmp/pydeps/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
54 passed, 1 warning in 3.79s
The suite covers an unknown chain (404), Gmail without credentials (400), and an empty extractive brief.
Extractive generation made no network call. The contract suite mocks HTTP and passed inside the full pytest run.
A failed podcast job stores a non-empty error string.

### Docs and onboarding: 10 / 10

yes  docker compose up or uvicorn
yes  INBOX_BRIEF_GOOGLE_CLIENT_ID
yes  Mail.Read and offline_access
yes  @gongrzhe/server-gmail-autoauth-mcp
yes  @softeria/ms-365-mcp-server
yes  stdio: and streamable HTTP
yes  scripts/verify-connections
yes  make benchmark
yes  cloud model only with a saved key
yes  Europe/London

## Score history

| Iteration | Connectivity and MCP robustness | Thread consolidation | Noise filtering | Suggestions and the ask box | Script faithfulness | Neutrality | Audio naturalness and emotion | UX simplicity | Day, library, and re-surface | Privacy and security | Reliability | Docs and onboarding | Total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 8 | 10 | 10 | 10 | 10 | 10 | 7 | 10 | 10 | 10 | 8 | 4 | 107 |
| 2 | 8 | 10 | 10 | 10 | 10 | 10 | 7 | 10 | 10 | 10 | 10 | 10 | 115 |
| 3 | 8 | 10 | 10 | 10 | 10 | 10 | 7 | 10 | 10 | 10 | 10 | 10 | 115 |
| 4 | 8 | 10 | 10 | 10 | 10 | 10 | 7 | 10 | 10 | 10 | 10 | 10 | 115 |
| 5 | 8 | 10 | 10 | 10 | 10 | 10 | 7 | 10 | 10 | 10 | 10 | 10 | 115 |

## Live versus mocked

Contract tests mock the Gmail API, Microsoft Graph, and the GongRzhe and Softeria MCP tool responses. They are not live calls.
`scripts/verify-connections` is the only live check. On this run it did not receive a PASS from Google or Microsoft unless the connectivity evidence says exit 0.
Thread, noise, ask, script, and privacy checks run on local fixtures and the benchmark corpus. No mail leaves the machine.

## Ceilings

- **Connectivity and MCP robustness** (8/10). 8/10 until scripts/verify-connections exits 0 against a real mailbox: set the Google or Microsoft client id and secret, connect the account, and run the script. A mock cannot award these 2 points.
- **Audio naturalness and emotion** (7/10). 7/10 until a person listens to demo/kokoro-british.mp3 against demo/transcript-british.json and writes benchmark/listening.json with their name, naturalness 10, and emotion 10. The automated proxy cannot award the last 3 points.
