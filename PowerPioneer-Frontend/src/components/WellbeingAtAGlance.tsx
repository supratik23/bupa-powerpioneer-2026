import { ArrowDownRight, ArrowRight, ArrowUpRight, CircleAlert, CircleCheck } from "lucide-react";
import type { Explanation, RiskBand, RiskSnapshot, WellbeingSummary } from "../api/types";
import { featureLabel, formatDate, num, wellbeingChange, wellbeingPercent } from "../lib/format";

/**
 * Plain-language versions of the wellbeing numbers on My wellbeing.
 * The score is the mean check-in answer (1–4) shown as 0–100; the five levels split
 * that range into equal fifths, matching the mood words used in the mood chart.
 */
const LEVELS = [
  { min: 80, word: "Great", emoji: "😊", tone: "great", phrase: "doing great" },
  { min: 60, word: "Good", emoji: "🙂", tone: "good", phrase: "doing well" },
  { min: 40, word: "Okay", emoji: "😐", tone: "okay", phrase: "doing okay" },
  { min: 20, word: "Low", emoji: "😟", tone: "low", phrase: "having a harder time" },
  { min: 0, word: "Very low", emoji: "😣", tone: "verylow", phrase: "finding things tough" },
] as const;

const levelFor = (pct: number) => LEVELS.find((l) => pct >= l.min) ?? LEVELS[LEVELS.length - 1];

const BAND_TEXT: Record<RiskBand, { title: string; text: string; tone: string }> = {
  LOW: { title: "Low workload risk", text: "Your recent work pattern looks manageable.", tone: "good" },
  MEDIUM: { title: "Medium workload risk", text: "Some strain is showing in your recent shifts — worth keeping an eye on.", tone: "okay" },
  MODERATE: { title: "Medium workload risk", text: "Some strain is showing in your recent shifts — worth keeping an eye on.", tone: "okay" },
  HIGH: { title: "High workload risk", text: "Your recent work pattern is putting you under strain. Your manager can help adjust it.", tone: "low" },
  CRITICAL: { title: "Very high workload risk", text: "Your work pattern is under heavy strain. Please talk to your manager or use the support options.", tone: "verylow" },
};

/** Change over ~a week, in words. */
function changeInWords(delta: number): { text: string; dir: "up" | "down" | "flat" } {
  const size = Math.abs(delta);
  if (size < 2) return { text: "About the same as a week ago", dir: "flat" };
  const amount = size < 5 ? "A little" : size < 10 ? "Noticeably" : "Much";
  return delta > 0 ? { text: `${amount} better than a week ago`, dir: "up" } : { text: `${amount} lower than a week ago`, dir: "down" };
}

function strengthWord(value: number, max: number) {
  const r = max > 0 ? value / max : 0;
  return r >= 0.66 ? "Strong effect" : r >= 0.33 ? "Moderate effect" : "Slight effect";
}

function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return null;
  const w = 220;
  const h = 44;
  const lo = Math.min(...values, 0);
  const hi = Math.max(...values, 100);
  const x = (i: number) => 4 + (i / (values.length - 1)) * (w - 8);
  const y = (v: number) => 4 + ((hi - v) / (hi - lo || 1)) * (h - 8);
  const pts = values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  return (
    <svg className="wag-spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <line x1="0" x2={w} y1={y(60)} y2={y(60)} className="wag-spark-ref" />
      <polyline points={pts} />
      <circle cx={x(values.length - 1)} cy={y(values[values.length - 1])} r="3.5" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// "How you're doing" — replaces the raw score / change / snapshot tiles
// ---------------------------------------------------------------------------
export function WellbeingOverview({ summary }: { summary: WellbeingSummary }) {
  const pct = wellbeingPercent(summary.latest_wellbeing_score);
  if (pct === null) {
    return <p className="pp-muted">No wellbeing score yet. Answer a check-in on My shift to get started.</p>;
  }
  const level = levelFor(pct);
  const change = wellbeingChange(summary.history, 7);
  const words = change ? changeInWords(change.delta) : null;
  const before = change ? wellbeingPercent(summary.history.find((h) => h.snapshot_date === change.since)?.wellbeing_score) : null;
  const series = summary.history.map((h) => wellbeingPercent(h.wellbeing_score)).filter((v): v is number => v !== null);
  const band = summary.latest_risk_band ? BAND_TEXT[summary.latest_risk_band] : null;

  const drivers = summary.top_drivers;
  const max = Math.max(0, ...drivers.map((d) => Math.abs(Number(d.shap_value))));
  const against = drivers.filter((d) => d.contribution_direction === "INCREASES_RISK");
  const helping = drivers.filter((d) => d.contribution_direction === "DECREASES_RISK");

  return (
    <div className="wag">
      {/* 1. headline */}
      <div className="wag-headline">
        <span className="wag-emoji" aria-hidden="true">{level.emoji}</span>
        <div>
          <strong>You’re {level.phrase}</strong>
          <small>
            Wellbeing {Math.round(pct)} out of 100 · from your check-ins up to {formatDate(summary.latest_snapshot_date)}
          </small>
        </div>
      </div>

      {/* 2. where that sits on the scale */}
      <div className="wag-scale" aria-label={`Wellbeing level: ${level.word}`}>
        <div className="wag-scale-track">
          {[...LEVELS].reverse().map((l) => (
            <i key={l.tone} className={`wag-seg ${l.tone} ${l === level ? "on" : ""}`} />
          ))}
          <b className="wag-marker" style={{ left: `${Math.min(98, Math.max(2, pct))}%` }} />
        </div>
        <div className="wag-scale-labels">
          {[...LEVELS].reverse().map((l) => (
            <span key={l.tone} className={l === level ? "on" : ""}>{l.word}</span>
          ))}
        </div>
      </div>

      {/* 3. trend in words + last 10 days */}
      <div className="wag-row">
        <div className={`wag-trend ${words?.dir ?? "flat"}`}>
          {words?.dir === "up" ? <ArrowUpRight size={18} /> : words?.dir === "down" ? <ArrowDownRight size={18} /> : <ArrowRight size={18} />}
          <div>
            <strong>{words ? words.text : "Not enough history yet"}</strong>
            {change && before !== null && (
              <small>
                {Math.round(before)} on {formatDate(change.since)} → {Math.round(pct)} now
              </small>
            )}
          </div>
        </div>
        {series.length >= 2 && (
          <div className="wag-sparkbox">
            <Sparkline values={series} />
            <small>Last {series.length} days</small>
          </div>
        )}
      </div>

      {/* 4. what the risk badge means */}
      {band && (
        <div className={`wag-band ${band.tone}`}>
          <strong>{band.title}</strong>
          <span>{band.text}</span>
        </div>
      )}

      {/* 5. drivers in plain language */}
      <div className="wag-drivers">
        <span className="section-kicker">What’s affecting it</span>
        {drivers.length === 0 ? (
          <p className="pp-muted">Nothing stands out in your recent shifts.</p>
        ) : (
          <div className="wag-driver-cols">
            <DriverList title="Weighing on you" tone="against" items={against} max={max} />
            <DriverList title="Helping you" tone="helping" items={helping} max={max} />
          </div>
        )}
      </div>
    </div>
  );
}

function DriverList({ title, tone, items, max }: { title: string; tone: string; items: Explanation[]; max: number }) {
  if (!items.length) return null;
  return (
    <div className={`wag-driver-list ${tone}`}>
      <strong>{title}</strong>
      <ul>
        {items.map((d) => (
          <li key={d.feature_name} title={`Model contribution ${num(d.shap_value, 2)}`}>
            <span>{featureLabel(d.feature_name)}</span>
            <small>{strengthWord(Math.abs(Number(d.shap_value)), max)}</small>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Work pattern tiles with context and a "within guidance" check
// ---------------------------------------------------------------------------
type Tile = { label: string; value: string; helper: string; warn: boolean };

function patternTiles(s: RiskSnapshot): Tile[] {
  const n = (v: unknown) => (v === null || v === undefined ? null : Number(v));
  const worked = n(s.actual_hours_worked_30d) ?? 0;
  const contracted = n(s.contracted_hours_30d) ?? 0;
  const overtime = n(s.overtime_hours_30d) ?? 0;
  const ratio = n(s.overtime_ratio_30d) ?? 0;
  const rest = n(s.minimum_rest_hours_between_shifts);
  const sinceLeave = n(s.days_since_last_meaningful_leave);
  return [
    {
      label: "Hours worked",
      value: `${num(worked, 0)}h`,
      helper: contracted ? `of ${num(contracted, 0)}h contracted` : "in the last 30 days",
      warn: contracted > 0 && worked > contracted * 1.1,
    },
    {
      label: "Overtime",
      value: `${num(overtime, 0)}h`,
      helper: overtime > 0 ? `${Math.round(ratio * 100)}% on top of your hours` : "None — nice",
      warn: ratio > 0.1,
    },
    { label: "Night shifts", value: String(s.night_shifts_30d), helper: "in 30 days", warn: s.night_shifts_30d > 8 },
    { label: "Long shifts", value: String(s.long_shifts_30d), helper: "12h+ shifts in 30 days", warn: s.long_shifts_30d > 8 },
    {
      label: "Days in a row",
      value: String(s.max_consecutive_work_days),
      helper: "longest run · 6 or fewer is best",
      warn: s.max_consecutive_work_days > 6,
    },
    {
      label: "Missed breaks",
      value: String(s.missed_breaks_30d),
      helper: s.missed_breaks_30d ? "every shift should include one" : "You got your breaks",
      warn: s.missed_breaks_30d > 0,
    },
    {
      label: "Shortest rest",
      value: rest === null ? "—" : `${num(rest, 0)}h`,
      helper: "between shifts · 11h+ is best",
      warn: rest !== null && rest < 11,
    },
    {
      label: "Since a proper break",
      value: sinceLeave === null ? "—" : `${sinceLeave} days`,
      helper: sinceLeave !== null && sinceLeave > 90 ? "consider booking some leave" : "since 5+ days of leave",
      warn: sinceLeave !== null && sinceLeave > 90,
    },
  ];
}

export function WorkPatternSignals({ snapshot }: { snapshot: RiskSnapshot }) {
  const tiles = patternTiles(snapshot);
  const flagged = tiles.filter((t) => t.warn).length;
  return (
    <>
      <p className={`wag-pattern-summary ${flagged ? "warn" : "ok"}`}>
        {flagged ? <CircleAlert size={15} /> : <CircleCheck size={15} />}
        {flagged
          ? `${flagged} of ${tiles.length} signals are outside recommended limits (highlighted below).`
          : "Everything is within recommended limits."}
      </p>
      <div className="pp-stat-grid">
        {tiles.map((t) => (
          <div key={t.label} className={`pp-stat ${t.warn ? "warn" : ""}`}>
            <span>{t.label}</span>
            <strong>{t.value}</strong>
            <small className="pp-muted">{t.helper}</small>
          </div>
        ))}
      </div>
    </>
  );
}
