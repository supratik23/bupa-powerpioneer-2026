from datetime import datetime, timedelta, timezone
from fastmcp import FastMCP
from psycopg.types.json import Jsonb
from config import settings
from services.db_service import SupabaseDBConnectionManager
from services.risk_feature_service import WELLBEING_WINDOW_DAYS, _utc, compute_wellbeing_score
from services.shiftguard_repository import QUESTION_TRIGGER_TYPES, ToolInputError, dumps, parse_date, resolve_employee
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("ShiftGuard Check-in Tool")

PROMPT_VERSION = "shiftguard-agent-checkin-v1"
OPTIONS_REQUIRED = 4


@mcp.tool()
def create_checkin_question(employee: str, question_text: str, options: list[str],
                            trigger_type: str = "RISK_TRIGGERED", reason: str = "",
                            expires_in_hours: int = 0) -> str:
    """
    Save a personalised wellbeing check-in question for one employee (tables `question` + `question_option`).
    It appears in the employee's pending check-ins in the ShiftGuard app; their answers feed the model's
    wellbeing_score (1-4 scale).

    Write a short, supportive question about how they are coping (rest, breaks, workload, sleep, support).
    Never mention the risk score, the model or diagnoses.

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        question_text: The question shown to the employee.
        options: EXACTLY 4 answer texts ordered from worst to best wellbeing,
            e.g. ["Very difficult", "Somewhat difficult", "Mostly manageable", "Very manageable"].
            They are scored 1, 2, 3, 4 in that order (1 = struggling, 4 = good).
        trigger_type: RISK_TRIGGERED (default), SCHEDULED, ROSTER_EVENT, RISK_EVENT, MANUAL, ONBOARDING,
            MATERNITY_RETURN, POST_SHIFT or ADHOC.
        reason: Why the question was generated (stored in question.context_data).
        expires_in_hours: Hours until the question expires. 0 uses CHECKIN_QUESTION_EXPIRY_HOURS (24).
    """
    try:
        question_text = (question_text or "").strip()
        trigger_type = (trigger_type or "RISK_TRIGGERED").strip().upper()
        if not question_text:
            raise ToolInputError("question_text is required.")
        if trigger_type not in QUESTION_TRIGGER_TYPES:
            raise ToolInputError(f"trigger_type must be one of {', '.join(QUESTION_TRIGGER_TYPES)}.")
        options = [str(o).strip() for o in (options or []) if str(o).strip()]
        if len(options) != OPTIONS_REQUIRED:
            raise ToolInputError(
                f"Exactly {OPTIONS_REQUIRED} options are required (worst to best), got {len(options)}."
            )
        if len({o.lower() for o in options}) != OPTIONS_REQUIRED:
            raise ToolInputError("The 4 options must be different.")
        hours = int(expires_in_hours) if int(expires_in_hours or 0) > 0 else settings.CHECKIN_QUESTION_EXPIRY_HOURS
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)

        with SupabaseDBConnectionManager() as db:
            emp = resolve_employee(db, employee)
            connection = db.db_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO question (question_text, source, trigger_type, generated_for_employee_id,
                                              context_data, model_name, prompt_version, is_active, expires_at)
                        VALUES (%s, 'GEMINI', %s, %s, %s, %s, %s, true, %s)
                        RETURNING question_id
                        """,
                        (question_text, trigger_type, emp["employee_id"],
                         Jsonb({"source": "shiftguard-agent", "reason": reason.strip() or None,
                                "created_for_date": datetime.now(timezone.utc).date().isoformat()}),
                         settings.GEMINI_MODEL, PROMPT_VERSION, expires_at),
                    )
                    question_id = cursor.fetchone()[0]
                    for score, text in enumerate(options, start=1):
                        cursor.execute(
                            "INSERT INTO question_option (question_id, option_text, normalized_score, display_order) "
                            "VALUES (%s, %s, %s, %s)",
                            (question_id, text, score, score),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return dumps({
            "created": True,
            "question_id": question_id,
            "employee": f"{emp['first_name']} {emp['last_name']}",
            "question_text": question_text,
            "options": [{"option_text": t, "normalized_score": i} for i, t in enumerate(options, start=1)],
            "expires_at": expires_at,
        })
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("create_checkin_question failed")
        return f"Error creating check-in question: {e}"


@mcp.tool()
def get_checkin_responses(employee: str, days: int = 7, as_of_date: str = "") -> str:
    """
    An employee's recent check-in answers and their wellbeing_score (mean answer on the 1-4 scale over the
    last 7 days, the value the risk model uses). Use for "how has X been feeling?".

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        days: How many days of answers to list (1-90).
        as_of_date: YYYY-MM-DD end date. Defaults to today (UTC).
    """
    try:
        days = max(1, min(int(days), 90))
        d = parse_date(as_of_date)
        with SupabaseDBConnectionManager() as db:
            emp = resolve_employee(db, employee)
            rows = db.fetch_all(
                """
                SELECT r.responded_at, q.question_text, o.option_text, o.normalized_score
                FROM employee_response r
                JOIN question q ON q.question_id = r.question_id
                JOIN question_option o ON o.option_id = r.option_id
                WHERE r.employee_id = %s AND r.responded_at >= %s AND r.responded_at < %s
                ORDER BY r.responded_at DESC
                """,
                (emp["employee_id"], _utc(d - timedelta(days=days - 1)), _utc(d + timedelta(days=1))),
            )
            score = compute_wellbeing_score(db, emp["employee_id"], d)
        return dumps({
            "employee": f"{emp['first_name']} {emp['last_name']}",
            "as_of_date": d,
            "wellbeing_score_7d": score,
            "wellbeing_scale": f"1 = struggling, 4 = good (mean over the last {WELLBEING_WINDOW_DAYS} days)",
            "responses": rows,
        })
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("get_checkin_responses failed")
        return f"Error fetching check-in responses: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
