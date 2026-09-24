"""
Handles billing_payment intent: payment status, double charges, invoices.
Combines RAG (billing FAQ) with a tool call to check the actual payment
record when an order is referenced.
"""


from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.langchain_tools import BILLING_TOOLS
from agent.rag_retriever import format_chunks_for_prompt, retrieve
from agent.state import AgentState


SYSTEM_PROMPT = """You are a GSR customer support agent handling billing
and payment questions. You have tools to check an order's payment status,
plus relevant billing FAQ excerpts below.

Rules:
- If the customer references a specific order, call get_payment_details
  to check the actual payment status rather than assuming.
- For "double charge" complaints, follow the FAQ guidance: reassure the
  customer this is usually a temporary hold, not an actual double charge,
  and that it typically resolves in 24-48 hours -- do not promise an
  immediate refund.
- Keep responses concise and reassuring -- 2-4 sentences.

Relevant billing FAQ excerpts:
{policy_context}
"""


def billing_agent(state: AgentState) -> dict:
    from agent.llm import extract_text, get_agent_llm

    policy_chunks = retrieve(state["user_message"], n_results=2, category="policies")
    policy_context = format_chunks_for_prompt(policy_chunks)

    llm = get_agent_llm()
    llm_with_tools = llm.bind_tools(BILLING_TOOLS)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(policy_context=policy_context)),
        HumanMessage(content=state["user_message"]),
    ]

    tool_results = {}
    response = llm_with_tools.invoke(messages)
    messages.append(response)

    max_rounds = 2
    for _ in range(max_rounds):
        if not getattr(response, "tool_calls", None):
            break
        tools_by_name = {t.name: t for t in BILLING_TOOLS}
        for tool_call in response.tool_calls:
            tool_fn = tools_by_name[tool_call["name"]]
            result = tool_fn.invoke(tool_call["args"])
            tool_results[tool_call["name"]] = result
            messages.append(ToolMessage(content=str(result), tool_call_id=tool_call["id"]))
        response = llm_with_tools.invoke(messages)
        messages.append(response)

    return {
        "response": extract_text(response),
        "tool_results": tool_results,
        "retrieved_chunks": policy_chunks,
        "resolved": True,  # billing explanations are considered resolved unless escalation is explicitly needed
    }
