import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, TrendingDown, TrendingUp, Minus } from "lucide-react";
import { api } from "../api/client";
import type { EmployeeResponse, Question } from "../api/types";
import { useAsync } from "../lib/useAsync";
import { ErrorNote, Loading } from "./ui";

/**
 * "How my mood has shifted" — daily average of the user's own check-in answers.
 * Each answer is placed on a 1–5 scale from its option's normalized_score
 * relative to that question's lowest/highest option, then averaged per day.
 */

const RANGES = [14, 30, 90] as const;
const DAY = 86400000;
const HEIGHT = 330;
// Generous top/side margins so the enlarged hover emoji never clips.
const M = { top: 34, right: 40, bottom: 44, left: 124 };

const MOOD_LEVELS = [
  { at: 5, emoji: "😊", text: "Great" },
  { at: 4, emoji: "🙂", text: "Good" },
  { at: 3, emoji: "😐", text: "Okay" },
  { at: 2, emoji: "😟", text: "Low" },
  { at: 1, emoji: "😣", text: "Very low" },
];

function moodWord(score: number) {
  return MOOD_LEVELS[5 - Math.min(5, Math.max(1, Math.round(score)))];
}

interface DayPoint {
  day: Date;
  mood: number;
  answers: Array<{ question: string; answer: string; mood: number }>;
}

const dayKey = (d: Date) => `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
const startOfDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};
const fmtLong = (d: Date) => d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
const fmtTick = (d: Date) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
const fmtWeekday = (d: Date) => d.toLocaleDateString("en-GB", { weekday: "short" });

function toDays(responses: EmployeeResponse[], questionById: Map<string, Question>): DayPoint[] {
  const byDay = new Map<string, { day: Date; answers: DayPoint["answers"] }>();
  responses.forEach((r) => {
    const q = questionById.get(r.question_id);
    const option = q?.options.find((o) => o.option_id === r.option_id);
    if (!q || !option) return;
    const scores = q.options.map((o) => o.normalized_score);
    const min = Math.min(...scores);
    const max = Math.max(...scores);
    const mood = max === min ? 3 : 1 + ((option.normalized_score - min) / (max - min)) * 4;
    const day = startOfDay(new Date(r.responded_at));
    const entry = byDay.get(dayKey(day)) ?? { day, answers: [] };
    entry.answers.push({ question: q.question_text, answer: option.option_text, mood });
    byDay.set(dayKey(day), entry);
  });
  return [...byDay.values()]
    .map((d) => ({ ...d, mood: d.answers.reduce((s, a) => s + a.mood, 0) / d.answers.length }))
    .sort((a, b) => +a.day - +b.day);
}

export function MoodTrend({ employeeId, questionById }: { employeeId: string; questionById: Map<string, Question> }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>(14);
  const responses = useAsync(
    () =>
      api.listAll<EmployeeResponse>("/employee-responses/", {
        employee: employeeId,
        responded_at__gte: new Date(startOfDay(new Date()).getTime() - (range - 1) * DAY).toISOString(),
        ordering: "responded_at",
      }),
    [employeeId, range],
  );
  const points = useMemo(() => toDays(responses.data ?? [], questionById), [responses.data, questionById]);

  // Measure the container so text and marks render at real pixel sizes.
  const wrapRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(720);
  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setWidth(Math.max(300, entry.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Selected day: defaults to the most recent check-in; hover previews another day.
  const [selected, setSelected] = useState<number | null>(null);
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => {
    setSelected(null);
    setHover(null);
  }, [range, responses.data]);
  const current = hover ?? selected ?? (points.length ? points.length - 1 : null);
  const day = current !== null ? points[current] : null;

  const narrow = width < 560;
  const left = narrow ? 44 : M.left;
  const end = startOfDay(new Date());
  const start = new Date(end.getTime() - (range - 1) * DAY);
  const plotW = width - left - M.right;
  const plotH = HEIGHT - M.top - M.bottom;
  // 30/90-day ranges have many points: draw plain dots instead of emoji bubbles to avoid clutter.
  const compact = range !== 14;
  // Keep points (active dot radius 26 + emoji) clear of the y-axis labels and the right edge.
  const PAD_X = compact ? 14 : 36;
  const x = (d: Date) => left + PAD_X + ((+d - +start) / Math.max(DAY, +end - +start)) * (plotW - 2 * PAD_X);
  const y = (mood: number) => M.top + ((5 - mood) / 4) * plotH;

  // Label each check-in day when they fit; otherwise fall back to evenly spaced dates.
  const pointXs = points.map((p) => x(p.day));
  const labelsFit = points.length > 0 && pointXs.every((px, i) => i === 0 || px - pointXs[i - 1] >= 52);
  const tickCount = narrow ? 3 : 5;
  const ticks: Date[] = labelsFit
    ? points.map((p) => p.day)
    : Array.from({ length: tickCount }, (_, i) => new Date(+start + Math.round(((range - 1) * i) / (tickCount - 1)) * DAY));

  // Summary
  const average = points.length ? points.reduce((s, p) => s + p.mood, 0) / points.length : null;
  const best = points.reduce<DayPoint | null>((b, p) => (!b || p.mood > b.mood ? p : b), null);
  const totalAnswers = points.reduce((s, p) => s + p.answers.length, 0);
  const half = Math.floor(points.length / 2);
  const shift =
    points.length >= 2
      ? points.slice(half).reduce((s, p) => s + p.mood, 0) / (points.length - half) -
        points.slice(0, Math.max(1, half)).reduce((s, p) => s + p.mood, 0) / Math.max(1, half)
      : null;
  const direction = shift === null ? null : shift >= 0.25 ? "up" : shift <= -0.25 ? "down" : "flat";

  const nearest = (px: number) =>
    points.reduce((best, p, i) => (Math.abs(x(p.day) - px) < Math.abs(x(points[best].day) - px) ? i : best), 0);

  const linePath = points.map((p, i) => `${i ? "L" : "M"}${x(p.day)},${y(p.mood)}`).join(" ");
  const areaPath = points.length
    ? `${linePath} L${x(points[points.length - 1].day)},${y(1)} L${x(points[0].day)},${y(1)} Z`
    : "";

  return (
    <div className="mood-trend">
      <div className="mood-toolbar">
        <div className="filter-tabs" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button key={r} className={range === r ? "active" : ""} onClick={() => setRange(r)}>
              Last {r} days
            </button>
          ))}
        </div>
      </div>

      <ErrorNote message={responses.error} onRetry={responses.reload} />

      {points.length > 0 && average !== null && (
        <div className="mood-stats">
          <div className="mood-stat">
            <span>Average mood</span>
            <strong>
              <em aria-hidden="true">{moodWord(average).emoji}</em> {moodWord(average).text}
            </strong>
            <small>{average.toFixed(1)} out of 5</small>
          </div>
          <div className="mood-stat">
            <span>Direction</span>
            <strong className={`mood-dir ${direction ?? "flat"}`}>
              {direction === "up" ? <TrendingUp size={18} /> : direction === "down" ? <TrendingDown size={18} /> : <Minus size={18} />}
              {direction === "up" ? "Lifting" : direction === "down" ? "Dipping" : direction === "flat" ? "Steady" : "—"}
            </strong>
            <small>
              {shift === null ? "Need 2+ days to compare" : `${shift > 0 ? "+" : ""}${shift.toFixed(1)} vs earlier in the period`}
            </small>
          </div>
          <div className="mood-stat">
            <span>Best day</span>
            <strong>
              <em aria-hidden="true">{best ? moodWord(best.mood).emoji : ""}</em> {best ? fmtTick(best.day) : "—"}
            </strong>
            <small>{best ? `${fmtWeekday(best.day)} · ${moodWord(best.mood).text}` : ""}</small>
          </div>
          <div className="mood-stat">
            <span>Check-ins</span>
            <strong>{totalAnswers}</strong>
            <small>
              on {points.length} day{points.length === 1 ? "" : "s"}
            </small>
          </div>
        </div>
      )}

      <div className="mood-chart" ref={wrapRef} style={{ opacity: responses.loading && responses.data ? 0.5 : 1 }}>
        {responses.loading && !responses.data ? (
          <Loading text="Loading your check-ins…" />
        ) : points.length === 0 ? (
          <p className="pp-muted mood-empty">
            No check-ins in the last {range} days. Answer one from “Your wellbeing rhythm” on My shift to start your trend.
          </p>
        ) : (
          <svg
            width={width}
            height={HEIGHT}
            role="img"
            aria-label={`Your daily mood over the last ${range} days. Use left and right arrow keys to move between days.`}
            tabIndex={0}
            onPointerMove={(e) => setHover(nearest(e.clientX - e.currentTarget.getBoundingClientRect().left))}
            onPointerLeave={() => setHover(null)}
            onClick={(e) => setSelected(nearest(e.clientX - e.currentTarget.getBoundingClientRect().left))}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") setSelected(Math.max(0, (current ?? points.length) - 1));
              if (e.key === "ArrowRight") setSelected(Math.min(points.length - 1, (current ?? -1) + 1));
            }}
          >
            <defs>
              <linearGradient id="mood-area" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" className="mood-area-top" />
                <stop offset="100%" className="mood-area-bottom" />
              </linearGradient>
            </defs>

            {/* Zones: doing well (top) and struggling (bottom) */}
            <rect x={left} y={y(5)} width={plotW} height={y(3.5) - y(5)} className="mood-zone good" />
            <rect x={left} y={y(2.5)} width={plotW} height={y(1) - y(2.5)} className="mood-zone low" />
            {!narrow && (
              <>
                <text x={width - M.right - 8} y={y(5) + 16} textAnchor="end" className="mood-zone-label good">Doing well</text>
                <text x={width - M.right - 8} y={y(1) - 8} textAnchor="end" className="mood-zone-label low">Struggling</text>
              </>
            )}

            {MOOD_LEVELS.map((lvl) => (
              <g key={lvl.at}>
                <line x1={left} x2={width - M.right} y1={y(lvl.at)} y2={y(lvl.at)} className="mood-grid" />
                <text x={left - 14} y={y(lvl.at)} className="mood-ylabel" dominantBaseline="central" textAnchor="end">
                  <tspan className="mood-ylabel-emoji">{lvl.emoji}</tspan>
                  {!narrow && <tspan dx="6">{lvl.text}</tspan>}
                </text>
              </g>
            ))}

            {ticks.map((t) => (
              <text key={+t} x={x(t)} y={HEIGHT - 14} className="mood-xlabel" textAnchor="middle">
                {fmtTick(t)}
              </text>
            ))}

            {points.length > 1 && <path d={areaPath} fill="url(#mood-area)" />}
            {points.length > 1 && <path d={linePath} className="mood-line" />}

            {day && (
              <line className="mood-crosshair" x1={x(day.day)} x2={x(day.day)} y1={M.top} y2={HEIGHT - M.bottom} />
            )}

            {points.map((p, i) => (
              <g key={+p.day} className={`mood-point ${i === current ? "active" : ""} ${compact ? "compact" : ""}`}>
                <circle
                  cx={x(p.day)}
                  cy={y(p.mood)}
                  r={compact ? (i === current ? 7 : 4) : i === current ? 26 : 19}
                  className="mood-dot"
                />
                {!compact && (
                  <text
                    // key changes on activation so the "pop" animation replays on every hover
                    key={i === current ? "live" : "still"}
                    x={x(p.day)}
                    y={y(p.mood) + 1}
                    textAnchor="middle"
                    dominantBaseline="central"
                    className="mood-emoji"
                  >
                    {moodWord(p.mood).emoji}
                  </text>
                )}
              </g>
            ))}
          </svg>
        )}
      </div>

      {day && current !== null && (
        <div className="mood-day" aria-live="polite">
          <div className="mood-day-head">
            <button
              className="ghost-icon"
              aria-label="Previous check-in day"
              disabled={current === 0}
              onClick={() => setSelected(current - 1)}
            >
              <ChevronLeft size={18} />
            </button>
            <div>
              <span>{fmtLong(day.day)}</span>
              <strong>
                {moodWord(day.mood).emoji} {moodWord(day.mood).text}
                <small> · {day.mood.toFixed(1)} / 5</small>
              </strong>
            </div>
            <button
              className="ghost-icon"
              aria-label="Next check-in day"
              disabled={current === points.length - 1}
              onClick={() => setSelected(current + 1)}
            >
              <ChevronRight size={18} />
            </button>
          </div>
          <ul>
            {day.answers.map((a, i) => (
              <li key={i}>
                <span>{a.question}</span>
                <strong className={`mood-answer m${Math.round(a.mood)}`}>
                  {moodWord(a.mood).emoji} {a.answer}
                </strong>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
