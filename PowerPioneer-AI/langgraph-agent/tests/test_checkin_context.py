"""
Context-aware check-ins (no database): end-of-life care debrief, maternity / onboarding focus, support messages,
and the guidance search used by the copilot.

    .venv\\Scripts\\python -m pytest tests/test_checkin_context.py -q
"""
import json
import os
import sys
from datetime import date, timedelta
from unittest import mock

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
sys.path.insert(0, APP_DIR)

from services import checkin_service as cs  # noqa: E402

TODAY = date.today()


class FakeDB:
    """Enough of SupabaseDBConnectionManager for serve_question."""

    def __init__(self, open_question=None):
        self.open_question = open_question
        self.cursor_obj = mock.MagicMock()
        self.connection = mock.MagicMock()
        self.connection.cursor.return_value.__enter__.return_value = self.cursor_obj

    def db_connection(self):
        return self.connection

    def fetch_one(self, sql, params=None):
        return {"question_id": params[0], "question_text": "q", "source": "TEMPLATE", "trigger_type": "POST_SHIFT",
                "generated_for_employee_id": "e1", "context_data": {"focus": "end_of_life_care"},
                "model_name": None, "prompt_version": "v", "is_active": True, "expires_at": None, "created_at": None}

    def fetch_all(self, sql, params=None):
        return []


def serve(appointment_type, open_question=None):
    db = FakeDB()
    with mock.patch.object(cs, "find_open_question", return_value=open_question), \
            mock.patch.object(cs, "find_queued_question", return_value=None), \
            mock.patch.object(cs, "_recent_question_texts", return_value=[]), \
            mock.patch.object(cs, "_insert_question", return_value="new-q") as insert:
        question, served_from = cs.serve_question(db, "e1", {"appointment_id": "a1", "appointment_type": appointment_type})
    return question, served_from, insert


def test_end_of_life_appointment_serves_debrief_now():
    question, served_from, insert = serve("END_OF_LIFE_CARE")
    assert served_from == "end_of_life_care"
    args, kwargs = insert.call_args
    assert args[2] == cs.END_OF_LIFE_QUESTIONS[0][0]
    assert kwargs["trigger_type"] == "POST_SHIFT" and kwargs["context"]["focus"] == "end_of_life_care"
    assert question["question_id"] == "new-q"


def test_end_of_life_does_not_stack_on_open_debrief():
    open_q = {"question_id": "old", "context_data": {"focus": "end_of_life_care"}, "is_active": True, "expires_at": None}
    _, served_from, insert = serve("END_OF_LIFE_CARE", open_question=open_q)
    assert served_from == "open" and not insert.called


def test_other_appointment_uses_template_first_time():
    _, served_from, insert = serve("MEDICATION_ROUND")
    assert served_from == "template"
    assert insert.call_args.kwargs.get("trigger_type", cs.TRIGGER_TYPE) == cs.TRIGGER_TYPE


def test_focus_maternity_onboarding_default():
    assert cs.checkin_focus({"maternity_return_date": TODAY - timedelta(days=20), "hire_date": None}) == \
        ("maternity_return", "MATERNITY_RETURN")
    assert cs.checkin_focus({"maternity_return_date": None, "hire_date": TODAY - timedelta(days=30)}) == \
        ("onboarding", "ONBOARDING")
    assert cs.checkin_focus({"maternity_return_date": TODAY - timedelta(days=200),
                             "hire_date": TODAY - timedelta(days=900)}) == (None, cs.TRIGGER_TYPE)


def test_support_only_after_low_answers():
    db = mock.MagicMock()
    db.fetch_one.return_value = {"normalized_score": 1, "context_data": {"focus": "end_of_life_care"}}
    assert cs.support_for_answer(db, "q", "o")["title"] == cs.SUPPORT_MESSAGES["end_of_life_care"][0]
    db.fetch_one.return_value = {"normalized_score": 2, "context_data": None}
    assert cs.support_for_answer(db, "q", "o")["title"] == cs.SUPPORT_MESSAGES["default"][0]
    db.fetch_one.return_value = {"normalized_score": 3, "context_data": {}}
    assert cs.support_for_answer(db, "q", "o") is None


def test_guidance_search_finds_relevant_section():
    from mcp_server.planning_tool import search_wellbeing_guidance
    result = json.loads(search_wellbeing_guidance("support after a patient death"))
    assert result["results"][0]["title"] == "End-of-life care and patient death"
    assert search_wellbeing_guidance("the and of").startswith("Error")
