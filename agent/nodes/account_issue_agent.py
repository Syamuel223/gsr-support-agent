"""
Handles account_issue intent: password reset, account details, Prime
membership, and -- critically -- security concerns (unauthorized access,
disputed orders). Per knowledge_base/faqs/account_security_faq.md, any
security-sensitive report must be escalated to a human, never resolved by
the bot alone, and no refund/account change should be processed until a
human has reviewed it.
"""

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from agent.rag_retriever import format_chunks_for_prompt, retrieve
from agent.state import AgentState

SECURITY_CHECK_PROMPT = """Does this customer message describe a security
concern -- unauthorized account access, a disputed/unrecognized order, a
suspected hacked account, or similar? Answer only true or false."""


class SecurityCheck(BaseModel):
    is_security_concern: bool = Field(
        description="True if this involves unauthorized access, a disputed "
                     "order, or suspected account compromise"
    )


ANSWER_PROMPT = """You are a GSR customer support agent handling routine
account questions (password reset, updating details, Prime membership).
Answer using the FAQ context below. Keep responses concise -- 2-4
sentences.

Relevant FAQ excerpts:
{policy_context}
"""


def account_issue_agent(state: AgentState) -> dict:
    from agent.llm import extract_text, get_agent_llm

    llm = get_agent_llm()

    # Security check first, before anything else -- this gate matters more
    # than answering helpfully, per the "escalate immediately" policy rule.
    security_llm = llm.with_structured_output(SecurityCheck)
    check = security_llm.invoke([
        SystemMessage(content=SECURITY_CHECK_PROMPT),
        HumanMessage(content=state["user_message"]),
    ])

    if check.is_security_concern:
        return {
            "response": (
                "I understand this is concerning, and I want to make sure it's "
                "handled carefully. I'm connecting you with a member of our "
                "security team right away who can look into this properly. "
                "In the meantime, please change your password as a precaution."
            ),
            "resolved": False,
            "needs_escalation": True,
            "escalation_reason": "Customer reported a potential account security issue.",
        }

    # Routine account question -- answer via RAG.
    chunks = retrieve(state["user_message"], n_results=2, category="faqs")
    policy_context = format_chunks_for_prompt(chunks)
    response = llm.invoke([
        SystemMessage(content=ANSWER_PROMPT.format(policy_context=policy_context)),
        HumanMessage(content=state["user_message"]),
    ])

    return {
        "response": extract_text(response),
        "retrieved_chunks": chunks,
        "resolved": len(chunks) > 0,
    }
