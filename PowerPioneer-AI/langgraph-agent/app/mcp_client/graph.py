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


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
_agent = None

# Initialize the checkpoint saver for the agent graph short term memory
checkpoint_saver = InMemorySaver()

TOOL_INTENT_PATTERNS = (
    r"\b(search|find|lookup|look up|fetch|show|list|count)\b.*\b(document|member|site|organization|record|data)\b",
    r"\b(create|add)\b.*\b(task|material|record)\b",
    r"\b(task|material)\b.*\b(create|add|record)\b",
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

async def get_agent_graph():
    """Get the agent instance"""
    global _agent
    try:
        if _agent is None:
            logger.info("Agent graph is not initialized; building it now.")
            _agent = await agent_graph()
        return _agent
    except Exception:
        logger.exception("Unable to initialize or retrieve the agent graph.")
        raise


