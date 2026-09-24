"""
Shared state passed between every node in the LangGraph pipeline. Each node
reads what it needs and returns a partial dict of updates -- LangGraph
merges these into the running state automatically.
"""

from typing import Literal, Optional, TypedDict

Intent = Literal[
    "order_status",
    "returns_refunds",
    "product_question",
    "billing_payment",
    "account_issue",
    "general_policy",
    "unclear",
]


class RetrievedChunk(TypedDict):
    text: str
    source_file: str
    section_title: str


class AgentState(TypedDict, total=False):
    # --- input ---
    session_id: str
    customer_id: Optional[str]        # resolved by identify_customer
    user_message: str
    conversation_history: list[dict]  # [{"role": "user"|"assistant", "content": str}]

    # --- routing ---
    intent: Optional[Intent]
    intent_confidence: Optional[float]

    # --- working data gathered by specialist nodes ---
    customer_profile: Optional[dict]
    retrieved_chunks: list[RetrievedChunk]
    tool_results: dict          # e.g. {"get_order_status": {...}, "check_return_eligibility": {...}}

    # --- outcome ---
    response: Optional[str]
    resolved: bool
    needs_escalation: bool
    escalation_reason: Optional[str]
    ticket_id: Optional[str]

    # --- retry/loop control ---
    retry_count: int
