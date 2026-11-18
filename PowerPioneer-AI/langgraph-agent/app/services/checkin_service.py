"""
Check-in question lifecycle for the appointment-completed flow.

    serve_question()          appointment completed -> return the employee's open question, or activate the
                              QUEUED one, or (first time only) create one from the template bank.
    generate_next_question()  background: Gemini writes the NEXT question, stored QUEUED (is_active = false,
                              hidden from the backend's /questions/pending/) until the next completed appointment.
    record_answer()           employee_response insert, one answer per employee and question.

Every question has exactly 4 options scored 1..4 (1 = struggling, 4 = good), because the risk model's
wellbeing_score is the mean of these scores over the last 7 days.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from config import settings
from services.shiftguard_repository import SUPPORT_NUDGE_KIND, to_jsonable

logger = logging.getLogger(__name__)

TRIGGER_TYPE = "ROSTER_EVENT"          # allowed by chk_question_trigger_type
PROMPT_VERSION = "shiftguard-checkin-v1"
QUEUED, SERVED = "QUEUED", "SERVED"

# Fallback questions (worst -> best). Used the first time and whenever Gemini is unavailable.
TEMPLATE_QUESTIONS = [
    ("How are you feeling after that task?", ["Drained", "A bit tired", "Okay", "Good"]),
    ("How manageable does your workload feel right now?",
     ["Overwhelming", "Quite heavy", "Mostly manageable", "Very manageable"]),
    ("Have you been able to take the breaks you need today?",
     ["Not at all", "Barely", "Mostly", "Yes, fully"]),
    ("How supported do you feel by your team today?",
     ["Not supported", "A little", "Fairly supported", "Well supported"]),
    ("How rested did you feel coming into this shift?",
     ["Exhausted", "Quite tired", "Mostly rested", "Well rested"]),
    ("How are you coping emotionally with today's work?",
     ["Struggling", "Finding it hard", "Coping okay", "Coping well"]),
]

QUESTION_COLUMNS = """
    q.question_id, q.question_text, q.source, q.trigger_type, q.generated_for_employee_id, q.context_data,
    q.model_name, q.prompt_version, q.is_active, q.expires_at, q.created_at
"""


class CheckinError(Exception):
    """Business rule violation; `status` is the HTTP status the API returns."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class GeneratedQuestion(BaseModel):
    """Structured output requested from Gemini."""

    question_text: str = Field(description="One short, supportive check-in question (max 120 characters).")
    options: list[str] = Field(description="Exactly 4 short answers ordered from worst to best wellbeing.")

    @field_validator("question_text")
    @classmethod
    def _question(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 5 <= len(v) <= 160:
            raise ValueError("question_text must be 5-160 characters")
        return v

    @field_validator("options")
    @classmethod
    def _options(cls, v: list[str]) -> list[str]:
        v = [" ".join(o.split()) for o in v if o and o.strip()]
        if len(v) != 4 or len({o.lower() for o in v}) != 4 or any(len(o) > 40 for o in v):
            raise ValueError("exactly 4 distinct options of at most 40 characters are required")
        return v


# ---------------------------------------------------------------------------------------------------------
# Reading / shaping
# ---------------------------------------------------------------------------------------------------------
def _shape_question(db, row: dict) -> dict:
    """Same JSON shape as the Django QuestionSerializer, so the frontend renders it unchanged."""
    options = db.fetch_all(
        "SELECT option_id, option_text, normalized_score, display_order FROM question_option "
        "WHERE question_id = %s ORDER BY display_order",
        (row["question_id"],),
    )
    now = datetime.now(timezone.utc)
    return to_jsonable({
        **row,
        "is_open": bool(row["is_active"]) and (row["expires_at"] is None or row["expires_at"] > now),
        "options": options,
    })


def _unanswered(alias: str = "q") -> str:
    return (f"NOT EXISTS (SELECT 1 FROM employee_response r WHERE r.question_id = {alias}.question_id "
            f"AND r.employee_id = %s)")


def find_open_question(db, employee_id) -> dict | None:
    """Latest active, unexpired, unanswered question generated for this employee."""
    return db.fetch_one(
        f"SELECT {QUESTION_COLUMNS} FROM question q WHERE q.generated_for_employee_id = %s AND q.is_active "
        f"AND (q.expires_at IS NULL OR q.expires_at > now()) AND {_unanswered()} "
        "ORDER BY q.created_at DESC LIMIT 1",
        (employee_id, employee_id),
    )


def find_queued_question(db, employee_id) -> dict | None:
    return db.fetch_one(
        f"SELECT {QUESTION_COLUMNS} FROM question q WHERE q.generated_for_employee_id = %s AND NOT q.is_active "
        f"AND q.context_data ->> 'queue_status' = %s AND {_unanswered()} ORDER BY q.created_at DESC LIMIT 1",
        (employee_id, QUEUED, employee_id),
    )


def _recent_question_texts(db, employee_id, limit: int = 8) -> list[str]:
    rows = db.fetch_all(
        "SELECT question_text FROM question WHERE generated_for_employee_id = %s "
        "AND coalesce(context_data ->> 'kind', '') <> %s ORDER BY created_at DESC LIMIT %s",
        (employee_id, SUPPORT_NUDGE_KIND, limit),
    )
    return [r["question_text"] for r in rows]


# ---------------------------------------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------------------------------------
def _insert_question(cursor, employee_id, text: str, options: list[str], *, source: str, model_name: str | None,
                     active: bool, context: dict) -> Any:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=settings.CHECKIN_QUESTION_EXPIRY_HOURS) if active else None
    cursor.execute(
        """
        INSERT INTO question (question_text, source, trigger_type, generated_for_employee_id, context_data,
                              model_name, prompt_version, is_active, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING question_id
        """,
        (text, source, TRIGGER_TYPE, employee_id, Jsonb(context), model_name, PROMPT_VERSION, active, expires_at),
    )
    question_id = cursor.fetchone()[0]
    for score, option_text in enumerate(options, start=1):          # worst -> best = 1..4
        cursor.execute(
            "INSERT INTO question_option (question_id, option_text, normalized_score, display_order) "
            "VALUES (%s, %s, %s, %s)",
            (question_id, option_text, score, score),
        )
    return question_id


def _pick_template(recent_texts: list[str]) -> tuple[str, list[str]]:
    for text, options in TEMPLATE_QUESTIONS:
        if text not in recent_texts:
            return text, options
    return TEMPLATE_QUESTIONS[len(recent_texts) % len(TEMPLATE_QUESTIONS)]


def serve_question(db, employee_id, appointment: dict) -> tuple[dict, str]:
    """
    Return (question, served_from) for an employee who just completed an appointment.
    served_from: 'open' (already showing), 'queued' (activated now) or 'template' (first time / nothing queued).
    """
    connection = db.db_connection()
    try:
        with connection.cursor() as cursor:
            # Serialize concurrent completions for the same employee (one open question at a time).
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(employee_id),))

            row = find_open_question(db, employee_id)
            served_from = "open"
            if row is None:
                queued = find_queued_question(db, employee_id)
                if queued is not None:
                    context = dict(queued["context_data"] or {})
                    context.update(queue_status=SERVED, served_at=datetime.now(timezone.utc).isoformat(),
                                   served_for_appointment_id=str(appointment["appointment_id"]))
                    cursor.execute(
                        "UPDATE question SET is_active = true, expires_at = %s, context_data = %s WHERE question_id = %s",
                        (datetime.now(timezone.utc) + timedelta(hours=settings.CHECKIN_QUESTION_EXPIRY_HOURS),
                         Jsonb(context), queued["question_id"]),
                    )
                    question_id, served_from = queued["question_id"], "queued"
                else:
                    text, options = _pick_template(_recent_question_texts(db, employee_id))
                    question_id = _insert_question(
                        cursor, employee_id, text, options, source="TEMPLATE", model_name=None, active=True,
                        context={"source": "shiftguard-checkin", "queue_status": SERVED, "generated_by": "template",
                                 "served_for_appointment_id": str(appointment["appointment_id"])},
                    )
                    served_from = "template"
                row = db.fetch_one(f"SELECT {QUESTION_COLUMNS} FROM question q WHERE q.question_id = %s", (question_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return _shape_question(db, row), served_from


def _generate_with_gemini(prompt: str) -> tuple[GeneratedQuestion, str]:
    """Ask Gemini (primary model, then GEMINI_FALLBACK_MODELS) for a structured question."""
    from langchain_google_genai.chat_models import GoogleAPIError, GoogleRateLimitError
    from services.llm_service import get_gemini_llm, get_gemini_fallback_models

    models = [settings.GEMINI_MODEL, *get_gemini_fallback_models()]
    last_error: Exception | None = None
    for model in models:
        try:
            llm = get_gemini_llm(model=model).with_structured_output(GeneratedQuestion)
            result = llm.invoke(prompt)
            if isinstance(result, dict):
                result = GeneratedQuestion(**result)
            return result, model
        except (GoogleAPIError, GoogleRateLimitError) as e:      # overloaded / rate limited -> next model
            last_error = e
            logger.warning("Gemini %s unavailable for question generation: %s", model, e)
        except Exception as e:                                    # invalid output etc. -> next model
            last_error = e
            logger.warning("Gemini %s returned an unusable question: %s", model, e)
    raise RuntimeError(f"No Gemini model produced a question: {last_error}")


def _build_prompt(db, employee: dict, appointment: dict | None) -> str:
    recent = db.fetch_all(
        """
        SELECT q.question_text, o.option_text, o.normalized_score, r.responded_at
        FROM employee_response r
        JOIN question q ON q.question_id = r.question_id
        JOIN question_option o ON o.option_id = r.option_id
        WHERE r.employee_id = %s ORDER BY r.responded_at DESC LIMIT 6
        """,
        (employee["employee_id"],),
    )
    answers = "\n".join(f"- \"{r['question_text']}\" -> \"{r['option_text']}\" ({r['normalized_score']}/4)" for r in recent) or "- none yet"
    asked = "\n".join(f"- {t}" for t in _recent_question_texts(db, employee["employee_id"])) or "- none yet"
    task = f"{appointment.get('title')} ({appointment.get('appointment_type') or 'care task'})" if appointment else "a care task"
    return f"""You write one short wellbeing check-in question for a healthcare worker, shown in an app right after
they finish a task. Role: {employee.get('job_role') or 'healthcare worker'}. Task just completed: {task}.

Their recent check-in answers (1 = struggling, 4 = good):
{answers}

Questions already asked recently (do NOT repeat or closely paraphrase these):
{asked}

Rules:
- Ask about how they are coping right now: energy, rest, breaks, workload, emotional load, support, or sleep.
  Vary the topic. If recent answers are low, gently follow up on that topic.
- Warm, plain, non-clinical language. Max 120 characters. No names, no diagnoses, no mention of risk, scores or AI.
- Exactly 4 answer options, each 1-4 words, ordered from WORST to BEST wellbeing (they are scored 1, 2, 3, 4).
"""


def generate_next_question(employee_id, appointment_id=None) -> dict:
    """
    Background job: store the employee's NEXT question as QUEUED (inactive). Skips when one is already queued.
    Gemini writes it; if every Gemini model fails, a template question is queued instead.
    """
    from services.db_service import SupabaseDBConnectionManager

    with SupabaseDBConnectionManager() as db:
        if find_queued_question(db, employee_id):
            return {"status": "already_queued"}
        employee = db.fetch_one("SELECT employee_id, job_role FROM employee WHERE employee_id = %s", (employee_id,))
        appointment = None
        if appointment_id:
            appointment = db.fetch_one(
                "SELECT appointment_id, title, appointment_type FROM appointment WHERE appointment_id = %s",
                (appointment_id,),
            )
        prompt = _build_prompt(db, employee, appointment)

    try:
        generated, model = _generate_with_gemini(prompt)
        text, options, source, model_name, generated_by = generated.question_text, generated.options, "GEMINI", model, "gemini"
    except Exception as e:
        logger.warning("Falling back to a template question: %s", e)
        with SupabaseDBConnectionManager() as db:
            text, options = _pick_template(_recent_question_texts(db, employee_id))
        source, model_name, generated_by = "TEMPLATE", None, "template"

    with SupabaseDBConnectionManager() as db:
        connection = db.db_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (str(employee_id),))
                if find_queued_question(db, employee_id):          # another request queued one meanwhile
                    connection.rollback()
                    return {"status": "already_queued"}
                question_id = _insert_question(
                    cursor, employee_id, text, options, source=source, model_name=model_name, active=False,
                    context={"source": "shiftguard-checkin", "queue_status": QUEUED, "generated_by": generated_by,
                             "generated_after_appointment_id": str(appointment_id) if appointment_id else None},
                )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    logger.info("Queued next check-in question %s for employee %s (%s)", question_id, employee_id, generated_by)
    return {"status": "queued", "question_id": str(question_id), "generated_by": generated_by}


def record_answer(db, employee_id, question_id, option_id) -> dict:
    """Insert employee_response. One answer per employee and question; the option must belong to the question."""
    connection = db.db_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT question_id, generated_for_employee_id, is_active FROM question WHERE question_id = %s FOR UPDATE",
                (question_id,),
            )
            question = cursor.fetchone()
            if question is None:
                raise CheckinError("Question not found.", 404)
            _, generated_for, is_active = question
            if generated_for is not None and str(generated_for) != str(employee_id):
                raise CheckinError("This question belongs to another employee.", 403)
            if not is_active:
                raise CheckinError("This question has not been served yet.", 409)
            cursor.execute(
                "SELECT 1 FROM question_option WHERE option_id = %s AND question_id = %s", (option_id, question_id)
            )
            if cursor.fetchone() is None:
                raise CheckinError("The option does not belong to this question.", 400)
            cursor.execute(
                "SELECT 1 FROM employee_response WHERE employee_id = %s AND question_id = %s", (employee_id, question_id)
            )
            if cursor.fetchone() is not None:
                raise CheckinError("This question has already been answered.", 409)
            cursor.execute(
                "INSERT INTO employee_response (employee_id, question_id, option_id, responded_at) "
                "VALUES (%s, %s, %s, now()) RETURNING response_id, responded_at",
                (employee_id, question_id, option_id),
            )
            response_id, responded_at = cursor.fetchone()
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"response_id": str(response_id), "responded_at": responded_at.isoformat()}
