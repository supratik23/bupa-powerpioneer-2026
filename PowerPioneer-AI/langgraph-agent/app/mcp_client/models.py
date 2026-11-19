from typing import Annotated, Any, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel


class AgentRequest(BaseModel):
    """Agent Request Model. Send `query` for a new question, or `resume` to approve/decline a paused action."""
    query: str | None = None
    session_id: str
    user_id: str | None = None             # ignored when a login token is sent (the token decides who is asking)
    organization_id: str | None = "bupa"
    organization_name: str | None = "Bupa"
    resume: dict[str, Any] | None = None   # {"approved": true|false, "comment": "..."}


class AgentResponse(BaseModel):
    """Agent Response Model"""
    response: str
    token_usage: str | None = None
    pending_approval: dict[str, Any] | None = None   # {"type": "approval", "actions": [...]} while paused


class AgentState(TypedDict):
    """Agent State"""
    messages: Annotated[list[BaseMessage], add_messages]
    organization_id: str | None = None
    session_id: str | None = None
    organization_name: str | None = None
    user_id: str | None = None
    next_destination: str | None = None
