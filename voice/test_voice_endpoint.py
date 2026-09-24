"""
Tests the /chat/voice endpoint over real HTTP, avoiding PowerShell's curl
alias quirks entirely. Generates its own test audio (via TTS) so no
external audio file is needed.

Requires the API server running first:
    uvicorn api.main:app --reload --port 8000

Then:
    python voice/test_voice_endpoint.py "Where is my order ord_000519?" cust_000000
"""

import sys

import requests

BASE_URL = "http://127.0.0.1:8000"


def main():
    from voice.tts import synthesize_speech

    question = sys.argv[1] if len(sys.argv) > 1 else "Where is my order ord_000519?"
    customer_id = sys.argv[2] if len(sys.argv) > 2 else "cust_000000"

    print(f"1. Synthesizing test question to audio: {question!r}")
    audio_path = synthesize_speech(question)
    print(f"   -> {audio_path}")

    print("\n2. Sending to /chat/voice...")
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/chat/voice",
            params={"session_id": "voice-test-session", "customer_id": customer_id},
            files={"audio": ("question.wav", f, "audio/wav")},
        )
    resp.raise_for_status()

    print(f"   -> Transcript (X-Transcript header): {resp.headers.get('X-Transcript')}")
    print(f"   -> Intent (X-Intent header): {resp.headers.get('X-Intent')}")
    print(f"   -> Escalated (X-Escalated header): {resp.headers.get('X-Escalated')}")
    print(f"   -> Response text (X-Response-Text header): {resp.headers.get('X-Response-Text')}")

    with open("response.wav", "wb") as f:
        f.write(resp.content)
    print("\n3. Saved spoken response to response.wav -- play it to hear the agent's reply.")


if __name__ == "__main__":
    main()