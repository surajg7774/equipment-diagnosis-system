# ServiceDiagnose AI - backend

An AI-assisted equipment fault diagnosis API for field technicians. A technician describes a
problem in plain English; the service retrieves similar past issues from a vector database and
asks an **LLM** (local Ollama in development, Groq when deployed) to write a tailored diagnosis,
recommended action and severity.

It uses **Retrieval-Augmented Generation (RAG)**: the retrieved past cases are *context examples*
for the LLM, not the answer. Because the LLM writes a new diagnosis for the actual report, the
system can also handle issues that match nothing in the knowledge base.

Stack: Python, FastAPI, Pydantic v2, SQLAlchemy (SQLite), ChromaDB, `all-MiniLM-L6-v2` embeddings
(ONNX runtime, no PyTorch), an LLM behind a swappable interface (Ollama locally or Groq's free
tier hosted), and a vision-language model for photo analysis (Groq, `qwen/qwen3.8-27b`). Local development needs no API key; deployment needs a free Groq key.
See [Deployment](#deployment-render--vercel) for hosting on Render + Vercel.

## How a diagnosis works

```
 technician's text
        |
        v
 1 RETRIEVE   embed text -> ChromaDB top-3 most similar past cases (+ similarity score)
        |
        v
 2 DECIDE     best similarity >= threshold (default 0.50)?
        |        yes -> give the 3 cases to the LLM as reference examples
        |        no  -> give the LLM nothing; it diagnoses from general knowledge
        v
 3 GENERATE   the LLM (Ollama or Groq) writes a NEW root cause + fix + severity for THIS issue
        |
        v
 response:  diagnosis, recommended_action ......... written by the LLM
            retrieval_confidence .................. similarity of the best retrieved case (0-1)
            llm_confidence ........................ the LLM's own certainty in its diagnosis (0-1)
            similar_cases ......................... what retrieval found (always shown)
            severity .............................. more severe of keyword heuristic and LLM
            diagnosis_basis / note ................ says whether it was grounded in a past case
            is_valid_issue ........................ false if the input is not an equipment problem
```

## Prerequisites

* **Python 3.10+** (developed on 3.13).
* **An LLM provider** (`LLM_PROVIDER`, default `ollama`). Not required to run the tests.
  * **`groq`** (hosted, what you deploy with): set `LLM_PROVIDER=groq` and `GROQ_API_KEY` (free key
    from <https://console.groq.com/keys>) in your git-ignored `.env`. Nothing to install.
  * **`ollama`** (local, offline development):
  1. Install Ollama from <https://ollama.com/download>.
  2. Pull the model (about 2 GB, one time): `ollama pull llama3.2:3b`
     (the lighter of `llama3.2:3b` ~2.0 GB and `phi3:mini` ~2.2 GB).
  3. Make sure Ollama is running (the desktop app starts it; otherwise run `ollama serve`)
     and that `ollama list` shows the model.

  To use a different model, set `OLLAMA_MODEL` (see Configuration). Both a missing Ollama and a
  missing model make `POST /diagnose` return `503` and `/health` report `"llm": "error"`; the
  server log says which one and how to fix it.

  *Timing:* a warm diagnosis takes a few seconds (about 5 s in testing, nearly all of it the LLM;
  retrieval takes under 50 ms). The first request after Ollama has unloaded the model must load it
  from disk and can take minutes. The server starts a background warm-up at launch, and
  `OLLAMA_KEEP_ALIVE` (default 30 minutes) keeps the model loaded between requests.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows   (macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # optional - the defaults work (macOS/Linux: cp)
python -m app.db.seed             # load the knowledge base into ChromaDB (safe to re-run)
uvicorn app.main:app
```

Interactive API docs: <http://localhost:8000/docs>. The first run downloads the embedding model
(about 80 MB) once. If the knowledge base is empty at startup the server seeds it automatically
(`AUTO_SEED_ON_STARTUP`), so the explicit `python -m app.db.seed` step is optional.

## Example

```bash
curl -X POST http://localhost:8000/api/v1/diagnose \
  -H "Content-Type: application/json" \
  -d '{"description": "pump making loud grinding noise and leaking oil"}'
```

Real response from a local run (action text shortened):

```json
{
  "is_valid_issue": true,
  "ticket_id": 1,
  "severity": "high",
  "diagnosis": "The loud grinding noise and oil leakage suggest that the pump bearings may be worn or contaminated, leading to excessive wear and oil degradation. This could also indicate a lack of proper lubrication or contamination from contaminants in the fluid.",
  "recommended_action": "First, safely isolate the pump by shutting off the power and closing the inlet and outlet valves. Then, visually inspect the bearings for any signs of wear or contamination. If bearings are found to be worn, replace them. ...",
  "retrieval_confidence": 0.5921,
  "llm_confidence": 0.85,
  "llm_confidence_defaulted": false,
  "confidence_score": 0.5921,
  "diagnosis_basis": "similar_cases",
  "note": null,
  "similar_cases": [
    { "id": "KB-002", "equipment_type": "pump", "similarity_score": 0.5921, "...": "..." },
    { "id": "KB-001", "equipment_type": "pump", "similarity_score": 0.5875, "...": "..." },
    { "id": "KB-004", "equipment_type": "pump", "similarity_score": 0.5414, "...": "..." }
  ]
}
```

For `"laptop battery drains within an hour and the laptop shuts down at 30 percent"` (nothing
similar in the knowledge base) the best similarity is 0.27, below the threshold. The LLM is called
*without* examples, yet it can still be fairly sure of a battery-wear diagnosis, and the response
says both things:

```json
{ "diagnosis_basis": "general_reasoning",
  "note": "No closely matching past case found - diagnosis based on general reasoning.",
  "retrieval_confidence": 0.2688,
  "llm_confidence": 0.78 }
```

For input that is not an equipment problem (`"what is the capital of France"`) the LLM flags it,
the API still answers with HTTP 200, but **nothing is stored**, so history stays clean:

```json
{ "is_valid_issue": false, "ticket_id": null, "severity": null, "similar_cases": [],
  "note": "This does not appear to describe an equipment issue, so it was not saved to ticket history." }
```

## Two confidence scores

A diagnosis reports two different numbers (both 0-1, shown as percentages in the UI):

| Field | What it measures | Where it comes from |
|---|---|---|
| `retrieval_confidence` | How well the knowledge base covers this issue: the cosine similarity of the best-matching past case | The vector search (as before) |
| `llm_confidence` | How certain the model says it is that its diagnosis is correct, **independent of whether a past case matched** | The LLM, asked to rate itself 0-100 (converted to 0-1) |

Why both matter: they answer different questions and can disagree in useful ways.

* **Low retrieval, high LLM** (the laptop battery above): nothing similar is in the knowledge base,
  but the fault is a well-known one. Reporting only retrieval similarity made such answers look
  untrustworthy.
* **High retrieval, low LLM** (`"it makes a noise when it runs"`: 0.62 retrieval, 0.30 LLM): the
  words resemble a past case, but the report is too vague for the model to be sure.
* Both high: a known issue, clearly described. Both low: treat the answer as a starting point.

`confidence_score` is still returned as a **deprecated alias of `retrieval_confidence`**, so existing
clients keep working. Tickets (and `/history`) still store the retrieval similarity only.

**When the model gives no usable number** (missing, out of range, or not numeric, e.g. one real Groq
reply said `"thirty"`), the request still succeeds: a warning `llm_confidence_unusable` is logged,
`llm_confidence` is set to the neutral default `0.5`, and `llm_confidence_defaulted` is `true` so
clients do not present the default as the model's opinion (the UI marks it "estimate unavailable").
Accepted spellings are `72`, `"72"`, `"72%"` and the fraction `0.85`; anything else is treated as
unusable rather than guessed at.

## Feedback loop: technicians improve the knowledge base

The knowledge base does not have to stay frozen at its 28 seed examples. Every diagnosis is a
**ticket** that starts `pending`; a technician reviews it on the History page, and a reviewed case
is added to ChromaDB, so the next *similar* report can retrieve it.

```
 diagnose ──► ticket (pending) ──► technician reviews ──┬─ Confirm ──► verified record = the AI's diagnosis
                                                        └─ Correct ──► verified record = the technician's root cause + fix
                                                                              │
              next similar report ◄── retrieves it (as a close match) ◄───────┘
```

**Review status and priority** (new `review_status` / `review_priority` on every ticket):

| Field | Values | Meaning |
|---|---|---|
| `review_status` | `pending` / `confirmed` / `corrected` | `pending` until a technician acts. Never moves back to pending |
| `review_priority` | `high` / `low` | Set when the ticket is created: `high` for medium/high severity, `low` otherwise. Only affects ordering: the **Needs review** list shows high-priority tickets first |

**Transitions:** `pending → confirmed`, `pending → corrected`, `confirmed → corrected`, and
`corrected → corrected` (edit). Confirming twice is harmless; confirming a *corrected* ticket is
refused (`409`). A correction stores the technician's root cause and fix **next to** the original AI
diagnosis, which is never overwritten, so the two can be compared (History → *Show details*).

**Endpoints**

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/tickets/{id}/confirm` | Confirm the AI was right; adds the AI's diagnosis to the knowledge base. Body optional: `{equipment_type}` |
| POST | `/api/v1/tickets/{id}/correct` | `{root_cause, recommended_fix, equipment_type?}`; adds the *corrected* case |
| GET | `/api/v1/knowledge-base/stats` | `{total, seed, verified, verified_confirmed, verified_corrected}`: makes the growth visible |
| GET | `/api/v1/history?review_status=pending` | Filter by status (`pending` lists high priority first). The History page shows the counts and filters |

**What a verified record looks like.** It is matched on the technician's *report text* (as seed records
are), carries the answer (confirmed: the AI's; corrected: the technician's), and is marked
`source: "verified"` in its metadata (seed records are `seed`). Retrieved cases expose this as
`similar_cases[].source`, and the UI shows a "Verified by a technician" chip. The record id is
`VC-<ticket>-<hex>`. Photo tickets are matched by the AI's visual description (a file name is not a
symptom report). A quick thumbs up/down is *not* a review and never adds anything.

**Measured on the real system** (Groq + ONNX embeddings): a report about a laptop battery had no
close match (retrieval 0.27, `general_reasoning`). After a technician confirmed it, a *differently
worded* report of the same problem retrieved that case as its top match at **0.83** and was answered
from `similar_cases`. A corrected forklift case was retrieved for a similar report at 0.88, with the
technician's root cause and fix. An unconfirmed ticket was never retrieved.

**Consistency guarantees**
* A re-seed (`python -m app.db.seed`, or the auto-seed on startup) only ever touches **seed** records;
  verified ones are left alone (the old clean-up would have deleted them: now covered by a regression test).
* The record is written to ChromaDB **first** and the database committed second; if the vector store
  fails, the ticket stays `pending` and the API answers 503, and if the commit fails the new record is
  removed again.
* The database is the source of truth: at startup, any reviewed ticket whose record is missing from
  the vector store (a deleted `chroma_db`, a wiped disk) is **restored** from its ticket.
* Older databases are upgraded in place at startup (`ALTER TABLE ... ADD COLUMN`, logged as
  `schema_column_added`); no need to delete `servicediagnose.db`.

**Limitations (read before relying on it)**
* **No safeguard against a wrong confirmation.** One click makes a case "verified" and it immediately
  influences retrieval *and* the answers the LLM writes. A technician confirming a bad diagnosis (or
  typing a wrong correction) pollutes the knowledge base, and there is no undo or removal yet.
* **No identity or roles:** anyone who can open the History page can confirm or correct, and the
  reviewer is not recorded.
* **Near-duplicates accumulate:** confirming five reports of the same fault adds five records.
* Verified records without an equipment type are matched on the report text alone.
* **Hosting:** on a free Render instance both the database and the vector store are wiped on restart,
  so verified cases do not survive there. The restore step only helps when the database persists
  (e.g. hosted PostgreSQL).

**Planned improvements:** require **two independent confirmations** (or agreement between a
confirmation and the AI) before a case is trusted, and weight or flag single-reviewer cases;
record the reviewer and add roles; let an admin retract a verified case; merge near-duplicates;
keep an audit trail of changes.

## Image analysis

`POST /api/v1/diagnose-image` sends an uploaded photo to a **vision-language model**, which describes
any visible damage, wear, leaks, corrosion or abnormal conditions and rates the severity.

* **Provider / model:** Groq, **`qwen/qwen3.8-27b`**. It is the only model on the checked account
  whose `input_modalities` include `image` (`GET https://api.groq.com/openai/v1/models` reports this
  per model). It reuses `GROQ_API_KEY`. Choose with `VISION_PROVIDER` (`groq` or `none`) and
  `GROQ_VISION_MODEL`. Another provider (e.g. Gemini) is one more `VisionService` subclass in
  `app/services/vision_service.py`.
* **Request:** multipart upload, field `file`: JPEG, PNG or WebP, up to 5 MB (`MAX_IMAGE_SIZE_BYTES`).
  The format is detected from the file's bytes, not its name or `Content-Type`; invalid uploads are
  rejected (415 / 413 / 422) *before* any call to the model.
* **Response:**

  ```json
  { "is_equipment_photo": true, "ticket_id": 4, "damage_detected": true, "severity": "high",
    "description": "A large stack of steel pipes with severe, widespread orange-brown rust ...",
    "recommended_action": "Inspect wall thickness; if pitted or thin, scrap the pipes ...",
    "confidence": 0.95, "model_name": "qwen/qwen3.8-27b", "provider": "groq", "note": null }
  ```

  `confidence` is the model's self-reported certainty (0-1), or `null` if it gave no usable number.
  A photo that is **not equipment** (a bird, a person...) is answered with `is_equipment_photo: false`
  but **not stored**, exactly like non-equipment text.
* **Errors:** `503` `vision_unavailable` (disabled, no key, outage, or rate limited, each with its own
  log hint), `502` `vision_bad_response`, `422` if the provider cannot read the image. Without a
  `GROQ_API_KEY` the server still starts; only this endpoint answers 503. Nothing is ever invented.
* **Repeatability:** run at temperature 0 (`VISION_TEMPERATURE`). In testing the same photo gave the
  same severity and confidence three times out of three, though the wording still varies slightly.
  (At 0.2 the same photo flipped between *medium* and *high*.)

**Verified on real photos** (CC0 test images in `tests/fixtures/images/`): a stack of rusted pipes
-> *damage, severe corrosion, threaded ends rusted*; a new stop-arm product graphic -> *no damage*,
and it read the text in the picture; a bird on a rusty pipe -> *not equipment*, not stored.

**Known limitations: treat the result as an assistive first pass, not an inspection.**

* It is a **general-purpose** vision model, **not fine-tuned on equipment-failure imagery**. It
  describes what is visible; it cannot see inside a machine, measure wall thickness, or judge
  load, and it can miss subtle faults (hairline cracks, early corrosion) or misjudge poor,
  dark or distant photos. Severity is the model's opinion, not a standard.
* It can misread context: in testing it called water discharging from a pipe's open end an
  active "leak from a break".
* **Rate limit:** the Groq free tier allows about 7,000 input tokens a minute and one image costs
  about 2,000, so **about 3 analyses per minute** across all users; beyond that the endpoint
  answers 503 "busy, wait a minute".
* **Privacy:** the photo is sent to Groq (a third party) for analysis. Do not upload images you
  are not allowed to share.
* The UI labels it *AI-generated visual assessment, not a substitute for professional inspection*.

## Rate limiting

`/api/v1/diagnose` and `/api/v1/diagnose-image` are limited to **10 requests per minute per client**
(`RATE_LIMIT_PER_MINUTE`, window `RATE_LIMIT_WINDOW_SECONDS` = 60). Both endpoints spend your Groq quota
and share one allowance per client. `/history`, `/stats`, `/health` and the review endpoints are not limited.

Over the limit the API answers **`429`** with a `Retry-After` header and the usual error shape:

```json
{ "error": { "code": "rate_limited", "message": "Too many requests. Please wait 42 seconds and try again.", "request_id": "..." } }
```

The web app turns that into "Too many requests, please wait a moment (about 42 seconds) and try again."

* **How it works:** an in-memory *sliding window*: each client's recent request times are kept and a
  request is allowed if fewer than the limit happened in the last 60 s. Space frees up one request at a
  time (no "everything resets at :00" burst). Refused requests are not counted, so retrying cannot extend
  the wait. No Redis, no new dependency; about 60 lines in `app/core/rate_limit.py`, with an injectable
  clock so the tests move time instead of sleeping. `RATE_LIMIT_PER_MINUTE=0` turns it off.
* **Who is "a client" (`RATE_LIMIT_PROXY_HOPS`):** by default the IP of the TCP connection. Behind a
  reverse proxy such as Render every connection comes from the proxy, so the real client is read from
  `X-Forwarded-For`. Each proxy *appends* to that header and a caller can send its own first value, so only
  entries on the **right** can be trusted: `RATE_LIMIT_PROXY_HOPS=N` means "the last N entries were added
  by proxies I trust". `render.yaml` sets **1**. Set it too low and clients merely share a bucket (safe);
  too high and a client could invent its own address and dodge the limit. If the header has fewer entries
  than expected, the connection address is used. Each new client is logged as `rate_limit_new_client`
  with the key that was derived, so you can check what the limiter sees on the real deployment.
* **Limitations:** counters live in one process's memory, so a restart (including Render's spin-down)
  forgets them and several instances would each count separately. It protects your API quota; it is not
  a defence against a determined distributed attack, and one office behind a shared IP shares one allowance.

## Statistics

`GET /api/v1/stats` (the **Stats** page in the web app) summarises usage and the knowledge base's growth:

```json
{ "total_diagnoses_performed": 12, "text_diagnoses": 10, "image_diagnoses": 2,
  "resolution": { "counted": 10, "similar_cases": 6, "general_reasoning": 4,
                  "similar_cases_pct": 60.0, "general_reasoning_pct": 40.0 },
  "knowledge_base_size": 31, "original_seed_count": 28, "technician_verified_count": 3,
  "review": { "pending": 8, "confirmed": 2, "corrected": 2 },
  "average_confidence": { "retrieval": 0.512, "llm": 0.81, "image": 0.9 } }
```

* **`total_diagnoses_performed`** counts stored tickets. Inputs rejected as "not an equipment issue" are
  answered but never stored (see above), so they are not counted, the same rule as `/history`.
* **`resolution`** covers *text* diagnoses: `similar_cases` means retrieval found a close match that was
  handed to the LLM as examples, `general_reasoning` means nothing matched and the LLM used general
  knowledge. Tickets saved before this was recorded have no basis and are left out of `counted` rather
  than guessed. A percentage is `null` (not 0) when nothing has been counted.
* **`knowledge_base_size`** is every record retrieval can find: `original_seed_count` plus
  `technician_verified_count`. These three are `null` if the vector store cannot be read; the usage
  numbers are still returned.
* **Averages** (0-1) are over rows that have a value: the retrieval average is over text tickets, the
  LLM average skips diagnoses where the model gave no usable number (it is not counted as 0), and photo
  confidence is its own average because it is a different kind of number.
* Tickets keep the counters in the SQL database (`diagnosis_basis`, `llm_confidence`); they are
  computed with SQL aggregates on each request, which is fine at this scale. Like the rest of the
  ticket data they reset when Render's free disk does.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/diagnose` | RAG diagnosis from a text description (stored as a ticket) |
| POST | `/api/v1/diagnose-image` | AI visual assessment of an equipment photo by a vision-language model (see [Image analysis](#image-analysis)) |
| GET | `/api/v1/history` | Paginated past tickets, newest first (`page`, `page_size`) |
| POST | `/api/v1/feedback` | `{ticket_id, was_correct}`; a quick thumbs up/down (analytics only; adds nothing to the knowledge base) |
| POST | `/api/v1/tickets/{id}/confirm`, `/correct` | Technician review: adds the case to the knowledge base (see [Feedback loop](#feedback-loop-technicians-improve-the-knowledge-base)) |
| GET | `/api/v1/knowledge-base/stats` | Seed vs technician-verified record counts |
| GET | `/api/v1/stats` | Usage and knowledge-base growth: totals, similar-case vs general-reasoning split, average confidences (see [Statistics](#statistics)) |
| GET | `/health` | Database, vector store and LLM status (503 if any is down) |
| GET | `/health/live` | Liveness only: always 200 while the process is up (use as the host's health check) |

Every error has the same shape, `{"error": {"code", "message", "details?", "request_id?"}}`:
`422` validation (with per-field messages), `404` unknown ticket, `429` rate limited (with
`Retry-After`), `503` LLM unavailable or
knowledge base not seeded, `502` unusable LLM output, `500` unexpected (generic message plus a
`request_id` for finding the log entry; stack traces are only ever logged).

## Configuration

All settings are environment variables (or `.env`); see [.env.example](.env.example).

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` (local dev) or `groq` (deployment) |
| `GROQ_API_KEY` | *(none)* | **Secret.** Required when `LLM_PROVIDER=groq`; the app refuses to start without it |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id. List the ones your key can use: `GET https://api.groq.com/openai/v1/models` |
| `GROQ_REASONING_EFFORT` | `low` | For reasoning models (gpt-oss). Leave empty for non-reasoning models |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Any OpenAI-compatible endpoint |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Where Ollama listens (unused when `groq`) |
| `OLLAMA_MODEL` | `llama3.2:3b` | Ollama model (unused when `groq`) |
| `OLLAMA_KEEP_ALIVE` | `30m` | How long Ollama keeps the model in RAM |
| `LLM_TIMEOUT_SECONDS` | `180` | Per-request limit (covers a cold Ollama model load) |
| `LLM_TEMPERATURE` / `LLM_MAX_TOKENS` | `0.2` / `1024` | Reasoning models count hidden thinking against the token limit |
| `VISION_PROVIDER` | `groq` | `groq` or `none` (disables `/diagnose-image`). Needs `GROQ_API_KEY` |
| `GROQ_VISION_MODEL` | `qwen/qwen3.8-27b` | Must accept image input (see Image analysis) |
| `VISION_TEMPERATURE` | `0` | 0 = most repeatable |
| `VISION_MAX_TOKENS` / `VISION_TIMEOUT_SECONDS` | `1024` / `60` | Output cap / request limit |
| `GROQ_VISION_REASONING_EFFORT` | *(empty)* | Optional; not sent when empty |
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed by CORS. Production: the frontend URL |
| `RATE_LIMIT_PER_MINUTE` | `10` | Requests per client per window on the two AI endpoints; `0` disables (see Rate limiting) |
| `RATE_LIMIT_WINDOW_SECONDS` | `60` | Length of that window |
| `RATE_LIMIT_PROXY_HOPS` | `0` | Trusted proxies in front of the app (0 = use the connection address; `render.yaml` sets 1) |
| `AUTO_SEED_ON_STARTUP` | `true` | Rebuild the knowledge base at boot if it is empty (ephemeral hosts) |
| `EMBEDDING_BACKEND` | `onnx` | `onnx` (about 210 MB RAM) or `sentence-transformers` (PyTorch, about 750 MB; extra install) |
| `LOW_CONFIDENCE_THRESHOLD` | `0.50` | Minimum similarity for a "close match" |
| `TOP_K` | `3` | Cases retrieved as context |
| `DATABASE_URL` | `sqlite:///./servicediagnose.db` | Any SQLAlchemy URL (e.g. PostgreSQL) |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | ChromaDB storage |
| `KNOWLEDGE_BASE_PATH` | `data/knowledge_base.json` | Source file for seeding |

## Tests

```bash
pytest                     # offline: the LLM is faked, no model download, runs in seconds
pytest -m integration      # opt-in: real embedding model + the configured LLM provider
                           # (Ollama or Groq; skipped if it is not ready; Groq uses a little quota)
pytest -m integration -k vision   # real photos through the real vision model (~2 min: paced
                                  # for the free-tier limit of ~3 images/minute)
```

The default suite covers the severity heuristic, similarity parsing with a mocked ChromaDB
response, prompt building and LLM-output parsing, the Ollama adapter against a faked HTTP layer
(connection failure, timeout, model not pulled, malformed output), the Groq adapter (auth, rate-limit, truncated-output and
key-redaction cases), the vision adapter against a faked HTTP layer (inline base64 image, output
parsing, every failure mode, never logging the image), the photo endpoint with a fake vision model, settings and secrets handling, CORS (allowed, blocked, preflight, error
responses), start-up auto-seeding on an empty disk, the RAG routing logic with a faked LLM, seeding
idempotency, the rate limiter (a fake clock moves time, so no test sleeps) and the statistics
arithmetic and endpoint, and the API through FastAPI's `TestClient`. The integration tests
check real retrieval and that the similarity threshold still separates known from unknown issues.

## Design notes and limitations

* **Two confidences, deliberately separate** (see above). `retrieval_confidence` is how well the
  knowledge base covers the issue; `llm_confidence` is the model's own certainty. Neither is a
  calibrated probability of being right. The LLM's number is *self-reported*: it moves sensibly
  (about 0.3 for vague reports, 0.9 for clear ones in testing) but models tend to cluster on a few
  round values (often 0.85), so read it as a rough high/medium/low signal, not a precise percentage.
* **The 0.50 threshold was measured, not guessed.** With `all-MiniLM-L6-v2` on this knowledge base,
  reworded known issues scored 0.56-0.91, off-topic text 0.04-0.14, and most unknown equipment
  issues 0.25-0.52. A few near-misses that share equipment words (e.g. "pump pressure gauge reads
  zero") score higher and are treated as matches; the prompt tells the LLM to ignore irrelevant
  examples. Re-measure if you change the embedding model or the knowledge base.
* **Severity is the more severe of two opinions**: the documented keyword heuristic
  (`app/services/severity.py`) and the LLM's. The heuristic stops a small model from downplaying
  something like smoke; the LLM catches dangers the keyword list does not know.
* **No silent fallback.** If the LLM is down, the API returns 503. It never presents a raw
  database lookup as if it were a diagnosis.
* **Non-equipment input is rejected by the LLM, with a safety override.** The LLM returns
  `is_valid_issue`. If it says `false`, the request is answered but not stored. If the keyword
  heuristic nevertheless finds trouble words ("caught fire", "leaking"), the report is kept: wrongly
  discarding a real emergency is worse than keeping a junk ticket.
* **Advisory only.** A 3B model can be wrong, so diagnoses should be verified by a technician.
* Tickets store the final diagnosis, retrieved cases, `diagnosis_basis` and the LLM's confidence (the
  latter two feed `/stats`) but not the `note` text.
  Schema is created with `create_all` plus a small startup step that adds new columns to older databases; use
  Alembic migrations for anything more involved.
* **Abuse protection is basic.** The two AI endpoints are rate limited per client (see
  [Rate limiting](#rate-limiting)), but there is no authentication: anyone with the API URL can still use
  up to the limit, and the limiter's counters are in memory and per instance.
* **ChromaDB sometimes leaves a freshly written record out of its search index.** Measured on
  chromadb 1.5.9: roughly 1 in 8 single-record writes into an already-populated collection were stored
  (`get(ids=...)` found them) yet missing from similarity results, which would have meant a confirmed case
  silently never being retrieved. Re-writing the record fixed every case seen, so after each verified-case
  write `KnowledgeBaseService` queries for it and re-writes it (up to 2 more times), logging
  `knowledge_base_index_repaired`; if it still cannot be found it logs `knowledge_base_index_miss` and
  keeps the review (the case also stays in the SQL ticket, so a restart restores it). Seed records were
  never affected (0 of 150 fresh collections), and a test guards this against real ChromaDB.
* **Embeddings use the ONNX runtime, not PyTorch.** Same model weights, identical vectors (cosine
  similarity 1.00000, same similarity scores, so the 0.50 threshold is unchanged), but about 210 MB
  of RAM instead of about 750 MB. Texts are embedded 4 at a time: embedding all 28 records in one
  batch made the process grow by about 260 MB.

### Swap points

* **LLM** -> `app/services/llm_service.py` holds the `LLMService` interface and both adapters
  (`OllamaLLMService`, `GroqLLMService`), picked by `LLM_PROVIDER` in `create_llm_service`. To add a
  provider, write one more subclass and one more branch there; nothing else changes.
* **Vision** -> `app/services/vision_service.py` holds the `VisionService` interface, the Groq
  adapter and `create_vision_service` (picked by `VISION_PROVIDER`). Add a provider with one more
  subclass and one more branch.
* **Database** -> change `DATABASE_URL`.

## Project structure

```
app/
  api/        route handlers only (thin controllers) + dependency injection
  services/   diagnosis_service (RAG pipeline), llm_service, embedding_service,
              severity, vision_service, ticket_service, review_service, knowledge_base_service
  models/     SQLAlchemy models        schemas/  Pydantic request/response models
  db/         engine/session, ChromaDB setup, seed script
  core/       settings, structured JSON logging, exceptions, in-memory rate limiter
data/knowledge_base.json   28 synthetic issue records
tests/
```

## Deployment (Render + Vercel)

```
browser --> Vercel (static React app) --> Render (FastAPI) --> Groq (LLM)
```

Both free tiers work for a demo. These steps follow Render's and Vercel's documentation but have
not been run on the live platforms yet; the app itself was verified locally in a fresh,
PyTorch-free environment (see "Measured footprint").

### 1. Backend on Render

Push the repo to GitHub. Either let Render read [render.yaml](render.yaml)
(**New > Blueprint**; it prompts for the two secrets below, only at creation) or create a **Web
Service** by hand with these values:

| Setting | Value |
|---|---|
| Runtime | Python 3 |
| Root directory | the folder containing `app/` (blank if it is the repo root) |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check path | `/health/live` (liveness only, so a Groq outage cannot make Render restart a healthy server) |
| Instance type | Free (512 MB RAM, 0.1 CPU) |

Environment variables:

| Variable | Value | Notes |
|---|---|---|
| `PYTHON_VERSION` | `3.13.5` | Must be fully qualified; this is the tested version |
| `LLM_PROVIDER` | `groq` | |
| `GROQ_API_KEY` | *your key* | **Secret.** Never commit it |
| `ALLOWED_ORIGINS` | `https://<your-app>.vercel.app` | The frontend URL, no path. Comma-separate several |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Optional (default). `llama-3.1-70b-versatile` is retired |
| `GROQ_REASONING_EFFORT` | `low` | Optional (default) |
| `VISION_PROVIDER` / `GROQ_VISION_MODEL` | `groq` / `qwen/qwen3.8-27b` | Optional (defaults). Photo analysis reuses `GROQ_API_KEY` |
| `EMBEDDING_BACKEND` | `onnx` | Optional (default); this is what makes it fit in 512 MB |
| `AUTO_SEED_ON_STARTUP` | `true` | Optional (default) |
| `RATE_LIMIT_PER_MINUTE` | `10` | Optional (default). Per client, on the two AI endpoints |
| `RATE_LIMIT_PROXY_HOPS` | `1` | **Set this on Render** (the default 0 would make every visitor share one allowance, because all connections come from Render's proxy). See [Rate limiting](#rate-limiting) |
| `DATABASE_URL` | `sqlite:///./servicediagnose.db` | Optional (default); ephemeral on the free tier |
| `CHROMA_PERSIST_DIR` | `./chroma_db` | Optional (default); ephemeral on the free tier |
| `OLLAMA_BASE_URL` | `http://127.0.0.1:11434` | Unused in production; documented only |

The frontend URL is not known until step 2, so deploy the backend first with a placeholder
`ALLOWED_ORIGINS`, then edit it once you have the Vercel URL and save/deploy the change.

### 2. Frontend on Vercel

1. **Add New > Project**, import the repo.
2. **Root Directory:** `frontend`. Framework preset: **Vite** (detected).
3. **Build command:** `npm run build`. **Output directory:** `dist`.
4. **Environment variable:** `VITE_API_BASE_URL` = `https://<your-service>.onrender.com` (the Render URL).
   It is baked in at build time, so changing it needs a redeploy. The build fails with a clear
   message if it is missing, rather than shipping a site that calls the wrong place.
5. Deploy. [frontend/vercel.json](frontend/vercel.json) rewrites all paths to `index.html` so
   reloading `/history` works.

### 3. Check it

```bash
curl https://<your-service>.onrender.com/health/live    # {"status":"alive"}
curl https://<your-service>.onrender.com/health         # llm "ok", knowledge_base_size 28
curl https://<your-service>.onrender.com/api/v1/stats   # usage counters; knowledge_base_size 28 on a fresh start
```

Then check the rate limiter sees real visitors: send one diagnosis from your browser and look in the Render
logs for `rate_limit_new_client`. Its `client_key` should be **your public IP** (compare with
`curl ifconfig.me`). If it is an address that stays the same for every visitor, `RATE_LIMIT_PROXY_HOPS` is
too low (everyone shares one allowance, safe but strict); if it changes when you change the
`X-Forwarded-For` header you send, it is too high.

Then open the Vercel URL: the header pill should say "Backend online".

### What to expect on the free tier

* **Cold starts:** Render spins the service down after 15 minutes idle and takes about a minute to
  wake it. Start-up also loads the embedding model and re-seeds the knowledge base (3 s on a fast
  laptop; slower on 0.1 CPU).
* **Ephemeral storage:** tickets and feedback (SQLite) are lost on every restart, redeploy and
  spin-down; the knowledge base is rebuilt automatically. For durable history, point `DATABASE_URL`
  at a hosted PostgreSQL (also add a PostgreSQL driver such as `psycopg` to `requirements.txt`).
* **Groq limits:** the free tier is rate-limited; the API returns `503` when Groq refuses a request.
* **Measured footprint** (Windows, fresh PyTorch-free venv, empty storage, real Groq calls): about
  300 MB peak for the whole app, versus Render's 512 MB limit. With PyTorch it would be about
  750 MB and would not fit.
