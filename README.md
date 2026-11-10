# RouteGrid

**RouteGrid** is a low-latency, reflex-driven **System 1 decision engine** designed to ingest, classify, and dispatch high-volume customer grievances and complaints to the appropriate enterprise departments (Finance, Logistics, Sales, Customer Support, Legal, etc.).

Operating as an automated ingress gatekeeper, RouteGrid eliminates manual inbox triage by analyzing incoming message content, extracting core intent and signals, and instantly routing payloads to downstream resolution queues.

---

## ⚡ Core Architecture: The System 1 Layer

Inspired by the dual-process cognitive framework, **RouteGrid** serves as the **fast-path / reflexive (System 1)** layer of customer support infrastructure:

1. **Ingestion & Normalization:** Ingests raw multi-part emails, decodes MIME fragments, and cleans structured text payloads.
2. **Intent & Feature Extraction:** Identifies critical urgency signals, complaint markers, and contextual department vectors.
3. **Instant Triage (System 1):** Executes rapid deterministic and heuristic routing decisions without incurring heavy, slow, or costly large-model roundtrips on straightforward requests.
4. **Dispatch & Routing:** Dispatches the normalized ticket with metadata tags directly to department-specific endpoints, message brokers, or escalation queues.

---

## 📬 Routing to ZEISS India queues

`main.py` runs an IMAP IDLE listener: it connects to the configured mailbox,
waits for new mail, and routes each message as it arrives. Classification uses
an OpenRouter [Decisions model](https://openrouter.ai/docs/guides/community/jev)
and one API call asks three typed questions:

| Question | Type | Purpose |
|---|---|---|
| `is_zeiss_inquiry` | `noul` | Reject automated notifications, newsletters and spam |
| `department` | `choice` | Pick exactly one of the ten ZEISS India queues |
| `urgency` | `score` | Rank routine → time-sensitive → urgent |

| Queue slug | Email address | Purpose |
|---|---|---|
| `info_in` | info.in@zeiss.com | General ZEISS India inquiries and customer assistance |
| `mikroservice_india` | mikroservice.india@zeiss.com | Microscopy service, repairs and maintenance |
| `info_microscopy_in` | info.microscopy.in@zeiss.com | Microscopy product and application inquiries |
| `info_meditec_in` | info.meditec.in@zeiss.com | Medical technology, ophthalmology and surgical equipment |
| `iolorder_in` | iolorder.in@zeiss.com | Intraocular lens orders and medical consumables |
| `info_metrology_in` | info.metrology.in@zeiss.com | Industrial metrology, measurement and inspection |
| `zeiss_co_in` | info@zeiss.co.in | Optical products and consumer optics |
| `dpo_in` | dpo.in@zeiss.com | Data privacy and GDPR / DPDP requests |
| `legal_in` | legal.in@zeiss.com | Legal and compliance matters |
| `webmaster` | webmaster@zeiss.com | Website problems, broken links and login failures |
| `_review` | *(local)* | Not an inquiry, low confidence, or classification error |

Mail is written to `queues/<queue>/<YYYY-MM-DD>.jsonl` — one record per line
with the original message, the chosen queue, the full probability
distribution, urgency and the model that answered. Nothing is sent to the
ZEISS addresses; a downstream worker reads the queue files.

### Project layout

```
main.py                      Entry point: listener + async consumer
src/
  config.py                  Environment/.env settings
  models.py                  Decisions API request/response models
  decisions.py               HTTP client for /api/alpha/decisions
  ingestion/
    mail_parser.py           MIME → normalized mail record
    imap_listener.py         IMAP IDLE listener (thread)
  routing/
    decision.py              RoutingDecision + log formatting
    queues.py                Queue registry + JSONL writer
    router.py                Questions, classification, dispatch, CLI
queues/                      Per-queue JSONL output (git-ignored)
```

### Running the listener

```bash
python main.py
```

On connect the listener skips the existing backlog and only processes mail
that arrives afterwards. The mailbox is opened read-only: messages are never
marked read, moved or deleted.

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `IMAP_SERVER` | `imap.mail.yahoo.com` | IMAP host |
| `IMAP_PORT` | `993` | IMAP SSL port |
| `EMAIL_ACCOUNT` | — | Mailbox login (required) |
| `APP_PASSWORD` | — | Mailbox app password (required) |
| `IMAP_FOLDER` | `INBOX` | Folder to watch |
| `IDLE_TIMEOUT` | `60` | Seconds per IDLE wait before re-checking |
| `API_KEY` | — | OpenRouter API key (required) |
| `ROUTER_MODEL` | `parallel/decisions-fast:free` | Decisions model ID |
| `ROUTER_THRESHOLD` | `0.60` | Minimum queue probability before routing |
| `ROUTER_INQUIRY_THRESHOLD` | `0.50` | Minimum probability that the mail is a real inquiry |
| `QUEUE_DIR` | `./queues` | Where queue files are written |

### Classifying a single message

```bash
python -m src.routing.router sample.json --dry-run   # classify, print probabilities
python -m src.routing.router sample.json             # classify and enqueue
python -m src.routing.router mail.eml                # works with raw .eml files
python -m src.routing.router --subject "IOL order" --body "Please send 40 lenses."
python -m src.routing.router --list-queues
```

