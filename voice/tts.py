"""
Local text-to-speech using pyttsx3, which wraps the operating system's own
voices (SAPI5 on Windows, so no model download and no internet needed).
Like stt.py, this is a stateless post-processing layer -- it has no idea
what GSR is; it just turns the agent's already-generated response text
into audio.

Note: pyttsx3's engine is not safely reusable across repeated calls in a
long-running process (a known library quirk -- calling runAndWait() twice
on one engine instance can hang or error). So each call here creates a
fresh engine instance rather than keeping one global engine alive, which
is the reliable pattern for a server that handles many requests.
"""

import os
import tempfile


def synthesize_speech(text: str, output_path: str = None) -> str:
    """
    Synthesize text to a .wav file. If output_path is not given, writes to
    a new temp file and returns its path.
    """
    import pyttsx3

    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)

    engine = pyttsx3.init()
    rate = os.environ.get("TTS_RATE")
    if rate:
        engine.setProperty("rate", int(rate))

    engine.save_to_file(text, output_path)
    engine.runAndWait()
    engine.stop()

    return output_path


def speak(text: str):
    """Speak text directly through the system's speakers (CLI/dev use)."""
    import pyttsx3

    engine = pyttsx3.init()
    engine.say(text)
    engine.runAndWait()
    engine.stop()


if __name__ == "__main__":
    import sys

    text = " ".join(sys.argv[1:]) or "Hello, this is a test of the GSR support agent's voice."
    print(f"Speaking: {text}")
    speak(text)
