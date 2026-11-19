"""
Offline tests for the ShiftGuard graph: approval interrupt / resume, caller scoping in tools, and the SSE stream.
No Gemini, database or SMTP needed: a scripted runnable stands in for the LLM.

    .venv\\Scripts\\python -m pytest tests/test_graph_approval.py -q
"""
import asyncio
import json
import os
import sys

import pytest

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP_DIR)

from langchain_core.messages import AIMessage, ToolMessage  # noqa: E402
from langchain_core.runnables import RunnableLambda  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.types import Command  # noqa: E402

from app.mcp_client.agent import _event_stream, _pending_approval  # noqa: E402
from app.mcp_client.graph import build_shiftguard_agent_graph  # noqa: E402
from services.access_scope import CURRENT_CALLER, Caller  # noqa: E402
from tools.registry import ScopedTool  # noqa: E402

sent: list[str] = []


def whoami() -> str:
    """Return who the tool thinks is asking."""
    caller = CURRENT_CALLER.get()
    return f"caller={caller.employee_id if caller else None} staff={caller.is_staff if caller else None}"


def send_notification_email(input_data: str) -> str:
    """Fake email tool (same name as the real one, so it needs approval)."""
    sent.append(input_data)
    return "sent"


EMAIL_ARGS = {"input_data": json.dumps({"to": ["m@example.com"], "notification_type": "general",
                                        "data": {"subject": "Check in", "message": "Please check in with Priya."}})}


def scripted_llm(script):
    """Runnable returning the next scripted AIMessage on each call."""
    calls = iter(script)
    return RunnableLambda(lambda _messages: next(calls))


def make_graph(script):
    tools = [ScopedTool.from_function(whoami), ScopedTool.from_function(send_notification_email)]
    return build_shiftguard_agent_graph(scripted_llm(script), tools, checkpointer=InMemorySaver(),
                                        approval_required=frozenset({"send_notification_email"}))


def config(thread="t1", staff=False):
    return {"configurable": {"thread_id": thread,
                             "caller": Caller("mgr-1", "Sonia", is_staff=staff, is_manager=True).as_config()}}


def human(text):
    from langchain_core.messages import HumanMessage
    return {"messages": [HumanMessage(content=text)], "session_id": "s", "organization_name": "Bupa"}


def test_scope_reaches_tools():
    graph = make_graph([
        AIMessage(content="", tool_calls=[{"name": "whoami", "args": {}, "id": "c1"}]),
        AIMessage(content="done"),
    ])
    result = asyncio.run(graph.ainvoke(human("who am i"), config()))
    tool_msg = next(m for m in result["messages"] if isinstance(m, ToolMessage))
    assert tool_msg.content == "caller=mgr-1 staff=False"
    assert CURRENT_CALLER.get() is None          # reset after the call


def test_approval_then_approve_runs_tool():
    sent.clear()
    graph = make_graph([
        AIMessage(content="", tool_calls=[{"name": "send_notification_email", "args": EMAIL_ARGS, "id": "e1"}]),
        AIMessage(content="Email sent."),
    ])
    cfg = config("t-approve")
    asyncio.run(graph.ainvoke(human("email the manager"), cfg))
    pending = _pending_approval(asyncio.run(graph.aget_state(cfg)))
    assert pending and pending["actions"][0]["tool"] == "send_notification_email"
    assert pending["actions"][0]["details"]["To"] == "m@example.com"
    assert "check in with Priya" in pending["actions"][0]["preview"]
    assert sent == []                             # nothing sent before approval

    result = asyncio.run(graph.ainvoke(Command(resume={"approved": True}), cfg))
    assert len(sent) == 1
    assert result["messages"][-1].content == "Email sent."
    assert _pending_approval(asyncio.run(graph.aget_state(cfg))) is None


def test_approval_then_decline_skips_tool():
    sent.clear()
    graph = make_graph([
        AIMessage(content="", tool_calls=[{"name": "send_notification_email", "args": EMAIL_ARGS, "id": "e2"}]),
        AIMessage(content="OK, I won't send it."),
    ])
    cfg = config("t-decline")
    asyncio.run(graph.ainvoke(human("email the manager"), cfg))
    result = asyncio.run(graph.ainvoke(Command(resume={"approved": False, "comment": "not now"}), cfg))
    assert sent == []
    declined = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert declined and "declined" in declined[-1].content and "not now" in declined[-1].content
    assert result["messages"][-1].content == "OK, I won't send it."


def test_stream_emits_steps_approval_and_answer():
    graph = make_graph([
        AIMessage(content="", tool_calls=[{"name": "whoami", "args": {}, "id": "w1"}]),
        AIMessage(content="", tool_calls=[{"name": "send_notification_email", "args": EMAIL_ARGS, "id": "e3"}]),
        AIMessage(content="All done."),
    ])
    cfg = config("t-stream")

    async def collect(graph_input):
        return [json.loads(chunk[len("data: "):]) async for chunk in _event_stream(graph, graph_input, cfg)]

    first = asyncio.run(collect(human("check and email")))
    kinds = [e["type"] for e in first]
    assert {"type": "step", "status": "start", "id": "w1", "tool": "whoami", "label": "whoami"} in first
    assert any(e["type"] == "step" and e["status"] == "end" and e["tool"] == "whoami" and e["ok"] for e in first)
    assert "approval" in kinds and kinds[-1] == "done"

    second = asyncio.run(collect(Command(resume={"approved": True})))
    assert any(e["type"] == "step" and e["status"] == "end" and e["tool"] == "send_notification_email" for e in second)
    assert {"type": "message", "text": "All done."} in second


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
