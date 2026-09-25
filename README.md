# GSR Support Agent — Multi-Agent Customer Support (Voice + Text)

A multi-agent customer support system for **GSR (GlobalShop Retail)**, a
fictional e-commerce company built for this project. Customers chat or
speak to the agent about orders, returns, billing, and account issues; a
LangGraph multi-agent pipeline routes each request to a specialist agent,
which answers using RAG (for policy questions) or real tool calls via a
custom MCP server (for account-specific data like order status).

## Status
🚧 Phase 6 in progress: Streamlit frontend (chat + voice, talks to the
FastAPI backend over HTTP).

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
Real-time signup webhook -- new customers are queryable immediately,
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

## Troubleshooting

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
curl -X POST "http://127.0.0.1:8000/chat/voice?session_id=s1&customer_id=cust_000000" \
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
Opens at http://localhost:8501. Use the sidebar to either sign in as an
existing customer (e.g. `cust_000000`) or sign up as a brand new one --
signing up there and then immediately chatting proves the same real-time
requirement as the CLI demo, but interactively. Type a message or use the
built-in mic recorder to test voice.

## Running the API + real-time signup demo
```bash
uvicorn api.main:app --reload --port 8000
```
In another terminal:
```bash
python scripts/demo_realtime_signup.py
```
This registers a brand new customer via /webhook/new-signup and
immediately chats as them via /chat -- proving there's no batch/refresh
delay between signup and being queryable.

You can also call the endpoints directly:
```bash
curl -X POST http://127.0.0.1:8000/webhook/new-signup \
  -H "Content-Type: application/json" \
  -d '{"name": "Test User", "email": "test@example.com", "city": "Pune", "state": "MH"}'

curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": "s1", "customer_id": "cust_000000", "message": "Where is my order ord_000519?"}'
```

## Repo layout
```
data/             synthetic data generator + DuckDB loader
knowledge_base/   policy and FAQ markdown docs (RAG source)
rag/              embedding/indexing scripts (added in a later phase)
mcp_server/       custom MCP server + tools (added in a later phase)
agent/            LangGraph multi-agent graph + nodes (added in a later phase)
voice/            STT/TTS layer (added in a later phase)
api/              FastAPI app + real-time signup webhook (added in a later phase)
frontend/         chat + voice UI (added in a later phase)
```

## License
MIT
