"""
FastAPI layer over the LangGraph agent.

Endpoints:
    POST /chat               -- send a text message, get the agent's response
    POST /chat/voice          -- send an audio file, get transcript + text
                                 response + a spoken-audio response back
    POST /auth/signup         -- create an account and sign in
    POST /auth/login          -- sign in with email and password
    POST /auth/logout         -- clear the signed-in cookie
    GET  /health              -- basic liveness check, includes concurrency stats

Concurrency design (Phase 7):
    - Session storage is delegated to api/session_store.py (Redis if
      REDIS_URL is set and reachable, in-memory fallback otherwise) --
      see that module for why.
    - Endpoints are async, and the actual blocking work (the LangGraph
      invocation, which does real LLM API calls + DB queries) runs in a
      thread pool via asyncio.to_thread(), so one slow request doesn't
      block the event loop from accepting/serving other requests.
    - A semaphore caps how many agent invocations run *concurrently*
      (GSR_MAX_CONCURRENT_AGENT_CALLS, default 10) -- this protects the
      LLM provider's rate limit and DuckDB's single-writer constraint from
      being hit by a sudden burst, at the cost of queuing excess requests
      rather than rejecting them outright (graceful degradation over
      hard failure, same principle used in the AskWarehouse project).

Run:
    uvicorn api.main:app --reload --port 8000
"""

import asyncio
import logging
import os
import tempfile
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.graph import app as agent_app
from api.session_store import get_session, save_turn
from mcp_server.tools import get_customer_profile
from api.auth import authenticate, create_account, get_account, initialize_auth_store, issue_token, verify_token

app = FastAPI(title="GSR Support Agent API")

# The React storefront is built into frontend/dist for deployment. During
# frontend development Vite runs separately and calls this API directly.
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "GSR_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(","),
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)

MAX_CONCURRENT_AGENT_CALLS = int(os.environ.get("GSR_MAX_CONCURRENT_AGENT_CALLS", 10))
_agent_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENT_CALLS)
_active_agent_calls = 0  # for /health visibility only
logger = logging.getLogger("gsr.chat")


def _invoke_agent_sync(initial_state: dict) -> dict:
    """The actual blocking call -- runs off the event loop via asyncio.to_thread."""
    return agent_app.invoke(initial_state)


async def _run_chat_turn(session_id: str, message: str, customer_id: str | None) -> dict:
    """
    Core chat logic shared by both /chat (text) and /chat/voice. Keeping
    this in one place means the voice path can never drift from the text
    path's behavior -- both go through the exact same agent invocation
    and session handling.
    """
    global _active_agent_calls
    turn_started = time.perf_counter()

    session = get_session(session_id)
    stored_customer_id = session["customer_id"]
    if stored_customer_id and stored_customer_id != customer_id:
        raise HTTPException(status_code=403, detail="This conversation belongs to a different signed-in account. Start a new chat.")
    if stored_customer_id and not customer_id:
        raise HTTPException(status_code=401, detail="Please sign in again to continue this conversation.")
    effective_customer_id = customer_id

    initial_state = {
        "session_id": session_id,
        "customer_id": effective_customer_id,
        "user_message": message,
        "conversation_history": session["history"],
        "retrieved_chunks": [],
        "tool_results": {},
        "resolved": False,
        "needs_escalation": False,
        "retry_count": 0,
    }

    queued_at = time.perf_counter()
    async with _agent_semaphore:
        queue_ms = round((time.perf_counter() - queued_at) * 1000, 1)
        agent_started = time.perf_counter()
        _active_agent_calls += 1
        try:
            result = await asyncio.to_thread(_invoke_agent_sync, initial_state)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Agent pipeline error: {e}")
        finally:
            _active_agent_calls -= 1
    agent_ms = round((time.perf_counter() - agent_started) * 1000, 1)
    timings_ms = {
        **result.get("node_timings_ms", {}),
        "semaphore_wait": queue_ms,
        "agent_total": agent_ms,
        "request_total": round((time.perf_counter() - turn_started) * 1000, 1),
    }
    logger.info("chat completed intent=%s source=%s timings_ms=%s", result.get("intent"), result.get("intent_source"), timings_ms)

    updated_session = save_turn(
        session_id, customer_id, message, result.get("response", "")
    )

    return {
        "response": result.get("response", ""),
        "intent": result.get("intent"),
        "resolved": result.get("resolved", False),
        "escalated": result.get("needs_escalation", False),
        "ticket_id": result.get("ticket_id"),
        "customer_id": updated_session["customer_id"],
        "intent_source": result.get("intent_source"),
        "timings_ms": timings_ms,
    }


class ChatRequest(BaseModel):
    session_id: str = Field(..., description="Stable id for this conversation")
    message: str
    model_config = {"extra": "forbid"}


class ChatResponse(BaseModel):
    response: str
    intent: str | None
    resolved: bool
    escalated: bool
    ticket_id: str | None
    customer_id: str | None
    intent_source: str | None
    timings_ms: dict[str, float]


class AuthSignupRequest(BaseModel):
    name: str
    email: str
    password: str


class AuthLoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    customer_id: str
    email: str
    name: str


@app.on_event("startup")
async def startup_auth_store():
    await asyncio.to_thread(initialize_auth_store)


def _authenticated_customer(request: Request) -> str | None:
    authorization = request.headers.get("authorization", "")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else request.cookies.get("gsr_access")
    if not token:
        return None
    customer_id = verify_token(token)
    if not customer_id or not get_account(customer_id):
        raise HTTPException(status_code=401, detail="Your sign-in has expired. Please sign in again.")
    return customer_id


def _set_auth_cookie(response: Response, customer_id: str, request: Request):
    response.set_cookie(
        "gsr_access", issue_token(customer_id), max_age=60 * 60 * 12,
        httponly=True, secure=request.url.scheme == "https", samesite="lax", path="/",
    )


@app.post("/auth/signup", response_model=AuthResponse, status_code=201)
async def auth_signup(req: AuthSignupRequest, request: Request, response: Response):
    try:
        account = await asyncio.to_thread(create_account, req.name, req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=409 if "already exists" in str(e) else 400, detail=str(e))
    _set_auth_cookie(response, account["customer_id"], request)
    return AuthResponse(**account)


@app.post("/auth/login", response_model=AuthResponse)
async def auth_login(req: AuthLoginRequest, request: Request, response: Response):
    account = await asyncio.to_thread(authenticate, req.email, req.password)
    if not account:
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    _set_auth_cookie(response, account["customer_id"], request)
    return AuthResponse(**account)


@app.get("/auth/me", response_model=AuthResponse)
async def auth_me(request: Request):
    customer_id = _authenticated_customer(request)
    if not customer_id:
        raise HTTPException(status_code=401, detail="Please sign in to continue.")
    return AuthResponse(**get_account(customer_id))


@app.post("/auth/logout")
async def auth_logout(response: Response):
    response.delete_cookie("gsr_access", httponly=True, samesite="lax", path="/")
    return {"signed_out": True}


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request):
    customer_id = _authenticated_customer(request)
    result = await _run_chat_turn(req.session_id, req.message, customer_id)
    return ChatResponse(**result)


@app.post("/chat/voice")
async def chat_voice(
    session_id: str,
    request: Request,
    audio: UploadFile = File(...),
):
    """
    Voice-in, voice-out: accepts an audio file, transcribes it locally
    (Whisper), runs the exact same agent pipeline as /chat, synthesizes
    the response to speech locally (pyttsx3), and returns a .wav file.
    The transcript and response text are included as response headers
    (X-Transcript, X-Response-Text, X-Intent) since the body is audio.
    """
    from voice.stt import transcribe_audio
    from voice.tts import synthesize_speech

    # save the uploaded audio to a temp file for whisper to read
    suffix = os.path.splitext(audio.filename or "audio.wav")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
        tmp_in.write(await audio.read())
        input_path = tmp_in.name

    try:
        # Whisper transcription is also blocking CPU work -- keep it off
        # the event loop too, same reasoning as the agent invocation.
        transcription = await asyncio.to_thread(transcribe_audio, input_path)
    finally:
        os.unlink(input_path)

    transcript = transcription["text"]
    if not transcript:
        raise HTTPException(status_code=400, detail="Could not transcribe any speech from the audio")

    result = await _run_chat_turn(session_id, transcript, _authenticated_customer(request))

    output_path = await asyncio.to_thread(synthesize_speech, result["response"])

    return FileResponse(
        output_path,
        media_type="audio/wav",
        filename="response.wav",
        headers={
            "X-Transcript": transcript,
            "X-Response-Text": result["response"],
            "X-Intent": result.get("intent") or "",
            "X-Escalated": str(result.get("escalated", False)),
        },
    )


@app.get("/health")
async def health():
    checks = {"status": "ok", "timestamp": datetime.now().isoformat()}
    try:
        start = time.perf_counter()
        await asyncio.to_thread(get_customer_profile, "health_check_nonexistent_id")
        checks["database"] = "reachable"
        checks["database_latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
    except Exception as e:
        checks["database"] = f"error: {e}"
        checks["status"] = "degraded"

    checks["concurrency"] = {
        "active_agent_calls": _active_agent_calls,
        "max_concurrent_agent_calls": MAX_CONCURRENT_AGENT_CALLS,
    }
    return checks


# Mount the compiled storefront after API routes so it cannot shadow them.
# The catch-all supports client-side React routes as the storefront grows.
_frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(_frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(_frontend_dist, "assets")), name="storefront-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def storefront(path: str):
        requested = os.path.join(_frontend_dist, path)
        if path and os.path.isfile(requested) and os.path.commonpath([_frontend_dist, requested]) == _frontend_dist:
            return FileResponse(requested)
        return FileResponse(os.path.join(_frontend_dist, "index.html"))
