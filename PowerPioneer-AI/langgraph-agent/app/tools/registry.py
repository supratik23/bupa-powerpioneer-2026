"""
The chat agent's tools, called in-process.

The tool functions live in app/mcp_server/*.py (decorated with FastMCP's @mcp.tool(), which in fastmcp 3 returns the
plain function), so the same code still runs as stdio MCP servers. Calling them directly avoids starting a Python
process per tool call (~10 s each) and lets every call see who is asking (CURRENT_CALLER), so managers only see
their own team.

APPROVAL_REQUIRED lists the tools the graph pauses on (LangGraph interrupt) until the manager approves.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool

from services.access_scope import CURRENT_CALLER, Caller

logger = logging.getLogger(__name__)

# Outward or hard-to-undo actions: emails, roster changes, leave decisions, buddy assignments.
APPROVAL_REQUIRED = frozenset({"send_notification_email", "reassign_shift", "decide_leave_request", "assign_buddy"})

# Short labels the UI shows while a tool runs.
TOOL_LABELS = {
    "find_employees": "Looking up employees",
    "get_employee_details": "Reading roster and profile",
    "predict_employee_risk": "Scoring burnout risk",
    "predict_risk_for_all_employees": "Scoring risk for the whole team",
    "list_at_risk_employees": "Finding who needs attention",
    "get_employee_risk_history": "Reading risk history",
    "create_intervention": "Recording a follow-up action",
    "update_intervention_status": "Updating the follow-up",
    "list_interventions": "Reading follow-up actions",
    "create_checkin_question": "Writing a check-in question",
    "get_checkin_responses": "Reading check-in answers",
    "send_notification_email": "Sending an email",
    "simulate_risk": "Simulating a what-if scenario",
    "review_upcoming_roster": "Projecting risk on the upcoming rota",
    "list_shifts": "Reading the rota",
    "suggest_shift_cover": "Finding cover for the shift",
    "reassign_shift": "Reassigning the shift",
    "list_leave_requests": "Reading leave requests",
    "review_leave_request": "Weighing up the leave request",
    "decide_leave_request": "Recording the leave decision",
    "suggest_buddy": "Matching a peer-support buddy",
    "assign_buddy": "Assigning the buddy",
    "search_wellbeing_guidance": "Checking wellbeing guidance",
}


class ScopedTool(StructuredTool):
    """StructuredTool that runs with the caller from config["configurable"]["caller"] in CURRENT_CALLER."""

    def _run(self, *args: Any, config: RunnableConfig, run_manager=None, **kwargs: Any) -> Any:
        caller = Caller.from_config(((config or {}).get("configurable") or {}).get("caller"))
        token = CURRENT_CALLER.set(caller)
        try:
            return super()._run(*args, config=config, run_manager=run_manager, **kwargs)
        finally:
            CURRENT_CALLER.reset(token)


def get_inprocess_tools() -> list[BaseTool]:
    """All ShiftGuard tools as LangChain tools (imports the risk model in the calling - main - thread)."""
    from mcp_server import checkin_tool, employee_tool, intervention_tool, notifsend_tool, planning_tool, risk_tool

    functions = [
        employee_tool.find_employees, employee_tool.get_employee_details,
        risk_tool.predict_employee_risk, risk_tool.predict_risk_for_all_employees,
        risk_tool.list_at_risk_employees, risk_tool.get_employee_risk_history,
        intervention_tool.create_intervention, intervention_tool.update_intervention_status,
        intervention_tool.list_interventions,
        checkin_tool.create_checkin_question, checkin_tool.get_checkin_responses,
        notifsend_tool.send_notification_email,
        planning_tool.simulate_risk, planning_tool.review_upcoming_roster, planning_tool.list_shifts,
        planning_tool.suggest_shift_cover, planning_tool.reassign_shift,
        planning_tool.list_leave_requests, planning_tool.review_leave_request, planning_tool.decide_leave_request,
        planning_tool.suggest_buddy, planning_tool.assign_buddy,
        planning_tool.search_wellbeing_guidance,
    ]
    tools = []
    for fn in functions:
        if not callable(fn):
            raise TypeError(f"{fn!r} is not a plain function; check the fastmcp version (decorators must return functions).")
        description = (fn.__doc__ or fn.__name__).strip()
        if fn.__name__ in APPROVAL_REQUIRED:
            description += "\n\nThe app shows this action to the manager for approval before it runs."
        tools.append(ScopedTool.from_function(func=fn, name=fn.__name__, description=description))
    logger.info("Loaded %d in-process tools", len(tools))
    return tools
