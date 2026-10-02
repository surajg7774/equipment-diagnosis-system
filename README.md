# ServiceDiagnose AI - backend

An AI-assisted equipment fault diagnosis API for field technicians. A technician describes a
problem in plain English; the service retrieves similar past issues from a vector database and
asks an **LLM** (local Ollama in development, Groq when deployed) to write a tailored diagnosis,
recommended action and severity.

It uses **Retrieval-Augmented Generation (RAG)**: the retrieved past cases are *context examples*
for the LLM, not the answer. Because the LLM writes a new diagnosis for the actual report, the
system can also handle issues that match nothing in the knowledge base.

Stack: Python, FastAPI, Pydantic v2, SQLAlchemy (SQLite), ChromaDB, `all-MiniLM-L6-v2` embeddings
(ONNX runtime, no PyTorch), and an LLM behind a swappable interface: Ollama locally or Groq's free
tier hosted. Local development needs no API key; deployment needs a free Groq key.
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
            confidence_score ...................... similarity of the best retrieved case
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

For `"forklift hydraulic lift is slow and the mast jerks"` (nothing similar in the knowledge base)
the best similarity is 0.38, below the threshold. The LLM is called *without* examples and the
response carries:

```json
{ "diagnosis_basis": "general_reasoning",
  "note": "No closely matching past case found - diagnosis based on general reasoning.",
  "confidence_score": 0.3809 }
```

For input that is not an equipment problem (`"what is the capital of France"`) the LLM flags it,
the API still answers with HTTP 200, but **nothing is stored**, so history stays clean:

```json
{ "is_valid_issue": false, "ticket_id": null, "severity": null, "similar_cases": [],
  "note": "This does not appear to describe an equipment issue, so it was not saved to ticket history." }
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/v1/diagnose` | RAG diagnosis from a text description (stored as a ticket) |
| POST | `/api/v1/diagnose-image` | **Placeholder** image diagnosis behind a swappable `VisionService` interface |
| GET | `/api/v1/history` | Paginated past tickets, newest first (`page`, `page_size`) |
| POST | `/api/v1/feedback` | `{ticket_id, was_correct}`; resubmitting updates the earlier answer |
| GET | `/health` | Database, vector store and LLM status (503 if any is down) |
| GET | `/health/live` | Liveness only: always 200 while the process is up (use as the host's health check) |

Every error has the same shape, `{"error": {"code", "message", "details?", "request_id?"}}`:
`422` validation (with per-field messages), `404` unknown ticket, `503` LLM unavailable or
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
| `ALLOWED_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | Comma-separated browser origins allowed by CORS. Production: the frontend URL |
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
```

The default suite covers the severity heuristic, similarity parsing with a mocked ChromaDB
response, prompt building and LLM-output parsing, the Ollama adapter against a faked HTTP layer
(connection failure, timeout, model not pulled, malformed output), the Groq adapter (auth, rate-limit, truncated-output and
key-redaction cases), settings and secrets handling, CORS (allowed, blocked, preflight, error
responses), start-up auto-seeding on an empty disk, the RAG routing logic with a faked LLM, seeding
idempotency, and the API through FastAPI's `TestClient`. The integration tests
check real retrieval and that the similarity threshold still separates known from unknown issues.

## Design notes and limitations

* **Confidence is retrieval similarity, not the LLM's certainty.** It tells you how well the
  knowledge base covers the issue. It is not a calibrated probability of being right.
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
* Tickets store the final diagnosis and retrieved cases but not `diagnosis_basis`/`note`.
  Schema is created with `create_all`; use Alembic migrations for production.
* No authentication or rate limiting yet: once deployed, anyone with the API URL can spend your
  Groq quota.
* **Embeddings use the ONNX runtime, not PyTorch.** Same model weights, identical vectors (cosine
  similarity 1.00000, same similarity scores, so the 0.50 threshold is unchanged), but about 210 MB
  of RAM instead of about 750 MB. Texts are embedded 4 at a time: embedding all 28 records in one
  batch made the process grow by about 260 MB.

### Swap points

* **LLM** -> `app/services/llm_service.py` holds the `LLMService` interface and both adapters
  (`OllamaLLMService`, `GroqLLMService`), picked by `LLM_PROVIDER` in `create_llm_service`. To add a
  provider, write one more subclass and one more branch there; nothing else changes.
* **Vision** -> `app/services/vision_service.py`; the current model is a placeholder that does not
  analyse the image (responses are flagged `is_placeholder: true`).
* **Database** -> change `DATABASE_URL`.

## Project structure

```
app/
  api/        route handlers only (thin controllers) + dependency injection
  services/   diagnosis_service (RAG pipeline), llm_service, embedding_service,
              severity, vision_service, ticket_service
  models/     SQLAlchemy models        schemas/  Pydantic request/response models
  db/         engine/session, ChromaDB setup, seed script
  core/       settings, structured JSON logging, exceptions
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
| `EMBEDDING_BACKEND` | `onnx` | Optional (default); this is what makes it fit in 512 MB |
| `AUTO_SEED_ON_STARTUP` | `true` | Optional (default) |
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
```

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
