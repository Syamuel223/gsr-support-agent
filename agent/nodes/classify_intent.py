"""
Classifies the customer's message into one of the Intent categories in
state.py, so the graph's conditional edge can route to the right
specialist node. Uses a small/cheap model since this is a simple
classification task, not something requiring deep reasoning.
"""

from pydantic import BaseModel, Field

from agent.state import AgentState, Intent

SYSTEM_PROMPT = """You are an intent classifier for GSR, an e-commerce
company's customer support system. Classify the customer's message into
exactly one of these categories:

- order_status: questions about where an order is, delivery timing, tracking
- returns_refunds: wanting to return an item, refund status, exchange
- product_question: questions about a product's features, availability, specs
- billing_payment: payment failures, double charges, invoices, EMI questions
- account_issue: password reset, account security, suspicious activity,
  updating account details, Prime membership
- general_policy: broad policy questions not tied to a specific order
  (e.g. "what's your return policy")
- unclear: message is too vague/ambiguous to classify confidently, or is
  unrelated to customer support entirely

If recent conversation history is provided, use it to interpret follow-up
messages correctly (e.g. "yes please" after the agent offered to check
something is NOT unclear -- classify based on what's actually being asked).

Respond with only the category label, nothing else."""


class IntentClassification(BaseModel):
    intent: Intent = Field(description="One of the defined intent categories")
    confidence: float = Field(description="Confidence from 0.0 to 1.0", ge=0.0, le=1.0)


def classify_intent(state: AgentState) -> dict:
    from langchain_core.prompts import ChatPromptTemplate

    from agent.history import format_history
    from agent.llm import get_classify_llm

    llm = get_classify_llm()
    structured_llm = llm.with_structured_output(IntentClassification)

    history_text = format_history(state.get("conversation_history", []))
    message = state["user_message"]
    if history_text:
        message = f"Previous conversation:\n{history_text}\n\nLatest message: {message}"

    prompt = ChatPromptTemplate.from_messages([
        ("system", SYSTEM_PROMPT),
        ("human", "{message}"),
    ])
    chain = prompt | structured_llm

    result: IntentClassification = chain.invoke({"message": message})

    return {
        "intent": result.intent,
        "intent_confidence": result.confidence,
    }


def route_by_intent(state: AgentState) -> str:
    """Conditional edge function -- returns the name of the next node."""
    intent = state.get("intent", "unclear")
    # Low-confidence classifications get routed to escalation rather than
    # guessed at by a specialist that might handle it wrong.
    if state.get("intent_confidence", 1.0) < 0.5:
        return "escalate"
    return {
        "order_status": "order_status_agent",
        "returns_refunds": "returns_refund_agent",
        "product_question": "product_qa_agent",
        "billing_payment": "billing_agent",
        "account_issue": "account_issue_agent",
        "general_policy": "product_qa_agent",  # policy Qs reuse the RAG-only agent
        "unclear": "escalate",
    }.get(intent, "escalate")
