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
}

multi_server_mcp_client = MultiServerMCPClient(mcp_servers_config)
