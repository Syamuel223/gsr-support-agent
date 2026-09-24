"""
FastAPI layer over the LangGraph agent.

Endpoints:
    POST /chat               -- send a message, get the agent's response
    POST /webhook/new-signup -- register a new customer (real-time, no
                                 batch delay -- immediately queryable by /chat)
    GET  /health              -- basic liveness check

Session state (conversation history, resolved customer_id) is kept
in-memory per session_id for this phase. This is fine for local dev and a
single-process demo; a later phase swaps this for Redis so it survives
restarts and works across multiple backend replicas (same pattern used in
the AskWarehouse project's caching layer).

Run:
    uvicorn api.main:app --reload --port 8000
"""

from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agent.graph import app as agent_app
from agent.langchain_tools import register_new_customer as register_new_customer_tool
from mcp_server.tools import get_customer_profile

app = FastAPI(title="GSR Support Agent API")

# --- in-memory session store (Phase 4; Redis-backed in a later phase) ---
# session_id -> {"customer_id": str | None, "history": list[dict]}
_sessions: dict[str, dict] = {}

MAX_HISTORY_STORED = 20  # cap per-session memory growth


def _get_session(session_id: str) -> dict:
    if session_id not in _sessions:
        _sessions[session_id] = {"customer_id": None, "history": []}
    return _sessions[session_id]


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Stable id for this conversation")
    message: str
    customer_id: str | None = Field(
        None, description="Set once (e.g. at login); remembered for the rest of the session"
    )


class ChatResponse(BaseModel):
    response: str
    intent: str | None
    resolved: bool
    escalated: bool
    ticket_id: str | None
    customer_id: str | None


class SignupRequest(BaseModel):
    name: str
    email: str
    city: str | None = None
    state: str | None = None


class SignupResponse(BaseModel):
    customer_id: str
    message: str


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    session = _get_session(req.session_id)

    # customer_id can be set on first message and is then sticky for the session
    if req.customer_id and not session["customer_id"]:
        session["customer_id"] = req.customer_id

    initial_state = {
        "session_id": req.session_id,
        "customer_id": session["customer_id"],
        "user_message": req.message,
        "conversation_history": session["history"],
        "retrieved_chunks": [],
        "tool_results": {},
        "resolved": False,
        "needs_escalation": False,
        "retry_count": 0,
    }

    try:
        result = agent_app.invoke(initial_state)
    except Exception as e:
        # Don't leak internal stack traces to the client; still return a
        # usable, honest response rather than a raw 500 with no context.
        raise HTTPException(status_code=502, detail=f"Agent pipeline error: {e}")

    # persist the turn
    session["history"].append({"role": "user", "content": req.message})
    session["history"].append({"role": "assistant", "content": result.get("response", "")})
    session["history"] = session["history"][-MAX_HISTORY_STORED:]

    return ChatResponse(
        response=result.get("response", ""),
        intent=result.get("intent"),
        resolved=result.get("resolved", False),
        escalated=result.get("needs_escalation", False),
        ticket_id=result.get("ticket_id"),
        customer_id=session["customer_id"],
    )


@app.post("/webhook/new-signup", response_model=SignupResponse)
def new_signup(req: SignupRequest):
    """
    Registers a new customer immediately in the operational database.
    The returned customer_id is queryable via /chat (or get_customer_profile
    directly) right away -- no batch/refresh delay, proving the real-time
    requirement this project was built around.
    """
    result = register_new_customer_tool.invoke({
        "name": req.name,
        "email": req.email,
        "city": req.city,
        "state": req.state,
    })
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to register customer")

    return SignupResponse(
        customer_id=result["customer_id"],
        message=f"Welcome to GSR, {req.name}! Your account is ready.",
    )


@app.get("/health")
def health():
    checks = {"status": "ok", "timestamp": datetime.now().isoformat()}
    try:
        # cheap real check: does the operational DB actually respond?
        get_customer_profile("health_check_nonexistent_id")
        checks["database"] = "reachable"
    except Exception as e:
        checks["database"] = f"error: {e}"
        checks["status"] = "degraded"
    return checks