# GSR Support Agent — Multi-Agent Customer Support (Voice + Text)

A multi-agent customer support system for **GSR (GlobalShop Retail)**, a
fictional e-commerce company built for this project. Customers chat or
speak to the agent about orders, returns, billing, and account issues; a
LangGraph multi-agent pipeline routes each request to a specialist agent,
which answers using RAG (for policy questions) or real tool calls via a
custom MCP server (for account-specific data like order status).

## Status
🚧 Phase 4 in progress: FastAPI layer + real-time signup webhook (voice
added in a later phase).

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
