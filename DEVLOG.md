
# DevLog — RouteGrid

## Day 1: Ingestion Pipeline & IMAP Integration

### Objective
Establish the foundational inbound email ingestion infrastructure for **RouteGrid**: securely connect to an IMAP mail server, retrieve incoming messages, and transform raw MIME payloads into clean, structured data for downstream System 1 decision triage.

---

### Architecture & Components

- **`src/ingestion/imap_client.py`**:
  - Implemented the `IMAPClient` class using Python's standard `imaplib`.
  - Configured secure SSL/TLS communication over port 993 with a custom `ssl.SSLContext` enforcing TLS 1.2.
  - Implemented `fetch_latest_emails()` to query `INBOX` in `readonly=True` mode (preventing unread flags from being altered) and retrieve message IDs in reverse chronological order.

- **`src/ingestion/mail_parser.py`**:
  - Implemented `clean_header_text()` using `email.header.decode_header` to decode RFC 2047 MIME-encoded headers (Subject, From, Date) into standard strings.
  - Implemented `get_email_body()` using `email.message_from_bytes` and tree walking (`msg.walk()`) to traverse multipart MIME payloads, extract `text/plain` sections, and filter out binary attachment parts.
  - Implemented `parse_raw_email()` to produce normalized dictionary records.

- **`src/main.py`**:
  - Added pipeline entry point orchestrating connection, retrieval, and standard output formatting with configurable limit bounds.

---

### Technical Obstacles & Debugging Log

1. **Network Firewall / Port 993 Drop (`WinError 10060`):**
   - *Problem:* Outbound socket connection to `imap.gmail.com:993` timed out due to institutional Wi-Fi firewall policies dropping non-HTTP traffic.
   - *Fix:* Switched network route to a mobile tethered hotspot to

## Day 2: Decisions-Based Routing to ZEISS India Queues

### Objective
Turn the ingestion pipeline into an actual router: classify every incoming message into one of the ten ZEISS India department queues, or park it for human review when the model is unsure.

---

### Architecture & Components

- **`models.py`**:
  - Added typed wrappers for OpenRouter's Decisions API: `Question` (`noul`, `choice`, `score`, `box`), `DecisionPayload` and `Answer`.
  - Validation happens before the request: `noul` must have exactly `true`/`false` criteria, `choice` needs a non-empty option map, `score` needs an ordered list of at least two levels, `box` takes no criteria.
  - `parse_answers()` rejects missing answer keys and mismatched answer types instead of silently defaulting.

- **`router.py`**:
  - Replaced the throwaway decision call with a full router: queue registry, question builder, classifier, queue writer and CLI.
  - One request asks three questions: `is_zeiss_inquiry` (`noul`), `department` (`choice` over the ten queues) and `urgency` (`score`).
  - Retries `429`/`5xx` with exponential backoff; surfaces `400`/`401`/`402` immediately with a hint.
  - Routes to `queues/<queue>/<YYYY-MM-DD>.jsonl`; below-threshold, non-inquiry, unknown-queue and failed classifications go to `queues/_review` with the reason attached, so no mail is lost.
  - Default model is `parallel/decisions-fast:free` (free, 32k context) and is configurable via `ROUTER_MODEL`.

- **`main.py`**:
  - `process_email()` now calls `route_email()`, which runs the blocking HTTP call in a worker thread via `asyncio.to_thread`.
  - Logs the queue, address, confidence, urgency and any review reason.

---

### Routing Policy

- Route only when `P(queue) >= 0.60` and `P(inquiry) >= 0.50`; otherwise review.
- Model-omitted probabilities fall back to the answer's `confidence`; if both are absent the mail still routes and is marked `unscored` rather than being buried.
- Queue files are JSONL so a downstream worker can tail them, and mail data stays out of git (`queues/*`, `.gitkeep` kept).

---

### Technical Obstacles & Debugging Log

1. **`requests` not installed in `.venv`:**
   - *Problem:* `router.py` imported `requests`, but the virtualenv only had `python-dotenv` and `IMAPClient`.
   - *Fix:* Installed `requests` and added it (plus `IMAPClient`) to `requirement.txt`.

2. **`sample.json` was not valid JSON:**
   - *Problem:* The file was a Python dict repr with a raw newline inside the `date` value, so neither `json.loads` nor `ast.literal_eval` could parse it.
   - *Fix:* Rewrote the sample as strict JSON; the loader still accepts Python-literal dicts as a fallback for older fixtures.

3. **`root=` leaked into the classifier:**
   - *Problem:* `route(mail, **kwargs)` forwarded `root` to `classify()`, so smoke-test writes landed in the real `queues/` directory while the test believed it was sandboxed.
   - *Fix:* Made `root` an explicit keyword-only parameter on `route()`/`route_email()` and asserted in the test that the path stays inside the temporary root.

4. **Misleading 401 body:**
   - *Problem:* An invalid OpenRouter key returns `401 {"message":"Missing Authentication header"}`, which reads like a client bug.
   - *Fix:* Added a hint to the error text (`API_KEY must be an OpenRouter key`) so the failure is obvious from the log.

---

### Validation

- Live classification checks passed: IOL order → `iolorder_in`, broken download link → `webmaster`, DPDP/GDPR deletion request → `dpo_in`, CMM calibration → `info_metrology_in`, microscope repair → `mikroservice_india`.
- Google security alert in `sample.json` correctly stayed out of the department queues and went to `_review` (`P(inquiry) = 0.02`).
- Offline checks covered threshold behaviour, unknown queue slugs, missing probabilities, API failure fallback and the async wrapper.


## Day 3: Listener Entry Point & Package Restructure

### Objective
Make the listener the single entry point and move the flat prototype files into a proper package, so ingestion, classification and dispatch each live in their own module.

---

### Architecture & Components

- **`main.py`** (entry point):
  - Starts the IMAP listener in a daemon thread and drains an `asyncio.Queue` in `email_consumer()`.
  - Logs each message, awaits `route_email()`, then prints the chosen queue/address/confidence.
  - On shutdown it sets the stop event and joins the listener thread.

- **`src/config.py`**:
  - Single place that loads `.env` and exposes IMAP, Decisions API, threshold and queue settings.

- **`src/models.py`**:
  - Moved the typed Decisions API models here unchanged (`Question`, `DecisionPayload`, `Answer`, `parse_answers`).

- **`src/decisions.py`**:
  - The only module that speaks HTTP. `ask()` posts a `DecisionPayload`, retries `429`/`5xx`, and returns a validated `DecisionsResponse` (answers, exact model build, cost).
  - Sends only `Authorization` and `Content-Type`; attribution headers are intentionally omitted.

- **`src/ingestion/mail_parser.py`**:
  - MIME header decoding and plain-text body extraction, moved out of `main.py`.

- **`src/ingestion/imap_listener.py`**:
  - `ImapListener` class wrapping the IDLE loop: connect, select read-only, skip the backlog (`UID > max`), fetch new UIDs, hand them to the event loop thread-safely.
  - Detects `UIDVALIDITY` changes and restarts from the new mailbox state.

- **`src/routing/decision.py`**:
  - `RoutingDecision` and `format_decision()`, shared by the router and the queue writer.

- **`src/routing/queues.py`**:
  - The ten ZEISS queue definitions plus `_review`, and the JSONL writer with a process-wide lock.

- **`src/routing/router.py`**:
  - Questions, state builder, `interpret()`, `classify()`, `route()`/`route_email()` and the one-off CLI (`python -m src.routing.router`).

---

### Behaviour Locked In

- Listener processes only mail that arrives after startup; the existing backlog is skipped.
- Mailbox stays untouched: read-only select, no `\Seen`, no moves, no deletes.
- Queue output remains local JSONL; nothing is forwarded to the ZEISS addresses.
- Low confidence, non-inquiry, unknown queue or API failure → `queues/_review` with the reason.

---

### Technical Obstacles & Debugging Log

1. **Silent listener under `timeout`/pipes:**
   - *Problem:* `timeout 15 python main.py` printed nothing because stdout is block-buffered when not a TTY and SIGTERM does not flush it.
   - *Fix:* Verified with `python -u`; the listener connected, logged `Watching INBOX for new mail (UID > 12470)` and idled correctly.

2. **RFC 2047 test fixture was wrong, not the parser:**
   - *Problem:* Setting a non-ASCII `EmailMessage` subject produced a literal `=C3=84...` string, so the decode test failed.
   - *Fix:* Used a real encoded word (`=?utf-8?q?...?=`) in the fixture; `clean_header_text()` decoded it to `Ärger mit dem Service`.

3. **Listener had to be testable without a server:**
   - *Problem:* The original `watch_mailbox()` was a single nested function tied to global config.
   - *Fix:* Split `_watch()` / `_fetch_new()` and injected server/account/folder, so a fake IMAP client can verify backlog skipping and UID advancement offline.

---

### Validation

- Offline: model validation, threshold/review rules, MIME parsing, listener backlog skipping, queue writing, API-failure fallback, async wrapper, consumer queue draining.
- Live API: IOL order → `iolorder_in`, broken link → `webmaster`, privacy request → `dpo_in`, CMM calibration → `info_metrology_in`.
- Live IMAP: connected to `imap.gmail.com:993`, selected `INBOX` read-only and entered IDLE.
