"""
Handles order_status intent: where's my order, is it delayed, tracking info.
Uses tool-calling so the LLM decides which order to look up (extracting an
order_id from the message/history) rather than the pipeline hardcoding it.
"""


from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent.langchain_tools import ORDER_STATUS_TOOLS
from agent.state import AgentState


SYSTEM_PROMPT = """You are a GSR customer support agent handling order
status questions. You have tools to look up order status and list a
customer's orders.

Rules:
- Never state a delivery date, status, or delay without having called a
  tool to check it. Do not guess or assume.
- If the customer didn't give an order_id, and they're an identified
  customer, call list_customer_orders first to find their recent orders.
- If you cannot find the order or the customer is not identified and gave
  no order_id, say so clearly and suggest they provide their order ID.
- Keep responses concise and friendly -- 2-4 sentences.
- If the order is delayed or was delivered late, acknowledge it directly
  and apologetically before giving the details.
"""


def order_status_agent(state: AgentState) -> dict:
    from agent.history import format_history
    from agent.llm import extract_text, get_agent_llm

    llm = get_agent_llm()
    llm_with_tools = llm.bind_tools(ORDER_STATUS_TOOLS)

    customer_context = ""
    if state.get("customer_profile"):
        customer_context = f"\n\n[Identified customer: {state['customer_profile']['customer_id']}]"

    history_text = format_history(state.get("conversation_history", []))
    history_context = f"\n\n[Previous conversation:\n{history_text}]" if history_text else ""

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=state["user_message"] + customer_context + history_context),
    ]

    tool_results = {}
    response = llm_with_tools.invoke(messages)
    messages.append(response)

    # simple single-round tool-calling loop (agent can call up to a few
    # tools in sequence, e.g. list orders -> then check one order's status)
    max_rounds = 3
    for _ in range(max_rounds):
        if not getattr(response, "tool_calls", None):
            break
        tools_by_name = {t.name: t for t in ORDER_STATUS_TOOLS}
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
        "resolved": bool(tool_results),  # if we successfully looked something up, consider it resolved
    }
