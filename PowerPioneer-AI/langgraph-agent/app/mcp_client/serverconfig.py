from langchain_mcp_adapters.client import MultiServerMCPClient
import os
import sys

python_path = os.pathsep.join([os.path.abspath("."), os.path.abspath("app")])
python_command = sys.executable


def stdio_server(script: str) -> dict:
    """stdio MCP server started with the same Python interpreter (.venv) as the FastAPI app."""
    return {
        "transport": "stdio",
        "command": python_command,
        "args": [os.path.abspath(f"app/mcp_server/{script}")],
        "env": {"PYTHONPATH": python_path},
    }


# ShiftGuard MCP servers. Each server exposes one or more tools; Gemini decides which tool to call.
mcp_servers_config = {
    # find_employees, get_employee_details
    "shiftguard_employee": stdio_server("employee_tool.py"),
    # predict_employee_risk, predict_risk_for_all_employees, list_at_risk_employees, get_employee_risk_history
    "shiftguard_risk": stdio_server("risk_tool.py"),
    # create_intervention, update_intervention_status, list_interventions
    "shiftguard_intervention": stdio_server("intervention_tool.py"),
    # create_checkin_question, get_checkin_responses
    "shiftguard_checkin": stdio_server("checkin_tool.py"),
    # send_notification_email
    "send_notification_email": stdio_server("notifsend_tool.py"),
    # simulate_risk, review_upcoming_roster, list_shifts, suggest_shift_cover, reassign_shift, list_leave_requests,
    # review_leave_request, decide_leave_request, suggest_buddy, assign_buddy, search_wellbeing_guidance
    "shiftguard_planning": stdio_server("planning_tool.py"),
}
# Only used when AGENT_TOOL_MODE=mcp. The default (inprocess) calls the same functions directly: app/tools/registry.py

multi_server_mcp_client = MultiServerMCPClient(mcp_servers_config)
