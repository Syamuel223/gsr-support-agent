"""
Sits between a specialist agent and the final response. Decides whether
the issue is genuinely resolved or should be escalated to a human --
based on explicit signals set by the specialist nodes (resolved,
needs_escalation), not a second LLM guess layered on top.
"""

from agent.state import AgentState


def resolution_check(state: AgentState) -> dict:
    if state.get("needs_escalation"):
        return {}  # already flagged explicitly by the specialist node (e.g. security)

    if not state.get("resolved", False):
        return {
            "needs_escalation": True,
            "escalation_reason": "Specialist agent could not confidently resolve the request.",
        }

    return {}


def route_after_resolution(state: AgentState) -> str:
    """Conditional edge function."""
    return "escalate" if state.get("needs_escalation") else "respond"
