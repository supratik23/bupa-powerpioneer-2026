"""
Shared data access for the ShiftGuard MCP tools (Supabase Postgres, psycopg 3).

Table and column names match the live Supabase schema used by PowerPioneer-Backend-Core
(Django models in employees/, rostering/, surveys/, wellbeing/):

    employee, shift_roster, attendance, leave_request,
    question, question_option, employee_response,
    employee_risk_snapshot, risk_prediction, risk_explanation, intervention
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

# Values allowed by the CHECK constraints in Supabase
INTERVENTION_ACTION_TYPES = (
    "EMAIL_BUDDY", "EMAIL_MANAGER", "EMPLOYEE_NUDGE", "FOLLOW_UP_CHECKIN", "MANAGER_REVIEW", "HR_ESCALATION",
    "NO_ACTION", "NOTIFY_MANAGER", "NOTIFY_BUDDY", "SUGGEST_BUDDY", "SCHEDULE_CHECKIN", "SEND_SURVEY",
    "SEND_MESSAGE", "ASSIGN_MANAGER", "REMOVE_MANAGER", "ASSIGN_BUDDY", "REMOVE_BUDDY", "OTHER",
)
INTERVENTION_STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETED", "FAILED", "CANCELLED", "SKIPPED")
QUESTION_TRIGGER_TYPES = (
    "SCHEDULED", "ROSTER_EVENT", "RISK_EVENT", "MANUAL", "RISK_TRIGGERED", "ONBOARDING",
    "MATERNITY_RETURN", "POST_SHIFT", "ADHOC",
)
RISK_BAND_ORDER = {"LOW": 0, "MEDIUM": 1, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}

# The XGBoost scorer writes this model_name; Django's rule scorer writes 'wellbeing-rules'.
XGBOOST_MODEL_NAME = "XGBOOST"

EMPLOYEE_COLUMNS = """
    e.employee_id, e.employee_number, e.first_name, e.last_name, e.email, e.job_role, e.department,
    e.location, e.employment_type, e.contracted_weekly_hours, e.hire_date, e.maternity_return_date,
    e.is_active, e.manager_employee_id, e.buddy_employee_id,
    m.first_name AS manager_first_name, m.last_name AS manager_last_name, m.email AS manager_email,
    b.first_name AS buddy_first_name, b.last_name AS buddy_last_name, b.email AS buddy_email
"""
EMPLOYEE_FROM = """
    FROM employee e
    LEFT JOIN employee m ON m.employee_id = e.manager_employee_id
    LEFT JOIN employee b ON b.employee_id = e.buddy_employee_id
"""


class ToolInputError(ValueError):
    """Raised for invalid tool input; the message is returned to the LLM."""


def to_jsonable(value: Any) -> Any:
    """Convert DB values (Decimal, UUID, date, datetime) to JSON-safe values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v) for v in value]
    return value


def dumps(value: Any) -> str:
    return json.dumps(to_jsonable(value), indent=2)


def parse_date(value: str | None, default: date | None = None) -> date:
    """Parse YYYY-MM-DD; None/empty -> default (today in UTC)."""
    if value in (None, "", "today"):
        return default or datetime.now(timezone.utc).date()
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise ToolInputError(f"Invalid date '{value}'. Use the format YYYY-MM-DD.") from None


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


def shape_employee(row: dict) -> dict:
    """Public view of an employee row (never includes auth columns such as password)."""
    def person(prefix: str, id_key: str):
        if not row.get(id_key):
            return None
        return {
            "employee_id": row[id_key],
            "name": f"{row.get(prefix + '_first_name') or ''} {row.get(prefix + '_last_name') or ''}".strip(),
            "email": row.get(prefix + "_email"),
        }

    return to_jsonable({
        "employee_id": row["employee_id"],
        "employee_number": row["employee_number"],
        "name": f"{row['first_name']} {row['last_name']}".strip(),
        "email": row["email"],
        "job_role": row["job_role"],
        "department": row["department"],
        "location": row["location"],
        "employment_type": row["employment_type"],
        "contracted_weekly_hours": row["contracted_weekly_hours"],
        "hire_date": row["hire_date"],
        "maternity_return_date": row["maternity_return_date"],
        "is_active": row["is_active"],
        "manager": person("manager", "manager_employee_id"),
        "buddy": person("buddy", "buddy_employee_id"),
    })


def resolve_employee(db, identifier: str) -> dict:
    """
    Find exactly one employee by employee_id (UUID), email, employee_number or full/partial name.
    Raises ToolInputError when nothing or more than one employee matches.
    """
    identifier = (identifier or "").strip()
    if not identifier:
        raise ToolInputError("An employee identifier (employee_id, email, employee_number or name) is required.")

    if _is_uuid(identifier):
        row = db.fetch_one(f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} WHERE e.employee_id = %s", (identifier,))
        if row:
            return row
        raise ToolInputError(f"No employee found with employee_id {identifier}.")

    rows = db.fetch_all(
        f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} "
        "WHERE lower(e.email) = lower(%s) OR lower(e.employee_number) = lower(%s)",
        (identifier, identifier),
    )
    if not rows:
        rows = db.fetch_all(
            f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} "
            "WHERE (e.first_name || ' ' || e.last_name) ILIKE %s ORDER BY e.last_name, e.first_name LIMIT 10",
            (f"%{identifier}%",),
        )
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise ToolInputError(f"No employee matches '{identifier}'. Use find_employees to search.")
    matches = ", ".join(f"{r['first_name']} {r['last_name']} <{r['email']}> ({r['employee_id']})" for r in rows)
    raise ToolInputError(f"'{identifier}' matches several employees: {matches}. Ask the user which one.")


def latest_xgboost_prediction(db, employee_id) -> dict | None:
    return db.fetch_one(
        """
        SELECT p.prediction_id, p.risk_score, p.risk_band, p.model_version, p.predicted_at,
               s.risk_snapshot_id, s.snapshot_date
        FROM risk_prediction p
        JOIN employee_risk_snapshot s ON s.risk_snapshot_id = p.risk_snapshot_id
        WHERE p.employee_id = %s AND p.model_name = %s AND s.is_training_record = false
        ORDER BY s.snapshot_date DESC, p.predicted_at DESC
        LIMIT 1
        """,
        (employee_id, XGBOOST_MODEL_NAME),
    )
