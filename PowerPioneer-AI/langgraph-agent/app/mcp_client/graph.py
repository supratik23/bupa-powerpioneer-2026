import asyncio
import logging
import json
import traceback
import re
from typing import Literal
from langgraph.graph import StateGraph, START, END
from .models import AgentState
from ..prompts.prompt_file import build_tool_agent_context_prompt, build_generic_agent_context_prompt
from config import settings
from langchain.messages import SystemMessage
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, interrupt
from langchain_core.runnables import RunnableConfig
from collections.abc import Sequence
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from ..prompts.prompt_file import system_message_for_tooling_agent, system_message_for_generic_agent
from ..prompts.prompt_file import system_message_for_shiftguard_agent, build_shiftguard_context_prompt


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_agent = None

# Initialize the checkpoint saver for the agent graph short term memory
checkpoint_saver = InMemorySaver()

TOOL_INTENT_PATTERNS = (
    r"\b(search|find|lookup|look up|fetch|show|list|count)\b.*\b(document|member|site|organization|record|data)\b",
    r"\b(create|add)\b.*\b(task|material|record)\b",
    r"\b(task|material)\b.*\b(create|add|record)\b",
    r"\b(send|notify|email|mail)\b.*\b(email|mail|notification|notify)\b",
)


def query_requires_tools(query: str) -> bool:
    """Return whether a request matches one of the registered MCP tool intents."""
    normalized_query = query.casefold().strip()
    return any(re.search(pattern, normalized_query) for pattern in TOOL_INTENT_PATTERNS)


def message_text(content: object) -> str:
    """Extract text from plain or multimodal LangChain message content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and isinstance(block.get("text"), str)
        )
    return ""

async def agent_graph():
    """New Agent State Graph with enhanced tool handling and error management"""
    try:
        # This function is for Langgraph agent with improved features or different structure as needed.

        # AGENT NODE 1: Define the node for AI Agent with tools. This node will handle the interaction with the LLM agent and manage tool usage.
        async def call_agent_with_tools(state: AgentState) -> dict:
            try:
                from app.main import llm_agent_with_tools

                context_message = SystemMessage(content=build_tool_agent_context_prompt(state))
                messages = [context_message, *state.get("messages", [])]
                result = await llm_agent_with_tools.ainvoke({"messages": messages})
                return {"messages": result["messages"], "next_destination": "router"}
            except Exception:
                logger.exception(
                    "Tool agent node failed. session_id=%s organization_id=%s message_count=%s",
                    state.get("session_id"),
                    state.get("organization_id"),
                    len(state.get("messages", [])),
                )
                raise
        
        # AGENT NODE 2: Define the node for another AI Agent without tools. This node will handle the interaction with the LLM agent and manage responses without tool usage.
        async def call_generic_agent(state: AgentState) -> dict:
            try:
                from app.main import generic_llm_agent

                context_message = SystemMessage(content=build_generic_agent_context_prompt(state))
                messages = [context_message, *state.get("messages", [])]
                result = await generic_llm_agent.ainvoke({"messages": messages})
                return {"messages": result["messages"], "next_destination": "router"}
            except Exception:
                logger.exception(
                    "Generic agent node failed. session_id=%s organization_id=%s message_count=%s",
                    state.get("session_id"),
                    state.get("organization_id"),
                    len(state.get("messages", [])),
                )
                raise

        # Define a function to fetch the list of available tools from the main application context.
        def get_tools() -> list:
            from app.main import available_tools
            return available_tools

        # ROUTER NODE: This node will handle the routing of requests based on the presence of tools.
        async def router_node(state: AgentState) -> str:
            """Route by deterministic intent instead of relying on an LLM classification response."""
            try:
                messages = state.get("messages", [])
                last_message = messages[-1] if messages else None
                query = message_text(getattr(last_message, "content", "")) if last_message else ""
                needs_tools = query_requires_tools(query)

                if needs_tools and not settings.OLLAMA_SUPPORTS_TOOLS:
                    raise RuntimeError(
                        f"The configured Ollama model '{settings.OLLAMA_MODEL}' is marked as not supporting tool calls. "
                        "Use a tool-capable model or set OLLAMA_SUPPORTS_TOOLS=true."
                    )

                destination = "internal_agent_node" if needs_tools else "generic_agent_node"
                logger.info("Routing request to %s. needs_tools=%s query=%r", destination, needs_tools, query)
                return {"next_destination": destination}
            except Exception:
                logger.exception(
                    "Router node failed. session_id=%s organization_id=%s message_count=%s",
                    state.get("session_id"),
                    state.get("organization_id"),
                    len(state.get("messages", [])),
                )
                raise

        async def route_next(state: AgentState) -> Literal["internal_agent_node", "generic_agent_node"]:
            return state["next_destination"]

        workflow = StateGraph(AgentState)

        tool_node = ToolNode(get_tools(), handle_tool_errors="When creating the tool node, an error occurred: {error}. Please check the tool configuration and availability.")
        workflow.add_node("llm_agent_node", call_agent_with_tools)
        workflow.add_node("generic_agent_node", call_generic_agent)
        workflow.add_node("router", router_node)
        workflow.add_node("tools", tool_node)

        workflow.add_edge(START, "router")

        workflow.add_conditional_edges("router", route_next, {"internal_agent_node": "llm_agent_node", "generic_agent_node": "generic_agent_node"})
        workflow.add_conditional_edges("llm_agent_node", tools_condition)
        workflow.add_edge("tools", "llm_agent_node")

        workflow.add_edge("generic_agent_node", END)

        return workflow.compile(checkpointer=checkpoint_saver)
    except Exception as exc:
        logger.exception("Failed to build agent graph. available_tools=%s", len(get_tools()))
        raise RuntimeError(f"Failed to build agent graph: {exc}") from exc

def without_tool_traffic(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """
    Drop tool calls / tool results from the history. Used for the generic agent, which has no tools bound:
    Gemini rejects function-call parts when no matching function declarations are supplied.
    """
    cleaned: list[AnyMessage] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            continue
        if isinstance(message, AIMessage) and message.tool_calls:
            text = message_text(message.content)
            if text.strip():
                cleaned.append(AIMessage(content=text))
            continue
        cleaned.append(message)
    return cleaned


def build_gemini_agent_graph(
    llm: BaseChatModel,
    llm_with_tools: Runnable,
    tools: Sequence[BaseTool],
    checkpointer=None,
):
    """
    Agent State Graph for the Gemini LLM with a native LangGraph tool loop:

        START -> router -> tool_agent_node <-> tools -> END
                        -> generic_agent_node -> END

    :param llm: plain Gemini chat model, used by the generic agent (no tools).
    :param llm_with_tools: Gemini chat model with the MCP tools bound (get_gemini_llm_with_tools).
    :param tools: the MCP tools executed by the ToolNode.
    :param checkpointer: short-term memory saver; defaults to the module level InMemorySaver.
    """
    try:
        # ROUTER NODE: deterministic intent routing on the latest user message.
        async def router_node(state: AgentState) -> dict:
            messages = state.get("messages", [])
            last_human = next((m for m in reversed(messages) if isinstance(m, HumanMessage)), None)
            query = message_text(last_human.content) if last_human else ""
            needs_tools = bool(tools) and query_requires_tools(query)
            destination = "tool_agent_node" if needs_tools else "generic_agent_node"
            logger.info("Routing request to %s. needs_tools=%s query=%r", destination, needs_tools, query)
            return {"next_destination": destination}

        def route_next(state: AgentState) -> Literal["tool_agent_node", "generic_agent_node"]:
            return state.get("next_destination") or "generic_agent_node"

        # AGENT NODE 1: Gemini with tools bound. Emits tool calls that are executed by the ToolNode.
        async def tool_agent_node(state: AgentState) -> dict:
            try:
                system = SystemMessage(
                    content=f"{system_message_for_tooling_agent}\n\n{build_tool_agent_context_prompt(state)}"
                )
                response = await llm_with_tools.ainvoke([system, *state.get("messages", [])])
                return {"messages": [response]}
            except Exception:
                logger.exception(
                    "Tool agent node failed. session_id=%s organization_id=%s message_count=%s",
                    state.get("session_id"), state.get("organization_id"), len(state.get("messages", [])),
                )
                raise

        # AGENT NODE 2: Gemini without tools.
        async def generic_agent_node(state: AgentState) -> dict:
            try:
                system = SystemMessage(
                    content=f"{system_message_for_generic_agent}\n\n{build_generic_agent_context_prompt(state)}"
                )
                history = without_tool_traffic(state.get("messages", []))
                response = await llm.ainvoke([system, *history])
                return {"messages": [response]}
            except Exception:
                logger.exception(
                    "Generic agent node failed. session_id=%s organization_id=%s message_count=%s",
                    state.get("session_id"), state.get("organization_id"), len(state.get("messages", [])),
                )
                raise

        workflow = StateGraph(AgentState)
        workflow.add_node("router", router_node)
        workflow.add_node("tool_agent_node", tool_agent_node)
        workflow.add_node("generic_agent_node", generic_agent_node)
        workflow.add_node("tools", ToolNode(list(tools), handle_tool_errors=True))

        workflow.add_edge(START, "router")
        workflow.add_conditional_edges(
            "router", route_next, {"tool_agent_node": "tool_agent_node", "generic_agent_node": "generic_agent_node"}
        )
        # tools_condition returns "tools" when the last AIMessage has tool calls, otherwise END.
        workflow.add_conditional_edges("tool_agent_node", tools_condition, {"tools": "tools", END: END})
        workflow.add_edge("tools", "tool_agent_node")
        workflow.add_edge("generic_agent_node", END)

        graph = workflow.compile(checkpointer=checkpointer or checkpoint_saver)
        logger.info("Gemini agent graph compiled with %d tools.", len(tools))
        return graph
    except Exception as exc:
        logger.exception("Failed to build Gemini agent graph.")
        raise RuntimeError(f"Failed to build Gemini agent graph: {exc}") from exc


def build_shiftguard_agent_graph(
    llm_with_tools: Runnable,
    tools: Sequence[BaseTool],
    checkpointer=None,
    approval_required: frozenset[str] | set[str] = frozenset(),
):
    """
    ShiftGuard agent graph. No keyword router: every request goes to Gemini with all tools bound, and the LLM
    decides which tool(s) to call (or answers directly). Outward / hard-to-undo tool calls (approval_required) pause
    at approval_gate (LangGraph interrupt) until the manager approves or declines them:

        START -> shiftguard_agent_node
        shiftguard_agent_node -> approval_gate            (the model asked for tools)
        shiftguard_agent_node -> END                      (final answer)
        approval_gate         -> tools                    (approved, or nothing needed approval)
        approval_gate         -> shiftguard_agent_node    (declined: a ToolMessage per call says so)
        tools                 -> shiftguard_agent_node
    """
    from .approval import describe_action

    try:
        async def shiftguard_agent_node(state: AgentState, config: RunnableConfig) -> dict:
            try:
                caller = (config.get("configurable") or {}).get("caller")
                system = SystemMessage(
                    content=f"{system_message_for_shiftguard_agent}\n\n{build_shiftguard_context_prompt(state, caller)}"
                )
                response = await llm_with_tools.ainvoke([system, *state.get("messages", [])], config)
                if getattr(response, "tool_calls", None):
                    logger.info("Gemini selected tools: %s", [call["name"] for call in response.tool_calls])
                return {"messages": [response]}
            except Exception:
                logger.exception(
                    "ShiftGuard agent node failed. session_id=%s organization_id=%s message_count=%s",
                    state.get("session_id"), state.get("organization_id"), len(state.get("messages", [])),
                )
                raise

        async def approval_gate(state: AgentState) -> Command:
            last = state["messages"][-1]
            calls = list(getattr(last, "tool_calls", None) or [])
            sensitive = [c for c in calls if c["name"] in approval_required]
            if not sensitive:
                return Command(goto="tools")

            actions = []
            for call in sensitive:
                described = await asyncio.to_thread(describe_action, call["name"], call.get("args") or {})
                actions.append({"id": call["id"], **described})
            # Pauses the run here. On resume, interrupt() returns the manager's decision and this node re-runs.
            decision = interrupt({"type": "approval", "actions": actions})
            if isinstance(decision, dict):
                approved, comment = bool(decision.get("approved")), str(decision.get("comment") or "").strip()
            else:
                approved, comment = bool(decision), ""
            if approved:
                logger.info("Manager approved %s", [c["name"] for c in sensitive])
                return Command(goto="tools")

            logger.info("Manager declined %s", [c["name"] for c in sensitive])
            note = f" Their note: {comment}" if comment else ""
            declined = [
                ToolMessage(
                    content=(f"Not done: the manager declined this action.{note} Do not retry it unless they ask."
                             if c["name"] in approval_required else
                             "Not run: the manager declined a related action in the same step."),
                    tool_call_id=c["id"], name=c["name"], status="error",
                )
                for c in calls
            ]
            return Command(goto="shiftguard_agent_node", update={"messages": declined})

        def after_agent(state: AgentState) -> Literal["approval_gate", "__end__"]:
            last = state["messages"][-1]
            return "approval_gate" if getattr(last, "tool_calls", None) else END

        workflow = StateGraph(AgentState)
        workflow.add_node("shiftguard_agent_node", shiftguard_agent_node)
        workflow.add_node("approval_gate", approval_gate, destinations=("tools", "shiftguard_agent_node"))
        workflow.add_node("tools", ToolNode(list(tools), handle_tool_errors=True))
        workflow.add_edge(START, "shiftguard_agent_node")
        workflow.add_conditional_edges("shiftguard_agent_node", after_agent, {"approval_gate": "approval_gate", END: END})
        workflow.add_edge("tools", "shiftguard_agent_node")

        graph = workflow.compile(checkpointer=checkpointer or checkpoint_saver)
        logger.info("ShiftGuard agent graph compiled with %d tools (%d need approval).", len(tools),
                    len([t for t in tools if t.name in approval_required]))
        return graph
    except Exception as exc:
        logger.exception("Failed to build ShiftGuard agent graph.")
        raise RuntimeError(f"Failed to build ShiftGuard agent graph: {exc}") from exc


async def get_agent_graph():
    """Get the agent instance"""
    global _agent
    try:
        if _agent is None:
            logger.info("Agent graph is not initialized; building it now.")
            # Previous graph (create_agent based, Ollama/OpenAI): _agent = await agent_graph()
            # Previous Gemini graph with keyword routing: _agent = build_gemini_agent_graph(llm, llm_with_tools, available_tools)
            from app.main import llm_with_tools, available_tools, approval_required_tools
            _agent = build_shiftguard_agent_graph(llm_with_tools, available_tools,
                                                  approval_required=approval_required_tools)
        return _agent
    except Exception:
        logger.exception("Unable to initialize or retrieve the agent graph.")
        raise


