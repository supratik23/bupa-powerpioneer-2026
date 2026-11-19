"""
/agent/invoke and /agent/stream require a manager/HR login (Django JWT) unless AGENT_REQUIRE_AUTH=false.

    .venv\\Scripts\\python -m pytest tests/test_agent_invoke.py -q
"""
from unittest import mock

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)   # no `with`: the lifespan (Gemini, model, tools) is not started for these checks

REQUEST = {"query": "Who needs attention?", "session_id": "test_session_123", "user_id": "u1",
           "organization_id": "bupa", "organization_name": "Bupa"}


def test_invoke_requires_login():
    with mock.patch("app.mcp_client.agent.settings.AGENT_REQUIRE_AUTH", True):
        response = client.post("/agent/invoke", json=REQUEST)
    assert response.status_code == 401


def test_stream_requires_login():
    with mock.patch("app.mcp_client.agent.settings.AGENT_REQUIRE_AUTH", True):
        response = client.post("/agent/stream", json={"session_id": "s", "query": "hi"})
    assert response.status_code == 401


def test_briefing_requires_login():
    with mock.patch("app.mcp_client.agent.settings.AGENT_REQUIRE_AUTH", True):
        response = client.get("/briefing/latest")
    assert response.status_code == 401
