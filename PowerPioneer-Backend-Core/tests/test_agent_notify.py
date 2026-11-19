"""POST /api/internal/notify/ - the AI agent's real-time bell push. No database needed."""
import uuid
from unittest import mock

from django.test import SimpleTestCase, override_settings

URL = "/api/internal/notify/"


@override_settings(AGENT_INTERNAL_KEY="test-key")
class AgentNotifyTests(SimpleTestCase):
    def post(self, body, key="test-key"):
        return self.client.post(URL, body, content_type="application/json", HTTP_X_AGENT_KEY=key)

    def test_rejects_wrong_key(self):
        res = self.post({"employee_id": str(uuid.uuid4()), "payload": {"kind": "briefing"}}, key="nope")
        self.assertEqual(res.status_code, 403)

    def test_rejects_unknown_kind(self):
        res = self.post({"employee_id": str(uuid.uuid4()), "payload": {"kind": "anything"}})
        self.assertEqual(res.status_code, 400)

    def test_rejects_bad_employee_id(self):
        res = self.post({"employee_id": "not-a-uuid", "payload": {"kind": "briefing"}})
        self.assertEqual(res.status_code, 400)

    def test_pushes_notification(self):
        employee_id = uuid.uuid4()
        with mock.patch("chat.views.notify_employee") as notify:
            res = self.post({"employee_id": str(employee_id), "payload": {"kind": "intervention", "employee_name": "Priya"}})
        self.assertEqual(res.status_code, 202)
        notify.assert_called_once_with(employee_id, {"kind": "intervention", "employee_name": "Priya", "source": "agent"})
