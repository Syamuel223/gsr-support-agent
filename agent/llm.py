"""
Centralized LLM client construction, so every node gets its model from one
place instead of each hardcoding a provider. Defaults to Google Gemini
(free tier available, good for development/demo); set GSR_LLM_PROVIDER=
anthropic to switch back to Claude if you have API credits.

Env vars:
    GSR_LLM_PROVIDER      "google" (default) or "anthropic"
    GSR_CLASSIFY_MODEL    model used for cheap intent classification
    GSR_AGENT_MODEL       model used by the specialist agents (tool-calling)
    GOOGLE_API_KEY        required if using Gemini
    ANTHROPIC_API_KEY     required if using Claude
"""

import os

PROVIDER = os.environ.get("GSR_LLM_PROVIDER", "google").lower()

DEFAULT_MODELS = {
    "google": {
        "classify": "gemini-3.6-flash",
        "agent": "gemini-3.6-flash",
    },
    "anthropic": {
        "classify": "claude-haiku-4-5-20251001",
        "agent": "claude-sonnet-4-5",
    },
}


def _model_name(kind: str) -> str:
    env_var = "GSR_CLASSIFY_MODEL" if kind == "classify" else "GSR_AGENT_MODEL"
    return os.environ.get(env_var, DEFAULT_MODELS[PROVIDER][kind])


def _build(kind: str, temperature: float = 0):
    model = _model_name(kind)
    if PROVIDER == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, temperature=temperature)
    elif PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, temperature=temperature)
    else:
        raise ValueError(f"Unknown GSR_LLM_PROVIDER: {PROVIDER!r} (expected 'google' or 'anthropic')")


def get_classify_llm(temperature: float = 0):
    """Cheap/fast model for intent classification and yes/no checks."""
    return _build("classify", temperature)


def get_agent_llm(temperature: float = 0):
    """Model used by specialist agents that do tool-calling and reasoning."""
    return _build("agent", temperature)


def extract_text(response) -> str:
    """
    Normalize an LLM response's .content into a plain string, regardless
    of provider. Anthropic returns a plain string. Gemini (via
    langchain-google-genai) returns a list of content blocks, e.g.
    [{"type": "text", "text": "...", "extras": {"signature": "..."}}] --
    this pulls just the actual text out of blocks like that.
    """
    content = response.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)
