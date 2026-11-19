from datetime import datetime, timedelta, timezone
from fastmcp import FastMCP
from psycopg.types.json import Jsonb
from config import settings
from services.access_scope import team_filter_sql
from services.db_service import SupabaseDBConnectionManager
from services.notify_service import notify_employee_async
from services.shiftguard_repository import (
    INTERVENTION_ACTION_TYPES, INTERVENTION_STATUSES, ToolInputError, dumps, latest_xgboost_prediction,
    resolve_employee,
)
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("ShiftGuard Intervention Tool")

MANAGER_ACTIONS = {"EMAIL_MANAGER", "NOTIFY_MANAGER", "MANAGER_REVIEW"}
BUDDY_ACTIONS = {"EMAIL_BUDDY", "NOTIFY_BUDDY"}
OPEN_OR_DONE = ("PENDING", "IN_PROGRESS", "COMPLETED")

INTERVENTION_SELECT = """
    SELECT i.intervention_id, i.employee_id, e.first_name || ' ' || e.last_name AS employee_name,
           i.prediction_id, i.target_employee_id, t.first_name || ' ' || t.last_name AS target_name,
           t.email AS target_email, i.action_type, i.action_status, i.action_payload, i.failure_reason,
           i.triggered_at, i.completed_at
    FROM intervention i
    JOIN employee e ON e.employee_id = i.employee_id
    LEFT JOIN employee t ON t.employee_id = i.target_employee_id
"""


@mcp.tool()
def create_intervention(employee: str, action_type: str, reason: str, target_employee: str = "",
                        prediction_id: str = "", action_status: str = "PENDING", message: str = "",
                        requested_by_user_id: str = "", allow_duplicate: bool = False) -> str:
    """
    Record a follow-up action for an employee in the `intervention` table, linked to their latest XGBoost
    risk prediction. Use after a HIGH/CRITICAL prediction or when the user asks for a follow-up.

    Args:
        employee: The employee the intervention concerns (employee_id, email, employee_number or name).
        action_type: One of EMAIL_MANAGER, EMAIL_BUDDY, NOTIFY_MANAGER, NOTIFY_BUDDY, MANAGER_REVIEW,
            EMPLOYEE_NUDGE, FOLLOW_UP_CHECKIN, SCHEDULE_CHECKIN, SEND_SURVEY, SEND_MESSAGE, HR_ESCALATION,
            SUGGEST_BUDDY, ASSIGN_MANAGER, REMOVE_MANAGER, ASSIGN_BUDDY, REMOVE_BUDDY, NO_ACTION, OTHER.
        reason: Why the action is needed (stored in action_payload).
        target_employee: Who receives/performs it. Empty -> the employee's manager for manager actions,
            their buddy for buddy actions.
        prediction_id: Risk prediction to link. Empty -> the employee's latest XGBoost prediction.
        action_status: PENDING (default), IN_PROGRESS, COMPLETED, FAILED, CANCELLED or SKIPPED.
        message: Optional message text sent or to be sent (stored in action_payload).
        requested_by_user_id: The user_id from the request context.
        allow_duplicate: False skips creating the same action_type for the employee within
            INTERVENTION_DEDUP_DAYS days and returns the existing one.
    """
    try:
        action_type = (action_type or "").strip().upper()
        action_status = (action_status or "PENDING").strip().upper()
        if action_type not in INTERVENTION_ACTION_TYPES:
            raise ToolInputError(f"action_type must be one of {', '.join(INTERVENTION_ACTION_TYPES)}.")
        if action_status not in INTERVENTION_STATUSES:
            raise ToolInputError(f"action_status must be one of {', '.join(INTERVENTION_STATUSES)}.")
        if not reason.strip():
            raise ToolInputError("A reason is required.")

        with SupabaseDBConnectionManager() as db:
            emp = resolve_employee(db, employee)

            target_id = None
            if target_employee.strip():
                target_id = resolve_employee(db, target_employee, scoped=False)["employee_id"]
            elif action_type in MANAGER_ACTIONS:
                target_id = emp["manager_employee_id"]
                if not target_id:
                    raise ToolInputError(f"{emp['first_name']} {emp['last_name']} has no manager assigned; pass target_employee.")
            elif action_type in BUDDY_ACTIONS:
                target_id = emp["buddy_employee_id"]
                if not target_id:
                    raise ToolInputError(f"{emp['first_name']} {emp['last_name']} has no buddy assigned; pass target_employee.")

            prediction = None
            if prediction_id.strip():
                prediction = db.fetch_one(
                    "SELECT prediction_id, risk_band, risk_score FROM risk_prediction WHERE prediction_id = %s AND employee_id = %s",
                    (prediction_id.strip(), emp["employee_id"]),
                )
                if not prediction:
                    raise ToolInputError(f"prediction_id {prediction_id} does not belong to this employee.")
            else:
                prediction = latest_xgboost_prediction(db, emp["employee_id"])

            if not allow_duplicate:
                since = datetime.now(timezone.utc) - timedelta(days=settings.INTERVENTION_DEDUP_DAYS)
                existing = db.fetch_one(
                    INTERVENTION_SELECT + " WHERE i.employee_id = %s AND i.action_type = %s "
                    "AND i.action_status = ANY(%s) AND i.triggered_at >= %s ORDER BY i.triggered_at DESC LIMIT 1",
                    (emp["employee_id"], action_type, list(OPEN_OR_DONE), since),
                )
                if existing:
                    return dumps({"created": False, "reason": f"A {action_type} intervention already exists in the last "
                                  f"{settings.INTERVENTION_DEDUP_DAYS} days.", "intervention": existing})

            payload = {
                "reason": reason.strip(),
                "source": "shiftguard-agent",
                "risk_band": prediction["risk_band"] if prediction else None,
                "risk_score": float(prediction["risk_score"]) if prediction else None,
            }
            if message.strip():
                payload["message"] = message.strip()
            if requested_by_user_id.strip():
                payload["requested_by_user_id"] = requested_by_user_id.strip()

            row = db.fetch_one(
                """
                INSERT INTO intervention (employee_id, prediction_id, target_employee_id, action_type, action_status,
                                          action_payload, triggered_at, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s, now(), CASE WHEN %s = 'COMPLETED' THEN now() END)
                RETURNING intervention_id
                """,
                (emp["employee_id"], prediction["prediction_id"] if prediction else None, target_id, action_type,
                 action_status, Jsonb(payload), action_status),
            )
            db.connection.commit()
            created = db.fetch_one(INTERVENTION_SELECT + " WHERE i.intervention_id = %s", (row["intervention_id"],))
        if target_id and action_status in ("PENDING", "IN_PROGRESS", "COMPLETED"):
            notify_employee_async(target_id, {
                "kind": "intervention", "intervention_id": str(row["intervention_id"]), "action_type": action_type,
                "employee_id": str(emp["employee_id"]), "employee_name": f"{emp['first_name']} {emp['last_name']}",
            })
        return dumps({"created": True, "intervention": created})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("create_intervention failed")
        return f"Error creating intervention: {e}"


@mcp.tool()
def update_intervention_status(intervention_id: str, action_status: str, failure_reason: str = "") -> str:
    """
    Change the status of an intervention, e.g. to COMPLETED after the notification email was sent,
    or FAILED (with failure_reason) when sending failed.

    Args:
        intervention_id: UUID of the intervention.
        action_status: PENDING, IN_PROGRESS, COMPLETED, FAILED, CANCELLED or SKIPPED.
        failure_reason: Optional text, used with FAILED.
    """
    try:
        action_status = (action_status or "").strip().upper()
        if action_status not in INTERVENTION_STATUSES:
            raise ToolInputError(f"action_status must be one of {', '.join(INTERVENTION_STATUSES)}.")
        with SupabaseDBConnectionManager() as db:
            affected = db.execute(
                """
                UPDATE intervention
                SET action_status = %s,
                    failure_reason = CASE WHEN %s <> '' THEN %s ELSE failure_reason END,
                    completed_at = CASE WHEN %s = 'COMPLETED' THEN now() ELSE completed_at END,
                    updated_at = now()
                WHERE intervention_id = %s
                """,
                (action_status, failure_reason.strip(), failure_reason.strip(), action_status, intervention_id.strip()),
            )
            if not affected:
                raise ToolInputError(f"No intervention with id {intervention_id}.")
            row = db.fetch_one(INTERVENTION_SELECT + " WHERE i.intervention_id = %s", (intervention_id.strip(),))
        return dumps({"updated": True, "intervention": row})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("update_intervention_status failed")
        return f"Error updating intervention: {e}"


@mcp.tool()
def list_interventions(employee: str = "", action_status: str = "", limit: int = 20) -> str:
    """
    List interventions, newest first.

    Args:
        employee: Optional employee filter (employee_id, email, employee_number or name).
        action_status: Optional status filter (PENDING, IN_PROGRESS, COMPLETED, FAILED, CANCELLED, SKIPPED).
        limit: Maximum rows (1-100).
    """
    try:
        limit = max(1, min(int(limit), 100))
        team_sql, params = team_filter_sql("e")
        where = [team_sql.removeprefix(" AND ")] if team_sql else []
        with SupabaseDBConnectionManager() as db:
            if employee.strip():
                where.append("i.employee_id = %s")
                params.append(resolve_employee(db, employee)["employee_id"])
            if action_status.strip():
                status = action_status.strip().upper()
                if status not in INTERVENTION_STATUSES:
                    raise ToolInputError(f"action_status must be one of {', '.join(INTERVENTION_STATUSES)}.")
                where.append("i.action_status = %s")
                params.append(status)
            sql = INTERVENTION_SELECT + (f" WHERE {' AND '.join(where)}" if where else "") + \
                " ORDER BY i.triggered_at DESC LIMIT %s"
            rows = db.fetch_all(sql, (*params, limit))
        return dumps({"count": len(rows), "interventions": rows})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("list_interventions failed")
        return f"Error listing interventions: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
