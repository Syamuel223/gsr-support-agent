"""
GSR MCP server -- exposes the operational-data tools in tools.py over the
Model Context Protocol, so the LangGraph agent (or any MCP-compatible
client) can call them as real actions rather than guessing account data.

Run as a module (recommended -- ensures the tools import resolves correctly
regardless of working directory):
    python -m mcp_server.server
    python -m mcp_server.server --http --port 8765
"""

import argparse

from mcp.server.fastmcp import FastMCP

try:
    from mcp_server import tools
except ImportError:
    # fallback if launched as a plain script from inside mcp_server/
    import tools

mcp = FastMCP("gsr-support-tools")


@mcp.tool()
def get_customer_profile(customer_id: str) -> dict:
    """Look up a GSR customer's profile (name, email, city, state, tier) by customer_id."""
    return tools.get_customer_profile(customer_id)


@mcp.tool()
def get_order_status(order_id: str) -> dict:
    """
    Get the current status and delivery details of a specific order,
    including whether it's currently delayed or was delivered late.
    """
    return tools.get_order_status(order_id)


@mcp.tool()
def list_customer_orders(customer_id: str, limit: int = 10) -> dict:
    """List a customer's most recent orders."""
    return tools.list_customer_orders(customer_id, limit)


@mcp.tool()
def get_payment_details(order_id: str) -> dict:
    """Get the payment method, amount, and status for a specific order's payment."""
    return tools.get_payment_details(order_id)


@mcp.tool()
def check_return_eligibility(order_id: str, order_item_id: str = None) -> dict:
    """
    Check whether an order (or a specific item within it) is still
    eligible for return, based on GSR's category-specific return windows.
    Always call this before initiate_refund.
    """
    return tools.check_return_eligibility(order_id, order_item_id)


@mcp.tool()
def initiate_refund(order_id: str, order_item_id: str, reason: str) -> dict:
    """
    Start a return/refund request for a specific item on an order.
    Re-validates eligibility internally -- will fail if the item is past
    its return window even if the caller didn't check first.
    Valid reasons: defective_item, wrong_item_received, no_longer_needed,
    better_price_found, item_damaged_in_transit, size_issue.
    """
    return tools.initiate_refund(order_id, order_item_id, reason)


@mcp.tool()
def create_support_ticket(customer_id: str, category: str, priority: str = "medium",
                           order_id: str = None) -> dict:
    """
    Create a new support ticket for a customer. Valid categories:
    order_status, returns_refunds, product_question, billing_payment,
    account_issue, delivery_delay, damaged_item, wrong_item_received.
    Valid priorities: low, medium, high.
    """
    return tools.create_support_ticket(customer_id, category, priority, order_id)


@mcp.tool()
def update_ticket(ticket_id: str, status: str) -> dict:
    """Update a support ticket's status (e.g. 'resolved', 'escalated', 'open')."""
    return tools.update_ticket(ticket_id, status)


@mcp.tool()
def escalate_to_human(ticket_id: str, context_summary: str) -> dict:
    """
    Escalate a ticket to a human support agent, with a short summary of
    the conversation so far so the human doesn't have to start from
    scratch. Use this for account security issues, disputes, or anything
    the specialist agents can't resolve confidently.
    """
    return tools.escalate_to_human(ticket_id, context_summary)


@mcp.tool()
def register_new_customer(name: str, email: str, city: str = None, state: str = None) -> dict:
    """
    Register a brand new customer. The customer becomes immediately
    queryable via get_customer_profile right after this call -- no
    batch/refresh delay.
    """
    return tools.register_new_customer(name, email, city, state)


@mcp.tool()
def send_notification(customer_id: str, channel: str, message: str) -> dict:
    """Send a notification to a customer via the given channel (e.g. 'email', 'sms')."""
    return tools.send_notification(customer_id, channel, message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="Run as HTTP server instead of stdio")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.http:
        mcp.run(transport="streamable-http", port=args.port)
    else:
        mcp.run()
