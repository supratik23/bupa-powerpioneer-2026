import type { Employee, RiskSnapshot, Shift } from "../api/types";
import { formatHours, label } from "./format";
import { startOfDay } from "./shifts";

/**
 * Maternity return-to-work support, derived entirely from existing Supabase data
 * (there is no plan table):
 *
 *  - Eligible:    employee.maternity_return_date is set and is within the last RETURN_PLAN_WEEKS weeks.
 *  - Week N of M: weeks elapsed since maternity_return_date, over a fixed RETURN_PLAN_WEEKS phased return.
 *  - Check-in:    weekly, on the same weekday as the return date.
 *  - Guidelines:  checked against the latest employee_risk_snapshot:
 *      Protected rest breaks         nursing_or_recovery_breaks_missed_30d = 0
 *      Predictable shift pattern     return_schedule_variance_hours_30d <= MAX_VARIANCE_HOURS
 *      Gradual workload increase     overtime_hours_since_maternity_return <= MAX_OVERTIME_HOURS
 *    plus "adjustments honoured" = maternity_adjustments_fulfilment_ratio.
 */
export const RETURN_PLAN_WEEKS = 12;
export const MAX_VARIANCE_HOURS = 4;
export const MAX_OVERTIME_HOURS = 5;

const DAY = 86400000;
const hrs = (v: number) => (v < 1 ? `${Math.round(v * 60)} min` : formatHours(v));

export interface Guideline {
  label: string;
  /** true = being met, false = not being met, null = no data yet */
  met: boolean | null;
  detail: string;
}

export interface ReturnPlan {
  returnDate: Date;
  daysSince: number;
  week: number;
  totalWeeks: number;
  /** 0–1 through the phased-return window */
  progress: number;
  nextCheckIn: Date;
  guidelines: Guideline[];
  /** maternity_adjustments_fulfilment_ratio as 0–100, or null */
  adjustmentsPct: number | null;
  onTrack: boolean;
}

/** Employees with a maternity return date inside the phased-return window. */
export function isReturning(employee: Pick<Employee, "maternity_return_date"> | null | undefined, today = new Date()): boolean {
  if (!employee?.maternity_return_date) return false;
  const days = Math.floor((startOfDay(today).getTime() - new Date(`${employee.maternity_return_date}T00:00:00`).getTime()) / DAY);
  return days >= 0 && days < RETURN_PLAN_WEEKS * 7;
}

function nextWeekday(returnDate: Date, today: Date): Date {
  const d = startOfDay(today);
  const diff = (returnDate.getDay() - d.getDay() + 7) % 7;
  return new Date(d.getTime() + diff * DAY);
}

export function buildReturnPlan(
  employee: Pick<Employee, "maternity_return_date">,
  snapshot: RiskSnapshot | null,
  today = new Date(),
): ReturnPlan | null {
  if (!isReturning(employee, today)) return null;
  const returnDate = new Date(`${employee.maternity_return_date}T00:00:00`);
  const daysSince = Math.floor((startOfDay(today).getTime() - returnDate.getTime()) / DAY);
  const n = (v: unknown) => (v === null || v === undefined ? null : Number(v));

  const missedBreaks = n(snapshot?.nursing_or_recovery_breaks_missed_30d);
  const variance = n(snapshot?.return_schedule_variance_hours_30d);
  const overtime = n(snapshot?.overtime_hours_since_maternity_return);
  const ratio = n(snapshot?.maternity_adjustments_fulfilment_ratio);

  const guidelines: Guideline[] = [
    {
      label: "Protected rest breaks",
      met: missedBreaks === null ? null : missedBreaks === 0,
      detail: missedBreaks === null ? "Not tracked yet" : missedBreaks === 0 ? "No breaks missed" : `${missedBreaks} missed in 30 days`,
    },
    {
      label: "Predictable shift pattern",
      met: variance === null ? null : variance <= MAX_VARIANCE_HOURS,
      detail: variance === null ? "Not tracked yet" : `${hrs(variance)} schedule variance`,
    },
    {
      label: "Gradual workload increase",
      met: overtime === null ? null : overtime <= MAX_OVERTIME_HOURS,
      detail: overtime === null ? "Not tracked yet" : `${hrs(overtime)} overtime since return`,
    },
  ];

  return {
    returnDate,
    daysSince,
    week: Math.min(RETURN_PLAN_WEEKS, Math.floor(daysSince / 7) + 1),
    totalWeeks: RETURN_PLAN_WEEKS,
    progress: Math.min(1, (daysSince + 1) / (RETURN_PLAN_WEEKS * 7)),
    nextCheckIn: nextWeekday(returnDate, today),
    guidelines,
    adjustmentsPct: ratio === null ? null : Math.round(ratio * 100),
    onTrack: guidelines.every((g) => g.met !== false),
  };
}

/** "Today" / "Mon 23 Nov" */
export function checkInLabel(date: Date, today = new Date()): string {
  if (startOfDay(date).getTime() === startOfDay(today).getTime()) return "Today";
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

/** Today's supported pattern from the roster: today's shift length, else "Off today". */
export function todaysPattern(shifts: Shift[], today = new Date()): { value: string; helper: string } {
  const key = startOfDay(today).getTime();
  const todays = shifts.find((s) => startOfDay(new Date(s.shift_start)).getTime() === key);
  const next = shifts.find((s) => new Date(s.shift_start) > today && startOfDay(new Date(s.shift_start)).getTime() !== key);
  const hours = (s: Shift) => `${formatHours(Number(s.planned_hours))} ${label(s.shift_type).toLowerCase()} shift`;
  if (todays) return { value: hours(todays), helper: "Rostered today" };
  return {
    value: "Off today",
    helper: next
      ? `Next: ${new Date(next.shift_start).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })} · ${formatHours(Number(next.planned_hours))}`
      : "No upcoming shifts",
  };
}

/** "3 shifts this week · avg 8h 30m" from the employee's shifts in the current Mon–Sun week. */
export function weekPattern(shifts: Shift[], today = new Date()): string {
  const d = startOfDay(today);
  const monday = new Date(d.getTime() - ((d.getDay() + 6) % 7) * DAY);
  const sunday = new Date(monday.getTime() + 7 * DAY);
  const week = shifts.filter((s) => new Date(s.shift_start) >= monday && new Date(s.shift_start) < sunday);
  if (!week.length) return "No shifts this week";
  const avg = week.reduce((sum, s) => sum + Number(s.planned_hours), 0) / week.length;
  return `${week.length} shift${week.length === 1 ? "" : "s"} this week · avg ${formatHours(avg)}`;
}
