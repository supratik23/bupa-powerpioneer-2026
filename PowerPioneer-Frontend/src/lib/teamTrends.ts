import type { RiskSnapshot } from "../api/types";
import { featureLabel } from "./format";

/** One point per week, oldest first. null = no snapshots that week. */
export interface WeeklyPoint {
  weekStart: Date;
  /** Average wellbeing_score (0–100). */
  wellbeing: number | null;
  /** Average hours worked as % of contracted hours (actual_hours_worked_30d / contracted_hours_30d). */
  workload: number | null;
  /** Average overtime_ratio_30d as a percentage. */
  overtime: number | null;
  /** Average missed_breaks_30d. */
  missedBreaks: number | null;
}

const WEEK = 7 * 86400000;

const avg = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);

function startOfWeek(date: Date): Date {
  const d = new Date(date);
  d.setHours(0, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); // Monday
  return d;
}

/** Buckets risk snapshots into the last `weeks` calendar weeks and averages them. */
export function weeklySeries(snapshots: RiskSnapshot[], weeks: number, now = new Date()): WeeklyPoint[] {
  const thisWeek = startOfWeek(now).getTime();
  const buckets = Array.from({ length: weeks }, (_, i) => ({
    weekStart: new Date(thisWeek - (weeks - 1 - i) * WEEK),
    rows: [] as RiskSnapshot[],
  }));
  snapshots.forEach((s) => {
    const index = weeks - 1 - Math.floor((thisWeek - startOfWeek(new Date(s.snapshot_date)).getTime()) / WEEK);
    if (index >= 0 && index < weeks) buckets[index].rows.push(s);
  });
  return buckets.map(({ weekStart, rows }) => ({
    weekStart,
    wellbeing: avg(rows.filter((r) => r.wellbeing_score != null).map((r) => Number(r.wellbeing_score))),
    workload: avg(
      rows
        .filter((r) => Number(r.contracted_hours_30d) > 0)
        .map((r) => (Number(r.actual_hours_worked_30d) / Number(r.contracted_hours_30d)) * 100),
    ),
    overtime: avg(rows.map((r) => Number(r.overtime_ratio_30d) * 100)),
    missedBreaks: avg(rows.map((r) => Number(r.missed_breaks_30d))),
  }));
}

/** Plain-language insight from the weekly series (rule-based, no AI call). */
export function trendInsight(series: WeeklyPoint[]): { title: string; text: string; rising: boolean } | null {
  const known = (key: keyof Omit<WeeklyPoint, "weekStart">) =>
    series.map((p) => p[key]).filter((v): v is number => v != null);
  const workload = known("workload");
  const wellbeing = known("wellbeing");
  const overtime = known("overtime");
  if (workload.length < 2 && wellbeing.length < 2) return null;

  // Consecutive week-on-week rises in overtime at the end of the window.
  let streak = 0;
  for (let i = overtime.length - 1; i > 0 && overtime[i] > overtime[i - 1]; i -= 1) streak += 1;

  const change = (values: number[]) => (values.length >= 2 ? values[values.length - 1] - values[0] : 0);
  const workDelta = change(workload);
  const wellDelta = change(wellbeing);
  const parts: string[] = [];
  if (streak >= 2) parts.push(`Overtime has risen for ${streak} consecutive weeks`);
  else if (overtime.length >= 2) parts.push(`Overtime is ${change(overtime) >= 0 ? "up" : "down"} ${Math.abs(change(overtime)).toFixed(1)} pts over the period`);
  if (wellbeing.length >= 2) parts.push(`average wellbeing ${wellDelta >= 0 ? "rose" : "fell"} ${Math.abs(wellDelta).toFixed(0)} pts`);

  const rising = workDelta > 2 || wellDelta < -2 || streak >= 2;
  const title = rising
    ? "Workload pressure is increasing."
    : wellDelta > 2
      ? "Wellbeing is improving."
      : "Patterns are broadly stable.";
  const text = parts.length ? `${parts.join(", while ")}.` : "Not enough history yet to describe a trend.";
  return { title, text: text.charAt(0).toUpperCase() + text.slice(1), rising };
}

/** Week-over-week change for the factor bars, from the last two weeks with data. */
function lastChange(series: WeeklyPoint[], key: "overtime" | "workload" | "missedBreaks"): number | null {
  const values = series.map((p) => p[key]).filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const [prev, last] = values.slice(-2);
  if (!prev) return null;
  return Math.round(((last - prev) / Math.abs(prev)) * 100);
}

export interface LeadingFactor {
  label: string;
  /** Share of the team (0–100) with this factor among their risk drivers. */
  share: number;
  count: number;
  change: number | null;
}

/** Most common risk-increasing drivers across the team (risk_explanation via /wellbeing/team/). */
export function leadingFactors(
  drivers: Array<Array<{ feature_name: string; contribution_direction: string }>>,
  series: WeeklyPoint[],
  limit = 4,
): LeadingFactor[] {
  const counts = new Map<string, number>();
  drivers.forEach((list) => {
    new Set(list.filter((d) => d.contribution_direction === "INCREASES_RISK").map((d) => d.feature_name)).forEach(
      (name) => counts.set(name, (counts.get(name) ?? 0) + 1),
    );
  });
  const people = drivers.length || 1;
  const changeFor = (feature: string) =>
    feature.startsWith("overtime")
      ? lastChange(series, "overtime")
      : feature.startsWith("missed_breaks")
        ? lastChange(series, "missedBreaks")
        : feature.includes("hours_worked")
          ? lastChange(series, "workload")
          : null;
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([feature, count]) => ({
      label: featureLabel(feature),
      count,
      share: Math.round((count / people) * 100),
      change: changeFor(feature),
    }));
}
