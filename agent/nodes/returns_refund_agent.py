"""
Handles returns_refunds intent: checking eligibility, explaining policy,
and initiating a return when eligible. Combines RAG (policy explanation)
with tool calls (real eligibility checks against the actual order).
"""


from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.langchain_tools import RETURNS_TOOLS
from agent.rag_retriever import format_chunks_for_prompt, retrieve
from agent.state import AgentState


SYSTEM_PROMPT = """You are a GSR customer support agent handling returns
and refunds. You have tools to check return eligibility and initiate a
refund, plus relevant policy excerpts below.

Rules:
- If the customer is identified but didn't give an order_id or which
  order they mean (e.g. "my last order", "the cookware set I bought"),
  call list_customer_orders first to find candidate orders rather than
  asking them to look up and type their order ID -- they're already
  authenticated, so make use of that.
- ALWAYS call check_return_eligibility before telling a customer whether
  they can return something, or before calling initiate_refund. Never
  state eligibility from memory or from the policy text alone -- the
  actual deadline depends on this specific order's delivered_date.
- Only call initiate_refund after the customer has confirmed they want to
  proceed and you've confirmed eligibility.
- If not eligible, explain why clearly (using the policy context below)
  and do not initiate a refund.
- If you truly cannot identify which order/item the customer means after
  checking their order history, ask a specific clarifying question rather
  than a generic "please provide your order ID."
- Keep responses concise and empathetic -- 2-4 sentences.

Relevant policy excerpts:
{policy_context}
"""


def returns_refund_agent(state: AgentState) -> dict:
    from agent.history import format_history
    from agent.llm import extract_text, get_agent_llm

    policy_chunks = retrieve(state["user_message"], n_results=2, category="policies")
    policy_context = format_chunks_for_prompt(policy_chunks)

    llm = get_agent_llm()
    llm_with_tools = llm.bind_tools(RETURNS_TOOLS)

    customer_context = ""
    if state.get("customer_profile"):
        customer_context = f"\n\n[Identified customer: {state['customer_profile']['customer_id']}]"

    history_text = format_history(state.get("conversation_history", []))
    history_context = f"\n\n[Previous conversation:\n{history_text}]" if history_text else ""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(policy_context=policy_context)),
        HumanMessage(content=state["user_message"] + customer_context + history_context),
    ]

    tool_results = {}
    response = llm_with_tools.invoke(messages)
    messages.append(response)

    max_rounds = 3
    for _ in range(max_rounds):
        if not getattr(response, "tool_calls", None):
            break
        tools_by_name = {t.name: t for t in RETURNS_TOOLS}
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
        "resolved": bool(tool_results),
    }
