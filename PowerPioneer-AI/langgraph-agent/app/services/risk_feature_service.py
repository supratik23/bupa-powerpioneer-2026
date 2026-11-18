"""
Computes the 26 ShiftGuard risk-model features for one employee and one prediction date D,
following "ShiftGuard Risk Model: Input Specification".

- Dates and the 23:00-06:00 night window are in UTC (the backend runs with TIME_ZONE = "UTC").
- S30 = shift_roster rows with shift_start in [D-29 00:00, D+1 00:00); S90 starts at D-89.
- hours_worked = coalesce(actual_hours, planned_hours).
- NULL stays None (never filled with 0); values are plain int/float, not Decimal, and are not rounded.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any

FEATURE_NAMES = [
    "contracted_hours_30d", "actual_hours_worked_30d", "overtime_hours_30d", "overtime_ratio_30d",
    "night_shifts_30d", "long_shifts_30d", "max_consecutive_work_days", "max_consecutive_night_shifts",
    "minimum_rest_hours_between_shifts", "short_notice_roster_changes_30d", "missed_breaks_30d",
    "unplanned_absence_days_90d", "unplanned_absence_episodes_90d", "late_arrivals_30d",
    "days_since_last_meaningful_leave", "cancelled_or_rejected_leave_90d", "understaffed_shift_ratio_30d",
    "average_patient_load_ratio_30d", "redeployments_90d", "wellbeing_score", "days_since_maternity_return",
    "return_schedule_variance_hours_30d", "overtime_hours_since_maternity_return",
    "maternity_adjustments_fulfilment_ratio", "nursing_or_recovery_breaks_missed_30d", "end_of_life_care_7d",
]

LONG_SHIFT_HOURS = 12.0
NIGHT_WINDOW = (23, 6)
NIGHT_SHIFT_MIN_NIGHT_HOURS = 3.0
MEANINGFUL_LEAVE_MIN_DAYS = 5
MEANINGFUL_LEAVE_TYPES = {"ANNUAL", "STUDY", "COMPASSIONATE", "UNPAID", "MATERNITY", "PATERNITY", "PARENTAL"}
UNPLANNED_ABSENCE_TYPES = {"SICK", "UNPLANNED", "UNAUTHORISED", "FAMILY_EMERGENCY"}
MATERNITY_TRACKING_DAYS = 365
WELLBEING_WINDOW_DAYS = 7

SHIFT_COLUMNS = """
    shift_id, shift_start, shift_end, planned_hours, actual_hours, shift_type,
    expected_patient_load, actual_patient_load, planned_staff_count, actual_staff_count,
    understaffed_flag, missed_break_flag, short_notice_change_flag, redeployment_flag
"""


class NoShiftsInWindow(Exception):
    """The employee has no shifts in S30 and must not be scored (e.g. managers)."""


def _utc(d: date, t: time = time.min) -> datetime:
    return datetime.combine(d, t, tzinfo=timezone.utc)


def _num(value: Any) -> float | None:
    if value is None:
        return None
    return float(value) if isinstance(value, Decimal) else float(value)


def _longest_run(days: set[date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    return best


def night_hours(start: datetime, end: datetime) -> float:
    """Hours of [start, end) inside the 23:00-06:00 UTC night window."""
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)
    night_start_h, night_end_h = NIGHT_WINDOW
    total = 0.0
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        w_start = _utc(day, time(night_start_h))
        w_end = _utc(day + timedelta(days=1), time(night_end_h))
        overlap = (min(end, w_end) - max(start, w_start)).total_seconds()
        if overlap > 0:
            total += overlap / 3600
        day += timedelta(days=1)
    return total


def hours_worked(shift: dict) -> float:
    return _num(shift["actual_hours"] if shift["actual_hours"] is not None else shift["planned_hours"])


def is_night_shift(shift: dict) -> bool:
    return shift["shift_type"] == "NIGHT" or night_hours(shift["shift_start"], shift["shift_end"]) >= NIGHT_SHIFT_MIN_NIGHT_HOURS


def is_long_shift(shift: dict) -> bool:
    duration = (shift["shift_end"] - shift["shift_start"]).total_seconds() / 3600
    return max(duration, hours_worked(shift)) >= LONG_SHIFT_HOURS


def _shift_date(shift: dict) -> date:
    return shift["shift_start"].astimezone(timezone.utc).date()


def _has_end_of_life_flag(db) -> bool:
    row = db.fetch_one(
        "SELECT 1 AS ok FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'shift_roster' AND column_name = 'end_of_life_care_flag'"
    )
    return row is not None


def compute_wellbeing_score(db, employee_id, d: date) -> float | None:
    """#20: mean check-in answer (1-4 scale) over the last 7 days; no responses -> None."""
    row = db.fetch_one(
        """
        SELECT avg(o.normalized_score) AS wellbeing_score, count(*) AS responses
        FROM employee_response r
        JOIN question_option o ON o.option_id = r.option_id
        WHERE r.employee_id = %s AND r.responded_at >= %s AND r.responded_at < %s
        """,
        (employee_id, _utc(d - timedelta(days=WELLBEING_WINDOW_DAYS - 1)), _utc(d + timedelta(days=1))),
    )
    return _num(row["wellbeing_score"]) if row and row["responses"] else None


def compute_features(db, employee: dict, d: date) -> dict[str, Any]:
    """
    Return a dict with all 26 feature keys for `employee` (a row with employee_id, contracted_weekly_hours,
    hire_date, maternity_return_date) at date `d`. Raises NoShiftsInWindow when S30 is empty.
    """
    employee_id = employee["employee_id"]
    end = _utc(d + timedelta(days=1))
    start_30 = _utc(d - timedelta(days=29))
    start_90 = _utc(d - timedelta(days=89))
    date_30, date_90 = d - timedelta(days=29), d - timedelta(days=89)

    shifts_90 = db.fetch_all(
        f"SELECT {SHIFT_COLUMNS} FROM shift_roster WHERE employee_id = %s AND shift_start >= %s AND shift_start < %s "
        "ORDER BY shift_start",
        (employee_id, start_90, end),
    )
    shifts_30 = [s for s in shifts_90 if s["shift_start"] >= start_30]
    if not shifts_30:
        raise NoShiftsInWindow(f"Employee {employee_id} has no shifts between {date_30} and {d}.")

    f: dict[str, Any] = {}

    # -- Hours and overtime (#1-#4) -------------------------------------------
    weekly = _num(employee.get("contracted_weekly_hours"))
    contracted_30 = weekly * 30 / 7 if weekly is not None else 0.0
    actual_30 = sum(hours_worked(s) for s in shifts_30)
    overtime_30 = max(0.0, actual_30 - contracted_30) if contracted_30 > 0 else 0.0
    f["contracted_hours_30d"] = contracted_30
    f["actual_hours_worked_30d"] = actual_30
    f["overtime_hours_30d"] = overtime_30
    f["overtime_ratio_30d"] = overtime_30 / contracted_30 if contracted_30 > 0 else 0.0

    # -- Shift patterns (#5-#11, #17-#19) -------------------------------------
    night_shifts = [s for s in shifts_30 if is_night_shift(s)]
    f["night_shifts_30d"] = len(night_shifts)
    f["long_shifts_30d"] = sum(1 for s in shifts_30 if is_long_shift(s))
    f["max_consecutive_work_days"] = _longest_run({_shift_date(s) for s in shifts_30})
    f["max_consecutive_night_shifts"] = _longest_run({_shift_date(s) for s in night_shifts})
    gaps = [
        max(0.0, (nxt["shift_start"] - prev["shift_end"]).total_seconds() / 3600)
        for prev, nxt in zip(shifts_30, shifts_30[1:])
    ]
    f["minimum_rest_hours_between_shifts"] = min(gaps) if gaps else None
    f["short_notice_roster_changes_30d"] = sum(1 for s in shifts_30 if s["short_notice_change_flag"])
    f["missed_breaks_30d"] = sum(1 for s in shifts_30 if s["missed_break_flag"])

    # -- Attendance (#12-#14) -------------------------------------------------
    attendance = db.fetch_all(
        "SELECT attendance_date, attendance_status, late_minutes, absence_type, absence_episode_id "
        "FROM attendance WHERE employee_id = %s AND attendance_date >= %s AND attendance_date <= %s",
        (employee_id, date_90, d),
    )
    unplanned = [
        a for a in attendance
        if a["attendance_status"] == "ABSENT" and a["absence_type"] in UNPLANNED_ABSENCE_TYPES
    ]
    f["unplanned_absence_days_90d"] = len({a["attendance_date"] for a in unplanned})
    episode_ids = {a["absence_episode_id"] for a in unplanned if a["absence_episode_id"]}
    loose_days = sorted({a["attendance_date"] for a in unplanned if not a["absence_episode_id"]})
    loose_runs = sum(1 for i, day in enumerate(loose_days) if i == 0 or (day - loose_days[i - 1]).days > 1)
    f["unplanned_absence_episodes_90d"] = len(episode_ids) + loose_runs
    f["late_arrivals_30d"] = sum(
        1 for a in attendance
        if a["attendance_date"] >= date_30 and ((a["late_minutes"] or 0) > 0 or a["attendance_status"] == "LATE")
    )

    # -- Leave (#15-#16) ------------------------------------------------------
    leaves = db.fetch_all(
        "SELECT leave_type, start_date, end_date, status, requested_at FROM leave_request WHERE employee_id = %s",
        (employee_id,),
    )
    meaningful_ends = [
        min(lv["end_date"], d) for lv in leaves
        if lv["status"] == "APPROVED" and lv["leave_type"] in MEANINGFUL_LEAVE_TYPES
        and (lv["end_date"] - lv["start_date"]).days + 1 >= MEANINGFUL_LEAVE_MIN_DAYS and lv["start_date"] <= d
    ]
    hire_date = employee.get("hire_date")
    if meaningful_ends:
        f["days_since_last_meaningful_leave"] = (d - max(meaningful_ends)).days
    elif hire_date and hire_date <= d:
        f["days_since_last_meaningful_leave"] = (d - hire_date).days
    else:
        f["days_since_last_meaningful_leave"] = None
    f["cancelled_or_rejected_leave_90d"] = sum(
        1 for lv in leaves
        if lv["status"] in ("CANCELLED", "REJECTED") and start_90 <= lv["requested_at"] < end
    )

    understaffed = sum(
        1 for s in shifts_30
        if s["understaffed_flag"]
        or (s["planned_staff_count"] is not None and s["actual_staff_count"] is not None
            and s["actual_staff_count"] < s["planned_staff_count"])
    )
    f["understaffed_shift_ratio_30d"] = understaffed / len(shifts_30)
    load_ratios = [
        _num(s["actual_patient_load"]) / _num(s["expected_patient_load"])
        for s in shifts_30
        if s["actual_patient_load"] is not None and s["expected_patient_load"] is not None
        and _num(s["expected_patient_load"]) > 0
    ]
    f["average_patient_load_ratio_30d"] = sum(load_ratios) / len(load_ratios) if load_ratios else None
    f["redeployments_90d"] = sum(1 for s in shifts_90 if s["redeployment_flag"])

    # -- Check-in wellbeing (#20) ---------------------------------------------
    f["wellbeing_score"] = compute_wellbeing_score(db, employee_id, d)

    # -- Maternity return (#21-#25) -------------------------------------------
    for key in ("days_since_maternity_return", "return_schedule_variance_hours_30d",
                "overtime_hours_since_maternity_return", "maternity_adjustments_fulfilment_ratio",
                "nursing_or_recovery_breaks_missed_30d"):
        f[key] = None
    ret = employee.get("maternity_return_date")
    if ret and ret <= d:
        days_since = (d - ret).days
        f["days_since_maternity_return"] = days_since
        if days_since <= MATERNITY_TRACKING_DAYS:
            ret_start = _utc(ret)
            since_return_30 = [s for s in shifts_30 if s["shift_start"] >= ret_start]
            all_since_return = db.fetch_all(
                "SELECT planned_hours, actual_hours FROM shift_roster "
                "WHERE employee_id = %s AND shift_start >= %s AND shift_start < %s",
                (employee_id, ret_start, end),
            )
            f["return_schedule_variance_hours_30d"] = sum(
                abs(_num(s["actual_hours"]) - _num(s["planned_hours"]))
                for s in since_return_30 if s["actual_hours"] is not None
            )
            f["overtime_hours_since_maternity_return"] = sum(
                max(0.0, _num(s["actual_hours"]) - _num(s["planned_hours"]))
                for s in all_since_return if s["actual_hours"] is not None
            )
            if since_return_30:
                respected = sum(
                    1 for s in since_return_30
                    if not is_night_shift(s) and not is_long_shift(s) and not s["short_notice_change_flag"]
                )
                f["maternity_adjustments_fulfilment_ratio"] = respected / len(since_return_30)
            f["nursing_or_recovery_breaks_missed_30d"] = sum(1 for s in since_return_30 if s["missed_break_flag"])

    # -- End-of-life care (#26) -----------------------------------------------
    # No app table records it yet -> 0. If shift_roster.end_of_life_care_flag is added later, count it.
    f["end_of_life_care_7d"] = 0
    if _has_end_of_life_flag(db):
        row = db.fetch_one(
            "SELECT count(*) AS n FROM shift_roster WHERE employee_id = %s AND end_of_life_care_flag "
            "AND shift_start >= %s AND shift_start < %s",
            (employee_id, _utc(d - timedelta(days=6)), end),
        )
        f["end_of_life_care_7d"] = int(row["n"])

    missing = [name for name in FEATURE_NAMES if name not in f]
    if missing:  # defensive: the model raises on a missing key
        raise RuntimeError(f"Feature computation is missing keys: {missing}")
    return {name: f[name] for name in FEATURE_NAMES}
