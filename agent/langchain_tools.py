"""
Wraps mcp_server/tools.py functions as LangChain @tool-decorated functions,
so LangGraph agent nodes can bind them to an LLM for tool-calling.

Design note: the LangGraph pipeline calls these functions directly (in the
same process) rather than going through the MCP protocol, for lower latency
and simpler error handling. The MCP server in mcp_server/server.py exposes
the *same* underlying tools.py functions over MCP separately, so external
MCP clients (Claude Desktop, other agents, etc.) can still connect to GSR's
tools independently. Both paths share one source of truth: tools.py.
"""

from langchain_core.tools import tool

from mcp_server import tools as _tools


@tool
def get_customer_profile(customer_id: str) -> dict:
    """Look up a GSR customer's profile (name, email, city, state, tier) by customer_id."""
    return _tools.get_customer_profile(customer_id)


@tool
def get_order_status(order_id: str) -> dict:
    """Get the current status and delivery details of a specific order, including
    whether it's currently delayed or was delivered late."""
    return _tools.get_order_status(order_id)


@tool
def list_customer_orders(customer_id: str, limit: int = 10) -> dict:
    """List a customer's most recent orders, most recent first."""
    return _tools.list_customer_orders(customer_id, limit)


@tool
def check_return_eligibility(order_id: str, order_item_id: str = None) -> dict:
    """Check whether an order (or a specific item in it) is still eligible for
    return, based on GSR's category-specific return windows. Always call this
    before initiate_refund."""
    return _tools.check_return_eligibility(order_id, order_item_id)


@tool
def initiate_refund(order_id: str, order_item_id: str, reason: str) -> dict:
    """Start a return/refund request for a specific item on an order. Valid
    reasons: defective_item, wrong_item_received, no_longer_needed,
    better_price_found, item_damaged_in_transit, size_issue."""
    return _tools.initiate_refund(order_id, order_item_id, reason)


@tool
def get_payment_details(order_id: str) -> dict:
    """Get the payment method, amount, and status for a specific order's payment."""
    return _tools.get_payment_details(order_id)


@tool
def create_support_ticket(customer_id: str, category: str, priority: str = "medium",
                           order_id: str = None) -> dict:
    """Create a new support ticket. Valid categories: order_status,
    returns_refunds, product_question, billing_payment, account_issue,
    delivery_delay, damaged_item, wrong_item_received. Valid priorities:
    low, medium, high."""
    return _tools.create_support_ticket(customer_id, category, priority, order_id)


@tool
def escalate_to_human(ticket_id: str, context_summary: str) -> dict:
    """Escalate a ticket to a human support agent, with a short summary of the
    conversation so far."""
    return _tools.escalate_to_human(ticket_id, context_summary)


@tool
def register_new_customer(name: str, email: str, city: str = None, state: str = None) -> dict:
    """Register a brand new customer. They become immediately queryable via
    get_customer_profile right after this call -- no batch/refresh delay."""
    return _tools.register_new_customer(name, email, city, state)


@tool
def send_notification(customer_id: str, channel: str, message: str) -> dict:
    """Send a notification to a customer via the given channel (e.g. 'email', 'sms')."""
    return _tools.send_notification(customer_id, channel, message)


# Grouped by which specialist agent typically needs them, so each node only
# binds the tools relevant to its job (smaller tool list = more reliable
# tool selection by the LLM).
ORDER_STATUS_TOOLS = [get_order_status, list_customer_orders]
RETURNS_TOOLS = [check_return_eligibility, initiate_refund, get_order_status, list_customer_orders]
BILLING_TOOLS = [get_payment_details, get_order_status]
ALL_TOOLS = [
    get_customer_profile, get_order_status, list_customer_orders,
    check_return_eligibility, initiate_refund, get_payment_details,
    create_support_ticket, escalate_to_human, register_new_customer,
    send_notification,
]