"""
FastAPI layer over the LangGraph agent.

Endpoints:
    POST /chat               -- send a text message, get the agent's response
    POST /chat/voice          -- send an audio file, get transcript + text
                                 response + a spoken-audio response back
    POST /webhook/new-signup -- register a new customer (real-time, no
                                 batch delay -- immediately queryable by /chat)
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
import os
import tempfile
import time
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.graph import app as agent_app
from agent.langchain_tools import register_new_customer as register_new_customer_tool
from api.session_store import get_session, save_turn
from mcp_server.tools import get_customer_profile

app = FastAPI(title="GSR Support Agent API")

MAX_CONCURRENT_AGENT_CALLS = int(os.environ.get("GSR_MAX_CONCURRENT_AGENT_CALLS", 10))
_agent_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENT_CALLS)
_active_agent_calls = 0  # for /health visibility only


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

    session = get_session(session_id)
    effective_customer_id = session["customer_id"] or customer_id

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

    async with _agent_semaphore:
        _active_agent_calls += 1
        try:
            result = await asyncio.to_thread(_invoke_agent_sync, initial_state)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Agent pipeline error: {e}")
        finally:
            _active_agent_calls -= 1

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
    }


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
async def chat(req: ChatRequest):
    result = await _run_chat_turn(req.session_id, req.message, req.customer_id)
    return ChatResponse(**result)


@app.post("/chat/voice")
async def chat_voice(
    session_id: str,
    audio: UploadFile = File(...),
    customer_id: str | None = None,
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

    result = await _run_chat_turn(session_id, transcript, customer_id)

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


@app.post("/webhook/new-signup", response_model=SignupResponse)
async def new_signup(req: SignupRequest):
    """
    Registers a new customer immediately in the operational database.
    The returned customer_id is queryable via /chat (or get_customer_profile
    directly) right away -- no batch/refresh delay, proving the real-time
    requirement this project was built around.
    """
    result = await asyncio.to_thread(
        register_new_customer_tool.invoke,
        {"name": req.name, "email": req.email, "city": req.city, "state": req.state},
    )
    if not result.get("success"):
        raise HTTPException(status_code=500, detail="Failed to register customer")

    return SignupResponse(
        customer_id=result["customer_id"],
        message=f"Welcome to GSR, {req.name}! Your account is ready.",
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
