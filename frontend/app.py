"""
Streamlit frontend for the GSR support agent -- talks to the FastAPI
backend (api/main.py) over HTTP, exactly like any other client would.
This file has zero direct imports from agent/, mcp_server/, etc. -- it
only knows about the API, which is the correct boundary (the frontend
should be swappable without touching backend logic, and vice versa).

Run (with the API already running separately):
    uvicorn api.main:app --reload --port 8000      # terminal 1
    streamlit run frontend/app.py                   # terminal 2
"""

import hashlib
import os
import uuid

import requests
import streamlit as st

API_BASE_URL = os.environ.get("GSR_API_BASE_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="GSR Support", page_icon="🛒", layout="centered")


# --- session state setup ---
if "session_id" not in st.session_state:
    st.session_state.session_id = str(uuid.uuid4())
if "customer_id" not in st.session_state:
    st.session_state.customer_id = None
if "customer_name" not in st.session_state:
    st.session_state.customer_name = None
if "api_client" not in st.session_state:
    st.session_state.api_client = requests.Session()
if "messages" not in st.session_state:
    st.session_state.messages = []  # [{"role": "user"|"assistant", "content": str, ...}]


class ChatAPIError(Exception):
    """Carries the actual FastAPI error detail, not just an HTTP status code."""
    pass


def _extract_error_detail(resp: requests.Response) -> str:
    """Pull the actual FastAPI 'detail' message out of an error response,
    instead of just the generic HTTP status text -- this is what actually
    tells you *why* something failed (e.g. the real agent exception)."""
    try:
        return resp.json().get("detail", resp.text)
    except ValueError:
        return resp.text or f"HTTP {resp.status_code}"


def call_chat_api(message: str) -> dict:
    resp = st.session_state.api_client.post(f"{API_BASE_URL}/chat", json={
        "session_id": st.session_state.session_id,
        "message": message,
    }, timeout=60)
    if not resp.ok:
        raise ChatAPIError(_extract_error_detail(resp))
    return resp.json()


def call_voice_api(audio_bytes: bytes) -> dict:
    resp = st.session_state.api_client.post(
        f"{API_BASE_URL}/chat/voice",
        params={"session_id": st.session_state.session_id},
        files={"audio": ("recording.wav", audio_bytes, "audio/wav")},
        timeout=120,  # local Whisper on CPU can be slow
    )
    if not resp.ok:
        raise ChatAPIError(_extract_error_detail(resp))
    return {
        "audio_bytes": resp.content,
        "transcript": resp.headers.get("X-Transcript", ""),
        "response_text": resp.headers.get("X-Response-Text", ""),
        "intent": resp.headers.get("X-Intent", ""),
        "escalated": resp.headers.get("X-Escalated", "False") == "True",
    }


# --- sidebar: account authentication ---
with st.sidebar:
    st.header("GSR Customer")
    if st.session_state.customer_id:
        st.success(f"Signed in as {st.session_state.customer_name or 'GSR customer'}")
        if st.button("Sign out"):
            st.session_state.api_client.post(f"{API_BASE_URL}/auth/logout", timeout=10)
            st.session_state.customer_id = None
            st.session_state.customer_name = None
            st.session_state.session_id = str(uuid.uuid4())
            st.rerun()
    else:
        mode = st.radio("Account", ["Sign in", "Create account"], horizontal=True)
        name = st.text_input("Name") if mode == "Create account" else None
        email = st.text_input("Email", key="auth_email")
        password = st.text_input("Password", type="password", key="auth_password")
        if st.button(mode):
            payload = {"email": email, "password": password}
            endpoint = "login"
            if mode == "Create account":
                payload["name"] = name
                endpoint = "signup"
            try:
                resp = st.session_state.api_client.post(f"{API_BASE_URL}/auth/{endpoint}", json=payload, timeout=30)
                if resp.ok:
                    account = resp.json()
                    st.session_state.customer_id = account["customer_id"]
                    st.session_state.customer_name = account["name"]
                    st.session_state.session_id = str(uuid.uuid4())
                    st.rerun()
                else:
                    st.error(_extract_error_detail(resp))
            except requests.RequestException as e:
                st.error(f"Could not reach the API at {API_BASE_URL}: {e}")

    st.divider()
    st.caption(f"API: {API_BASE_URL}")
    st.caption(f"session_id: {st.session_state.session_id[:8]}...")

# --- main chat area ---
st.title("🛒 GSR Support")
st.caption("Ask about orders, returns, billing, or your account -- by text or voice.")

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if msg.get("intent"):
            badge = "🔴 Escalated" if msg.get("escalated") else "🟢 Resolved"
            st.caption(f"{badge} · intent: {msg['intent']}")
        if msg.get("audio_bytes"):
            st.audio(msg["audio_bytes"], format="audio/wav")

# --- voice input ---
audio_value = st.audio_input("Or record a voice message")
if audio_value is not None:
    audio_bytes = audio_value.read()
    audio_hash = hashlib.md5(audio_bytes).hexdigest()

    if st.session_state.get("last_audio_hash") != audio_hash:
        st.session_state.last_audio_hash = audio_hash

        with st.spinner("Transcribing and thinking..."):
            try:
                result = call_voice_api(audio_bytes)
            except ChatAPIError as e:
                st.error(f"Support system error: {e}")
                result = None
            except requests.RequestException as e:
                st.error(f"Could not reach the API at {API_BASE_URL} -- "
                         f"is `uvicorn api.main:app` still running? ({e})")
                result = None

        if result:
            st.session_state.messages.append({"role": "user", "content": result["transcript"]})
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["response_text"],
                "intent": result["intent"],
                "escalated": result["escalated"],
                "audio_bytes": result["audio_bytes"],
            })
            st.rerun()

# --- text input ---
if prompt := st.chat_input("Type a message..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.spinner("Thinking..."):
        try:
            result = call_chat_api(prompt)
            st.session_state.messages.append({
                "role": "assistant",
                "content": result["response"],
                "intent": result.get("intent"),
                "escalated": result.get("escalated"),
            })
        except ChatAPIError as e:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Sorry, the support system hit an error: {e}",
            })
        except requests.RequestException as e:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"Sorry, I couldn't reach the API at {API_BASE_URL} "
                            f"-- is `uvicorn api.main:app` still running? ({e})",
            })
    st.rerun()
