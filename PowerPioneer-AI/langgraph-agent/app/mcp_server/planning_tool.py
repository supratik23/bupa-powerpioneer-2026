"""
ShiftGuard planning tools: what-if risk simulation, roster look-ahead, shift cover, leave review and buddy matching.

Read-only tools (never write): simulate_risk, review_upcoming_roster, list_shifts, suggest_shift_cover,
list_leave_requests, review_leave_request, suggest_buddy, search_wellbeing_guidance.
Write tools (the chat agent asks the manager to approve them first): reassign_shift, decide_leave_request, assign_buddy.

All simulations run the same XGBoost model as the real scoring, but never save a prediction.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastmcp import FastMCP
from psycopg.types.json import Jsonb

from services.access_scope import team_filter_sql
from services.db_service import SupabaseDBConnectionManager
from services.escalation_service import FEATURE_LABELS
from services.notify_service import notify_employee_async
from services.risk_feature_service import (
    FEATURE_NAMES, MEANINGFUL_LEAVE_MIN_DAYS, MEANINGFUL_LEAVE_TYPES, NoShiftsInWindow, _utc, compute_features,
    compute_wellbeing_score, hours_worked,
)
from services.risk_model_service import get_risk_model, predict
from services.shiftguard_repository import (
    EMPLOYEE_COLUMNS, EMPLOYEE_FROM, RISK_BAND_ORDER, ToolInputError, dumps, latest_xgboost_prediction, parse_date,
    resolve_employee,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("ShiftGuard Planning Tool")

try:  # load numpy/xgboost in the main thread (see risk_tool.py)
    get_risk_model()
except Exception:
    logger.exception("Risk model could not be loaded at startup; the tools will report the error.")

MIN_REST_HOURS = 11            # rest needed between two shifts for a cover candidate
SHORT_NOTICE_HOURS = 72        # a reassignment this close to the start counts as a short-notice change
MAX_BUDDY_LOAD = 3             # people one buddy can support
GUIDANCE_FILE = Path(__file__).resolve().parents[1] / "knowledge" / "wellbeing_guidance.md"

SHIFT_SELECT = """
    SELECT s.shift_id, s.employee_id, e.first_name || ' ' || e.last_name AS employee_name, s.shift_start, s.shift_end,
           s.planned_hours, s.actual_hours, s.shift_type, s.location, s.understaffed_flag, s.short_notice_change_flag
    FROM shift_roster s JOIN employee e ON e.employee_id = s.employee_id
"""


# ---------------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------------
def _label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature.replace("_", " "))


def _name(row: dict) -> str:
    return f"{row['first_name']} {row['last_name']}".strip()


def _score(db, employee: dict, d, exclude: set[str] | None = None, overrides: dict | None = None,
           wellbeing_fallback: float | None = None) -> tuple[dict, dict]:
    """Features + model result without saving. A missing wellbeing_score (future date) uses wellbeing_fallback."""
    features = compute_features(db, employee, d, exclude)
    if features["wellbeing_score"] is None and wellbeing_fallback is not None:
        features["wellbeing_score"] = wellbeing_fallback
    if overrides:
        features.update(overrides)
    return features, predict(features)


def _summary(result: dict) -> dict:
    return {
        "risk_band": result["risk_band"],
        "risk_score": round(result["risk_probability"] * 100, 1),
        "top_factors": [
            {"factor": _label(f["feature"]), "feature": f["feature"], "value": f["value"],
             "effect": "increases risk" if f["direction"] == "INCREASES_RISK" else "decreases risk"}
            for f in result["top_factors"][:3]
        ],
    }


def _changed_features(before: dict, after: dict) -> list[dict]:
    changes = []
    for name in FEATURE_NAMES:
        a, b = before.get(name), after.get(name)
        if a != b and not (a is None and b is None):
            changes.append({"factor": _label(name), "feature": name,
                            "before": round(a, 2) if isinstance(a, float) else a,
                            "after": round(b, 2) if isinstance(b, float) else b})
    return changes


def _parse_overrides(text: str, base: dict) -> dict:
    """JSON object feature -> number (absolute) or "+N"/"-N" (relative to the scenario value)."""
    if not (text or "").strip():
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError:
        raise ToolInputError('feature_overrides must be a JSON object, e.g. {"night_shifts_30d": "-2"}.') from None
    if not isinstance(raw, dict):
        raise ToolInputError("feature_overrides must be a JSON object.")
    out = {}
    for name, value in raw.items():
        if name not in FEATURE_NAMES:
            raise ToolInputError(f"Unknown feature '{name}'. Valid features: {', '.join(FEATURE_NAMES)}.")
        if isinstance(value, str) and re.fullmatch(r"\s*[+-]\s*\d+(\.\d+)?\s*", value):
            out[name] = max(0.0, float(base.get(name) or 0) + float(value.replace(" ", "")))
        else:
            try:
                out[name] = float(value)
            except (TypeError, ValueError):
                raise ToolInputError(f"Value for {name} must be a number or '+N'/'-N'.") from None
    return out


def _band_change(before: str, after: str) -> str:
    diff = RISK_BAND_ORDER.get(after, 0) - RISK_BAND_ORDER.get(before, 0)
    return "up" if diff > 0 else "down" if diff < 0 else "same"


def _overlaps(db, employee_id, start, end, rest_hours: float = 0, ignore_shift_id=None) -> list[dict]:
    pad = timedelta(hours=rest_hours)
    return db.fetch_all(
        "SELECT shift_id, shift_start, shift_end, shift_type FROM shift_roster WHERE employee_id = %s "
        "AND shift_start < %s AND shift_end > %s AND shift_id IS DISTINCT FROM %s",
        (employee_id, end + pad, start - pad, ignore_shift_id),
    )


def _get_shift(db, shift_id: str) -> dict:
    try:
        row = db.fetch_one(SHIFT_SELECT + " WHERE s.shift_id = %s", ((shift_id or "").strip(),))
    except Exception:
        row = None
    if not row:
        raise ToolInputError(f"No shift with id {shift_id}. Use list_shifts or get_employee_details to find shift ids.")
    return row


# ---------------------------------------------------------------------------------------------------------
# what-if
# ---------------------------------------------------------------------------------------------------------
@mcp.tool()
def simulate_risk(employee: str, remove_shift_ids: list[str] | None = None, feature_overrides: str = "",
                  as_of_date: str = "") -> str:
    """
    What-if simulation: how would an employee's burnout risk change if their roster or workload changed?
    Runs the XGBoost model twice (baseline and scenario) WITHOUT saving anything.

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        remove_shift_ids: Shifts to take off them (ids from list_shifts / get_employee_details). When a removed
            shift is in the future, both scores are projected to the day of the latest removed shift, using the
            planned roster up to then.
        feature_overrides: Optional JSON object of model features to change, absolute ("night_shifts_30d": 4) or
            relative ("overtime_hours_30d": "-10"). Feature names are the 26 model features, e.g.
            night_shifts_30d, overtime_hours_30d, missed_breaks_30d, max_consecutive_work_days, wellbeing_score.
        as_of_date: YYYY-MM-DD. Defaults to today (UTC).

    Returns baseline and scenario band/score, the change, the features that changed and the scenario's top factors.
    """
    try:
        d = parse_date(as_of_date)
        today = datetime.now(timezone.utc).date()
        remove = [s.strip() for s in (remove_shift_ids or []) if s and s.strip()]
        if not remove and not (feature_overrides or "").strip():
            raise ToolInputError("Give remove_shift_ids and/or feature_overrides to simulate a change.")
        with SupabaseDBConnectionManager() as db:
            emp = resolve_employee(db, employee)
            for sid in remove:
                shift = _get_shift(db, sid)
                if str(shift["employee_id"]) != str(emp["employee_id"]):
                    raise ToolInputError(f"Shift {sid} belongs to {shift['employee_name']}, not {_name(emp)}.")
                d = max(d, shift["shift_start"].astimezone(timezone.utc).date())
            wellbeing_now = compute_wellbeing_score(db, emp["employee_id"], today)
            base_features, base = _score(db, emp, d, wellbeing_fallback=wellbeing_now)
            scen_features = compute_features(db, emp, d, set(remove)) if remove else dict(base_features)
            if scen_features["wellbeing_score"] is None:
                scen_features["wellbeing_score"] = wellbeing_now
            scen_features.update(_parse_overrides(feature_overrides, scen_features))
            scenario = predict(scen_features)
        b, s = _summary(base), _summary(scenario)
        return dumps({
            "employee": _name(emp),
            "scored_for_date": d,
            "projected": d > today,
            "saved": False,
            "baseline": b,
            "scenario": s,
            "risk_score_change": round(s["risk_score"] - b["risk_score"], 1),
            "band_change": _band_change(b["risk_band"], s["risk_band"]),
            "changed_features": _changed_features(base_features, scen_features),
            "note": "Simulation only - nothing was saved. Prototype model on synthetic data, not a clinical assessment.",
        })
    except NoShiftsInWindow as e:
        return f"Skipped: {e}"
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("simulate_risk failed")
        return f"Error running the simulation: {e}"


@mcp.tool()
def review_upcoming_roster(days_ahead: int = 7, department: str = "") -> str:
    """
    Roster look-ahead: projects every team member's risk to `days_ahead` days from today using the PLANNED roster,
    and flags who the upcoming rota pushes into a higher band. Use before publishing or changing a rota, or for
    "is next week's roster safe?". Nothing is saved.

    Args:
        days_ahead: 1-28 days.
        department: Optional department filter.
    """
    try:
        days_ahead = max(1, min(int(days_ahead), 28))
        today = datetime.now(timezone.utc).date()
        target = today + timedelta(days=days_ahead)
        team_sql, params = team_filter_sql("e")
        if department.strip():
            team_sql += " AND lower(e.department) = lower(%s)"
            params.append(department.strip())
        results, skipped = [], []
        with SupabaseDBConnectionManager() as db:
            employees = db.fetch_all(
                f"""SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM}
                    WHERE e.is_active = true AND EXISTS (SELECT 1 FROM shift_roster s WHERE s.employee_id = e.employee_id
                      AND s.shift_start >= %s AND s.shift_start < %s) {team_sql}
                    ORDER BY e.last_name, e.first_name""",
                [_utc(today - timedelta(days=29)), _utc(target + timedelta(days=1)), *params],
            )
            for emp in employees:
                try:
                    wellbeing = compute_wellbeing_score(db, emp["employee_id"], today)
                    _, now = _score(db, emp, today)
                    _, later = _score(db, emp, target, wellbeing_fallback=wellbeing)
                    upcoming = db.fetch_all(
                        "SELECT shift_id, shift_start, shift_type, planned_hours FROM shift_roster WHERE employee_id = %s "
                        "AND shift_start >= %s AND shift_start < %s ORDER BY shift_start",
                        (emp["employee_id"], _utc(today + timedelta(days=1)), _utc(target + timedelta(days=1))),
                    )
                    results.append({
                        "employee_id": emp["employee_id"],
                        "name": _name(emp),
                        "now": {"risk_band": now["risk_band"], "risk_score": round(now["risk_probability"] * 100, 1)},
                        "projected": {"risk_band": later["risk_band"],
                                      "risk_score": round(later["risk_probability"] * 100, 1)},
                        "band_change": _band_change(now["risk_band"], later["risk_band"]),
                        "upcoming_shifts": len(upcoming),
                        "upcoming_night_shifts": sum(1 for s in upcoming if s["shift_type"] == "NIGHT"),
                        "upcoming_hours": round(sum(float(s["planned_hours"] or 0) for s in upcoming), 1),
                        "projected_top_factor": _label(later["top_factors"][0]["feature"]) if later["top_factors"] else None,
                    })
                except NoShiftsInWindow:
                    skipped.append(_name(emp))
        results.sort(key=lambda r: (r["band_change"] != "up", -r["projected"]["risk_score"]))
        rising = [r for r in results if r["band_change"] == "up"]
        return dumps({
            "today": today, "projected_to": target, "employees_checked": len(results),
            "moving_to_higher_band": len(rising),
            "summary": [f"{r['name']}: {r['now']['risk_band']} -> {r['projected']['risk_band']}" for r in rising],
            "employees": results, "skipped": skipped, "saved": False,
        })
    except Exception as e:
        logger.exception("review_upcoming_roster failed")
        return f"Error reviewing the roster: {e}"


# ---------------------------------------------------------------------------------------------------------
# shifts and cover
# ---------------------------------------------------------------------------------------------------------
@mcp.tool()
def list_shifts(employee: str = "", start_date: str = "", days: int = 7, shift_type: str = "") -> str:
    """
    Rostered shifts (with shift_id) for one employee or the whole team, from start_date for `days` days.
    Use it to find the shift_id for "Thursday's night shift" before simulate_risk, suggest_shift_cover or
    reassign_shift.

    Args:
        employee: Optional employee (employee_id, email, employee_number or name). Empty = whole team.
        start_date: YYYY-MM-DD, defaults to today (UTC).
        days: 1-31.
        shift_type: Optional filter, e.g. DAY, NIGHT, EARLY, LATE, LONG_DAY.
    """
    try:
        d = parse_date(start_date)
        days = max(1, min(int(days), 31))
        where, params = ["s.shift_start >= %s", "s.shift_start < %s"], [_utc(d), _utc(d + timedelta(days=days))]
        with SupabaseDBConnectionManager() as db:
            if employee.strip():
                where.append("s.employee_id = %s")
                params.append(resolve_employee(db, employee)["employee_id"])
            else:
                team_sql, team_params = team_filter_sql("e")
                if team_sql:
                    where.append(team_sql.removeprefix(" AND "))
                    params += team_params
            if shift_type.strip():
                where.append("upper(s.shift_type) = upper(%s)")
                params.append(shift_type.strip())
            rows = db.fetch_all(SHIFT_SELECT + f" WHERE {' AND '.join(where)} ORDER BY s.shift_start LIMIT 200", params)
        for r in rows:
            r["weekday"] = r["shift_start"].astimezone(timezone.utc).strftime("%A")
        return dumps({"from": d, "days": days, "count": len(rows), "shifts": rows})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("list_shifts failed")
        return f"Error listing shifts: {e}"


@mcp.tool()
def suggest_shift_cover(shift_id: str, limit: int = 5) -> str:
    """
    Who could cover a shift? Ranks colleagues who are free (no overlapping shift and at least 11 h rest either
    side), lowest risk first, then fewest hours worked in the last 30 days. Read-only.

    Args:
        shift_id: The shift to cover.
        limit: 1-10 candidates.
    """
    try:
        limit = max(1, min(int(limit), 10))
        with SupabaseDBConnectionManager() as db:
            shift = _get_shift(db, shift_id)
            owner = resolve_employee(db, str(shift["employee_id"]))
            team_sql, params = team_filter_sql("e")
            candidates = db.fetch_all(
                f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} WHERE e.is_active = true AND e.employee_id <> %s "
                f"AND (lower(coalesce(e.department, '')) = lower(coalesce(%s, '')) OR e.job_role = %s) {team_sql}",
                [owner["employee_id"], owner["department"], owner["job_role"], *params],
            )
            ranked = []
            since = _utc(datetime.now(timezone.utc).date() - timedelta(days=29))
            for c in candidates:
                if _overlaps(db, c["employee_id"], shift["shift_start"], shift["shift_end"], 0):
                    continue            # already working then
                rest_ok = not _overlaps(db, c["employee_id"], shift["shift_start"], shift["shift_end"], MIN_REST_HOURS)
                worked = db.fetch_all(
                    "SELECT planned_hours, actual_hours FROM shift_roster WHERE employee_id = %s "
                    "AND shift_start >= %s AND shift_start < now()",
                    (c["employee_id"], since),
                )
                if not worked:          # managers / people who are not rostered
                    continue
                latest = latest_xgboost_prediction(db, c["employee_id"])
                band = latest["risk_band"] if latest else "UNKNOWN"
                if band in ("HIGH", "CRITICAL"):
                    continue
                ranked.append({
                    "employee_id": c["employee_id"], "name": _name(c), "job_role": c["job_role"],
                    "same_role": c["job_role"] == owner["job_role"],
                    "latest_risk_band": band,
                    "hours_last_30d": round(sum(hours_worked(w) for w in worked), 1),
                    "rest_ok": rest_ok,
                    "warning": None if rest_ok else f"less than {MIN_REST_HOURS} h rest next to another shift",
                })
        ranked.sort(key=lambda r: (not r["rest_ok"], not r["same_role"],
                                   RISK_BAND_ORDER.get(r["latest_risk_band"], 1), r["hours_last_30d"]))
        return dumps({
            "shift": shift, "current_employee": _name(owner), "candidates": ranked[:limit],
            "rules": (f"not already working then; HIGH/CRITICAL risk excluded; people with {MIN_REST_HOURS} h rest "
                      "either side first (others are flagged with a warning)"),
            "next_step": "Use simulate_risk to compare, then reassign_shift (needs the manager's approval).",
        })
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("suggest_shift_cover failed")
        return f"Error suggesting cover: {e}"


@mcp.tool()
def reassign_shift(shift_id: str, new_employee: str, reason: str) -> str:
    """
    Move a shift to another employee (writes shift_roster). REQUIRES the manager's approval - the app asks them
    before this runs. Refuses if the new employee already has an overlapping shift. A change within 72 h of the
    start is flagged as a short-notice change. Both employees are notified in the app.

    Args:
        shift_id: The shift to move.
        new_employee: Who takes it (employee_id, email, employee_number or name).
        reason: Why (stored on an intervention record).
    """
    try:
        if not reason.strip():
            raise ToolInputError("A reason is required.")
        with SupabaseDBConnectionManager() as db:
            shift = _get_shift(db, shift_id)
            owner = resolve_employee(db, str(shift["employee_id"]))
            new = resolve_employee(db, new_employee)
            if str(new["employee_id"]) == str(owner["employee_id"]):
                raise ToolInputError("The shift already belongs to that employee.")
            clash = _overlaps(db, new["employee_id"], shift["shift_start"], shift["shift_end"], 0, shift["shift_id"])
            if clash:
                raise ToolInputError(f"{_name(new)} already has a shift at that time ({clash[0]['shift_start']}).")
            short_notice = shift["shift_start"] - datetime.now(timezone.utc) < timedelta(hours=SHORT_NOTICE_HOURS)
            connection = db.db_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE shift_roster SET employee_id = %s, short_notice_change_flag = short_notice_change_flag OR %s, "
                        "updated_at = now() WHERE shift_id = %s",
                        (new["employee_id"], short_notice, shift["shift_id"]),
                    )
                    cursor.execute(
                        "INSERT INTO intervention (employee_id, prediction_id, target_employee_id, action_type, action_status, "
                        "action_payload, triggered_at, completed_at) VALUES (%s, %s, %s, 'OTHER', 'COMPLETED', %s, now(), now())",
                        (owner["employee_id"],
                         (latest_xgboost_prediction(db, owner["employee_id"]) or {}).get("prediction_id"),
                         new["employee_id"],
                         Jsonb({"source": "shiftguard-agent", "kind": "SHIFT_REASSIGNED", "shift_id": str(shift["shift_id"]),
                                "shift_start": shift["shift_start"].isoformat(), "reason": reason.strip(),
                                "short_notice": short_notice})),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        when = shift["shift_start"].astimezone(timezone.utc).strftime("%a %d %b %H:%M UTC")
        for person, text in ((new, f"You've been asked to cover the {shift['shift_type'].lower()} shift on {when}."),
                             (owner, f"Your {shift['shift_type'].lower()} shift on {when} has been covered by a colleague.")):
            notify_employee_async(person["employee_id"], {"kind": "shift_change", "shift_id": str(shift["shift_id"]),
                                                          "message": text})
        return dumps({"reassigned": True, "shift_id": shift["shift_id"], "from": _name(owner), "to": _name(new),
                      "shift_start": shift["shift_start"], "short_notice_change": short_notice})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("reassign_shift failed")
        return f"Error reassigning the shift: {e}"


# ---------------------------------------------------------------------------------------------------------
# leave
# ---------------------------------------------------------------------------------------------------------
LEAVE_SELECT = """
    SELECT l.leave_request_id, l.employee_id, e.first_name || ' ' || e.last_name AS employee_name, l.leave_type,
           l.start_date, l.end_date, (l.end_date - l.start_date + 1) AS days, l.status, l.requested_at, l.decision_at
    FROM leave_request l JOIN employee e ON e.employee_id = l.employee_id
"""


@mcp.tool()
def list_leave_requests(status: str = "PENDING", employee: str = "", limit: int = 20) -> str:
    """
    Leave requests for the team (or one employee), newest first.

    Args:
        status: PENDING (default), APPROVED, REJECTED, CANCELLED or ALL.
        employee: Optional employee filter.
        limit: 1-100.
    """
    try:
        limit = max(1, min(int(limit), 100))
        status = (status or "PENDING").strip().upper()
        where, params = [], []
        with SupabaseDBConnectionManager() as db:
            if employee.strip():
                where.append("l.employee_id = %s")
                params.append(resolve_employee(db, employee)["employee_id"])
            else:
                team_sql, team_params = team_filter_sql("e")
                if team_sql:
                    where.append(team_sql.removeprefix(" AND "))
                    params += team_params
            if status != "ALL":
                where.append("l.status = %s")
                params.append(status)
            rows = db.fetch_all(LEAVE_SELECT + (f" WHERE {' AND '.join(where)}" if where else "")
                                + " ORDER BY l.requested_at DESC LIMIT %s", (*params, limit))
        return dumps({"count": len(rows), "leave_requests": rows})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("list_leave_requests failed")
        return f"Error listing leave requests: {e}"


@mcp.tool()
def review_leave_request(leave_request_id: str) -> str:
    """
    Decision support for a leave request: the employee's risk now, if the leave is rejected (one more rejected
    request in 90 days) and after the leave is taken (a proper break resets 'time since last meaningful leave').
    Nothing is saved; the manager decides.

    Args:
        leave_request_id: The leave request id (from list_leave_requests).
    """
    try:
        today = datetime.now(timezone.utc).date()
        with SupabaseDBConnectionManager() as db:
            leave = db.fetch_one(LEAVE_SELECT + " WHERE l.leave_request_id = %s", ((leave_request_id or "").strip(),))
            if not leave:
                raise ToolInputError(f"No leave request with id {leave_request_id}.")
            emp = resolve_employee(db, str(leave["employee_id"]))
            features, now = _score(db, emp, today)
            rejected = predict({**features, "cancelled_or_rejected_leave_90d": (features["cancelled_or_rejected_leave_90d"] or 0) + 1})
            meaningful = leave["leave_type"] in MEANINGFUL_LEAVE_TYPES and leave["days"] >= MEANINGFUL_LEAVE_MIN_DAYS
            after = predict({**features, "days_since_last_meaningful_leave": 1}) if meaningful else now
        return dumps({
            "leave_request": leave,
            "counts_as_meaningful_break": meaningful,
            "why_not_meaningful": None if meaningful else
                f"Only {', '.join(sorted(MEANINGFUL_LEAVE_TYPES))} leave of {MEANINGFUL_LEAVE_MIN_DAYS}+ days resets the model's rest clock.",
            "days_since_last_meaningful_leave": features["days_since_last_meaningful_leave"],
            "risk_now": _summary(now),
            "if_rejected": _summary(rejected),
            "after_the_leave": _summary(after),
            "note": "Simulation only. Prototype model on synthetic data, not a clinical assessment.",
        })
    except NoShiftsInWindow as e:
        return f"Skipped: {e}"
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("review_leave_request failed")
        return f"Error reviewing the leave request: {e}"


@mcp.tool()
def decide_leave_request(leave_request_id: str, decision: str, comment: str = "") -> str:
    """
    Approve or reject a PENDING leave request (writes leave_request). REQUIRES the manager's approval - the app
    asks them before this runs. The employee is notified in the app.

    Args:
        leave_request_id: The leave request id.
        decision: APPROVED or REJECTED.
        comment: Optional note to the employee.
    """
    try:
        decision = (decision or "").strip().upper()
        if decision not in ("APPROVED", "REJECTED"):
            raise ToolInputError("decision must be APPROVED or REJECTED.")
        with SupabaseDBConnectionManager() as db:
            leave = db.fetch_one(LEAVE_SELECT + " WHERE l.leave_request_id = %s", ((leave_request_id or "").strip(),))
            if not leave:
                raise ToolInputError(f"No leave request with id {leave_request_id}.")
            resolve_employee(db, str(leave["employee_id"]))       # scope check
            if leave["status"] != "PENDING":
                raise ToolInputError(f"The request is already {leave['status']}.")
            db.execute("UPDATE leave_request SET status = %s, decision_at = now(), updated_at = now() "
                       "WHERE leave_request_id = %s", (decision, leave["leave_request_id"]))
        verb = "approved" if decision == "APPROVED" else "not approved"
        message = f"Your {leave['leave_type'].lower()} leave from {leave['start_date']} to {leave['end_date']} was {verb}."
        if comment.strip():
            message += f" Note: {comment.strip()}"
        notify_employee_async(leave["employee_id"], {"kind": "leave_decision", "leave_request_id": str(leave["leave_request_id"]),
                                                     "status": decision, "message": message})
        return dumps({"updated": True, "leave_request_id": leave["leave_request_id"], "employee": leave["employee_name"],
                      "status": decision})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("decide_leave_request failed")
        return f"Error deciding the leave request: {e}"


# ---------------------------------------------------------------------------------------------------------
# buddies
# ---------------------------------------------------------------------------------------------------------
@mcp.tool()
def suggest_buddy(employee: str, limit: int = 3) -> str:
    """
    Suggest peer-support buddies for an employee: same department or location, rostered on overlapping shifts
    (last and next 14 days), supporting fewer than 3 people already, and not at HIGH/CRITICAL risk themselves.
    Candidates' own risk data is never shown. Read-only.

    Args:
        employee: employee_id (UUID), email, employee_number or name.
        limit: 1-5.
    """
    try:
        limit = max(1, min(int(limit), 5))
        now = datetime.now(timezone.utc)
        with SupabaseDBConnectionManager() as db:
            emp = resolve_employee(db, employee)
            candidates = db.fetch_all(
                f"""SELECT {EMPLOYEE_COLUMNS},
                       (SELECT count(*) FROM employee x WHERE x.buddy_employee_id = e.employee_id AND x.is_active) AS buddy_load
                    {EMPLOYEE_FROM}
                    WHERE e.is_active = true AND e.employee_id <> %s AND e.employee_id IS DISTINCT FROM %s
                      AND (lower(coalesce(e.department, '')) = lower(coalesce(%s, ''))
                           OR lower(coalesce(e.location, '')) = lower(coalesce(%s, '')))""",
                (emp["employee_id"], emp["manager_employee_id"], emp["department"], emp["location"]),
            )
            ranked = []
            for c in candidates:
                if c["buddy_load"] >= MAX_BUDDY_LOAD:
                    continue
                latest = latest_xgboost_prediction(db, c["employee_id"])
                if latest and latest["risk_band"] in ("HIGH", "CRITICAL"):
                    continue
                overlap = db.fetch_one(
                    """SELECT count(*) AS n FROM shift_roster a JOIN shift_roster b
                         ON a.shift_start < b.shift_end AND b.shift_start < a.shift_end
                       WHERE a.employee_id = %s AND b.employee_id = %s AND a.shift_start >= %s AND a.shift_start < %s""",
                    (emp["employee_id"], c["employee_id"], now - timedelta(days=14), now + timedelta(days=14)),
                )["n"]
                score = overlap * 2 + (3 if c["job_role"] == emp["job_role"] else 0) \
                    + (2 if (c["department"] or "").lower() == (emp["department"] or "").lower() else 0) - c["buddy_load"]
                reasons = [f"{overlap} overlapping shifts in the last/next 14 days"]
                if c["job_role"] == emp["job_role"]:
                    reasons.append(f"same role ({c['job_role']})")
                reasons.append(f"currently buddies {c['buddy_load']} colleague(s)")
                ranked.append({"employee_id": c["employee_id"], "name": _name(c), "job_role": c["job_role"],
                               "department": c["department"], "match_score": score, "why": "; ".join(reasons)})
        ranked.sort(key=lambda r: -r["match_score"])
        current = f"{emp['buddy_first_name']} {emp['buddy_last_name']}" if emp["buddy_employee_id"] else None
        return dumps({"employee": _name(emp), "current_buddy": current, "suggestions": ranked[:limit],
                      "next_step": "assign_buddy (needs the manager's approval)."})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("suggest_buddy failed")
        return f"Error suggesting a buddy: {e}"


@mcp.tool()
def assign_buddy(employee: str, buddy: str, reason: str = "") -> str:
    """
    Set an employee's peer-support buddy (writes employee.buddy_employee_id and an ASSIGN_BUDDY intervention).
    REQUIRES the manager's approval - the app asks them before this runs. The new buddy is notified in the app.

    Args:
        employee: The employee who gets a buddy.
        buddy: The colleague who becomes their buddy (may be in another team).
        reason: Optional reason.
    """
    try:
        with SupabaseDBConnectionManager() as db:
            emp = resolve_employee(db, employee)
            mate = resolve_employee(db, buddy, scoped=False)
            if str(mate["employee_id"]) == str(emp["employee_id"]):
                raise ToolInputError("An employee cannot be their own buddy.")
            if not mate["is_active"]:
                raise ToolInputError(f"{_name(mate)} is not active.")
            connection = db.db_connection()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE employee SET buddy_employee_id = %s, updated_at = now() WHERE employee_id = %s",
                                   (mate["employee_id"], emp["employee_id"]))
                    cursor.execute(
                        "INSERT INTO intervention (employee_id, prediction_id, target_employee_id, action_type, action_status, "
                        "action_payload, triggered_at, completed_at) VALUES (%s, %s, %s, 'ASSIGN_BUDDY', 'COMPLETED', %s, now(), now())",
                        (emp["employee_id"], (latest_xgboost_prediction(db, emp["employee_id"]) or {}).get("prediction_id"),
                         mate["employee_id"],
                         Jsonb({"source": "shiftguard-agent", "reason": reason.strip() or None,
                                "previous_buddy_id": str(emp["buddy_employee_id"]) if emp["buddy_employee_id"] else None})),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        notify_employee_async(mate["employee_id"], {
            "kind": "buddy_assigned", "employee_id": str(emp["employee_id"]), "employee_name": _name(emp),
            "message": f"You're now {emp['first_name']}'s peer-support buddy. A friendly hello goes a long way!",
        })
        return dumps({"assigned": True, "employee": _name(emp), "buddy": _name(mate)})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("assign_buddy failed")
        return f"Error assigning the buddy: {e}"


# ---------------------------------------------------------------------------------------------------------
# guidance
# ---------------------------------------------------------------------------------------------------------
_STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "is", "are", "what", "how", "should",
              "i", "we", "do", "with", "about", "my", "our", "can", "be", "it", "they", "their", "after", "when"}


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    return {w.rstrip("s") if len(w) > 3 else w for w in words if w not in _STOPWORDS}


def _guidance_sections() -> list[tuple[str, str]]:
    text = GUIDANCE_FILE.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]
    return [(s.split("\n", 1)[0].strip(), s.split("\n", 1)[1].strip() if "\n" in s else "") for s in sections]


@mcp.tool()
def search_wellbeing_guidance(query: str, limit: int = 3) -> str:
    """
    Search the organisation's wellbeing guidance (rest rules, breaks, night shifts, end-of-life care debriefs,
    return to work, employee assistance, leave). Use it to ground advice to managers and quote the guidance title.

    Args:
        query: What the manager needs, e.g. "rest between night shifts" or "support after a patient death".
        limit: 1-5 sections.
    """
    try:
        wanted = _terms(query)
        if not wanted:
            raise ToolInputError("Give a few words to search for.")
        scored = []
        for title, body in _guidance_sections():
            title_terms, body_terms = _terms(title), _terms(body)
            score = 3 * len(wanted & title_terms) + len(wanted & body_terms)
            if score:
                scored.append((score, title, body))
        scored.sort(key=lambda s: -s[0])
        hits = [{"title": t, "guidance": b} for _, t, b in scored[:max(1, min(int(limit), 5))]]
        return dumps({"query": query, "results": hits,
                      "source": "ShiftGuard wellbeing guidance (prototype content - replace with approved policy)"})
    except ToolInputError as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("search_wellbeing_guidance failed")
        return f"Error searching guidance: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio")
