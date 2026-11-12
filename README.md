# RouteGrid

**Prototype email triage for ZEISS India.** RouteGrid is the routing layer for a proposed unified customer email channel: customers write to one address, `contact@zeiss.com`, and RouteGrid decides which department queue should own each message. It watches an IMAP inbox, asks an OpenRouter Decisions model three typed questions, and appends the message to a local JSONL queue for downstream processing. It does not send replies, forward mail, or change anything in the mailbox.

> **Status:** prototype. Output is local JSONL under `queues/`. There is no database, ticketing integration, or downstream consumer in this repository. For the rationale and the broader understand please provided Document.

## What it does

- Watches the configured IMAP mailbox — the proposed unified inbox, `contact@zeiss.com` — over SSL using `IDLE`.
- Skips the existing backlog and processes only mail that arrives after startup.
- Normalizes each message to `{id, from, subject, date, body}`.
- Sends one Decisions API request containing three typed questions.
- Appends the message and the resulting decision to the matching department queue, `queues/<queue>/<UTC-date>.jsonl`, for downstream processing.
- Sends non-inquiries, low-confidence results, unknown queue names, and failed classifications to `queues/_review/`.

The pipeline is deliberately one-way: no auto-replies, no forwarding, no moves, and no `\Seen` flags.

## Unified email channel

Today ZEISS India publishes a separate address for each department:

| Public address | Purpose / department |
|---|---|
| info.in@zeiss.com | General ZEISS India inquiries, company information, and customer assistance |
| mikroservice.india@zeiss.com | Microscopy technical support, equipment servicing, repairs, and maintenance |
| info.microscopy.in@zeiss.com | Microscopy product inquiries, sales information, and application assistance |
| info.meditec.in@zeiss.com | Medical technology inquiries, including ophthalmology and surgical equipment |
| iolorder.in@zeiss.com | Intraocular lens (IOL) orders, medical consumables, and related order inquiries |
| info.metrology.in@zeiss.com | Industrial metrology, measuring equipment, quality inspection, and related support |
| info@zeiss.co.in | General inquiries associated with ZEISS India's optical products and services |
| dpo.in@zeiss.com | Data privacy concerns, personal data requests, and GDPR/Indian privacy compliance |
| legal.in@zeiss.com | Legal inquiries, compliance matters, and privacy-related legal concerns |
| webmaster@zeiss.com | Website technical problems, broken links, and other website-related issues |

This puts the burden of knowing the org chart on the customer. A message sent to the wrong address is forwarded manually, delayed, or lost, and each inbox becomes a separate silo with no shared view of demand.

The target model is one public address, **`contact@zeiss.com`**, backed by RouteGrid:

1. The customer sends to `contact@zeiss.com`.
2. RouteGrid watches that mailbox and classifies each message.
3. The message is written to the matching department queue, or to `_review` when the policy is not confident.
4. A downstream service consumes the queue and performs the department-specific action: ticketing, assignment, reply, or delivery.

The existing department addresses remain useful as internal routing targets and can stay as aliases during the transition. The public interface becomes one address; the internal taxonomy stays intact.

> **Scope note:** the current prototype does not forward mail to the department addresses or send replies. It writes local JSONL queue records. Email delivery, alias management, and downstream processing are production integrations that sit outside this repository.

## Pipeline

```text
┌──────────────┐   IMAP IDLE   ┌────────────────┐   asyncio.Queue   ┌────────────────┐
│  Mail server │ ────────────▶ │  ImapListener  │ ────────────────▶ │ email_consumer │
└──────────────┘    new mail   │    (thread)    │                   └───────┬────────┘
                               └────────────────┘                           │ route_email()
                                                                            ▼
                                                              ┌──────────────────────────┐
                                                              │  Decisions API           │
                                                              │  ├ is_zeiss_inquiry      │
                                                              │  ├ department            │
                                                              │  └ urgency               │
                                                              └────────────┬─────────────┘
                                                                           │
                                                ┌──────────────────────────┴───────────────────────┐
                                                ▼                                                  ▼
                                  queues/<department>/<date>.jsonl                  queues/_review/<date>.jsonl
```

1. **Ingest** — `ImapListener` logs in, selects the folder read-only, records the highest existing UID, and waits on `IDLE`. On wake it fetches every UID above the cursor, parses the raw message, and hands it to the asyncio consumer through `loop.call_soon_threadsafe`.
2. **Normalize** — `mail_parser` decodes RFC 2047 headers and extracts the first non-attachment `text/plain` part into a normalized mail record.
3. **Classify** — `classify()` posts the message as the Decisions API `state` together with three typed questions.
4. **Dispatch** — `interpret()` applies the thresholds, and `enqueue()` appends the record to the winning queue or to `_review`.

The blocking HTTP call runs in a worker thread via `asyncio.to_thread`, so the event loop keeps draining the listener queue.

## The three questions

| Key | Type | What it decides |
|---|---|---|
| `is_zeiss_inquiry` | `noul` | Probability that the message is a genuine inquiry (customer, prospect, partner, supplier, regulator, or employee asking for information, support, a quotation, an order, or action) rather than an automated notification, newsletter, marketing blast, spam, or unrelated personal mail. |
| `department` | `choice` | Which of the ten ZEISS India queue slugs should own the message. |
| `urgency` | `score` | Ordered levels: routine, time-sensitive, urgent. Returned as a numeric score. |

The model returns typed answers with probabilities rather than free text. That lets the router enforce explicit thresholds instead of trusting a single label, and the full `department` distribution is stored so thresholds can be re-tuned later without re-classifying.

The model is only one of three layers. The policy in `interpret()` decides whether to trust the answer, and the action in `enqueue()` is limited to writing a department queue record or a review record. The model never sends, forwards, or moves mail. [`PITCH.md`](PITCH.md) describes the broader model + policy + action pattern and its reuse outside email.

Default model: `parallel/decisions-fast:free`, configurable with `ROUTER_MODEL`.

## Queues

These are the internal routing targets behind the unified inbox. In the unified-channel model, customers no longer need to know these addresses; RouteGrid maps each message to one of them, and the `address` is carried in the queue record as metadata for downstream processing.

| Slug | Address | Purpose |
|---|---|---|
| `info_in` | info.in@zeiss.com | General ZEISS India inquiries, company information, customer assistance, and mail that does not clearly belong to a specialist queue. |
| `mikroservice_india` | mikroservice.india@zeiss.com | Microscopy technical support, equipment servicing, repairs, maintenance visits, and service contracts. |
| `info_microscopy_in` | info.microscopy.in@zeiss.com | Microscopy product inquiries, sales information, application assistance, quotations, and demo requests. |
| `info_meditec_in` | info.meditec.in@zeiss.com | Medical technology inquiries, ophthalmology and surgical equipment, clinical applications, and Meditec sales. |
| `iolorder_in` | iolorder.in@zeiss.com | Intraocular lens (IOL) orders, medical consumables, order status, delivery, and related order inquiries. |
| `info_metrology_in` | info.metrology.in@zeiss.com | Industrial metrology, measuring equipment, quality inspection, calibration, and related support. |
| `zeiss_co_in` | info@zeiss.co.in | Optical products and services, vision care, eyeglass lenses, and consumer optics. |
| `dpo_in` | dpo.in@zeiss.com | Data privacy concerns, personal data access or deletion requests, and GDPR or Indian privacy compliance. |
| `legal_in` | legal.in@zeiss.com | Legal inquiries, compliance matters, contracts, litigation, and privacy-related legal concerns. |
| `webmaster` | webmaster@zeiss.com | Website technical problems, broken links, login failures, and other website issues. |
| `_review` | *(local only)* | Not an inquiry, low confidence, unknown queue, or classification error. |

The registry lives in `src/routing/queues.py`. Adding a department is a one-entry change: give it a slug, an address, and a purpose that helps the model distinguish it from the others. `_review` is not part of the registry; it is the local fallback defined by `REVIEW_QUEUE`.

## Routing rules

| Condition | Destination | Recorded reason |
|---|---|---|
| `P(inquiry) < ROUTER_INQUIRY_THRESHOLD` | `_review` | `not a ZEISS inquiry (p=... < ...)` |
| Chosen slug is not in the queue registry | `_review` | `model chose unknown queue '...'` |
| `P(queue) < ROUTER_THRESHOLD` | `_review` | `low confidence for <slug> (p=... < ...)` |
| Per-queue probability missing, answer-level `confidence` present | Threshold checked against that confidence | `low confidence ...` if below; otherwise routes |
| No per-queue probability and no answer-level confidence | Department queue | `unscored by model` |
| Any exception during classification | `_review` | `classification_failed: <error>` with `method: "error"` |

Defaults are `ROUTER_INQUIRY_THRESHOLD=0.50` and `ROUTER_THRESHOLD=0.60`.

The two missing-probability cases are intentional. Missing metadata is not evidence of a bad classification, so the message still routes rather than being buried. Every other uncertainty lands in `_review` with the reason attached.

`route()` never raises on classification failure; it writes a review record instead. It can still raise if the queue file itself cannot be written (for example, a permissions error).

## Setup

**Requirements:** Python 3.10+, an IMAP mailbox that allows app passwords, and an OpenRouter API key.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirement.txt
```

Dependencies are only `python-dotenv`, `requests`, and `IMAPClient`.

Create a `.env` file in the project root. `src/config.py` loads it from the repository root regardless of the current working directory:

```ini
# Mailbox
IMAP_SERVER=imap.gmail.com
IMAP_PORT=993
EMAIL_ACCOUNT=you@example.com
APP_PASSWORD=your-app-password

# OpenRouter
API_KEY=sk-or-v1-...

# Routing (optional)
ROUTER_MODEL=parallel/decisions-fast:free
ROUTER_THRESHOLD=0.60
ROUTER_INQUIRY_THRESHOLD=0.50
```

`EMAIL_ACCOUNT`, `APP_PASSWORD`, and an OpenRouter key (`API_KEY` or `OPENROUTER_API_KEY`) are required. Gmail needs 2-Step Verification and an [App Password](https://myaccount.google.com/apppasswords); a normal account password will not work.

## Configuration

All settings are read from the environment, with `.env` loaded once at import time. Restart the process after changing them.

| Variable | Default | Meaning |
|---|---|---|
| `IMAP_SERVER` | `imap.mail.yahoo.com` | IMAP host. |
| `IMAP_PORT` | `993` | IMAP SSL port. |
| `EMAIL_ACCOUNT` | — | Mailbox login. **Required.** |
| `APP_PASSWORD` | — | Mailbox app password. **Required.** |
| `IMAP_FOLDER` | `INBOX` | Folder to watch. |
| `IDLE_TIMEOUT` | `60` | Seconds per IDLE wait before re-checking. |
| `RECONNECT_DELAY` | `5` | Seconds to wait before reconnecting after an IMAP error. |
| `API_KEY` | — | OpenRouter key. `OPENROUTER_API_KEY` is used as a fallback. **Required.** |
| `ROUTER_MODEL` | `parallel/decisions-fast:free` | Decisions model ID. |
| `REQUEST_TIMEOUT` | `60` | HTTP timeout in seconds. |
| `RETRY_ATTEMPTS` | `3` | Total attempts for retryable HTTP responses. |
| `MAX_BODY_CHARS` | `8000` | Body characters sent to the model. |
| `ROUTER_THRESHOLD` | `0.60` | Minimum queue probability before routing. |
| `ROUTER_INQUIRY_THRESHOLD` | `0.50` | Minimum probability that the mail is a real inquiry. |
| `QUEUE_DIR` | `<repository>/queues` | Where queue files are written. A relative value is resolved against the current working directory. |

The endpoint is fixed at `https://openrouter.ai/api/alpha/decisions`.

## Running the listener

```bash
python main.py
```

Typical output:

```text
RouteGrid listening on imap.gmail.com:993 [INBOX]
Queue directory: /path/to/ZEISS/queues
Connecting to imap.gmail.com:993...
Watching INBOX for new mail (UID > 12470)...

========== NEW EMAIL ==========
UID: 12471
From: Dr Rao <dr.rao@eyehospital.in>
Subject: Purchase order for IOL lenses
Date: Wed, 11 Nov 2026 09:13:40 +0530
Body: Dear ZEISS India, we would like to order 40 intraocular lenses...
-------------------------------
Routed to: iolorder_in (iolorder.in@zeiss.com) confidence=0.99 urgency=0.31
===============================
```

Stop with `Ctrl+C`. Only mail arriving **after** startup is processed; the existing inbox is left untouched.

## Project layout

```text
main.py                      Entry point: IMAP listener thread + async consumer
PITCH.md                     Pitch: model + policy + action, and reuse beyond email
requirement.txt              Python dependencies
DEVLOG.md                    Historical build log (may name removed files)
src/
  config.py                  Environment and .env settings, loaded at import
  models.py                  Decisions API question/answer/payload models
  decisions.py               The only module that performs HTTP
  ingestion/
    imap_listener.py         IMAP IDLE listener, runs in a daemon thread
    mail_parser.py           MIME bytes -> normalized mail record
  routing/
    decision.py              RoutingDecision and log formatting
    queues.py                Queue registry and JSONL writer
    router.py                Questions, classification, dispatch, CLI
queues/                      Runtime output: <slug>/<YYYY-MM-DD>.jsonl
```
