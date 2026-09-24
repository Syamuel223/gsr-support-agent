"""
Handles product_question and general_policy intents: pure RAG, no
operational tools needed (no account-specific data involved). Grounds
every answer in retrieved policy/FAQ chunks and says so explicitly when
nothing relevant is found rather than answering from the LLM's own
(possibly wrong) assumptions about GSR's policies.
"""


from langchain_core.messages import HumanMessage, SystemMessage

from agent.rag_retriever import format_chunks_for_prompt, retrieve
from agent.state import AgentState


SYSTEM_PROMPT = """You are a GSR customer support agent answering general
policy and product questions. Answer ONLY using the policy context below.
If the context doesn't contain a real answer to the question, say you
don't have that information and offer to connect the customer with a
human agent -- do not make up policy details.

Keep responses concise and friendly -- 2-4 sentences.

Relevant policy/FAQ excerpts:
{policy_context}
"""


def product_qa_agent(state: AgentState) -> dict:
    from agent.history import format_history
    from agent.llm import extract_text, get_agent_llm

    chunks = retrieve(state["user_message"], n_results=3)
    policy_context = format_chunks_for_prompt(chunks)

    history_text = format_history(state.get("conversation_history", []))
    history_context = f"\n\n[Previous conversation:\n{history_text}]" if history_text else ""

    llm = get_agent_llm()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT.format(policy_context=policy_context)),
        HumanMessage(content=state["user_message"] + history_context),
    ]
    response = llm.invoke(messages)

    # Consider it resolved only if we actually found relevant context --
    # an empty/near-empty retrieval means the LLM likely couldn't ground
    # its answer, so route toward escalation instead of a confident guess.
    resolved = len(chunks) > 0 and chunks[0]["distance"] < 1.3

    return {
        "response": extract_text(response),
        "retrieved_chunks": chunks,
        "resolved": resolved,
    }
