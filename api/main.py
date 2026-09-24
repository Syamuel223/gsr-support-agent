"""
FastAPI layer over the LangGraph agent.

Endpoints:
    POST /chat               -- send a text message, get the agent's response
    POST /chat/voice          -- send an audio file, get transcript + text
                                 response + a spoken-audio response back
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

import os
import tempfile
from datetime import datetime

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
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


def _run_chat_turn(session_id: str, message: str, customer_id: str | None) -> dict:
    """
    Core chat logic shared by both /chat (text) and /chat/voice. Keeping
    this in one place means the voice path can never drift from the text
    path's behavior -- both go through the exact same agent invocation
    and session handling.
    """
    session = _get_session(session_id)

    if customer_id and not session["customer_id"]:
        session["customer_id"] = customer_id

    initial_state = {
        "session_id": session_id,
        "customer_id": session["customer_id"],
        "user_message": message,
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
        raise HTTPException(status_code=502, detail=f"Agent pipeline error: {e}")

    session["history"].append({"role": "user", "content": message})
    session["history"].append({"role": "assistant", "content": result.get("response", "")})
    session["history"] = session["history"][-MAX_HISTORY_STORED:]

    return {
        "response": result.get("response", ""),
        "intent": result.get("intent"),
        "resolved": result.get("resolved", False),
        "escalated": result.get("needs_escalation", False),
        "ticket_id": result.get("ticket_id"),
        "customer_id": session["customer_id"],
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
def chat(req: ChatRequest):
    result = _run_chat_turn(req.session_id, req.message, req.customer_id)
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
        transcription = transcribe_audio(input_path)
    finally:
        os.unlink(input_path)

    transcript = transcription["text"]
    if not transcript:
        raise HTTPException(status_code=400, detail="Could not transcribe any speech from the audio")

    result = _run_chat_turn(session_id, transcript, customer_id)

    output_path = synthesize_speech(result["response"])

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
