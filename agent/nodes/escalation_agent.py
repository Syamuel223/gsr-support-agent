"""
Terminal node for anything that couldn't be confidently resolved by a
specialist agent. Creates a support ticket (if one doesn't already exist
in state) and escalates it with a summary of the conversation, via the
same MCP-backed tools the specialist agents use.
"""

from agent.langchain_tools import create_support_ticket, escalate_to_human
from agent.state import AgentState


def escalation_agent(state: AgentState) -> dict:
    ticket_id = state.get("ticket_id")

    if not ticket_id:
        customer_id = state.get("customer_id") or "unknown_customer"
        ticket_result = create_support_ticket.invoke({
            "customer_id": customer_id,
            "category": state.get("intent") or "unclear",
            "priority": "high" if "security" in (state.get("escalation_reason") or "").lower() else "medium",
        })
        ticket_id = ticket_result.get("ticket_id")

    context_summary = (
        f"Customer message: {state['user_message']}\n"
        f"Detected intent: {state.get('intent', 'unclear')}\n"
        f"Reason for escalation: {state.get('escalation_reason', 'Not confidently resolved by specialist agent.')}\n"
        f"Tool results so far: {state.get('tool_results', {})}"
    )

    if ticket_id:
        escalate_to_human.invoke({
            "ticket_id": ticket_id,
            "context_summary": context_summary,
        })

    response = state.get("response")
    if not response:
        # no specialist response was generated (e.g. low-confidence intent) --
        # use a generic handoff message instead of leaving it blank
        response = (
            "I want to make sure this gets handled properly, so I'm connecting "
            "you with a member of our support team who can help further."
        )

    return {
        "ticket_id": ticket_id,
        "response": response,
        "needs_escalation": True,
    }
