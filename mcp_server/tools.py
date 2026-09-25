"""
The actual tool implementations backing the GSR MCP server. Each function
here queries the live operational DuckDB warehouse (never guesses account
data) and returns plain dicts/lists that server.py wraps as MCP tools.

Kept separate from server.py so this logic can be unit tested without the
MCP protocol layer in the way. Uses con.execute(sql, params).fetchall() /
.fetchone() throughout -- the standard DB-API-style parameter binding that
DuckDB (and sqlite3, used in local tests) both support reliably, rather
than relying on con.sql(..., params=...) which behaves inconsistently
across DuckDB versions.
"""

import random
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import duckdb

DB_PATH = Path(__file__).parent.parent / "data" / "gsr.duckdb"

# Category-specific return windows, in days from delivered_date.
# Mirrors knowledge_base/policies/return_refund_policy.md -- keep these in
# sync if the policy doc changes.
RETURN_WINDOW_DAYS = {
    "electronics": 10,
    "fashion": 15,
    "home_kitchen": 7,
    "books": 7,
    "beauty_personal_care": 7,
}
DEFAULT_RETURN_WINDOW_DAYS = 7


def _connect():
    return duckdb.connect(str(DB_PATH), read_only=False)


def _run_write_with_retry(fn, max_retries: int = 5):
    """
    DuckDB is a single-writer embedded database, and every tool call here
    opens its own short-lived connection -- fine for reads (which can run
    concurrently), but under real concurrent load (many users triggering
    refunds/tickets/signups at once), two write connections can briefly
    contend for the same file lock. Rather than pretending this can't
    happen, retry with jittered backoff on lock-related errors, which
    covers realistic concurrency for a demo/portfolio deployment.

    This is a mitigation, not a fix: DuckDB isn't built for high
    concurrent write throughput the way Postgres is. The honest
    production answer is migrating the operational tables to Postgres
    (the RAG/analytical side can stay on DuckDB/Chroma) once real
    concurrent write volume is expected -- noted in the README.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            return fn()
        except duckdb.Error as e:
            last_error = e
            if "lock" not in str(e).lower():
                raise  # not a concurrency issue -- don't mask a real bug by retrying it
            time.sleep(0.05 * (2 ** attempt) + random.uniform(0, 0.05))
    raise last_error


def get_customer_profile(customer_id: str) -> dict:
    """Look up a customer's profile by customer_id."""
    con = _connect()
    row = con.execute(
        """
        SELECT customer_id, name, email, city, state, signup_date, tier
        FROM customers WHERE customer_id = ?
        """,
        [customer_id],
    ).fetchone()
    con.close()
    if not row:
        return {"found": False, "error": f"No customer found with id {customer_id}"}
    cols = ["customer_id", "name", "email", "city", "state", "signup_date", "tier"]
    return {"found": True, **dict(zip(cols, row))}


def get_order_status(order_id: str) -> dict:
    """Get the current status and delivery details of a specific order."""
    con = _connect()
    row = con.execute(
        """
        SELECT order_id, customer_id, order_date, status,
               estimated_delivery_date, delivered_date
        FROM orders WHERE order_id = ?
        """,
        [order_id],
    ).fetchone()
    con.close()
    if not row:
        return {"found": False, "error": f"No order found with id {order_id}"}
    cols = ["order_id", "customer_id", "order_date", "status",
            "estimated_delivery_date", "delivered_date"]
    result = dict(zip(cols, row))

    # Compute delay flags server-side -- the agent should never eyeball
    # dates itself, per the value-grounding lesson from the BI project.
    now = datetime.now()
    if result["status"] not in ("delivered", "cancelled", "returned"):
        result["is_delayed"] = now > result["estimated_delivery_date"]
    elif result["status"] == "delivered" and result["delivered_date"]:
        result["was_late"] = result["delivered_date"] > result["estimated_delivery_date"]
    return {"found": True, **result}


def list_customer_orders(customer_id: str, limit: int = 10) -> dict:
    """List a customer's recent orders, most recent first."""
    con = _connect()
    rows = con.execute(
        """
        SELECT order_id, order_date, status, estimated_delivery_date, delivered_date
        FROM orders WHERE customer_id = ?
        ORDER BY order_date DESC LIMIT ?
        """,
        [customer_id, limit],
    ).fetchall()
    con.close()
    cols = ["order_id", "order_date", "status", "estimated_delivery_date", "delivered_date"]
    orders = [dict(zip(cols, r)) for r in rows]
    return {"customer_id": customer_id, "order_count": len(orders), "orders": orders}


def get_payment_details(order_id: str) -> dict:
    """Get payment method, amount, and status for a specific order."""
    con = _connect()
    row = con.execute(
        """
        SELECT payment_id, order_id, payment_method, amount, status
        FROM payments WHERE order_id = ?
        """,
        [order_id],
    ).fetchone()
    con.close()
    if not row:
        return {"found": False, "error": f"No payment record found for order {order_id}"}
    cols = ["payment_id", "order_id", "payment_method", "amount", "status"]
    return {"found": True, **dict(zip(cols, row))}


def check_return_eligibility(order_id: str, order_item_id: str = None) -> dict:
    """
    Check whether an order (or a specific item in it) is still eligible
    for return, based on category-specific return windows.
    """
    con = _connect()
    order = con.execute(
        "SELECT status, delivered_date FROM orders WHERE order_id = ?",
        [order_id],
    ).fetchone()
    if not order:
        con.close()
        return {"eligible": False, "reason": f"No order found with id {order_id}"}

    status, delivered_date = order
    if status != "delivered":
        con.close()
        return {
            "eligible": False,
            "reason": f"Order status is '{status}', not 'delivered' -- "
                      f"only delivered orders can be returned.",
        }

    item_query = """
        SELECT oi.order_item_id, p.product_name, p.category
        FROM order_items oi JOIN products p ON oi.product_id = p.product_id
        WHERE oi.order_id = ?
    """
    params = [order_id]
    if order_item_id:
        item_query += " AND oi.order_item_id = ?"
        params.append(order_item_id)
    items = con.execute(item_query, params).fetchall()
    con.close()

    if not items:
        return {"eligible": False, "reason": "No matching item found on this order."}

    now = datetime.now()
    results = []
    for item_id, product_name, category in items:
        window_days = RETURN_WINDOW_DAYS.get(category, DEFAULT_RETURN_WINDOW_DAYS)
        deadline = delivered_date + timedelta(days=window_days)
        eligible = now <= deadline
        results.append({
            "order_item_id": item_id,
            "product_name": product_name,
            "category": category,
            "return_window_days": window_days,
            "deadline": deadline.isoformat(),
            "eligible": eligible,
        })
    return {"order_id": order_id, "items": results}


def initiate_refund(order_id: str, order_item_id: str, reason: str) -> dict:
    """
    Create a return/refund request for a specific item. Always checks
    eligibility first (via check_return_eligibility) rather than trusting
    the caller -- an agent should call check_return_eligibility itself
    before this, but this function enforces it regardless.
    """
    eligibility = check_return_eligibility(order_id, order_item_id)
    if "items" not in eligibility or not eligibility["items"]:
        return {"success": False, "error": eligibility.get("reason", "Item not eligible")}
    item_check = eligibility["items"][0]
    if not item_check["eligible"]:
        return {
            "success": False,
            "error": f"Item is past its {item_check['return_window_days']}-day return "
                     f"window (deadline was {item_check['deadline']}).",
        }

    return_id = f"ret_{uuid.uuid4().hex[:8]}"

    def _write():
        con = _connect()
        try:
            con.execute(
                """
                INSERT INTO returns (return_id, order_id, order_item_id, reason, status, requested_at)
                VALUES (?, ?, ?, ?, 'requested', ?)
                """,
                [return_id, order_id, order_item_id, reason, datetime.now()],
            )
        finally:
            con.close()

    _run_write_with_retry(_write)
    return {"success": True, "return_id": return_id, "status": "requested"}


def create_support_ticket(customer_id: str, category: str, priority: str = "medium",
                           order_id: str = None) -> dict:
    """Create a new support ticket for a customer."""
    ticket_id = f"tkt_{uuid.uuid4().hex[:8]}"

    def _write():
        con = _connect()
        try:
            con.execute(
                """
                INSERT INTO tickets (ticket_id, customer_id, order_id, category, priority, status, created_at, resolved_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?, NULL)
                """,
                [ticket_id, customer_id, order_id, category, priority, datetime.now()],
            )
        finally:
            con.close()

    _run_write_with_retry(_write)
    return {"success": True, "ticket_id": ticket_id, "status": "open"}


def update_ticket(ticket_id: str, status: str) -> dict:
    """Update a ticket's status (e.g. to 'resolved' or 'escalated')."""
    resolved_at = datetime.now() if status == "resolved" else None

    def _write():
        con = _connect()
        try:
            con.execute(
                """
                UPDATE tickets SET status = ?, resolved_at = COALESCE(?, resolved_at)
                WHERE ticket_id = ?
                """,
                [status, resolved_at, ticket_id],
            )
            return con.execute(
                "SELECT ticket_id FROM tickets WHERE ticket_id = ?", [ticket_id]
            ).fetchone()
        finally:
            con.close()

    row = _run_write_with_retry(_write)
    if not row:
        return {"success": False, "error": f"No ticket found with id {ticket_id}"}
    return {"success": True, "ticket_id": ticket_id, "status": status}


def escalate_to_human(ticket_id: str, context_summary: str) -> dict:
    """
    Escalate a ticket to a human agent with a summary of what's been
    discussed so far. In production this would notify a real queue
    (Slack/Zendesk); here it just updates the ticket status.
    """
    result = update_ticket(ticket_id, "escalated")
    if not result["success"]:
        return result
    # In a real system: push context_summary to a human-agent queue/tool here.
    return {"success": True, "ticket_id": ticket_id, "escalated": True,
             "context_summary": context_summary}


def register_new_customer(name: str, email: str, city: str = None, state: str = None) -> dict:
    """
    Register a brand new customer. This is what the real-time signup
    webhook calls -- the customer is queryable immediately afterward,
    with no batch/refresh delay.
    """
    customer_id = f"cust_{uuid.uuid4().hex[:8]}"

    def _write():
        con = _connect()
        try:
            con.execute(
                """
                INSERT INTO customers (customer_id, name, email, city, state, signup_date, tier)
                VALUES (?, ?, ?, ?, ?, ?, 'regular')
                """,
                [customer_id, name, email, city, state, datetime.now()],
            )
        finally:
            con.close()

    _run_write_with_retry(_write)
    return {"success": True, "customer_id": customer_id}


def send_notification(customer_id: str, channel: str, message: str) -> dict:
    """
    Send a notification to a customer. Stubbed for this project -- logs
    the notification instead of actually sending email/SMS, but keeps
    the same interface an agent would call in production.
    """
    print(f"[NOTIFY:{channel}] to {customer_id}: {message}")
    return {"success": True, "channel": channel, "sent": True}
