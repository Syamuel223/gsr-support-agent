# GSR Support Agent

An e-commerce storefront with an embedded AI customer support agent. The
project combines a React storefront, a FastAPI API, a LangGraph support
workflow, MCP tools for customer and order data, and retrieval augmented
answers for store policies.

**Live demo:** [gsr-support-agent.onrender.com](https://gsr-support-agent.onrender.com/)

The storefront and API are deployed together as one Docker web service. The
free Render instance may sleep when idle, so its first response after a quiet
period can take longer.

## What it does

- Shows a responsive demo shop with product cards and a support chat launcher.
- Lets customers sign up and sign in, then ask for help in an authenticated
  chat.
- Routes requests to specialist agents for orders, returns, billing, account
  issues, and policy questions.
- Uses MCP tools and DuckDB for customer-specific information, and Chroma RAG
  retrieval for policy answers.
- Reports chat timing information to help diagnose slow responses.

The storefront is a demo: product listings, inventory, checkout, payment, and
shipment purchasing are not connected to a real commerce system. New accounts
are created in the support database; they do not automatically have a real
order history. Email verification and password reset are not implemented.

## Architecture

```text
React storefront (Vite build)
        |
FastAPI: signup, login, chat, health, static assets
        |
LangGraph: identify customer -> classify intent -> specialist -> resolve/escalate
        |                                      |
MCP tools + DuckDB                       Policy RAG + Chroma
```

Authentication uses salted PBKDF2 password hashes and a signed, HttpOnly
cookie. The API gets the customer identity from the authenticated cookie; the
browser cannot select another customer's ID in a chat request.

## Run locally

### With Docker

1. Copy `.env.example` to `.env` and set `GOOGLE_API_KEY`.
2. Start the app:

   ```bash
   docker compose up --build
   ```

The API and storefront will be available at [http://localhost:8000](http://localhost:8000).
On first start, the container generates the sample database and builds the
policy index. This downloads the embedding model and may take a few minutes.

### Without Docker

Create a Python environment, install the core requirements, and prepare the
local data and policy index:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-core.txt
python data/generate_synthetic_data.py
python data/load_data.py
python rag/embed_and_index.py
```

Create `.env` from `.env.example` and set `GOOGLE_API_KEY`, then start the API:

```bash
uvicorn api.main:app --reload --port 8000
```

For frontend development, open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Vite runs at [http://localhost:5173](http://localhost:5173) and proxies API
requests to the local FastAPI server. The React app is the customer storefront;
`frontend/app.py` is the separate Streamlit demo interface.

## Configuration

| Variable | Purpose |
| --- | --- |
| `GOOGLE_API_KEY` | Required for Google Gemini model requests. |
| `GSR_AUTH_SECRET_KEY` | Stable signing secret for production auth cookies. |
| `GSR_LLM_PROVIDER` | LLM provider selection; see `.env.example`. |
| `GSR_MAX_CONCURRENT_AGENT_CALLS` | Maximum simultaneous agent calls (default `10`). |
| `REDIS_URL` | Optional Redis session storage; local memory is used when unavailable. |
| `GSR_CORS_ORIGINS` | Optional comma-separated browser origins for API access. |

Generate a signing secret with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set `GOOGLE_API_KEY` and `GSR_AUTH_SECRET_KEY` in Render's service **Environment**
settings. Do not commit `.env` or paste secret values into logs or chat. If the
signing secret changes, existing login cookies will no longer work.

## Deploy to Render

The service uses the repository's root `Dockerfile`. It builds the React app,
installs the Python API, and starts Uvicorn on Render's assigned `PORT`.
Connect the GitHub repository as a Render Web Service with the repository root
as the build context and enable auto-deploy from `main`. Configure the required
environment variables above in the Render dashboard. The public service URL is
[https://gsr-support-agent.onrender.com](https://gsr-support-agent.onrender.com/).

Useful endpoints:

- `/` — React storefront
- `/health` — service health and concurrency status
- `/auth/signup`, `/auth/login`, `/auth/me`, `/auth/logout` — account routes
- `/chat` — authenticated text chat

## Other ways to try it

Run the command-line agent against the sample data:

```bash
python -m agent.graph "Where is my order ord_000519?" cust_000000
python -m agent.graph "What's your return policy for electronics?"
```

Run the Streamlit interface:

```bash
streamlit run frontend/app.py
```

Run the signup-and-chat demonstration script with the API running:

```bash
python scripts/demo_realtime_signup.py
```

## Project structure

```text
agent/           LangGraph workflow and specialist agents
api/             FastAPI routes, auth, and session handling
data/            Synthetic data and DuckDB loading scripts
frontend/        React storefront, Vite setup, and Streamlit demo
knowledge_base/  Store policy and FAQ source documents
mcp_server/      MCP tools used by the agents
rag/             Chroma indexing and retrieval
voice/           Local speech recognition and text-to-speech support
```

## Notes

- DuckDB is intended for this demo's scale. Higher write volume should use a
  multi-writer database such as Postgres.
- Clear first-turn requests can use keyword routing to skip the separate
  intent-classifier model call; contextual follow-ups still use the LLM.
- Voice support is a local capability and is not included in the Render Docker
  image. It requires additional system dependencies such as `ffmpeg`.

## License

MIT
