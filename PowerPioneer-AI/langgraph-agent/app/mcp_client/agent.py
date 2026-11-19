"""
Chat agent API (managers and HR).

POST /agent/stream   Server-Sent Events: live tool steps, answer tokens, approval requests, the final answer.
POST /agent/invoke   Same agent, one JSON response (Swagger / curl / tests).

Both take a new question ({"query": ...}) or the manager's decision on a paused action
({"resume": {"approved": true|false, "comment": "..."}}) for the same session_id.

Auth: the Django access token (Authorization: Bearer ...) is checked with Django /auth/me/. Only staff and managers
(people with direct reports) may use the agent; managers only see their own team. AGENT_REQUIRE_AUTH=false allows
calls without a token for local testing (treated as staff).
"""
import asyncio
import base64
import json
import logging
import time
import traceback
import uuid
from types import NoneType

import httpx
from fastapi import APIRouter, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse
from langchain.messages import AIMessage, HumanMessage
from langchain_core.messages import AIMessageChunk, ToolMessage
from langgraph.types import Command
from pydantic import BaseModel

from config import settings
from services.access_scope import Caller
from .graph import get_agent_graph, message_text
from .models import AgentRequest, AgentResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
agent_router = APIRouter()

CALLER_CACHE_SECONDS = 120
_caller_cache: dict[str, tuple[Caller, float]] = {}
AUTO_DECLINE = {"approved": False, "comment": "Not approved - the manager asked something else instead."}


# ---------------------------------------------------------------------------------------------------------
# who is asking
# ---------------------------------------------------------------------------------------------------------
def _has_reports(employee_id: str) -> bool:
    from services.db_service import SupabaseDBConnectionManager

    with SupabaseDBConnectionManager() as db:
        row = db.fetch_one("SELECT count(*) AS n FROM employee WHERE manager_employee_id = %s AND is_active",
                           (employee_id,))
    return bool(row and row["n"])


def resolve_agent_caller(authorization: str | None) -> Caller:
    """Verify the Django token and return the caller. Raises HTTPException 401/403/502/503."""
    if authorization and authorization.lower().startswith("bearer "):
        cached = _caller_cache.get(authorization)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        try:
            res = httpx.get(f"{settings.BACKEND_API_BASE_URL.rstrip('/')}/auth/me/",
                            headers={"Authorization": authorization, "Accept": "application/json"}, timeout=10)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"Cannot reach the backend to verify the login: {e}") from e
        if res.status_code in (401, 403):
            raise HTTPException(401, "Login expired or invalid. Please sign in again.")
        if res.status_code != 200:
            raise HTTPException(502, f"Backend login check failed ({res.status_code}).")
        me = res.json()
        employee_id = str(me.get("employee_id") or "")
        if not employee_id:
            raise HTTPException(502, "Backend did not return the employee id.")
        is_staff = bool(me.get("is_staff") or me.get("is_superuser"))
        caller = Caller(employee_id, f"{me.get('first_name') or ''} {me.get('last_name') or ''}".strip(),
                        is_staff, is_staff or _has_reports(employee_id))
        if not (caller.is_staff or caller.is_manager):
            raise HTTPException(403, "The ShiftGuard assistant is available to managers and HR.")
        if len(_caller_cache) > 1000:
            _caller_cache.clear()
        _caller_cache[authorization] = (caller, time.monotonic() + CALLER_CACHE_SECONDS)
        return caller
    if settings.AGENT_REQUIRE_AUTH:
        raise HTTPException(401, "Missing Authorization: Bearer <access token>.")
    return Caller("local-tester", "Local tester", is_staff=True, is_manager=True)


async def resolve_caller_async(authorization: str | None) -> Caller:
    return await asyncio.to_thread(resolve_agent_caller, authorization)


def _run_config(caller: Caller, session_id: str) -> dict:
    # The thread is per caller, so nobody can resume or read someone else's conversation.
    return {"configurable": {"thread_id": f"{caller.employee_id}:{session_id}", "caller": caller.as_config()},
            "recursion_limit": 40}


def _pending_approval(snapshot) -> dict | None:
    for item in getattr(snapshot, "interrupts", None) or ():
        value = getattr(item, "value", None)
        if isinstance(value, dict) and value.get("type") == "approval":
            return value
    return None


async def _graph_input(graph, config: dict, query, resume: dict | None, state_fields: dict):
    """A resume Command, or a new question (auto-declining any action still waiting for approval)."""
    if resume is not None:
        if not _pending_approval(await graph.aget_state(config)):
            raise HTTPException(409, "There is no action waiting for approval in this session.")
        return Command(resume={"approved": bool(resume.get("approved")), "comment": str(resume.get("comment") or "")})
    if not query:
        raise HTTPException(400, "Send a query or a resume decision.")
    if _pending_approval(await graph.aget_state(config)):
        await graph.ainvoke(Command(resume=AUTO_DECLINE), config)
    return {"messages": [HumanMessage(content=query, id=str(uuid.uuid4()))], **state_fields}


def _final_text(snapshot) -> str:
    for message in reversed((getattr(snapshot, "values", None) or {}).get("messages", [])):
        if isinstance(message, AIMessage) and not message.tool_calls:
            text = getattr(message, "text", None)
            text = text if isinstance(text, str) else message_text(message.content)
            if text and text.strip():
                return text.strip()
        if isinstance(message, HumanMessage):
            break
    return "No response generated by the agent."


# ---------------------------------------------------------------------------------------------------------
# streaming
# ---------------------------------------------------------------------------------------------------------
class StreamRequest(BaseModel):
    session_id: str
    query: str | None = None
    resume: dict | None = None          # {"approved": bool, "comment": str}
    organization_name: str | None = "Bupa"


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, default=str)}\n\n"


def _tool_ok(message: ToolMessage) -> bool:
    text = message.content if isinstance(message.content, str) else message_text(message.content)
    return getattr(message, "status", "success") != "error" and not text.lstrip().startswith(("Error", "Skipped"))


async def _event_stream(graph, graph_input, config: dict):
    from tools.registry import TOOL_LABELS

    try:
        async for mode, chunk in graph.astream(graph_input, config, stream_mode=["updates", "messages"]):
            if mode == "messages":
                message, meta = chunk
                if meta.get("langgraph_node") == "shiftguard_agent_node" and isinstance(message, AIMessageChunk):
                    text = message_text(message.content)
                    if text:
                        yield _sse({"type": "token", "text": text})
                continue
            for node, update in (chunk or {}).items():
                if node.startswith("__") or not isinstance(update, dict):
                    continue
                for message in update.get("messages", []) or []:
                    if isinstance(message, AIMessage) and message.tool_calls:
                        yield _sse({"type": "thinking_reset"})     # text so far was preamble, not the answer
                        for call in message.tool_calls:
                            yield _sse({"type": "step", "status": "start", "id": call["id"], "tool": call["name"],
                                        "label": TOOL_LABELS.get(call["name"], call["name"].replace("_", " "))})
                    elif isinstance(message, ToolMessage):
                        declined = node == "approval_gate"
                        yield _sse({"type": "step", "status": "declined" if declined else "end",
                                    "id": message.tool_call_id, "tool": message.name,
                                    "ok": (not declined) and _tool_ok(message)})
        snapshot = await graph.aget_state(config)
        pending = _pending_approval(snapshot)
        if pending:
            yield _sse({"type": "approval", "actions": pending["actions"]})
        else:
            yield _sse({"type": "message", "text": _final_text(snapshot)})
    except Exception as e:
        logger.exception("Agent stream failed")
        yield _sse({"type": "error", "message": f"The assistant hit a problem: {e}"})
    yield _sse({"type": "done"})


@agent_router.post("/stream")
async def stream_request(body: StreamRequest, authorization: str | None = Header(default=None)):
    """Stream one agent turn as Server-Sent Events (step / token / approval / message / error / done)."""
    caller = await resolve_caller_async(authorization)
    graph = await get_agent_graph()
    config = _run_config(caller, body.session_id)
    graph_input = await _graph_input(graph, config, (body.query or "").strip() or None, body.resume, {
        "organization_id": "bupa", "organization_name": body.organization_name, "session_id": body.session_id,
        "user_id": caller.employee_id,
    })
    return StreamingResponse(_event_stream(graph, graph_input, config), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------------------------------------
# one-shot JSON
# ---------------------------------------------------------------------------------------------------------
@agent_router.post("/invoke", response_model=AgentResponse)
async def invoke_request(
    request: Request,
    query: str | None = Form(None),
    session_id: str | None = Form(None),
    user_id: str | None = Form(None),
    organization_id: str | None = Form(None),
    organization_name: str | None = Form(None),
    image: UploadFile | None = File(None),
    authorization: str | None = Header(default=None),
) -> AgentResponse:
    """Run one agent turn and return the answer, or the action waiting for approval (pending_approval)."""
    caller = await resolve_caller_async(authorization)       # 401/403 are returned as HTTP errors
    try:
        if request.headers.get("content-type", "").startswith("application/json"):
            agent_request = AgentRequest.model_validate(await request.json())
        else:
            agent_request = AgentRequest(
                query=query,
                session_id=session_id,
                user_id=user_id,
                organization_id=organization_id,
                organization_name=organization_name,
            )

        message_content: str | list[dict[str, object]] | None = agent_request.query
        if image is not None:
            if not image.content_type or not image.content_type.startswith("image/"):
                raise ValueError("The attachment must be an image file.")
            image_bytes = await image.read()
            if not image_bytes:
                raise ValueError("The attached image is empty.")
            image_data_url = f"data:{image.content_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
            message_content = [
                {"type": "text", "text": message_content or "Please analyze the attached image."},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ]

        graph = await get_agent_graph()
        config = _run_config(caller, agent_request.session_id)
        graph_input = await _graph_input(graph, config, message_content, agent_request.resume, {
            "organization_id": agent_request.organization_id, "organization_name": agent_request.organization_name,
            "session_id": agent_request.session_id, "user_id": caller.employee_id,
        })
        before = len(((await graph.aget_state(config)).values or {}).get("messages", []))
        await graph.ainvoke(graph_input, config)
        snapshot = await graph.aget_state(config)
        current_turn = {"messages": (snapshot.values or {}).get("messages", [])[before:]}
        pending = _pending_approval(snapshot)
        if pending:
            titles = "; ".join(a.get("title", a.get("tool", "")) for a in pending["actions"])
            return AgentResponse(response=f"Waiting for your approval: {titles}",
                                 token_usage=get_token_usages_from_response(current_turn), pending_approval=pending)
        return AgentResponse(response=_final_text(snapshot), token_usage=get_token_usages_from_response(current_turn))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error invoking agent: {e}")
        logger.error(traceback.format_exc())
        return AgentResponse(response=f"Error processing query: {str(e)}", token_usage=None)


# ---------------------------------------------------------------------------------------------------------
# response helpers
# ---------------------------------------------------------------------------------------------------------
def get_AIMessage_from_response(res: dict) -> str:
    """Extract the AIMessage content from the agent response"""
    try:
        response = res["messages"]
        for ele in reversed(response):
            if type(ele) == AIMessage and ele.content and not isinstance(ele.content, NoneType):
                return str(ele.content)
        for ele in reversed(response):
            content = getattr(ele, "content", None)
            if content and not isinstance(content, NoneType):
                return str(content)
        return "No response generated by the agent."
    except Exception as e:
        logger.error(f"Error parsing agent response: {e}")
        logger.error(traceback.format_exc())
        return str(res) if res is not None else "No response generated by the agent."


def messages_after(messages: list, message_id: str | None) -> list:
    """Return only the messages after the given (human) message id, i.e. the messages produced in this turn."""
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "id", None) == message_id:
            return messages[index + 1:]
    return messages


def get_ai_message_text_from_response(res: dict) -> str:
    """
    Extract the final AI answer text. Gemini may return message content as a list of content blocks
    (text + thought signatures), so the text blocks are joined instead of str()-ing the whole content.
    """
    try:
        for ele in reversed(res.get("messages", [])):
            if isinstance(ele, AIMessage):
                text = getattr(ele, "text", None)
                if not isinstance(text, str):
                    text = message_text(ele.content)
                if text and text.strip():
                    return str(text).strip()
        return "No response generated by the agent."
    except Exception as e:
        logger.error(f"Error parsing agent response: {e}")
        logger.error(traceback.format_exc())
        return get_AIMessage_from_response(res)


def get_token_usages_from_response(res: dict) -> str | None:
    """Aggregate token usage from LangChain, OpenAI, or Ollama message metadata."""
    try:
        total_tokens = 0
        input_tokens = 0
        output_tokens = 0
        found_usage = False

        for message in res.get("messages", []):
            usage_metadata = getattr(message, "usage_metadata", None) or {}
            response_metadata = getattr(message, "response_metadata", None) or {}
            token_usage = response_metadata.get("token_usage") or {}

            message_input = usage_metadata.get("input_tokens")
            message_output = usage_metadata.get("output_tokens")
            message_total = usage_metadata.get("total_tokens")

            if message_input is None:
                message_input = token_usage.get("prompt_tokens")
            if message_output is None:
                message_output = token_usage.get("completion_tokens")
            if message_total is None:
                message_total = token_usage.get("total_tokens")

            # ChatOllama exposes counts in response_metadata instead of usage_metadata.
            if message_input is None:
                message_input = response_metadata.get("prompt_eval_count")
            if message_output is None:
                message_output = response_metadata.get("eval_count")
            if message_total is None and message_input is not None and message_output is not None:
                message_total = message_input + message_output

            if message_input is not None or message_output is not None or message_total is not None:
                found_usage = True
                input_tokens += int(message_input or 0)
                output_tokens += int(message_output or 0)
                total_tokens += int(message_total or 0)

        if not found_usage:
            logger.warning("No token usage metadata found in agent response messages.")
            return None

        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens

        return f"total_tokens={total_tokens}, input_tokens={input_tokens}, output_tokens={output_tokens}"
    except Exception:
        logger.exception("Error parsing token usage from agent response.")
        return None
