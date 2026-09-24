"""
Local speech-to-text using OpenAI's Whisper model, run entirely on-device
(no API calls, no cost). This is a stateless pre-processing layer -- it
knows nothing about GSR, orders, or agents; it just converts audio to
text, which then gets handed to the LangGraph pipeline exactly like a
typed message would be.

Model size tradeoff (set via WHISPER_MODEL_SIZE env var, default "base"):
    tiny   ~75 MB   fastest, lowest accuracy
    base   ~150 MB  good balance for a demo/CPU machine (default)
    small  ~500 MB  better accuracy, noticeably slower on CPU
    medium ~1.5 GB  only worth it with a GPU

The first call downloads the model weights (one-time, cached locally by
the whisper library) -- expect a pause the first time you run this.
"""

import os

_model = None
_model_size = os.environ.get("WHISPER_MODEL_SIZE", "base")


def _get_model():
    global _model
    if _model is None:
        import whisper
        _model = whisper.load_model(_model_size)
    return _model


def transcribe_audio(file_path: str) -> dict:
    """
    Transcribe an audio file (wav, mp3, m4a, etc. -- anything ffmpeg can
    read) to text.

    Returns:
        {"text": str, "language": str}
    """
    model = _get_model()
    result = model.transcribe(file_path)
    return {
        "text": result["text"].strip(),
        "language": result.get("language", "unknown"),
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m voice.stt <path_to_audio_file>")
        sys.exit(1)

    result = transcribe_audio(sys.argv[1])
    print(f"Language detected: {result['language']}")
    print(f"Transcript: {result['text']}")
