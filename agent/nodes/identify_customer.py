"""
First node in the graph: resolves which customer is actually chatting.

For this project, the frontend passes a customer_id directly once the
customer has "logged in" (simulated auth -- no real auth system needed for
a portfolio demo). If no customer_id is present, the conversation proceeds
as an anonymous/pre-signup visitor, which some intents (e.g. general_policy
questions, or triggering register_new_customer) can still handle.
"""

from agent.langchain_tools import get_customer_profile
from agent.state import AgentState


def identify_customer(state: AgentState) -> dict:
    customer_id = state.get("customer_id")
    if not customer_id:
        return {"customer_profile": None}

    profile = get_customer_profile.invoke({"customer_id": customer_id})
    if not profile.get("found"):
        # customer_id was provided but doesn't exist -- don't silently
        # proceed as if it were valid.
        return {"customer_profile": None, "customer_id": None}

    return {"customer_profile": profile}
