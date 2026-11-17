"""
Feature extraction: turns raw roster / attendance / leave / survey rows into the
columns of ``employee_risk_snapshot`` for one employee and one snapshot date.

Windows are inclusive of the snapshot date and reach back 30 or 90 days.
All date logic uses the project timezone (settings.TIME_ZONE).
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Max, Min
from django.utils import timezone

from rostering.models import (
    UNPLANNED_ABSENCE_TYPES,
    AttendanceStatus,
    LeaveStatus,
    LeaveType,
    ShiftType,
)

# --- tunables ---------------------------------------------------------------
LONG_SHIFT_HOURS = 12.0                 # a shift this long or longer is "long"
NIGHT_WINDOW = (23, 6)                  # 23:00 -> 06:00 counts as night time
NIGHT_SHIFT_MIN_NIGHT_HOURS = 3.0       # >= 3h inside the night window => night shift
MEANINGFUL_LEAVE_MIN_DAYS = 5           # approved non-sick leave of >= 5 days counts as a real break
MEANINGFUL_LEAVE_TYPES = {
    LeaveType.ANNUAL, LeaveType.STUDY, LeaveType.COMPASSIONATE, LeaveType.UNPAID,
    LeaveType.MATERNITY, LeaveType.PATERNITY, LeaveType.PARENTAL,
}
MATERNITY_TRACKING_DAYS = 365           # maternity-return metrics are tracked for a year
SURVEY_WINDOW_DAYS = 30


def _aware(d: date, t: time = time.min) -> datetime:
    return timezone.make_aware(datetime.combine(d, t))


def _local_date(dt: datetime) -> date:
    return timezone.localtime(dt).date()


def _longest_run(days: set[date]) -> int:
    best = run = 0
    prev = None
    for d in sorted(days):
        run = run + 1 if prev is not None and (d - prev).days == 1 else 1
        best = max(best, run)
        prev = d
    return best


def night_hours(start: datetime, end: datetime) -> float:
    """Hours of [start, end) that fall within the 23:00-06:00 night window (local time)."""
    start, end = timezone.localtime(start), timezone.localtime(end)
    night_start_h, night_end_h = NIGHT_WINDOW
    total = 0.0
    day = start.date() - timedelta(days=1)
    while day <= end.date():
        w_start = timezone.make_aware(datetime.combine(day, time(night_start_h)), start.tzinfo)
        w_end = timezone.make_aware(datetime.combine(day + timedelta(days=1), time(night_end_h)), start.tzinfo)
        overlap = (min(end, w_end) - max(start, w_start)).total_seconds()
        if overlap > 0:
            total += overlap / 3600
        day += timedelta(days=1)
    return total


def is_night_shift(shift) -> bool:
    return shift.shift_type == ShiftType.NIGHT or night_hours(shift.shift_start, shift.shift_end) >= NIGHT_SHIFT_MIN_NIGHT_HOURS


def is_long_shift(shift) -> bool:
    duration = (shift.shift_end - shift.shift_start).total_seconds() / 3600
    return max(duration, shift.hours_worked) >= LONG_SHIFT_HOURS


def _dec(value, places=4):
    if value is None:
        return None
    return Decimal(str(round(float(value), places)))


@dataclass
class FeatureSet:
    """Snapshot columns plus the survey signal (not stored as a column)."""

    columns: dict = field(default_factory=dict)
    survey_score: float | None = None      # 0..1, higher is better
    survey_responses: int = 0


def extract_features(employee, snapshot_date: date) -> FeatureSet:
    d = snapshot_date
    end = _aware(d + timedelta(days=1))           # exclusive upper bound
    start_30 = _aware(d - timedelta(days=29))
    start_90 = _aware(d - timedelta(days=89))
    date_30, date_90 = d - timedelta(days=29), d - timedelta(days=89)

    shifts_90 = list(
        employee.shifts.filter(shift_start__gte=start_90, shift_start__lt=end).order_by("shift_start")
    )
    shifts_30 = [s for s in shifts_90 if s.shift_start >= start_30]

    c: dict = {}

    # -- hours & overtime ---------------------------------------------------
    weekly = float(employee.contracted_weekly_hours or 0)
    contracted_30 = weekly * 30 / 7
    actual_30 = sum(s.hours_worked for s in shifts_30)
    overtime_30 = max(0.0, actual_30 - contracted_30) if contracted_30 > 0 else 0.0
    c["contracted_hours_30d"] = _dec(contracted_30)
    c["actual_hours_worked_30d"] = _dec(actual_30)
    c["overtime_hours_30d"] = _dec(overtime_30)
    c["overtime_ratio_30d"] = _dec(overtime_30 / contracted_30 if contracted_30 > 0 else 0)

    # -- shift patterns -----------------------------------------------------
    night_shifts = [s for s in shifts_30 if is_night_shift(s)]
    c["night_shifts_30d"] = len(night_shifts)
    c["long_shifts_30d"] = sum(1 for s in shifts_30 if is_long_shift(s))
    c["max_consecutive_work_days"] = _longest_run({_local_date(s.shift_start) for s in shifts_30})
    c["max_consecutive_night_shifts"] = _longest_run({_local_date(s.shift_start) for s in night_shifts})

    gaps = [
        max(0.0, (nxt.shift_start - prev.shift_end).total_seconds() / 3600)
        for prev, nxt in zip(shifts_30, shifts_30[1:])
    ]
    c["minimum_rest_hours_between_shifts"] = _dec(min(gaps)) if gaps else None

    c["short_notice_roster_changes_30d"] = sum(1 for s in shifts_30 if s.short_notice_change_flag)
    c["missed_breaks_30d"] = sum(1 for s in shifts_30 if s.missed_break_flag)
    c["redeployments_90d"] = sum(1 for s in shifts_90 if s.redeployment_flag)

    understaffed = sum(
        1 for s in shifts_30
        if s.understaffed_flag
        or (s.planned_staff_count is not None and s.actual_staff_count is not None
            and s.actual_staff_count < s.planned_staff_count)
    )
    c["understaffed_shift_ratio_30d"] = _dec(understaffed / len(shifts_30) if shifts_30 else 0)

    load_ratios = [
        float(s.actual_patient_load) / float(s.expected_patient_load)
        for s in shifts_30
        if s.actual_patient_load is not None and s.expected_patient_load
    ]
    c["average_patient_load_ratio_30d"] = _dec(sum(load_ratios) / len(load_ratios)) if load_ratios else None

    # -- attendance ---------------------------------------------------------
    attendance_90 = list(employee.attendance.filter(attendance_date__gte=date_90, attendance_date__lte=d))
    unplanned = [
        a for a in attendance_90
        if a.attendance_status == AttendanceStatus.ABSENT and a.absence_type in UNPLANNED_ABSENCE_TYPES
    ]
    c["unplanned_absence_days_90d"] = len({a.attendance_date for a in unplanned})
    episode_ids = {a.absence_episode_id for a in unplanned if a.absence_episode_id}
    loose_days = sorted({a.attendance_date for a in unplanned if not a.absence_episode_id})
    loose_episodes = sum(1 for i, day in enumerate(loose_days) if i == 0 or (day - loose_days[i - 1]).days > 1)
    c["unplanned_absence_episodes_90d"] = len(episode_ids) + loose_episodes
    c["late_arrivals_30d"] = sum(
        1 for a in attendance_90
        if a.attendance_date >= date_30 and (a.late_minutes > 0 or a.attendance_status == AttendanceStatus.LATE)
    )

    # -- leave --------------------------------------------------------------
    leaves = list(employee.leave_requests.all())
    meaningful_ends = [
        min(lv.end_date, d) for lv in leaves
        if lv.status == LeaveStatus.APPROVED and lv.leave_type in MEANINGFUL_LEAVE_TYPES
        and lv.duration_days >= MEANINGFUL_LEAVE_MIN_DAYS and lv.start_date <= d
    ]
    if meaningful_ends:
        c["days_since_last_meaningful_leave"] = (d - max(meaningful_ends)).days
    elif employee.hire_date and employee.hire_date <= d:
        c["days_since_last_meaningful_leave"] = (d - employee.hire_date).days
    else:
        c["days_since_last_meaningful_leave"] = None
    c["cancelled_or_rejected_leave_90d"] = sum(
        1 for lv in leaves
        if lv.status in (LeaveStatus.CANCELLED, LeaveStatus.REJECTED) and start_90 <= lv.requested_at < end
    )

    # -- maternity return ---------------------------------------------------
    for key in ("days_since_maternity_return", "return_schedule_variance_hours_30d",
                "overtime_hours_since_maternity_return", "maternity_adjustments_fulfilment_ratio",
                "nursing_or_recovery_breaks_missed_30d"):
        c[key] = None
    ret = employee.maternity_return_date
    if ret and ret <= d:
        days_since = (d - ret).days
        c["days_since_maternity_return"] = days_since
        if days_since <= MATERNITY_TRACKING_DAYS:
            ret_start = _aware(ret)
            since_return_30 = [s for s in shifts_30 if s.shift_start >= ret_start]
            all_since_return = list(employee.shifts.filter(shift_start__gte=ret_start, shift_start__lt=end))
            c["return_schedule_variance_hours_30d"] = _dec(sum(
                abs(float(s.actual_hours) - float(s.planned_hours))
                for s in since_return_30 if s.actual_hours is not None
            ))
            c["overtime_hours_since_maternity_return"] = _dec(sum(
                max(0.0, float(s.actual_hours) - float(s.planned_hours))
                for s in all_since_return if s.actual_hours is not None
            ))
            if since_return_30:
                respected = sum(
                    1 for s in since_return_30
                    if not is_night_shift(s) and not is_long_shift(s) and not s.short_notice_change_flag
                )
                c["maternity_adjustments_fulfilment_ratio"] = _dec(respected / len(since_return_30))
            c["nursing_or_recovery_breaks_missed_30d"] = sum(1 for s in since_return_30 if s.missed_break_flag)

    # -- survey -------------------------------------------------------------
    fs = FeatureSet(columns=c)
    responses = list(
        employee.responses.select_related("option")
        .filter(responded_at__gte=_aware(d - timedelta(days=SURVEY_WINDOW_DAYS - 1)), responded_at__lt=end)
    )
    if responses:
        from surveys.models import QuestionOption

        bounds = {
            row["question_id"]: (row["lo"], row["hi"])
            for row in QuestionOption.objects.filter(question_id__in={r.question_id for r in responses})
            .values("question_id").annotate(lo=Min("normalized_score"), hi=Max("normalized_score"))
        }
        values = []
        for r in responses:
            lo, hi = bounds.get(r.question_id, (0, 0))
            values.append((r.option.normalized_score - lo) / (hi - lo) if hi > lo else 0.5)
        fs.survey_score = sum(values) / len(values)
        fs.survey_responses = len(values)
    return fs
