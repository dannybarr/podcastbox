# PodcastBox benchmark rubric

These criteria are fixed. A later run may change the product. It may not change this file to lift a score.

Each metric is 0 to 10. A 10 is only the full criterion below. Partial points are only those written here.

## 1. Connectivity and MCP robustness

Sum the points. Cap at 10.

- 2: `test_gmail_oauth_refresh_pagination_thread_and_backoff` passes. That test uses recorded Gmail API JSON: OAuth code exchange, refresh, four list pages, `threadId`, and a 429 with `Retry-After` before success.
- 2: `test_outlook_oauth_refresh_pagination_thread_and_backoff` passes. Recorded Graph JSON: OAuth code exchange for `offline_access User.Read Mail.Read`, refresh, a page of 50 plus `@odata.nextLink`, `conversationId`, and a 429 before success.
- 2: `test_mcp_gmail_streamable_http_and_stdio` passes. GongRzhe tool names `search_emails` and `read_email`, streamable HTTP (including an SSE initialize) and stdio, and a second search page.
- 2: `test_mcp_outlook_streamable_http_pages` passes. Softeria tool names `list-mail-messages` and `get-mail-message`, with `@odata.nextLink`.
- 2: `scripts/verify-connections` exits 0. That means a live Gmail or Outlook check passed auth, list, fetch thread, and local disconnect. Exit 2 (nothing to check) scores 0 for this row. Exit 1 scores 0.

Mocks are not live. The last 2 points stay at 0 until a real mailbox is connected on the machine that runs the benchmark.

## 2. Thread consolidation

Labelled mailbox in `benchmark/corpus` (at least 40 messages) and `benchmark/labels/gold.json`.

Pairwise precision and recall on non-noise messages: a pair is gold when both messages share a `chain`. A pair is predicted when `build_chains` puts them in the same chain.

Score is 10 only when precision and recall are both 1. Otherwise the score is `min(9, round(10 * F1))`. Fewer than 40 messages scores 0.

## 3. Noise filtering

On the same gold file, a message is noise when `noise` is true. The product's `noise_reason` is the prediction.

Score is 10 only when precision and recall are both 1. Otherwise `min(9, round(10 * F1))`.

## 4. Suggestions and the ask box

Eight queries in `gold.json`. Each query passes when `ask_chains` returns exactly the expected chain keys, using the majority gold label of each predicted chain.

Score is 10 only when all eight pass. Otherwise `round(10 * passes / 8)` and at most 9 when any query fails.

## 5. Script faithfulness

Generate an extractive podcast for the Northquay chain with speech replaced by a test tone.

- 4 points when every segment has a source id and the neutrality guard keeps every sentence (no removal notes).
- 3 points when every number and every capitalised token in a line also appears in the cited source.
- 3 points when a planted line "This is a good idea" with no source overlap is removed by the guard.

## 6. Neutrality

On that same podcast, plus one line whose source text already contains "good":

- 5 points when the spoken podcast contains none of: i think, you should, we should, probably, good idea.
- 5 points when the guard keeps "good" only because the cited source contains it, and drops it when the source does not.

## 7. Audio naturalness and emotion

Automated proxy, 7 points maximum:

- 1: `demo/kokoro-british.mp3` exists, is larger than 10 KB, and starts with an MP3 frame or ID3 header.
- 1: `demo/transcript-british.json` has both S1 and S2.
- 1: segment timings in that transcript are monotonic and one range per segment.
- 1: the default voice preset is Kokoro British, `bf_emma` and `bm_george`.
- 1: preview files exist for Kokoro British, Kokoro American, and Dia.
- 1: saving a voice clip without consent raises `VoiceClipError`.
- 1: the British clip and the transcript durations agree within 2 seconds.

The remaining 3 points require `benchmark/listening.json` written by a person after listening: `listener` (non-empty name), `naturalness` 0-10, and `emotion` 0-10, all three at 10. A missing file, an empty listener, or a score under 10 awards 0 of these 3 points. The benchmark does not invent a listener.

## 8. UX simplicity

- 2: the app has exactly two screens, Home and Settings. Redirects do not count.
- 2: a running app reaches a podcast dialog in one click on "Turn into podcast", and the make button is on that dialog. Measured in the browser when `http://127.0.0.1:43123` is up. If the server is down, these 2 points are 0.
- 3: Lighthouse accessibility on the production build is at least 95 (2 points at 90, 1 point at 80).
- 3: Lighthouse performance on the production build is at least 90 (2 points at 75, 1 point at 50).

Lighthouse is skipped, and those points are 0, when Chrome or the production build cannot be measured.

## 9. Day, library, and re-surface

`server/tests/test_days.py` covers midnight bucketing, Home versus Library, later-day re-surface, full versus changed generation, and the all-emails filter.

Score is 10 only when that file passes. Otherwise `min(9, round(10 * passed / total))`.

## 10. Privacy and security

- 2: an API key written through `write_secret` is not plaintext in `settings.json`, and the ciphertext is not the key.
- 2: Gmail and Outlook tokens use the secrets table, not the settings JSON.
- 2: a voice clip is stored only under the data directory.
- 2: a scan of `server/inbox_brief`, `web/src`, `fixtures`, and `benchmark/corpus` finds no live key shaped like `sk-` plus 20 characters, `ya29.`, `AKIA` plus 16 characters, a PEM private key, or `xoxb-`. Tests may contain fakes. They are not scanned.
- 2: `assert_private_base_url` rejects a public model host, and `ai.chat` returns nothing when no API key is saved.

## 11. Reliability

- 4: `python3 -m pytest -q server/tests` exits 0.
- 2: the suite covers an unknown chain (404), Gmail without credentials (400), and an empty extractive brief.
- 2: extractive generation does not require a network call. The contract suite mocks HTTP and still passes.
- 2: a failed podcast job stores an error string.

These points come from the pytest run and from checks named in the runner. They are 0 when the check is absent.

## 12. Docs and onboarding

One point for each of these strings in `README.md`:

1. `docker compose up` or the local uvicorn command
2. `INBOX_BRIEF_GOOGLE_CLIENT_ID`
3. `Mail.Read` and `offline_access`
4. `@gongrzhe/server-gmail-autoauth-mcp`
5. `@softeria/ms-365-mcp-server`
6. `stdio:` and streamable HTTP
7. `scripts/verify-connections`
8. `make benchmark`
9. cloud model only with a saved key
10. `Europe/London`

## Ceilings

A metric that cannot reach 10 on this machine stays below 10. The report says which points were not awarded and what would award them. Scores are not rounded up to 10.
