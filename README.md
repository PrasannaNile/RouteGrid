<p align="center">
  <img src="https://i.postimg.cc/wv5nsJ0h/Route-Grid.png" alt="RouteGrid logo" width="360">
</p>

<h1 align="center">RouteGrid</h1>

<p align="center">
  <strong>Reflexive email triage for ZEISS India</strong><br>
  Watches an inbox, understands each message, and files it in the right department queue in a single API call.
</p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white">
  <img alt="OpenRouter Decisions" src="https://img.shields.io/badge/OpenRouter-Decisions-6467f2">
  <img alt="IMAP IDLE" src="https://img.shields.io/badge/IMAP-IDLE-0b7285">
</p>

---

RouteGrid is the **System 1** layer of an email support pipeline: the fast, reflexive gatekeeper that reads incoming mail and dispatches it to the correct ZEISS India department queue. It is not a chatbot and it does not generate replies. It makes one narrow, typed decision per message and gets out of the way.

- **Listens continuously** — connects over IMAP IDLE and reacts the moment mail arrives.
- **Understands intent** — asks a decision model whether the mail is a real inquiry, which queue owns it, and how urgent it is.
- **Never guesses silently** — low-confidence, non-inquiry, or failed classifications go to a human review queue with the reason attached.
- **Leaves the mailbox alone** — read-only access, no flags, no moves, no deletes.

> **Status:** prototype. Routing output is local JSONL; RouteGrid does not send or forward email.

---

## Contents

- [How it works](#how-it-works)
- [Queues](#queues)
- [Project layout](#project-layout)
- [Quick start](#quick-start)
- [Configuration](#configuration)
- [Classify a single message](#classify-a-single-message)
- [Queue output](#queue-output)
- [Routing policy](#routing-policy)
- [Operational notes](#operational-notes)
- [Security](#security)
- [Development](#development)

---

## How it works

```text
┌──────────────┐   IMAP IDLE   ┌───────────────┐   asyncio.Queue   ┌────────────────┐
│  Mail server │ ────────────▶ │ ImapListener  │ ────────────────▶ │ email_consumer │
└──────────────┘    new mail   └───────────────┘                   └───────┬────────┘
                                                                          │ route_email()
                                                                          ▼
                                                          ┌───────────────────────────┐
                                                          │  Decisions API            │
                                                          │  ├ is_zeiss_inquiry       │
                                                          │  ├ department             │
                                                          │  └ urgency                │
                                                          └─────────────┬─────────────┘
                                                                        │
                                             ┌──────────────────────────┴───────────────────────┐
                                             ▼                                                  ▼
                               queues/<department>/<date>.jsonl                  queues/_review/<date>.jsonl
```

1. **Ingest** — `ImapListener` logs in, selects the folder read-only, records the highest existing UID (so the old backlog is skipped), and waits on `IDLE`.
2. **Normalize** — `mail_parser` decodes RFC 2047 headers and extracts the first plain-text body part into a `{id, from, subject, date, body}` record.
3. **Classify** — one request to `POST /api/alpha/decisions` with the mail as `state` and three typed questions.
4. **Dispatch** — the winning queue is validated against the registry; the record is appended to that queue's JSONL file, or to `_review` when anything is off.

### Why a decision model?

The model returns **typed answers with probabilities**, not prose. There is no prompt engineering, no parsing of free text, and no way to get a plausible-sounding answer with no confidence attached. A `choice` answer carries the full distribution, so the router can enforce a threshold instead of trusting a single label.

| Question | Type | What it decides |
|---|---|---|
| `is_zeiss_inquiry` | `noul` | Is this a genuine inquiry, or an automated notification, newsletter, or spam? |
| `department` | `choice` | Which of the ten ZEISS India queues should own it? |
| `urgency` | `score` | Routine → time-sensitive → urgent |

Default model: [`parallel/decisions-fast:free`](https://openrouter.ai/parallel/decisions-fast:free).

---

## Queues

| Slug | Email address | Purpose |
|---|---|---|
| `info_in` | info.in@zeiss.com | General ZEISS India inquiries and customer assistance |
| `mikroservice_india` | mikroservice.india@zeiss.com | Microscopy technical support, servicing, repairs and maintenance |
| `info_microscopy_in` | info.microscopy.in@zeiss.com | Microscopy product, sales and application inquiries |
| `info_meditec_in` | info.meditec.in@zeiss.com | Medical technology, ophthalmology and surgical equipment |
| `iolorder_in` | iolorder.in@zeiss.com | Intraocular lens orders and medical consumables |
| `info_metrology_in` | info.metrology.in@zeiss.com | Industrial metrology, measurement, inspection and calibration |
| `zeiss_co_in` | info@zeiss.co.in | Optical products, vision care and consumer optics |
| `dpo_in` | dpo.in@zeiss.com | Data privacy, GDPR / DPDP requests and personal data |
| `legal_in` | legal.in@zeiss.com | Legal, compliance, contracts and litigation |
| `webmaster` | webmaster@zeiss.com | Website problems, broken links and login failures |
| `_review` | *(local)* | Not an inquiry, low confidence, unknown queue, or error |

The registry lives in [`src/routing/queues.py`](src/routing/queues.py). Adding a queue is a one-entry change: give it a slug, an address, and a description that helps the model tell it apart from the others.

---

## Project layout

```text
main.py                      Entry point: listener thread + async consumer
src/
  config.py                  Environment and .env settings
  models.py                  Decisions API request/response models
  decisions.py               HTTP client for /api/alpha/decisions
  ingestion/
    mail_parser.py           MIME → normalized mail record
    imap_listener.py         IMAP IDLE listener (runs in a thread)
  routing/
    decision.py              RoutingDecision + log formatting
    queues.py                Queue registry + JSONL writer
    router.py                Questions, classification, dispatch, CLI
queues/                      Per-queue JSONL output (git-ignored)
DEVLOG.md                    Build log and debugging notes
requirement.txt              Python dependencies
```

---

## Quick start

**Requirements:** Python 3.10+, a mailbox that supports IMAP with app passwords, and an OpenRouter API key.

```bash
git clone <repository-url>
cd RouteGrid

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirement.txt
```

Create a `.env` file in the project root:

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
```

> Gmail requires 2-Step Verification and an [App Password](https://myaccount.google.com/apppasswords). A normal account password will not work.

Start the listener:

```bash
python main.py
```

```text
RouteGrid listening on imap.gmail.com:993 [INBOX]
Queue directory: /path/to/RouteGrid/queues
Connecting to imap.gmail.com:993...
Watching INBOX for new mail (UID > 12470)...

========== NEW EMAIL ==========
UID: 12471
From: Dr Rao <dr.rao@eyehospital.in>
Subject: Purchase order for IOL lenses
Date: Wed, 11 Nov 2026 09:13:40 +0530
Body: Dear ZEISS India, we would like to order 40 intraocular lenses...
-------------------------------
Routed to: iolorder_in (iolorder.in@zeiss.com) confidence=1.00 urgency=0.25
===============================
```

Stop with `Ctrl+C`. Only mail that arrives **after** startup is processed; the existing inbox is left untouched.

---

## Configuration

All settings are read from the environment, with `.env` loaded from the project root.

| Variable | Default | Meaning |
|---|---|---|
| `IMAP_SERVER` | `imap.mail.yahoo.com` | IMAP host |
| `IMAP_PORT` | `993` | IMAP SSL port |
| `EMAIL_ACCOUNT` | — | Mailbox login **(required)** |
| `APP_PASSWORD` | — | Mailbox app password **(required)** |
| `IMAP_FOLDER` | `INBOX` | Folder to watch |
| `IDLE_TIMEOUT` | `60` | Seconds per IDLE wait before re-checking |
| `RECONNECT_DELAY` | `5` | Seconds to wait before reconnecting |
| `API_KEY` | — | OpenRouter key; `OPENROUTER_API_KEY` also works **(required)** |
| `ROUTER_MODEL` | `parallel/decisions-fast:free` | Decisions model ID |
| `ROUTER_THRESHOLD` | `0.60` | Minimum queue probability before routing |
| `ROUTER_INQUIRY_THRESHOLD` | `0.50` | Minimum probability that the mail is a real inquiry |
| `REQUEST_TIMEOUT` | `60` | HTTP timeout in seconds |
| `RETRY_ATTEMPTS` | `3` | Attempts for `429` / `5xx` responses |
| `MAX_BODY_CHARS` | `8000` | Body characters sent to the model |
| `QUEUE_DIR` | `./queues` | Where queue files are written |

---

## Classify a single message

The router has a small CLI that runs the same pipeline without the listener. `--dry-run` classifies and prints the full probability distribution without writing a queue file.

```bash
python -m src.routing.router --list-queues
python -m src.routing.router sample.json --dry-run
python -m src.routing.router sample.json
python -m src.routing.router mail.eml
python -m src.routing.router --subject "IOL order" --body "Please send 40 lenses."
```

Accepted inputs: a JSON mail record, a raw `.eml` file, or a plain-text file. Explicit `--subject` / `--sender` / `--body` flags override values read from the file.

---

## Queue output

Each routed message is appended as one JSON line to `queues/<queue>/<YYYY-MM-DD>.jsonl`:

```json
{
  "queued_at": "2026-11-11T09:14:02+00:00",
  "queue": "iolorder_in",
  "address": "iolorder.in@zeiss.com",
  "decision": {
    "confidence": 0.99,
    "probabilities": { "iolorder_in": 0.99, "info_in": 0.01 },
    "urgency": 0.31,
    "is_zeiss_inquiry": 1.0,
    "method": "decisions",
    "reason": "",
    "model": "parallel/decisions-fast-20261106",
    "cost_usd": 0.0
  },
  "mail": {
    "id": "12471",
    "from": "Dr Rao <dr.rao@eyehospital.in>",
    "subject": "Purchase order for IOL lenses",
    "date": "Wed, 11 Nov 2026 09:13:40 +0530",
    "body": "Dear ZEISS India, we would like to order 40 intraocular lenses..."
  }
}
```

`probabilities` contains the model's full distribution over the ten queues, so thresholds can be re-tuned later without re-classifying. `model` is the exact build that answered.

A downstream worker can tail these files, load them into a CRM, or feed a ticketing system. RouteGrid does not consume its own output.

---

## Routing policy

| Condition | Destination |
|---|---|
| Genuine inquiry and `P(queue) ≥ ROUTER_THRESHOLD` | That department queue |
| `P(inquiry) < ROUTER_INQUIRY_THRESHOLD` | `_review` — `not a ZEISS inquiry` |
| Best queue probability below the threshold | `_review` — `low confidence` |
| Model returns an unknown queue slug | `_review` — `unknown queue` |
| API error, timeout, or invalid response | `_review` — `classification_failed` |
| Model omits probabilities | Routes anyway, marked `unscored by model` |

The last case is deliberate: missing metadata is not evidence of a bad classification, so the message is routed rather than buried. Every other uncertainty lands in `_review` with the reason recorded.

---

## Operational notes

- **Backlog is skipped.** On connect, `last_uid` starts at the highest UID in the folder. Mail that arrived while the process was down is not replayed; rerun the CLI over an `.eml` export if you need to backfill.
- **Reconnects automatically.** Any IMAP exception is logged, then retried after `RECONNECT_DELAY`. A changed `UIDVALIDITY` resets the cursor to the new mailbox state.
- **Read-only.** The folder is selected with `readonly=True`; RouteGrid never sets `\Seen`, moves, or deletes messages.
- **Retries are narrow.** `429` and `5xx` responses are retried with exponential backoff. `400`, `401`, and `402` fail immediately with a hint in the log.
- **One API call per mail.** Classification is a single request; urgency rides along at no extra cost.
- **Costs are recorded.** Each queue record carries the `cost_usd` reported by the API.

---

## Security

- `.env` is git-ignored. Keep it that way.
- Use a dedicated app password for the mailbox, not your account password, and revoke it if the repo is shared.
- Rotate the OpenRouter key if it has ever been committed. Deleting the file in a later commit does not remove it from history; purge the history or rotate the credential.
- Queue files contain full message bodies and personal data. They are git-ignored for that reason; treat them with the same care as the mailbox itself.

---

## Development

- [`DEVLOG.md`](DEVLOG.md) records the build in stages: IMAP ingestion, decisions-based routing, then the listener/package restructure, including the obstacles hit along the way.
- The classification logic is pure and injectable: `interpret()` takes validated answers and returns a `RoutingDecision`, so threshold behaviour can be checked without network access.
- `route()` never raises on classification failure; it records the error in `_review`. That is the contract the consumer relies on.

```bash
python -m py_compile main.py src/*.py src/ingestion/*.py src/routing/*.py
```
