"""
Shared helper for formatting recent conversation turns into prompt context.
Used by classify_intent and the specialist agents so follow-up messages
("actually, can you escalate that?") have context instead of being
evaluated in isolation.
"""


def format_history(history: list[dict], max_turns: int = 4) -> str:
    """
    Format the last `max_turns` turns of conversation_history into a
    plain-text block. Returns an empty string if there's no history
    (first message in a session) -- callers should handle that case by
    simply not including a "previous conversation" section in the prompt.
    """
    if not history:
        return ""
    recent = history[-max_turns:]
    lines = []
    for turn in recent:
        role = "Customer" if turn.get("role") == "user" else "Agent"
        lines.append(f"{role}: {turn.get('content', '')}")
    return "\n".join(lines)
