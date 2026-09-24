"""
Wires every node into the full GSR support agent graph.

Flow:
    identify_customer -> classify_intent -> [specialist agent, routed by intent]
    -> resolution_check -> [respond | escalate]

Run a single test message:
    python -m agent.graph "Where is my order ord_000519?"
"""

import sys

from dotenv import load_dotenv

load_dotenv()  # loads ANTHROPIC_API_KEY (and any other vars) from .env --
                # must happen before any node imports/constructs an LLM client

from langgraph.graph import END, START, StateGraph

from agent.nodes.account_issue_agent import account_issue_agent
from agent.nodes.billing_agent import billing_agent
from agent.nodes.classify_intent import classify_intent, route_by_intent
from agent.nodes.escalation_agent import escalation_agent
from agent.nodes.identify_customer import identify_customer
from agent.nodes.order_status_agent import order_status_agent
from agent.nodes.product_qa_agent import product_qa_agent
from agent.nodes.resolution_check import resolution_check, route_after_resolution
from agent.nodes.returns_refund_agent import returns_refund_agent
from agent.state import AgentState


def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("identify_customer", identify_customer)
    graph.add_node("classify_intent", classify_intent)
    graph.add_node("order_status_agent", order_status_agent)
    graph.add_node("returns_refund_agent", returns_refund_agent)
    graph.add_node("product_qa_agent", product_qa_agent)
    graph.add_node("billing_agent", billing_agent)
    graph.add_node("account_issue_agent", account_issue_agent)
    graph.add_node("resolution_check", resolution_check)
    graph.add_node("escalate", escalation_agent)
    # terminal "respond" node is a no-op passthrough -- the response is
    # already in state by the time we get here; this just gives the graph
    # a clean, explicitly named endpoint for the happy path.
    graph.add_node("respond", lambda state: {})

    graph.add_edge(START, "identify_customer")
    graph.add_edge("identify_customer", "classify_intent")

    graph.add_conditional_edges("classify_intent", route_by_intent, {
        "order_status_agent": "order_status_agent",
        "returns_refund_agent": "returns_refund_agent",
        "product_qa_agent": "product_qa_agent",
        "billing_agent": "billing_agent",
        "account_issue_agent": "account_issue_agent",
        "escalate": "escalate",
    })

    for specialist_node in ["order_status_agent", "returns_refund_agent",
                             "product_qa_agent", "billing_agent", "account_issue_agent"]:
        graph.add_edge(specialist_node, "resolution_check")

    graph.add_conditional_edges("resolution_check", route_after_resolution, {
        "respond": "respond",
        "escalate": "escalate",
    })

    graph.add_edge("respond", END)
    graph.add_edge("escalate", END)

    return graph.compile()


app = build_graph()


def run(user_message: str, customer_id: str = None, session_id: str = "cli-session") -> dict:
    initial_state = {
        "session_id": session_id,
        "customer_id": customer_id,
        "user_message": user_message,
        "conversation_history": [],
        "retrieved_chunks": [],
        "tool_results": {},
        "resolved": False,
        "needs_escalation": False,
        "retry_count": 0,
    }
    return app.invoke(initial_state)


if __name__ == "__main__":
    message = sys.argv[1] if len(sys.argv) > 1 else "Where is my order?"
    cust = sys.argv[2] if len(sys.argv) > 2 else None
    result = run(message, customer_id=cust)

    print(f"\nIntent: {result.get('intent')} (confidence: {result.get('intent_confidence')})")
    print(f"Resolved: {result.get('resolved')} | Escalated: {result.get('needs_escalation')}")
    if result.get("ticket_id"):
        print(f"Ticket: {result['ticket_id']}")
    print(f"\nResponse:\n{result.get('response')}")