"""
End-to-end voice pipeline test, entirely local -- no server needed.

1. Synthesizes a sample question to a .wav file (simulating what a real
   microphone recording would give us)
2. Transcribes it back with Whisper
3. Runs the transcript through the actual agent graph
4. Synthesizes the agent's response to speech and plays it

This proves STT -> agent -> TTS works end to end before wiring it into
the API's /chat/voice endpoint (or a real microphone).

Run:
    python -m voice.test_voice_pipeline "Where is my order ord_000519?" cust_000000
"""

import sys

from dotenv import load_dotenv

load_dotenv()


def main():
    from agent.graph import run
    from voice.stt import transcribe_audio
    from voice.tts import speak, synthesize_speech

    question = sys.argv[1] if len(sys.argv) > 1 else "Where is my order ord_000519?"
    customer_id = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"1. Synthesizing sample question to audio: {question!r}")
    question_audio_path = synthesize_speech(question)
    print(f"   -> saved to {question_audio_path}")

    print("\n2. Transcribing it back with Whisper (this may take a moment on first run)...")
    transcription = transcribe_audio(question_audio_path)
    print(f"   -> transcript: {transcription['text']!r}")
    print(f"   -> detected language: {transcription['language']}")

    print("\n3. Running the transcript through the agent...")
    result = run(transcription["text"], customer_id=customer_id)
    print(f"   -> intent: {result.get('intent')}")
    print(f"   -> resolved: {result.get('resolved')} | escalated: {result.get('needs_escalation')}")
    print(f"   -> response: {result.get('response')}")

    print("\n4. Speaking the response aloud...")
    speak(result.get("response", ""))
    print("Done.")


if __name__ == "__main__":
    main()
