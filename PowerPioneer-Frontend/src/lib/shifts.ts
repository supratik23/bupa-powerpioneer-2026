import type { Shift, ShiftType } from "../api/types";
import { formatHours, formatTime, label } from "./format";

/** Colour family for a shift type (used by the schedule list and the roster timeline). */
export type ShiftKind = "day" | "long" | "night" | "oncall";

export function shiftKind(type: ShiftType): ShiftKind {
  if (type === "NIGHT") return "night";
  if (type === "LONG_DAY") return "long";
  if (type === "ON_CALL") return "oncall";
  return "day"; // DAY, EARLY, LATE
}

export const SHIFT_KIND_LABEL: Record<ShiftKind, string> = {
  day: "Day / early / late",
  long: "Long day",
  night: "Night",
  oncall: "On call",
};

export interface ShiftFlag {
  id: "understaffed" | "short-notice" | "redeployed" | "missed-break";
  text: string;
}

/** The roster flags stored on shift_roster, as short readable tags. */
export function shiftFlags(shift: Shift): ShiftFlag[] {
  const flags: ShiftFlag[] = [];
  if (shift.understaffed_flag) flags.push({ id: "understaffed", text: "Understaffed" });
  if (shift.short_notice_change_flag) flags.push({ id: "short-notice", text: "Short-notice change" });
  if (shift.redeployment_flag) flags.push({ id: "redeployed", text: "Redeployed" });
  if (shift.missed_break_flag) flags.push({ id: "missed-break", text: "Break missed" });
  return flags;
}

export const shiftTitle = (shift: Shift) => `${label(shift.shift_type)} shift`;
export const shiftRange = (shift: Shift) => `${formatTime(shift.shift_start)}–${formatTime(shift.shift_end)}`;
export const shiftHours = (shift: Shift) => formatHours(Number(shift.actual_hours ?? shift.planned_hours));

export function shiftState(shift: Shift, now = new Date()): "done" | "active" | "upcoming" {
  if (new Date(shift.shift_end) <= now) return "done";
  if (new Date(shift.shift_start) <= now) return "active";
  return "upcoming";
}

export function dayLabel(value: string | Date, now = new Date()): string {
  const date = typeof value === "string" ? new Date(value) : value;
  const diff = Math.round((startOfDay(date).getTime() - startOfDay(now).getTime()) / 86400000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Tomorrow";
  if (diff === -1) return "Yesterday";
  return date.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function startOfDay(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  return d;
}

/** "in 2h 15m" / "in 40 min" style countdown. */
export function untilLabel(target: string | Date, now = new Date()): string {
  const mins = Math.max(0, Math.round((new Date(target).getTime() - now.getTime()) / 60000));
  if (mins < 60) return `${mins} min`;
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  if (h >= 24) return `${Math.round(h / 24)} day${Math.round(h / 24) === 1 ? "" : "s"}`;
  return m ? `${h}h ${m}m` : `${h}h`;
}
