"""
Check-in APIs for PowerPioneer-Frontend (deterministic pipeline; Gemini only writes the next question).

POST /checkin/appointment-completed
    The employee marked an appointment COMPLETED -> return their check-in question (+ options) to show now,
    and generate the NEXT question in the background (held as QUEUED until the next completed appointment).

POST /checkin/answer
    Save the answer (employee_response) -> wellbeing score (mean answer score, last 7 days) -> 26 features ->
    XGBoost risk -> employee_risk_snapshot / risk_prediction / risk_explanation -> tiered follow-up
    (CRITICAL: manager + buddy + check-in, HIGH: manager, MEDIUM: buddy) with emails sent in the background.

Auth: the frontend forwards its Django JWT (Authorization: Bearer ...). The agent asks Django /auth/me/ who the
caller is, so nobody can answer for someone else. AGENT_REQUIRE_AUTH=false allows employee_id in the body
without a token (local testing only).
"""
from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from uuid import UUID

import httpx
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException
from pydantic import BaseModel

# The shared services use the same import roots as the MCP servers (PYTHONPATH = langgraph-agent + app).
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)

from config import settings  # noqa: E402
from services.checkin_service import (  # noqa: E402
    CheckinError, find_queued_question, generate_next_question, record_answer, serve_question, support_for_answer,
)
from services.db_service import SupabaseDBConnectionManager  # noqa: E402
from services.escalation_service import record_interventions, send_intervention_emails  # noqa: E402
from services.notify_service import notify_employee_async  # noqa: E402
from services.risk_feature_service import NoShiftsInWindow, compute_wellbeing_score  # noqa: E402
from services.risk_model_service import score_employee  # noqa: E402
from services.shiftguard_repository import EMPLOYEE_COLUMNS, EMPLOYEE_FROM  # noqa: E402

logger = logging.getLogger(__name__)
checkin_router = APIRouter()


class AppointmentCompletedRequest(BaseModel):
    appointment_id: UUID
    employee_id: UUID | None = None   # only used when AGENT_REQUIRE_AUTH=false and no token is sent


class AnswerRequest(BaseModel):
    question_id: UUID
    option_id: UUID
    employee_id: UUID | None = None   # only used when AGENT_REQUIRE_AUTH=false and no token is sent


# Verified token -> (employee_id, valid-until). The frontend polls /nudges/next every minute; caching avoids
# calling Django /auth/me/ on every request. Kept short so logouts/expiry take effect quickly.
TOKEN_CACHE_SECONDS = 120
_token_cache: dict[str, tuple[str, float]] = {}


def resolve_caller(authorization: str | None, body_employee_id: UUID | str | None) -> str:
    """Return the employee_id of the caller, verified with the Django backend."""
    body_employee_id = str(body_employee_id) if body_employee_id else None
    if authorization and authorization.lower().startswith("bearer "):
        cached = _token_cache.get(authorization)
        if cached and cached[1] > time.monotonic():
            employee_id = cached[0]
            if body_employee_id and body_employee_id != employee_id:
                raise HTTPException(403, "You can only submit check-ins for yourself.")
            return employee_id
        try:
            res = httpx.get(f"{settings.BACKEND_API_BASE_URL.rstrip('/')}/auth/me/",
                            headers={"Authorization": authorization, "Accept": "application/json"}, timeout=10)
        except httpx.HTTPError as e:
            raise HTTPException(503, f"Cannot reach the backend to verify the login: {e}") from e
        if res.status_code in (401, 403):
            raise HTTPException(401, "Login expired or invalid. Please sign in again.")
        if res.status_code != 200:
            raise HTTPException(502, f"Backend login check failed ({res.status_code}).")
        employee_id = str(res.json().get("employee_id") or "")
        if not employee_id:
            raise HTTPException(502, "Backend did not return the employee id.")
        if body_employee_id and body_employee_id != employee_id:
            raise HTTPException(403, "You can only submit check-ins for yourself.")
        if len(_token_cache) > 1000:
            _token_cache.clear()
        _token_cache[authorization] = (employee_id, time.monotonic() + TOKEN_CACHE_SECONDS)
        return employee_id
    if settings.AGENT_REQUIRE_AUTH:
        raise HTTPException(401, "Missing Authorization: Bearer <access token>.")
    if not body_employee_id:
        raise HTTPException(400, "employee_id is required when no token is sent.")
    return body_employee_id


def _queue_next(employee_id: str, appointment_id: str) -> None:
    try:
        result = generate_next_question(employee_id, appointment_id)
        logger.info("Next question for %s: %s", employee_id, result)
    except Exception:
        logger.exception("Generating the next question failed for %s", employee_id)


@checkin_router.post("/appointment-completed")
def appointment_completed(body: AppointmentCompletedRequest, background_tasks: BackgroundTasks,
                          authorization: str | None = Header(default=None)) -> dict:
    """Return the check-in question to show now; generate the next one in the background."""
    employee_id = resolve_caller(authorization, body.employee_id)
    try:
        with SupabaseDBConnectionManager() as db:
            appointment = db.fetch_one(
                "SELECT appointment_id, employee_id, status, title, appointment_type FROM appointment "
                "WHERE appointment_id = %s",
                (str(body.appointment_id),),
            )
            if appointment is None:
                raise HTTPException(404, "Appointment not found.")
            if str(appointment["employee_id"]) != employee_id:
                # e.g. a manager completed it for the employee: the check-in is for the employee, not the caller
                return {"appointment_id": str(body.appointment_id), "question": None,
                        "reason": "The appointment belongs to another employee; no check-in is shown to you."}
            if (appointment["status"] or "").upper() != "COMPLETED":
                raise HTTPException(409, "The appointment is not marked COMPLETED.")

            question, served_from = serve_question(db, employee_id, appointment)
            needs_next = find_queued_question(db, employee_id) is None
    except HTTPException:
        raise
    except CheckinError as e:
        raise HTTPException(e.status, str(e)) from e
    except Exception as e:
        logger.exception("appointment-completed failed")
        raise HTTPException(500, f"Could not load the check-in question: {e}") from e

    if needs_next:
        background_tasks.add_task(_queue_next, employee_id, str(body.appointment_id))
    return {
        "appointment_id": str(body.appointment_id),
        "question": question,
        "served_from": served_from,
        "next_question": "generating" if needs_next else "already_queued",
    }


@checkin_router.post("/answer")
def answer(body: AnswerRequest, background_tasks: BackgroundTasks,
           authorization: str | None = Header(default=None)) -> dict:
    """Save the answer, recalculate wellbeing + risk, store the prediction and trigger follow-up actions."""
    employee_id = resolve_caller(authorization, body.employee_id)
    today = datetime.now(timezone.utc).date()
    try:
        with SupabaseDBConnectionManager() as db:
            saved = record_answer(db, employee_id, str(body.question_id), str(body.option_id))
            support = support_for_answer(db, str(body.question_id), str(body.option_id))
            employee = db.fetch_one(f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} WHERE e.employee_id = %s", (employee_id,))
            risk, skipped_reason, actions = None, None, []
            try:
                summary = score_employee(db, employee, today, save=True)
                risk = {k: summary[k] for k in ("snapshot_date", "risk_band", "risk_score", "risk_probability",
                                                "prediction_id", "top_factors", "model_version")}
                wellbeing = summary["features"]["wellbeing_score"]
                actions = record_interventions(db, employee, risk)
            except NoShiftsInWindow as e:
                skipped_reason = f"Risk not calculated: {e}"
                wellbeing = compute_wellbeing_score(db, employee_id, today)
    except CheckinError as e:
        raise HTTPException(e.status, str(e)) from e
    except Exception as e:
        logger.exception("answer failed")
        raise HTTPException(500, f"Could not process the answer: {e}") from e

    if any(a["action_status"] == "PENDING" and a["action_type"].startswith("EMAIL_") for a in actions):
        background_tasks.add_task(send_intervention_emails, employee, risk, actions)
    for a in actions:   # real-time bell for the manager / buddy (best effort)
        if a["action_status"] == "PENDING" and a.get("target_employee_id"):
            payload = {"kind": "intervention", "intervention_id": a["intervention_id"], "action_type": a["action_type"],
                       "employee_id": employee_id, "employee_name": f"{employee['first_name']} {employee['last_name']}"}
            if a["target_role"] == "manager":
                payload["risk_band"] = risk["risk_band"]       # buddies never see risk levels
            notify_employee_async(a["target_employee_id"], payload)

    return {
        **saved,
        "question_id": str(body.question_id),
        "option_id": str(body.option_id),
        "wellbeing_score_7d": wellbeing,
        "risk": risk,
        "risk_skipped_reason": skipped_reason,
        "actions": [{k: a[k] for k in ("intervention_id", "action_type", "action_status", "target_role")} for a in actions],
        "support": support,   # {title, message} after a low answer, shown to the employee; never includes risk
    }
