"""
Risk-based follow-up actions after a check-in answer is scored (tiered policy):

    CRITICAL  EMAIL_MANAGER + EMAIL_BUDDY + SCHEDULE_CHECKIN (manager, within 48 h)
    HIGH      EMAIL_MANAGER
    MEDIUM    EMAIL_BUDDY            (no buddy assigned -> recorded as SKIPPED)
    LOW       nothing

Each action is an `intervention` row linked to the prediction. The same action_type is not repeated for an
employee within INTERVENTION_DEDUP_DAYS (unless the earlier one FAILED or was CANCELLED), so answering several
check-ins a day does not spam managers. Rows are created synchronously as PENDING; emails are sent afterwards
(background) and the row becomes COMPLETED or FAILED.

Privacy: managers get the band, score and plain-language drivers, never the check-in answers.
Buddies get a friendly nudge only, with no scores.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from psycopg.types.json import Jsonb

from config import settings

logger = logging.getLogger(__name__)

ESCALATION_POLICY: dict[str, list[str]] = {
    "CRITICAL": ["EMAIL_MANAGER", "EMAIL_BUDDY", "SCHEDULE_CHECKIN"],
    "HIGH": ["EMAIL_MANAGER"],
    "MEDIUM": ["EMAIL_BUDDY"],
    "MODERATE": ["EMAIL_BUDDY"],
    "LOW": [],
}
TARGETS = {"EMAIL_MANAGER": "manager", "SCHEDULE_CHECKIN": "manager", "EMAIL_BUDDY": "buddy"}
EMAIL_ACTIONS = {"EMAIL_MANAGER", "EMAIL_BUDDY"}
DEDUP_STATUSES = ("PENDING", "IN_PROGRESS", "COMPLETED", "SKIPPED")

FEATURE_LABELS = {
    "contracted_hours_30d": "contracted hours (30 days)",
    "actual_hours_worked_30d": "hours worked (30 days)",
    "overtime_hours_30d": "overtime hours (30 days)",
    "overtime_ratio_30d": "overtime relative to contract",
    "night_shifts_30d": "night shifts (30 days)",
    "long_shifts_30d": "12h+ shifts (30 days)",
    "max_consecutive_work_days": "consecutive working days",
    "max_consecutive_night_shifts": "consecutive night shifts",
    "minimum_rest_hours_between_shifts": "short rest between shifts",
    "short_notice_roster_changes_30d": "short-notice roster changes",
    "missed_breaks_30d": "missed breaks (30 days)",
    "unplanned_absence_days_90d": "unplanned absence days (90 days)",
    "unplanned_absence_episodes_90d": "unplanned absence episodes (90 days)",
    "late_arrivals_30d": "late arrivals (30 days)",
    "days_since_last_meaningful_leave": "time since last proper break/leave",
    "cancelled_or_rejected_leave_90d": "cancelled or rejected leave (90 days)",
    "understaffed_shift_ratio_30d": "share of understaffed shifts",
    "average_patient_load_ratio_30d": "patient load vs expected",
    "redeployments_90d": "redeployments (90 days)",
    "wellbeing_score": "recent check-in answers",
    "days_since_maternity_return": "recent return from maternity leave",
    "return_schedule_variance_hours_30d": "schedule changes since return",
    "overtime_hours_since_maternity_return": "overtime since return",
    "maternity_adjustments_fulfilment_ratio": "agreed return-to-work adjustments not met",
    "nursing_or_recovery_breaks_missed_30d": "missed nursing/recovery breaks",
    "end_of_life_care_7d": "end-of-life care in the last 7 days",
}
RECOMMENDED = {
    "CRITICAL": "Please arrange a supportive 1:1 within the next 48 hours.",
    "HIGH": "Please arrange a supportive check-in this week.",
}


def _drivers(top_factors: list[dict]) -> str:
    increasing = [f for f in top_factors if f.get("direction") == "INCREASES_RISK"][:3]
    return "; ".join(FEATURE_LABELS.get(f["feature"], f["feature"].replace("_", " ")) for f in increasing) or "several workload factors"


def _recently_done(db, employee_id, action_type) -> bool:
    if settings.INTERVENTION_DEDUP_DAYS <= 0:      # duplicate check disabled: always act
        return False
    since = datetime.now(timezone.utc) - timedelta(days=settings.INTERVENTION_DEDUP_DAYS)
    return db.fetch_one(
        "SELECT 1 FROM intervention WHERE employee_id = %s AND action_type = %s AND action_status = ANY(%s) "
        "AND triggered_at >= %s LIMIT 1",
        (employee_id, action_type, list(DEDUP_STATUSES), since),
    ) is not None


def record_interventions(db, employee: dict, risk: dict) -> list[dict]:
    """Create the intervention rows the policy requires for this prediction. Returns what was created."""
    band = risk["risk_band"]
    people = {
        "manager": (employee.get("manager_employee_id"), employee.get("manager_email"),
                    f"{employee.get('manager_first_name') or ''} {employee.get('manager_last_name') or ''}".strip()),
        "buddy": (employee.get("buddy_employee_id"), employee.get("buddy_email"),
                  f"{employee.get('buddy_first_name') or ''} {employee.get('buddy_last_name') or ''}".strip()),
    }
    created = []
    connection = db.db_connection()
    try:
        for action_type in ESCALATION_POLICY.get(band, []):
            if _recently_done(db, employee["employee_id"], action_type):
                logger.info("Skipping duplicate %s for %s", action_type, employee["employee_id"])
                continue
            role = TARGETS[action_type]
            target_id, target_email, target_name = people[role]
            status, failure = "PENDING", None
            if not target_id:
                status, failure = ("SKIPPED", f"No {role} assigned.") if role == "buddy" else ("FAILED", f"No {role} assigned.")
            elif action_type in EMAIL_ACTIONS and not target_email:
                status, failure = "FAILED", f"The {role} has no email address."
            payload = {
                "source": "shiftguard-checkin",
                "risk_band": band,
                "risk_score": risk["risk_score"],
                "snapshot_date": risk["snapshot_date"],
                "top_drivers": [f["feature"] for f in risk["top_factors"] if f.get("direction") == "INCREASES_RISK"][:3],
            }
            if action_type == "SCHEDULE_CHECKIN":
                payload["within_hours"] = 48
            row = db.fetch_one(
                """
                INSERT INTO intervention (employee_id, prediction_id, target_employee_id, action_type, action_status,
                                          action_payload, failure_reason, triggered_at, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, now(), CASE WHEN %s IN ('FAILED', 'SKIPPED') THEN now() END)
                RETURNING intervention_id
                """,
                (employee["employee_id"], risk["prediction_id"], target_id, action_type, status, Jsonb(payload),
                 failure, status),
            )
            created.append({
                "intervention_id": str(row["intervention_id"]), "action_type": action_type, "action_status": status,
                "failure_reason": failure, "target_role": role, "target_email": target_email, "target_name": target_name,
                "target_employee_id": str(target_id) if target_id else None,
            })
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return created


def _set_status(db, intervention_id: str, status: str, failure: str | None = None):
    db.execute(
        "UPDATE intervention SET action_status = %s, failure_reason = %s, "
        "completed_at = CASE WHEN %s IN ('COMPLETED', 'FAILED') THEN now() ELSE completed_at END, updated_at = now() "
        "WHERE intervention_id = %s",
        (status, failure, status, intervention_id),
    )


def _send_with_retry(send_email, recipients, subject, text, html, attempts: int = 3) -> None:
    """Retry temporary SMTP failures (dropped connection, timeout, 4xx). Auth/config errors fail immediately."""
    import smtplib
    import time

    for attempt in range(1, attempts + 1):
        try:
            send_email(recipients, subject, text, html)
            return
        except smtplib.SMTPAuthenticationError:
            raise
        except smtplib.SMTPResponseException as e:
            if not 400 <= e.smtp_code < 500 or attempt == attempts:     # 5xx = permanent (e.g. 525 IP blocked)
                raise
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, TimeoutError, OSError):
            if attempt == attempts:
                raise
        logger.warning("Email attempt %d/%d failed; retrying", attempt, attempts)
        time.sleep(2 * attempt)


def send_intervention_emails(employee: dict, risk: dict, interventions: list[dict]) -> None:
    """Background job: send the emails for PENDING email interventions and record the outcome."""
    from services.db_service import SupabaseDBConnectionManager
    from mcp_server.notifsend_tool import build_notification_content, send_email

    name = f"{employee['first_name']} {employee['last_name']}".strip()
    for item in interventions:
        if item["action_type"] not in EMAIL_ACTIONS or item["action_status"] != "PENDING":
            continue
        try:
            if item["action_type"] == "EMAIL_MANAGER":
                subject, text, html = build_notification_content("risk_alert", {
                    "employee_name": name,
                    "risk_band": risk["risk_band"],
                    "risk_score": risk["risk_score"],
                    "snapshot_date": risk["snapshot_date"],
                    "key_factors": _drivers(risk["top_factors"]),
                    "recommended_action": RECOMMENDED.get(risk["risk_band"], "Please check in with them."),
                })
            else:
                subject, text, html = build_notification_content("general", {
                    "subject": f"{employee['first_name']} could use a friendly check-in",
                    "message": (f"Hi {item['target_name'] or 'there'},\n\n"
                                f"As {employee['first_name']}'s buddy, you're in a great position to help. "
                                "They've had a demanding stretch recently - a quick chat, a coffee break together "
                                "or simply asking how they're doing can make a real difference.\n\n"
                                "Thank you for looking out for your colleague."),
                })
            _send_with_retry(send_email, [item["target_email"]], subject, text, html)
            status, failure = "COMPLETED", None
        except Exception as e:  # SMTP not configured / auth failure / network
            logger.warning("Email for intervention %s failed: %s", item["intervention_id"], e)
            status, failure = "FAILED", str(e)[:500]
        try:
            with SupabaseDBConnectionManager() as db:
                _set_status(db, item["intervention_id"], status, failure)
        except Exception:
            logger.exception("Could not update intervention %s", item["intervention_id"])
