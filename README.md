# GSR Support Agent — Multi-Agent Customer Support (Voice + Text)

**🔗 Live demo:** https://gsr-support-agent.onrender.com (core text API —
try `/health`, or POST to `/chat`. First request may take ~30s if the
free-tier instance has gone to sleep from inactivity.)

A multi-agent customer support system for **GSR (GlobalShop Retail)**, a
fictional e-commerce company built for this project. Customers chat or
speak to the agent about orders, returns, billing, and account issues; a
LangGraph multi-agent pipeline routes each request to a specialist agent,
which answers using RAG (for policy questions) or real tool calls via a
custom MCP server (for account-specific data like order status).

## Status
🚧 Phase 8 in progress: containerization + deployment documentation.

## Why this exists
Support teams answer the same handful of question types constantly (where's
my order, how do I return this, why was I charged twice) while genuinely
novel or sensitive issues (account security, disputes) need a human. This
project builds a tiered system: specialist agents resolve routine issues
end-to-end using real data, and escalate to a human with full context when
they can't.

## Two distinct data sources (same principle as our earlier BI project)
1. **Operational data** (`data/raw/` → DuckDB) — customers, orders,
   payments, returns, tickets. Queried live via MCP tools. Never guessed,
   never retrieved via RAG.
2. **Knowledge base** (`knowledge_base/`) — policy and FAQ documents
   (returns, shipping, billing, warranty, account/security). Retrieved via
   RAG to ground policy answers.

## Architecture

```
Voice/Text input
      │
Voice I/O layer (STT/TTS) -- stateless, separate from agent logic
      │ text
FastAPI (async)
      │
LangGraph multi-agent pipeline:
  identify_customer → classify_intent → specialist agent
  (order_status | returns_refund | product_qa | billing | account)
  → resolution_check → respond OR escalate_to_human
      │
Custom MCP Server: get_order_status | get_customer_profile |
  check_return_eligibility | initiate_refund | create_support_ticket |
  update_ticket | escalate_to_human | send_notification |
  register_new_customer
      │
DuckDB (operational data) + Chroma/pgvector (policy RAG index)
      ▲
Authenticated signup -- new customers are queryable immediately,
no batch delay
```

## Tech stack
LangGraph · LangChain · MCP (custom server) · DuckDB/Postgres ·
Chroma/pgvector · FastAPI (async) · Whisper (STT) · TTS · Streamlit ·
Docker

## Setup
```bash
pip install -r requirements.txt
python data/generate_synthetic_data.py
python data/load_data.py
python rag/embed_and_index.py
cp .env.example .env   # then add your real ANTHROPIC_API_KEY
```

## Running the agent (text, CLI)
```bash
python -m agent.graph "Where is my order ord_000519?" cust_000000
python -m agent.graph "What's your return policy for electronics?"
python -m agent.graph "I think someone accessed my account without permission"
```
The third example should escalate immediately (security-sensitive), per
the rule in knowledge_base/faqs/account_security_faq.md.

## Phase 7: caching, concurrency, load testing

**What's actually cached, and what isn't (on purpose):** RAG retrieval
(policy/FAQ lookups) is cached in-process (`functools.lru_cache`), since
many customers ask the same policy questions and the knowledge base only
changes when you re-run `embed_and_index.py`. Chat *responses* are
deliberately **not** cached -- they're customer-specific (order status,
account details), and caching them would either leak one customer's data
to another or serve stale account info. This mirrors the same principle
from the AskWarehouse project: cache what's safe and reusable, never
cache what's personalized.

**Session storage** (`api/session_store.py`) uses Redis if `REDIS_URL` is
set and reachable, and falls back to in-memory automatically (with a
clear log message) if not -- so local dev works with zero setup, but the
code is production-shaped. To actually use Redis locally:
```bash
# via Docker, simplest option
docker run -d -p 6379:6379 redis
```
Then add to `.env`:
```
REDIS_URL=redis://localhost:6379/0
```

**Concurrency**: `/chat` and `/auth/signup` are async; the actual
blocking work (LLM calls, DB queries) runs via `asyncio.to_thread` so one
slow request doesn't stall the whole server. A semaphore
(`GSR_MAX_CONCURRENT_AGENT_CALLS`, default 10) caps how many agent
invocations run *simultaneously* -- extra requests queue rather than get
rejected, protecting both the LLM provider's rate limit and DuckDB's
single-writer constraint from a traffic burst.

**A real, stated limitation**: DuckDB is a single-writer embedded
database. Write operations (refunds, tickets, signups) retry with
jittered backoff on transient lock conflicts (`mcp_server/tools.py`,
`_run_write_with_retry`), which handles realistic concurrent load for a
demo/portfolio deployment -- but it is not a substitute for a real
multi-writer database under production write volume. The honest answer
for scaling this further is migrating operational tables to Postgres
(RAG/analytical data can stay on DuckDB/Chroma).

### Running the load test
```bash
pip install -r requirements.txt   # includes locust now
uvicorn api.main:app --reload --port 8000   # terminal 1
locust -f load_test/locustfile.py --host http://127.0.0.1:8000   # terminal 2
```
Open http://localhost:8089, set **100 users**, spawn rate **10/s**, and
start the test. Read the real p50/p95/p99 latency and failure rate off
the Locust dashboard -- these are the numbers to put in your resume/
README, not estimates. A rising p95 with near-zero failures at high
concurrency reflects the semaphore queuing requests as designed; actual
5xx failures are the real signal to investigate.

## Phase 8: Deployment

**What's deployed vs. what stays local -- and why, explicitly.**

| Component | Deployed (Docker) | Local only |
|---|---|---|
| FastAPI core (`/chat`, `/auth/*`, `/health`) | ✅ | |
| RAG (Chroma) + MCP tools (DuckDB) | ✅ | |
| Redis session store | ✅ | |
| Streamlit frontend | | ✅ |
| Voice (`/chat/voice`, Whisper, pyttsx3) | | ✅ |

Voice is deliberately kept local rather than containerized: Whisper pulls
in PyTorch (~1-2GB), which doesn't fit a typical free-tier host's memory
budget, and pyttsx3 depends on OS-level speech engines (SAPI5/espeak)
that a minimal Linux container doesn't have. This isn't a limitation
discovered by accident -- it's a scoping decision: the *reasoning and
tool-use* architecture (the actual hard engineering problem) is what's
deployed and demoable via a public URL; voice I/O is a local capability
you can demo live in an interview instead. `requirements-core.txt` and
`requirements.txt` reflect this split explicitly.

### Running locally with Docker
```bash
cp .env.example .env   # fill in GOOGLE_API_KEY
docker compose up --build
```
First run builds the synthetic dataset + RAG index automatically (see
`entrypoint.sh`) and persists them in named volumes, so subsequent
`docker compose up` runs skip that step. API available at
`http://localhost:8000`.

### Deploying to a free-tier host (Render, Railway, Fly.io)
These all support "deploy from a Dockerfile" directly from your GitHub
repo:
1. Push this repo to GitHub (already done).
2. Create a new Web Service, point it at the repo, and let it detect the
   `Dockerfile`.
3. Set the `GOOGLE_API_KEY` environment variable in the host's dashboard
   (never commit it).
4. For Redis: most of these hosts offer a managed Redis add-on -- set
   `REDIS_URL` to its connection string. If you skip this, the app falls
   back to in-memory sessions automatically (fine for a demo, just won't
   survive a restart).
5. The container's port may be assigned dynamically by the host -- check
   their docs; you may need `--port $PORT` instead of the hardcoded 8000
   in `entrypoint.sh` depending on the platform.

### Architecture summary (for your resume/README)
```
Voice/Text input (Streamlit, local)
        |
FastAPI (async, semaphore-gated concurrency) -- deployed
        |
LangGraph multi-agent: identify_customer -> classify_intent ->
  [order_status | returns_refund | product_qa | billing | account_issue]
  -> resolution_check -> respond | escalate
        |
Custom MCP-backed tools (DuckDB) + RAG (Chroma, cached, thread-safe)
        |
Redis (sessions) -- deployed alongside the API
```

## Troubleshooting

**Load test shows "Could not connect to tenant default_tenant" on /chat**
This was a real thread-safety bug in the RAG retriever's lazy Chroma
client initialization -- fixed in `agent/rag_retriever.py` via a
double-checked lock (`_init_lock`). If you still see it, make sure
you're running the latest version of that file.

**Load test shows 429 RESOURCE_EXHAUSTED under concurrent load, even on
gemini-3.5-flash-lite**
This is expected, not a bug: Gemini's free tier has a per-minute rate
limit separate from the daily quota, and 100 simulated concurrent users
can exceed it almost immediately since each chat turn makes several LLM
calls. Mitigations: lower `GSR_MAX_CONCURRENT_AGENT_CALLS` to smooth out
the request rate, add delay between simulated users in
`load_test/locustfile.py` (increase `wait_time`), or note in your
writeup that the LLM provider's free-tier rate limit -- not the
application -- is the binding constraint at this concurrency level
(which is itself a legitimate, useful load-test finding).

**"429 RESOURCE_EXHAUSTED" / "exceeded your current quota"**
Gemini's free tier gives regular Flash models only ~20 requests/day as of
late 2026, and a single chat turn makes several LLM calls (intent
classification + tool-calling rounds), so this exhausts fast during
testing. The project defaults to `gemini-3.5-flash-lite`, which gets a
much higher ~500 requests/day free quota for the same $0 cost -- if you
still hit this, either wait for the daily reset (resets at midnight
Pacific Time) or switch providers (see `.env.example` for the Anthropic
option, if you have API credits).

**Frontend shows a generic error with no detail**
Check the `uvicorn` terminal -- FastAPI logs the full Python traceback
server-side even when the client only sees a generic error page. The
frontend's error messages also surface the FastAPI `detail` field
directly where possible.

## Voice setup (Phase 5)
Whisper (STT) needs the `ffmpeg` binary on your system PATH -- this is
separate from the Python package. On Windows:
```powershell
winget install ffmpeg
```
(Or download from https://ffmpeg.org/download.html and add it to PATH
manually.) Restart your terminal after installing so PATH updates take
effect. Verify with:
```powershell
ffmpeg -version
```

pyttsx3 (TTS) uses Windows' built-in SAPI5 voices -- no extra install
needed on Windows.

Test the full voice pipeline locally (no server needed):
```bash
python -m voice.test_voice_pipeline "Where is my order ord_000519?" cust_000000
```
This synthesizes a sample question to audio, transcribes it back with
Whisper, runs it through the real agent, and speaks the response aloud.
The first run downloads the Whisper model (~150 MB for the default
"base" size) -- expect a pause.

Once the API is running (see below), test voice over HTTP:
```bash
curl -X POST "http://127.0.0.1:8000/chat/voice?session_id=s1" \
  -F "audio=@question.wav" \
  --output response.wav
```
The transcript and response text come back as response headers
(`X-Transcript`, `X-Response-Text`), and `response.wav` is the spoken reply.

## Running the frontend
With the API running (see above), in a separate terminal:
```bash
streamlit run frontend/app.py
```
Opens at http://localhost:8501. Use the sidebar to create an account or sign
in with the email and password used at signup. Type a message or use the
built-in mic recorder to test voice.

## React storefront + embedded support chat

The responsive React storefront is served at the site root with a Gigi support
chat launcher in the bottom-right corner. Product cards and imagery are demo
content; inventory and checkout are not connected. The API also serves the
storefront in Docker/Render builds.

Clear first-turn order, return, billing, account-security, and policy requests
use conservative keyword routing to skip the separate intent-classifier model
call. Follow-up messages still use the LLM classifier so conversation context
is considered. Each chat response includes node timings and the API logs those
timings, making the classifier, specialist, semaphore wait, and full agent
duration visible when diagnosing slow responses.

For local development, start the API, then run Vite in another terminal:

```bash
uvicorn api.main:app --reload --port 8000
cd frontend
npm install
```

PowerShell:

```powershell
$env:VITE_API_BASE_URL="http://localhost:8000"
npm run dev
```

Open http://localhost:5173. Create an account using an email address and a
password of at least 12 characters, or sign in with that email and password.
The API stores salted PBKDF2 password hashes and uses an HttpOnly, signed,
12-hour cookie for authentication. `/chat` derives the customer identity from
that cookie; it rejects caller-supplied customer IDs. Existing synthetic
customers are not claimable by ID because their generated records have no
verified credentials. New accounts can use personalized support as real orders
are associated with them.

Set `GSR_AUTH_SECRET_KEY` to a long random value on Render, alongside
`GOOGLE_API_KEY`. Generate a key with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`. Without a
configured key, local development creates a temporary key, so signed-in users
will need to sign in again after an API restart.

## Running the authenticated signup and chat demo

```bash
uvicorn api.main:app --reload --port 8000
python scripts/demo_realtime_signup.py
```

The script creates an account, receives an HttpOnly authentication cookie,
and immediately sends a chat request as that authenticated customer. For
manual use, sign up and chat in the React storefront; do not pass a
`customer_id` in the chat request body.
## Repo layout
```
data/             synthetic data generator + DuckDB loader
knowledge_base/   policy and FAQ markdown docs (RAG source)
rag/              embedding/indexing scripts (added in a later phase)
mcp_server/       custom MCP server + tools (added in a later phase)
agent/            LangGraph multi-agent graph + nodes (added in a later phase)
voice/            STT/TTS layer (added in a later phase)
api/              FastAPI app + account authentication (added in a later phase)
frontend/         chat + voice UI (added in a later phase)
```

## License
MIT
