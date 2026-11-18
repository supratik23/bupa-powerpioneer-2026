import {
  ArrowLeftRight,
  Check,
  ClipboardCheck,
  ClipboardList,
  Coffee,
  FileText,
  HandHeart,
  HeartHandshake,
  LogIn,
  LogOut,
  Pill as PillIcon,
  RotateCcw,
} from "lucide-react";
import type { ReactNode } from "react";
import type { Appointment, AppointmentType, Shift } from "../api/types";
import { formatHours, formatTime, isoDate, label } from "../lib/format";
import { dayLabel } from "../lib/shifts";
import { isCompleted, shiftDay } from "../lib/appointments";
import { ErrorNote, Loading } from "./ui";

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------
const TYPE_META: Record<AppointmentType, { tone: string; icon: (size: number) => ReactNode }> = {
  HANDOVER: { tone: "handover", icon: (s) => <ArrowLeftRight size={s} /> },
  MEDICATION_ROUND: { tone: "medication", icon: (s) => <PillIcon size={s} /> },
  PERSONAL_CARE: { tone: "care", icon: (s) => <HandHeart size={s} /> },
  ASSESSMENT: { tone: "assessment", icon: (s) => <ClipboardCheck size={s} /> },
  CARE_PLAN_REVIEW: { tone: "review", icon: (s) => <ClipboardList size={s} /> },
  DOCUMENTATION: { tone: "docs", icon: (s) => <FileText size={s} /> },
  END_OF_LIFE_CARE: { tone: "eol", icon: (s) => <HeartHandshake size={s} /> },
};
const FALLBACK_META = { tone: "assessment", icon: (s: number) => <ClipboardCheck size={s} /> };

/** Gaps at least this long between tasks are shown as free time. */
const MIN_GAP_MINUTES = 15;

type TimeState = "done" | "active" | "upcoming" | "";

type Row =
  | { kind: "shift-start" | "shift-end"; at: Date; shift: Shift }
  | { kind: "appointment"; at: Date; end: Date; appointment: Appointment }
  | { kind: "gap"; at: Date; end: Date };

const at = (day: string, time: string) => new Date(`${day}T${time}`);
const minutes = (from: Date, to: Date) => Math.round((to.getTime() - from.getTime()) / 60000);
const duration = (mins: number) => (mins >= 60 ? formatHours(mins / 60) : `${mins} min`);

function buildRows(day: string, shift: Shift, appointments: Appointment[]): Row[] {
  const appts = appointments.map((a) => ({
    kind: "appointment" as const,
    at: at(day, a.start_time),
    end: at(day, a.end_time),
    appointment: a,
  }));
  const gaps: Row[] = [];
  for (let i = 1; i < appts.length; i += 1) {
    if (minutes(appts[i - 1].end, appts[i].at) >= MIN_GAP_MINUTES) {
      gaps.push({ kind: "gap", at: appts[i - 1].end, end: appts[i].at });
    }
  }
  const shiftRows: Row[] = [
    { kind: "shift-start", at: new Date(shift.shift_start), shift },
    { kind: "shift-end", at: new Date(shift.shift_end), shift },
  ];
  const order = { "shift-start": 0, appointment: 1, gap: 2, "shift-end": 3 };
  return [...shiftRows, ...appts, ...gaps].sort((a, b) => a.at.getTime() - b.at.getTime() || order[a.kind] - order[b.kind]);
}

function timeState(row: Row, now: Date, isToday: boolean): TimeState {
  if (!isToday) return "";
  const end = row.kind === "appointment" || row.kind === "gap" ? row.end : row.at;
  if (end <= now) return "done";
  if (row.at <= now) return "active";
  return "upcoming";
}

// ---------------------------------------------------------------------------
// component
// ---------------------------------------------------------------------------
export function DayPlan({
  shift,
  appointments,
  loading,
  error,
  onRetry,
  onToggle,
  busyIds,
  now = new Date(),
}: {
  /** The roster shift selected on the left; null when the user has no shifts. */
  shift: Shift | null;
  /** Appointments for that shift's day, sorted by start time. */
  appointments: Appointment[];
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onToggle: (appointment: Appointment) => void;
  busyIds: Set<string>;
  now?: Date;
}) {
  const day = shift ? shiftDay(shift) : null;
  const heading = shift ? `${dayLabel(shift.shift_start, now)}’s appointments` : "Appointments";

  return (
    <section className="surface dp-surface">
      <div className="surface-heading">
        <div>
          <span className="section-kicker">
            {shift ? `${label(shift.shift_type)} shift · ${formatTime(shift.shift_start)}–${formatTime(shift.shift_end)}` : "Your day"}
          </span>
          <h2>{heading}</h2>
        </div>
      </div>
      <ErrorNote message={error} onRetry={onRetry} />
      {loading ? (
        <Loading text="Loading appointments…" />
      ) : !shift || !day ? (
        <p className="schedule-empty">Select a shift from your roster to see its appointments.</p>
      ) : (
        <DayPlanBody day={day} shift={shift} appointments={appointments} now={now} onToggle={onToggle} busyIds={busyIds} />
      )}
    </section>
  );
}

function DayPlanBody({
  day,
  shift,
  appointments,
  now,
  onToggle,
  busyIds,
}: {
  day: string;
  shift: Shift;
  appointments: Appointment[];
  now: Date;
  onToggle: (a: Appointment) => void;
  busyIds: Set<string>;
}) {
  const isToday = day === isoDate(now);
  const canComplete = day <= isoDate(now);
  const rows = buildRows(day, shift, appointments);
  const booked = appointments.reduce((sum, a) => sum + minutes(at(day, a.start_time), at(day, a.end_time)), 0);
  const shiftMinutes = minutes(new Date(shift.shift_start), new Date(shift.shift_end));
  const share = shiftMinutes > 0 ? Math.round((booked / shiftMinutes) * 100) : null;
  const done = appointments.filter(isCompleted).length;
  const longestGap = rows.reduce((max, r) => (r.kind === "gap" ? Math.max(max, minutes(r.at, r.end)) : max), 0);
  const eol = appointments.filter((a) => a.appointment_type === "END_OF_LIFE_CARE").length;
  const next = isToday ? appointments.find((a) => !isCompleted(a) && at(day, a.end_time) > now) : undefined;

  if (appointments.length === 0) {
    return (
      <p className="schedule-empty">
        No appointments are booked for this shift yet. Pick another shift on the left to see its appointments.
      </p>
    );
  }

  return (
    <>
      <div className="dp-stats">
        <div>
          <span>Completed</span>
          <strong>
            {done}/{appointments.length}
          </strong>
          <i className="dp-progress" aria-hidden="true">
            <b style={{ width: `${(done / appointments.length) * 100}%` }} />
          </i>
        </div>
        <div>
          <span>Booked time</span>
          <strong>{duration(booked)}</strong>
          {share !== null && <small>{share}% of your shift</small>}
        </div>
        <div>
          <span>Longest free gap</span>
          <strong>{longestGap ? duration(longestGap) : "None"}</strong>
          {longestGap > 0 && longestGap < 30 && <small>Tight day for breaks</small>}
        </div>
      </div>

      {(next || eol > 0) && (
        <div className="dp-callouts">
          {next && (
            <span className="dp-callout">
              {at(day, next.start_time) <= now ? "Now" : "Next"}: <strong>{next.title}</strong> · {next.start_time.slice(0, 5)}
              {next.location ? ` · ${next.location}` : ""}
            </span>
          )}
          {eol > 0 && (
            <span className="dp-callout eol">
              <HeartHandshake size={13} /> {eol} end-of-life care {eol === 1 ? "visit" : "visits"} — take a moment afterwards
            </span>
          )}
        </div>
      )}

      <ol className="tl-list dp-list">
        {rows.map((row, i) => (
          <DayRow
            key={row.kind === "appointment" ? row.appointment.appointment_id : `${row.kind}-${i}`}
            row={row}
            state={timeState(row, now, isToday)}
            canComplete={canComplete}
            onToggle={onToggle}
            busy={row.kind === "appointment" && busyIds.has(row.appointment.appointment_id)}
          />
        ))}
      </ol>
    </>
  );
}

function DayRow({
  row,
  state,
  canComplete,
  onToggle,
  busy,
}: {
  row: Row;
  state: TimeState;
  canComplete: boolean;
  onToggle: (a: Appointment) => void;
  busy: boolean;
}) {
  if (row.kind === "gap") {
    const mins = minutes(row.at, row.end);
    return (
      <li className={`tl-item dp-item gap ${state}`}>
        <div className="tl-time">
          <strong>{formatTime(row.at)}</strong>
          <span>{duration(mins)}</span>
        </div>
        <div className="tl-node dp-node gap"><Coffee size={14} /></div>
        <div className="tl-copy">
          <span>Free time · {mins >= 30 ? "good moment for a break" : "short breather"}</span>
        </div>
      </li>
    );
  }

  if (row.kind !== "appointment") {
    const start = row.kind === "shift-start";
    const s = row.shift;
    return (
      <li className={`tl-item dp-item shift ${state}`}>
        <div className="tl-time">
          <strong>{formatTime(row.at)}</strong>
          <span>{start ? "Start" : "End"}</span>
        </div>
        <div className="tl-node dp-node shift">{start ? <LogIn size={14} /> : <LogOut size={14} />}</div>
        <div className="tl-copy">
          <div>
            <strong>{start ? `${label(s.shift_type)} shift starts` : "Shift ends"}</strong>
          </div>
          {start && s.location && <span>{s.location}</span>}
        </div>
      </li>
    );
  }

  const a = row.appointment;
  const completed = isCompleted(a);
  const meta = (a.appointment_type && TYPE_META[a.appointment_type]) || FALLBACK_META;
  return (
    <li className={`tl-item dp-item appt ${state} ${completed ? "completed" : ""}`}>
      <div className="tl-time">
        <strong>{a.start_time.slice(0, 5)}</strong>
        <span>{duration(minutes(row.at, row.end))}</span>
      </div>
      <div className={`tl-node dp-node ${completed ? "complete" : meta.tone}`}>
        {completed ? <Check size={14} strokeWidth={3} /> : meta.icon(14)}
      </div>
      <div className="tl-copy">
        <div>
          <strong>{a.title}</strong>
          {state === "active" && !completed && <span className="live-pill">Now</span>}
        </div>
        <span>
          {a.start_time.slice(0, 5)}–{a.end_time.slice(0, 5)}
          {a.location ? ` · ${a.location}` : ""}
          {a.appointment_type ? ` · ${label(a.appointment_type)}` : ""}
        </span>
      </div>
      {canComplete && (
        <button
          className={`dp-check ${completed ? "on" : ""}`}
          disabled={busy}
          aria-pressed={completed}
          aria-label={completed ? `Mark “${a.title}” as not done` : `Mark “${a.title}” as complete`}
          title={completed ? "Undo" : "Mark complete"}
          onClick={() => onToggle(a)}
        >
          {completed ? (
            <>
              <RotateCcw size={12} /> Undo
            </>
          ) : (
            <>
              <Check size={13} strokeWidth={3} /> Done
            </>
          )}
        </button>
      )}
    </li>
  );
}
