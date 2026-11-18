/** Display helpers shared by pages. */

const AVATAR_COLORS = ["#7c3aed", "#1677ff", "#00a69c", "#f59e0b", "#14b8a6", "#d9475f", "#6f43e8", "#0a4bbf"];

export function initials(name: string | null | undefined): string {
  if (!name) return "?";
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Stable colour per id so avatars keep their colour between renders. */
export function avatarColor(id: string): string {
  let hash = 0;
  for (let i = 0; i < id.length; i += 1) hash = (hash * 31 + id.charCodeAt(i)) >>> 0;
  return AVATAR_COLORS[hash % AVATAR_COLORS.length];
}

/** "LONG_DAY" -> "Long day" */
export function label(code: string | null | undefined): string {
  if (!code) return "—";
  const text = code.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const FEATURE_LABELS: Record<string, string> = {
  overtime_hours_30d: "Overtime hours (30 days)",
  overtime_ratio_30d: "High overtime ratio",
  night_shifts_30d: "Frequent night shifts",
  long_shifts_30d: "Frequent long shifts",
  max_consecutive_work_days: "Consecutive working days",
  max_consecutive_night_shifts: "Consecutive night shifts",
  minimum_rest_hours_between_shifts: "Short rest between shifts",
  short_notice_roster_changes_30d: "Short-notice roster changes",
  missed_breaks_30d: "Missed protected breaks",
  late_arrivals_30d: "Late arrivals",
  days_since_last_meaningful_leave: "Long time since a proper break",
  cancelled_or_rejected_leave_90d: "Cancelled or rejected leave",
  understaffed_shift_ratio_30d: "Understaffed shifts",
  average_patient_load_ratio_30d: "High patient load",
  redeployments_90d: "Redeployments",
  bradford_factor_90d: "Unplanned absence pattern",
  survey_sentiment_30d: "Check-in sentiment",
  overtime_hours_since_maternity_return: "Overtime since maternity return",
  maternity_adjustments_fulfilment_ratio: "Return-to-work adjustments missed",
  nursing_or_recovery_breaks_missed_30d: "Missed nursing / recovery breaks",
  return_schedule_variance_hours_30d: "Schedule variance after return",
  days_since_maternity_return: "Recent return from maternity leave",
  end_of_life_care_7d: "End-of-life care (7 days)",
  wellbeing_score: "Low check-in wellbeing",
};

export function featureLabel(name: string): string {
  return FEATURE_LABELS[name] ?? label(name);
}

/**
 * Supabase stores wellbeing_score as the mean check-in answer on the 1–4
 * question_option.normalized_score scale. The UI shows wellbeing as 0–100.
 */
export const WELLBEING_SCALE = { min: 1, max: 4 } as const;

/** wellbeing_score (1–4) -> 0–100. Values above 4 are legacy 0–100 rule-engine scores and pass through. */
export function wellbeingPercent(score: number | string | null | undefined): number | null {
  if (score === null || score === undefined || score === "") return null;
  const n = Number(score);
  if (!Number.isFinite(n)) return null;
  if (n > WELLBEING_SCALE.max) return Math.min(100, n);
  const pct = ((n - WELLBEING_SCALE.min) / (WELLBEING_SCALE.max - WELLBEING_SCALE.min)) * 100;
  return Math.max(0, Math.min(100, pct));
}

/**
 * Wellbeing change (0–100 points) between the latest snapshot and the one about `days`
 * earlier (the newest snapshot on or before latest − days; else the oldest available).
 * Snapshots are daily, so a day-on-day change is mostly noise — a week is more meaningful.
 */
export function wellbeingChange(
  history: Array<{ snapshot_date: string; wellbeing_score: number | string | null }>,
  days = 7,
): { delta: number; since: string } | null {
  const scored = history
    .map((h) => ({ date: h.snapshot_date, pct: wellbeingPercent(h.wellbeing_score) }))
    .filter((h): h is { date: string; pct: number } => h.pct !== null)
    .sort((a, b) => a.date.localeCompare(b.date));
  if (scored.length < 2) return null;
  const latest = scored[scored.length - 1];
  const cutoff = new Date(`${latest.date}T00:00:00`);
  cutoff.setDate(cutoff.getDate() - days);
  const target = isoDate(cutoff);
  const base = [...scored.slice(0, -1)].reverse().find((h) => h.date <= target) ?? scored[0];
  return { delta: latest.pct - base.pct, since: base.date };
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const date = value.length === 10 ? new Date(`${value}T00:00:00`) : new Date(value);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  return new Date(value).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatTime(value: string | Date): string {
  const date = typeof value === "string" ? new Date(value) : value;
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false });
}

export function formatHours(hours: number): string {
  const whole = Math.floor(hours);
  const minutes = Math.round((hours - whole) * 60);
  return minutes ? `${whole}h ${minutes}m` : `${whole}h`;
}

export function num(value: number | string | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.round(n * 10 ** digits) / 10 ** digits) : "—";
}

/** yyyy-mm-dd in local time. */
export function isoDate(date: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

/** ISO datetime -> value for <input type="datetime-local">. */
export function toLocalInput(value: string | null | undefined): string {
  if (!value) return "";
  const d = new Date(value);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** <input type="datetime-local"> value -> ISO datetime (UTC). */
export function fromLocalInput(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}
