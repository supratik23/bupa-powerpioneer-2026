import { useCallback, useMemo, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  Check,
  CircleHelp,
  ChevronDown,
  ChevronRight,
  Clock3,
  Heart,
  HeartPulse,
  Info,
  Leaf,
  LockKeyhole,
  Menu,
  MessageCircleHeart,
  Moon,
  PhoneCall,
  ShieldCheck,
  Sparkles,
  Sun,
  Sunrise,
  TrendingUp,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";
import { api, errorMessage } from "./api/client";
import type {
  Appointment,
  Employee,
  Question,
  RiskBand,
  RiskPrediction,
  RiskSnapshot,
  Shift,
  WellbeingSummary,
} from "./api/types";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { ProfileMenu } from "./components/HeaderMenus";
import { Relations } from "./components/Relations";
import { ErrorNote, Loading } from "./components/ui";
import {
  avatarColor,
  featureLabel,
  formatHours,
  formatTime,
  greeting,
  initials,
  isoDate,
  label,
  wellbeingPercent,
} from "./lib/format";
import { daysBeforeLatest, withSupabaseRows } from "./lib/wellbeingData";
import { RosterTimelineDrawer } from "./components/DayTimeline";
import { DayPlan } from "./components/DayPlan";
import { ReturnToWorkTeam } from "./components/ReturnToWork";
import { isCompleted, shiftDay } from "./lib/appointments";
import { DAYPART_META, ThemeToggle } from "./components/ThemeToggle";
import { DaypartProvider, useDaypart } from "./lib/daypart";
import { usePage } from "./lib/nav";
import { leadingFactors, trendInsight, weeklySeries } from "./lib/teamTrends";
import type { WeeklyPoint } from "./lib/teamTrends";
import { dayLabel, shiftFlags, shiftHours, shiftKind, shiftRange, shiftState, shiftTitle } from "./lib/shifts";
import type { PageId } from "./lib/nav";
import { useAsync } from "./lib/useAsync";
import { useEmployees } from "./lib/useEmployees";
import AuthPage from "./pages/AuthPage";
import LeavePage from "./pages/LeavePage";
import ProfilePage from "./pages/ProfilePage";
import RosterPage from "./pages/RosterPage";
import WellbeingPage from "./pages/WellbeingPage";
import AdminPage from "./pages/admin/AdminPage";

/** Pages reachable from the main tab switcher in the header. */
type Role = "employee" | "manager" | "wellbeing";
type RiskLevel = "Needs attention" | "Keep an eye" | "Doing well";
type Tone = "blue" | "amber" | "violet" | "teal";

type Nudge = {
  id: string;
  category: string;
  time: string;
  context: string;
  question: string;
  helper: string;
  status: "completed" | "now" | "later";
  tone: Tone;
  options: Array<{
    id: string;
    score: number;
    emoji: string;
    title: string;
  }>;
};

type TeamMember = {
  id: string;
  name: string;
  initials: string;
  role: string;
  department: string | null;
  risk: number;
  delta: number;
  level: RiskLevel;
  band: RiskBand | null;
  factors: string[];
  trend: number[];
  color: string;
  drivers: WellbeingSummary["top_drivers"];
};

// ---------------------------------------------------------------------------
// API -> view-model mapping
// ---------------------------------------------------------------------------
/** Check-in slots placed around natural pauses in the day (presentation only). */
const NUDGE_SLOTS: Array<{ time: string; tone: Tone }> = [
  { time: "08:45", tone: "blue" },
  { time: "10:30", tone: "amber" },
  { time: "12:15", tone: "violet" },
  { time: "14:30", tone: "teal" },
  { time: "16:00", tone: "blue" },
  { time: "17:30", tone: "amber" },
];

const TRIGGER_CATEGORY: Record<string, string> = {
  SCHEDULED: "Wellbeing pulse",
  RISK_TRIGGERED: "Personal check-in",
  ONBOARDING: "Settling in",
  MATERNITY_RETURN: "Return to work",
  POST_SHIFT: "After your shift",
  ADHOC: "Quick check-in",
};

const MOOD_EMOJI = ["😣", "😟", "😐", "🙂", "😊"];

function toNudge(question: Question, index: number, completed: boolean, isFirstPending: boolean): Nudge {
  const slot = NUDGE_SLOTS[index % NUDGE_SLOTS.length];
  const scores = question.options.map((o) => o.normalized_score);
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const short = question.question_text.length > 46 ? `${question.question_text.slice(0, 44)}…` : question.question_text;
  return {
    id: question.question_id,
    category: TRIGGER_CATEGORY[question.trigger_type] ?? "Check-in",
    time: slot.time,
    context: short,
    question: question.question_text,
    helper: "Choose the option that feels closest right now.",
    status: completed ? "completed" : isFirstPending ? "now" : "later",
    tone: slot.tone,
    options: [...question.options]
      .sort((a, b) => a.display_order - b.display_order)
      .map((o) => {
        const ratio = max === min ? 0.5 : (o.normalized_score - min) / (max - min);
        return {
          id: o.option_id ?? `${o.display_order}`,
          score: o.normalized_score,
          emoji: MOOD_EMOJI[Math.round(ratio * (MOOD_EMOJI.length - 1))],
          title: o.option_text,
        };
      }),
  };
}

function levelFor(band: RiskBand | null): RiskLevel {
  if (band === "HIGH" || band === "CRITICAL") return "Needs attention";
  if (band === "MEDIUM" || band === "MODERATE") return "Keep an eye";
  return "Doing well";
}

/** risk_prediction.risk_score (0–100, XGBoost) per employee, oldest first. */
function riskSeriesByEmployee(predictions: RiskPrediction[]): Map<string, number[]> {
  const byEmployee = new Map<string, number[]>();
  [...predictions]
    .sort((a, b) => a.predicted_at.localeCompare(b.predicted_at))
    .forEach((p) => {
      const list = byEmployee.get(p.employee_id) ?? [];
      list.push(Number(p.risk_score));
      byEmployee.set(p.employee_id, list);
    });
  return byEmployee;
}

function toMember(summary: WellbeingSummary, employee: Employee | undefined, riskSeries?: number[]): TeamMember {
  // Prefer the model's risk_score; fall back to inverted wellbeing (1–4 scale -> 0–100).
  const fallback = summary.history
    .map((h) => wellbeingPercent(h.wellbeing_score))
    .filter((v): v is number => v !== null)
    .map((v) => 100 - v);
  const history = riskSeries?.length ? riskSeries : fallback;
  const latestWellbeing = wellbeingPercent(summary.latest_wellbeing_score);
  const risk = history.length
    ? Math.round(history[history.length - 1])
    : latestWellbeing === null ? 0 : Math.round(100 - latestWellbeing);
  const scored = history.length > 0 || latestWellbeing !== null;
  const increasing = summary.top_drivers.filter((d) => d.contribution_direction === "INCREASES_RISK");
  const factors = (increasing.length ? increasing : summary.top_drivers).map((d) => featureLabel(d.feature_name));
  return {
    id: summary.employee_id,
    name: summary.full_name,
    initials: initials(summary.full_name),
    role: employee?.job_role ?? "Team member",
    department: employee?.department ?? null,
    risk,
    // Risk-point change since the previous prediction / snapshot.
    delta: history.length >= 2 ? Math.round(history[history.length - 1] - history[history.length - 2]) : 0,
    level: levelFor(summary.latest_risk_band),
    band: summary.latest_risk_band,
    factors: factors.length ? factors : [scored ? "No major risk factors" : "Not calculated yet"],
    trend: history.length ? history : [risk],
    color: avatarColor(summary.employee_id),
    drivers: summary.top_drivers,
  };
}

// ---------------------------------------------------------------------------
// layout
// ---------------------------------------------------------------------------
/** Logo: clicking it returns to the default view (My shift). */
function BrandMark({ onHome }: { onHome: () => void }) {
  return (
    <button type="button" className="brand-mark brand-home" aria-label="ShiftGuard home" title="Go to My shift" onClick={onHome}>
      <div className="pulse-mark">
        <Activity size={23} strokeWidth={2.3} />
      </div>
      <div>
        <strong>ShiftGuard</strong>
        <span>Frontline wellbeing</span>
      </div>
    </button>
  );
}

function RoleSwitch({
  role,
  setRole,
  showTeam,
}: {
  role: Role | null;
  setRole: (role: Role) => void;
  showTeam: boolean;
}) {
  return (
    <div className="role-switch" aria-label="Choose app view">
      <button
        className={role === "employee" ? "active" : ""}
        onClick={() => setRole("employee")}
      >
        <UserRound size={16} />
        My shift
      </button>
      {showTeam && (
        <button
          className={role === "manager" ? "active" : ""}
          onClick={() => setRole("manager")}
        >
          <UsersRound size={16} />
          Team view
        </button>
      )}
      <button
        className={role === "wellbeing" ? "active" : ""}
        onClick={() => setRole("wellbeing")}
      >
        <HeartPulse size={16} />
        My wellbeing
      </button>
    </div>
  );
}

function AppHeader({
  page,
  navigate,
}: {
  page: PageId;
  navigate: (page: PageId) => void;
}) {
  const { isManager } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const role: Role | null = page === "employee" || page === "manager" || page === "wellbeing" ? page : null;
  return (
    <header className="app-header">
      <BrandMark
        onHome={() => {
          setMobileOpen(false);
          navigate("employee");
        }}
      />
      <div className="desktop-role-switch">
        <RoleSwitch role={role} setRole={navigate} showTeam={isManager} />
      </div>
      <div className="header-actions">
        <ThemeToggle />
        <ProfileMenu page={page} navigate={navigate} />
        <button
          className="icon-button mobile-menu"
          aria-label="Open navigation"
          onClick={() => setMobileOpen(!mobileOpen)}
        >
          {mobileOpen ? <X size={20} /> : <Menu size={20} />}
        </button>
      </div>
      {mobileOpen && (
        <div className="mobile-role-panel">
          <RoleSwitch
            role={role}
            showTeam={isManager}
            setRole={(nextRole) => {
              navigate(nextRole);
              setMobileOpen(false);
            }}
          />
        </div>
      )}
    </header>
  );
}

function MetricCard({
  icon,
  label,
  value,
  helper,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  helper: string;
  tone: string;
}) {
  return (
    <article className="metric-card">
      <div className={`metric-icon ${tone}`}>{icon}</div>
      <div>
        <span className="eyebrow">{label}</span>
        <strong>{value}</strong>
        <p>{helper}</p>
      </div>
    </article>
  );
}

/** One of the user's shifts in the roster list (from /shifts/); selecting it shows its appointments. */
function ScheduleItem({
  shift,
  now,
  selected,
  onSelect,
  appointments,
}: {
  shift: Shift;
  now: Date;
  selected: boolean;
  onSelect: () => void;
  /** That day's appointments; null while loading. */
  appointments: Appointment[] | null;
}) {
  const state = shiftState(shift, now);
  const kind = shiftKind(shift.shift_type);
  const KindIcon = kind === "night" ? Moon : kind === "oncall" ? PhoneCall : kind === "long" ? Sunrise : Sun;
  const load = shift.actual_patient_load ?? shift.expected_patient_load;
  const flags = shiftFlags(shift);
  const detail = [
    shiftRange(shift),
    shift.location,
    load != null ? `${Number(load)} patients` : null,
  ].filter(Boolean).join(" · ");
  return (
    <li
      className={`schedule-item selectable ${state} ${selected ? "selected" : ""}`}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
    >
      <div className="schedule-time">
        <strong>{dayLabel(shift.shift_start, now)}</strong>
        <span>{shiftHours(shift)}</span>
      </div>
      <div className={`schedule-symbol ${kind}`}>
        {state === "done" ? <Check size={18} /> : <KindIcon size={18} />}
      </div>
      <div className="schedule-copy">
        <div>
          <strong>{shiftTitle(shift)}</strong>
          {state === "active" && <span className="live-pill">In progress</span>}
        </div>
        <span>{detail}</span>
        {(flags.length > 0 || (appointments && appointments.length > 0)) && (
          <div className="schedule-tags">
            {appointments && appointments.length > 0 && (
              <em className="shift-tag appts">
                {appointments.length} appointment{appointments.length === 1 ? "" : "s"}
                {appointments.some(isCompleted) ? ` · ${appointments.filter(isCompleted).length} done` : ""}
              </em>
            )}
            {flags.map((f) => (
              <em key={f.id} className={`shift-tag ${f.id}`}>{f.text}</em>
            ))}
          </div>
        )}
      </div>
      <ChevronRight className="schedule-chevron" size={16} aria-hidden="true" />
    </li>
  );
}

function WellbeingPanel({
  open,
  nudge,
  onClose,
  onSubmit,
}: {
  open: boolean;
  nudge: Nudge;
  onClose: () => void;
  onSubmit: (optionId: string) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);

  const resetAndClose = () => {
    setSelected(null);
    onClose();
  };

  if (!open) return null;

  return (
    <>
      <button
        className="panel-backdrop"
        aria-label="Close wellbeing panel"
        onClick={resetAndClose}
      />
      <aside className="wellbeing-panel" aria-live="polite">
        <div className="panel-header">
          <div>
            <div className="sparkle-label">
              <Sparkles size={14} />
              ShiftGuard
            </div>
            <span>Your private wellbeing space</span>
          </div>
          <button className="ghost-icon" onClick={resetAndClose} aria-label="Close">
            <X size={19} />
          </button>
        </div>

        <div className="panel-body">
          <div className="question-heading">
            <div className={`question-icon ${nudge.tone}`}>
              <MessageCircleHeart size={22} />
            </div>
            <span>{nudge.category}</span>
            <h2>{nudge.question}</h2>
            <p>{nudge.helper}</p>
          </div>
          <div
            className="checkin-options"
            style={{
              gridTemplateColumns: `repeat(${nudge.options.length}, minmax(58px, 1fr))`,
            }}
          >
            {nudge.options.map((option) => (
              <button
                key={option.id}
                className={selected === option.id ? "selected" : ""}
                disabled={selected !== null || nudge.status === "completed"}
                onClick={() => {
                  setSelected(option.id);
                  window.setTimeout(() => onSubmit(option.id), 120);
                }}
              >
                <span className="checkin-emoji" aria-hidden="true">
                  {option.emoji}
                </span>
                <strong>{option.title}</strong>
                <span className="radio-dot">
                  {selected === option.id && <span />}
                </span>
              </button>
            ))}
          </div>
          <p className="one-tap-note">
            <Sparkles size={13} />
            {nudge.status === "completed"
              ? "Thanks — you have already answered this check-in."
              : "One tap saves your private response and closes this check-in."}
          </p>
          <PrivacyNote compact />
        </div>
      </aside>
    </>
  );
}

function PrivacyNote({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`privacy-note ${compact ? "compact" : ""}`}>
      <LockKeyhole size={17} />
      <div>
        <strong>Private by design</strong>
        <span>
          Your manager sees only aggregated trends, never your response.
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// employee view ("My shift")
// ---------------------------------------------------------------------------
function useMyShifts(employeeId: string) {
  return useAsync(
    () =>
      api.list<Shift>("/shifts/", {
        employee: employeeId,
        // a week back, so recent shifts (and their appointments) can be selected too
        shift_start__gte: new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString(),
        ordering: "shift_start",
      }),
    [employeeId],
  );
}

function shiftSummary(shifts: Shift[]) {
  const now = new Date();
  const todayKey = now.toDateString();
  const current = shifts.find((s) => new Date(s.shift_start) <= now && new Date(s.shift_end) > now);
  const today = shifts.filter((s) => new Date(s.shift_start).toDateString() === todayKey);
  const upcoming = shifts.find((s) => new Date(s.shift_start) > now);
  const focus = current ?? today.find((s) => new Date(s.shift_start) > now) ?? today[today.length - 1] ?? null;

  const range = (s: Shift) => `${formatTime(s.shift_start)}–${formatTime(s.shift_end)}`;
  const nextLabel = (s: Shift) =>
    `${new Date(s.shift_start).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })}, ${formatTime(s.shift_start)}`;

  if (!focus) {
    return {
      status: "No shift today",
      range: upcoming ? `Next: ${nextLabel(upcoming)}` : "No upcoming shifts",
      value: "Off today",
      helper: upcoming ? `Next shift ${nextLabel(upcoming)}` : "No upcoming shifts rostered",
    };
  }
  const start = new Date(focus.shift_start);
  const end = new Date(focus.shift_end);
  const hours = Number(focus.planned_hours);
  if (focus === current) {
    const done = (now.getTime() - start.getTime()) / 3600000;
    return {
      status: "Shift in progress",
      range: range(focus),
      value: formatHours(hours),
      helper: `On track · ${formatHours(Math.max(0, done))} complete`,
    };
  }
  if (start > now) {
    return {
      status: "Shift starts soon",
      range: range(focus),
      value: formatHours(hours),
      helper: `${label(focus.shift_type)} shift · starts ${formatTime(start)}`,
    };
  }
  return {
    status: "Shift complete",
    range: range(focus),
    value: formatHours(Number(focus.actual_hours ?? hours)),
    helper: `Finished at ${formatTime(end)}${upcoming ? ` · next ${nextLabel(upcoming)}` : ""}`,
  };
}

/** The shift the My shift page focuses on: current, else today's next/last, else the next one. */
function focusShift(shifts: Shift[], now = new Date()) {
  const todayKey = now.toDateString();
  const current = shifts.find((s) => shiftState(s, now) === "active") ?? null;
  const today = shifts.filter((s) => new Date(s.shift_start).toDateString() === todayKey);
  const upcoming = shifts.find((s) => new Date(s.shift_start) > now) ?? null;
  const focus = current ?? today.find((s) => new Date(s.shift_start) > now) ?? today[today.length - 1] ?? null;
  return { current, focus, upcoming };
}

/** Greeting subtitle built from the real roster. */
function shiftSubtitle(shifts: Shift[], now = new Date()): string {
  const { current, focus, upcoming } = focusShift(shifts, now);
  const where = (s: Shift) => (s.location ? ` at ${s.location}` : "");
  const changed = (s: Shift) => (s.short_notice_change_flag ? " This shift was changed at short notice." : "");
  if (current) {
    return `You're on a ${label(current.shift_type).toLowerCase()} shift${where(current)} until ${formatTime(current.shift_end)}.${changed(current)}`;
  }
  if (focus && new Date(focus.shift_start) > now) {
    return `Your ${label(focus.shift_type).toLowerCase()} shift${where(focus)} starts at ${formatTime(focus.shift_start)}.${changed(focus)}`;
  }
  if (upcoming) {
    return `No more shifts today. Your next shift is ${dayLabel(upcoming.shift_start, now).toLowerCase()} at ${formatTime(upcoming.shift_start)}${where(upcoming)}.`;
  }
  return "No upcoming shifts on your roster.";
}

/** "Patient load" and "Staffing" cards for the focus shift (shift_roster columns). */
function shiftCards(shift: Shift | null) {
  if (!shift) {
    return {
      load: { value: "—", helper: "No shift today" },
      staff: { value: "—", helper: "No shift today" },
    };
  }
  const expected = shift.expected_patient_load;
  const actual = shift.actual_patient_load;
  const load =
    expected == null && actual == null
      ? { value: "Not recorded", helper: "No patient load on this shift" }
      : {
          value: `${Number(actual ?? expected)} patients`,
          helper:
            actual != null && expected != null
              ? `Expected ${Number(expected)} · actual ${Number(actual)}`
              : actual != null
                ? "Actual load"
                : "Expected load",
        };
  const planned = shift.planned_staff_count;
  const onShift = shift.actual_staff_count;
  const staff =
    planned == null && onShift == null
      ? { value: "Not recorded", helper: "No staffing data on this shift" }
      : {
          value: planned != null && onShift != null ? `${onShift} of ${planned}` : `${onShift ?? planned}`,
          helper: shift.understaffed_flag
            ? "Understaffed · flagged on the roster"
            : planned != null && onShift != null
              ? "Staff on shift vs planned"
              : "Planned staff",
        };
  return { load, staff };
}

function EmployeeView({
  onCheckIn,
  navigate,
}: {
  onCheckIn: () => void;
  navigate: (page: PageId) => void;
}) {
  const { daypart, mode } = useDaypart();
  const { user } = useAuth();
  const meId = user?.employee_id ?? "";
  const shifts = useMyShifts(meId);
  const pending = useAsync(() => api.list<Question>("/questions/pending/"), [meId]);
  const [answered, setAnswered] = useState<Question[]>([]);
  const [panelOpen, setPanelOpen] = useState(false);
  const [demoIndex, setDemoIndex] = useState<number | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [checkInError, setCheckInError] = useState<string | null>(null);
  const [timelineOpen, setTimelineOpen] = useState(false);
  const closeTimeline = useCallback(() => setTimelineOpen(false), []);
  const [selectedShiftId, setSelectedShiftId] = useState<string | null>(null);
  const [busyAppointments, setBusyAppointments] = useState<Set<string>>(() => new Set());
  const [appointmentError, setAppointmentError] = useState<string | null>(null);

  // Answered-this-session questions stay visible as "Done" until the next load.
  const wellbeingNudges = useMemo(() => {
    const open = (pending.data ?? []).filter((q) => q.options.length > 0 && !answered.some((a) => a.question_id === q.question_id));
    const ordered = [...answered, ...open];
    return ordered.map((q, i) => toNudge(q, i, i < answered.length, i === answered.length));
  }, [pending.data, answered]);
  const pendingNudges = wellbeingNudges.filter((n) => n.status !== "completed");
  const selectedNudge = wellbeingNudges.find((n) => n.id === selectedId) ?? pendingNudges[0] ?? wellbeingNudges[0];

  const openNudge = (nudge: Nudge) => {
    const nudgeIndex = pendingNudges.findIndex((item) => item.id === nudge.id);
    setDemoIndex(nudgeIndex >= 0 ? nudgeIndex : null);
    setSelectedId(nudge.id);
    setPanelOpen(true);
  };

  const startDemo = () => {
    if (!pendingNudges.length) return;
    setDemoIndex(0);
    setSelectedId(pendingNudges[0].id);
    setPanelOpen(true);
  };

  const submitAnswer = async (nudge: Nudge, optionId: string) => {
    setCheckInError(null);
    try {
      await api.post(`/questions/${nudge.id}/answer/`, { option_id: optionId });
      const question = pending.data?.find((q) => q.question_id === nudge.id);
      if (question) setAnswered((prev) => [...prev, question]);
      // Refresh the wellbeing score so the new answer feeds the team signal.
      api
        .post("/wellbeing/calculate/", { employee_id: meId })
        .then(onCheckIn)
        .catch(() => undefined);
      return true;
    } catch (err) {
      setCheckInError(errorMessage(err));
      return false;
    }
  };

  const today = new Date();
  const allShifts = shifts.data ?? [];
  const summary = shiftSummary(allShifts);
  const cards = shiftCards(focusShift(allShifts, today).focus);
  // Roster list: the last few worked shifts plus what's coming up.
  const rosterShifts = [
    ...allShifts.filter((s) => new Date(s.shift_end) <= today).slice(-3),
    ...allShifts.filter((s) => new Date(s.shift_end) > today).slice(0, 5),
  ];

  // Appointments for every day in the roster list (one request), grouped by day.
  const firstDay = rosterShifts.length ? shiftDay(rosterShifts[0]) : null;
  const lastDay = rosterShifts.length ? shiftDay(rosterShifts[rosterShifts.length - 1]) : null;
  const appointments = useAsync(
    () =>
      firstDay && lastDay
        ? api.listAll<Appointment>("/appointments/", {
            employee: meId,
            appointment_date__gte: firstDay,
            appointment_date__lte: lastDay,
            ordering: "appointment_date,start_time",
          })
        : Promise.resolve([] as Appointment[]),
    [meId, firstDay, lastDay],
  );
  const apptsByDay = useMemo(() => {
    const map = new Map<string, Appointment[]>();
    (appointments.data ?? []).forEach((a) => map.set(a.appointment_date, [...(map.get(a.appointment_date) ?? []), a]));
    return map;
  }, [appointments.data]);
  const apptsFor = (s: Shift) => apptsByDay.get(shiftDay(s)) ?? [];

  // Selected roster shift: the user's pick, else today's shift if it has appointments,
  // else the most recent shift that has appointments.
  const focus = focusShift(allShifts, today).focus;
  const defaultShift =
    (focus && apptsFor(focus).length ? focus : null) ??
    [...rosterShifts].reverse().find((s) => new Date(s.shift_start) <= today && apptsFor(s).length > 0) ??
    focus ??
    rosterShifts[0] ??
    null;
  const selectedShift = rosterShifts.find((s) => s.shift_id === selectedShiftId) ?? defaultShift;

  const toggleAppointment = async (a: Appointment) => {
    const completing = !isCompleted(a);
    const setStatus = (status: Appointment["status"]) =>
      appointments.setData((list) =>
        (list ?? []).map((x) => (x.appointment_id === a.appointment_id ? { ...x, status } : x)),
      );
    setAppointmentError(null);
    setBusyAppointments((prev) => new Set(prev).add(a.appointment_id));
    setStatus(completing ? "COMPLETED" : "SCHEDULED"); // optimistic
    try {
      const updated = await api.post<Appointment>(`/appointments/${a.appointment_id}/${completing ? "complete" : "reopen"}/`);
      setStatus(updated.status);
    } catch (err) {
      setStatus(a.status);
      setAppointmentError(errorMessage(err));
    } finally {
      setBusyAppointments((prev) => {
        const next = new Set(prev);
        next.delete(a.appointment_id);
        return next;
      });
    }
  };

  return (
    <main className="employee-page page-shell">
      <section className="welcome-row">
        <div>
          <span className="section-kicker">
            {today.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
            <span className="daypart-chip" title="Change it from the theme button in the header">
              {DAYPART_META[daypart].icon(12)}
              {DAYPART_META[daypart].label} theme{mode === "auto" ? " · auto" : ""}
            </span>
          </span>
          <h1>{greeting(today)}, {user?.first_name}.</h1>
          <p>{shifts.loading ? "Loading your roster…" : shiftSubtitle(shifts.data ?? [], today)}</p>
        </div>
        <div className="shift-status">
          <span className="status-dot" />
          {shifts.loading ? "Loading shift…" : summary.status}
          <strong>{shifts.loading ? "" : summary.range}</strong>
        </div>
      </section>

      <section className="employee-metrics">
        <MetricCard
          icon={<Clock3 size={20} />}
          label="Today’s shift"
          value={shifts.loading ? "…" : summary.value}
          helper={shifts.error ? "Could not load your roster" : summary.helper}
          tone="blue"
        />
        <MetricCard
          icon={<UsersRound size={20} />}
          label="Patient load"
          value={shifts.loading ? "…" : cards.load.value}
          helper={cards.load.helper}
          tone="teal"
        />
        <MetricCard
          icon={<UsersRound size={20} />}
          label="Staffing"
          value={shifts.loading ? "…" : cards.staff.value}
          helper={cards.staff.helper}
          tone="violet"
        />
      </section>

      <div className="employee-layout stacked">
        {/* Roster (left) and the selected shift's appointments (right) */}
        <div className="employee-main day-row">
          <section className="surface schedule-surface">
            <div className="surface-heading">
              <div>
                <span className="section-kicker">Your roster</span>
                <h2>Recent &amp; upcoming shifts</h2>
              </div>
              <button className="secondary-button" onClick={() => setTimelineOpen(true)}>
                <CalendarDays size={16} />
                Full roster
              </button>
            </div>
            <ErrorNote message={shifts.error} onRetry={shifts.reload} />
            {shifts.loading ? (
              <Loading text="Loading your shifts…" />
            ) : rosterShifts.length === 0 ? (
              <p className="schedule-empty">No shifts on your roster.</p>
            ) : (
              <>
                <p className="schedule-hint">Select a shift to see its appointments.</p>
                <ol className="schedule-list">
                  {rosterShifts.map((shift) => (
                    <ScheduleItem
                      key={shift.shift_id}
                      shift={shift}
                      now={today}
                      selected={selectedShift?.shift_id === shift.shift_id}
                      onSelect={() => setSelectedShiftId(shift.shift_id)}
                      appointments={appointments.loading ? null : apptsFor(shift)}
                    />
                  ))}
                </ol>
              </>
            )}
          </section>

          <DayPlan
            shift={selectedShift}
            appointments={selectedShift ? apptsFor(selectedShift) : []}
            loading={shifts.loading || appointments.loading}
            error={appointments.error ?? appointmentError}
            onRetry={() => {
              setAppointmentError(null);
              void appointments.reload();
            }}
            onToggle={(a) => void toggleAppointment(a)}
            busyIds={busyAppointments}
            now={today}
          />
        </div>

        <aside className="employee-side wide">
          <section className="surface moments-card">
            <div className="moments-heading">
              <div>
                <span className="section-kicker">For you today</span>
                <h2>Your wellbeing rhythm</h2>
              </div>
              {pendingNudges.length > 0 && (
                <button className="demo-button" onClick={startDemo}>
                  <Sparkles size={13} />
                  Answer all {pendingNudges.length}
                </button>
              )}
            </div>
            <p className="moments-intro">
              Small check-ins placed around natural pauses in your day.
            </p>
            <ErrorNote message={pending.error ?? checkInError} onRetry={pending.error ? pending.reload : undefined} />
            {pending.loading ? (
              <Loading text="Loading check-ins…" />
            ) : wellbeingNudges.length === 0 ? (
              <p className="moments-intro">You’re all caught up — no check-ins waiting.</p>
            ) : (
              <div className="moment-list">
                {wellbeingNudges.map((nudge) => (
                  <button
                    className={`moment-row ${nudge.status} ${nudge.tone}`}
                    key={nudge.id}
                    onClick={() => openNudge(nudge)}
                  >
                    <span className="moment-time">{nudge.time}</span>
                    <span className="moment-marker">
                      {nudge.status === "completed" ? (
                        <Check size={14} />
                      ) : nudge.status === "now" ? (
                        <Heart size={14} fill="currentColor" />
                      ) : (
                        <Clock3 size={14} />
                      )}
                    </span>
                    <span className="moment-copy">
                      <strong>{nudge.category}</strong>
                      <small>{nudge.context}</small>
                    </span>
                    <span className="moment-status">
                      {nudge.status === "completed"
                        ? "Done"
                        : nudge.status === "now"
                          ? "Now"
                          : "Later"}
                    </span>
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="surface trust-card">
            <div className="shield-badge"><ShieldCheck size={22} /></div>
            <div>
              <span className="section-kicker">Privacy promise</span>
              <h3>Your words stay yours.</h3>
              <p>
                Team leads only see combined patterns and contributing work
                factors. They never see individual answers.
              </p>
              <button className="inline-link" onClick={() => navigate("wellbeing")}>
                How your data is used <ArrowRight size={15} />
              </button>
            </div>
          </section>
        </aside>
      </div>

      <button
        className={`floating-support ${panelOpen ? "open" : ""}`}
        aria-label="Open ShiftGuard wellbeing support"
        onClick={() => {
          if (!panelOpen) {
            if (!selectedNudge) {
              navigate("wellbeing");
              return;
            }
            setDemoIndex(pendingNudges.length ? 0 : null);
            setSelectedId(pendingNudges[0]?.id ?? selectedNudge.id);
          } else {
            setDemoIndex(null);
          }
          setPanelOpen(!panelOpen);
        }}
      >
        {panelOpen ? <X size={23} /> : <Heart size={23} fill="currentColor" />}
        {!panelOpen && pendingNudges.length > 0 && <span>{pendingNudges.length}</span>}
      </button>
      {selectedNudge && (
        <WellbeingPanel
          key={selectedNudge.id}
          open={panelOpen}
          nudge={selectedNudge}
          onClose={() => {
            setPanelOpen(false);
            setDemoIndex(null);
          }}
          onSubmit={(optionId) => {
            const current = selectedNudge;
            const remaining = pendingNudges.filter((n) => n.id !== current.id);
            setPanelOpen(false);
            void submitAnswer(current, optionId).then((ok) => {
              if (ok && demoIndex !== null && remaining.length > 0) {
                window.setTimeout(() => {
                  setDemoIndex(0);
                  setSelectedId(remaining[0].id);
                  setPanelOpen(true);
                }, 450);
              } else {
                setDemoIndex(null);
              }
            });
          }}
        />
      )}
      <RosterTimelineDrawer
        open={timelineOpen}
        shifts={shifts.data ?? []}
        loading={shifts.loading}
        error={shifts.error}
        onClose={closeTimeline}
        onOpenRoster={() => navigate("roster")}
      />
    </main>
  );
}

// ---------------------------------------------------------------------------
// manager view ("Team view")
// ---------------------------------------------------------------------------
function StatusPill({ level }: { level: RiskLevel }) {
  return (
    <span
      className={`status-pill ${
        level === "Needs attention"
          ? "danger"
          : level === "Keep an eye"
            ? "warning"
            : "healthy"
      }`}
    >
      {level}
    </span>
  );
}

/** Contributing factors in the team table: first two, then "+N more" to expand. */
const FACTORS_PREVIEW = 2;

function FactorsCell({ factors }: { factors: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const hidden = factors.length - FACTORS_PREVIEW;
  const shown = expanded ? factors : factors.slice(0, FACTORS_PREVIEW);

  // The whole row is a button (opens the drawer), so this toggle is a
  // keyboard-accessible span that stops the click reaching the row.
  const toggle = (e: React.MouseEvent | React.KeyboardEvent) => {
    e.stopPropagation();
    setExpanded((v) => !v);
  };

  return (
    <div className={`factors-cell ${expanded ? "expanded" : ""}`}>
      <strong>{shown[0]}</strong>
      {shown.slice(1).map((factor) => (
        <span key={factor}>+ {factor}</span>
      ))}
      {hidden > 0 && (
        <small
          className="factor-more"
          role="button"
          tabIndex={0}
          aria-expanded={expanded}
          onClick={toggle}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              toggle(e);
            }
          }}
        >
          {expanded ? "Show less" : `Show ${hidden} more`}
          <ChevronDown size={12} />
        </small>
      )}
    </div>
  );
}

function MiniTrend({ values, level }: { values: number[]; level: RiskLevel }) {
  const series = values.length > 1 ? values : [values[0] ?? 0, values[0] ?? 0];
  const points = series
    .map((value, index) => {
      const x = (index / (series.length - 1)) * 78 + 2;
      const y = 31 - (value / 100) * 27;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg className={`mini-trend ${level.replace(/\s+/g, "-").toLowerCase()}`} viewBox="0 0 82 34" aria-hidden="true">
      <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/** Team trend chart: weekly averages of the team's risk snapshots. */
function OverviewChart({ series, loading }: { series: WeeklyPoint[]; loading: boolean }) {
  const values = series.flatMap((p) => [p.wellbeing, p.workload]).filter((v): v is number => v != null);
  if (loading) return <div className="chart-wrap"><Loading text="Loading team trend…" /></div>;
  if (values.length === 0) {
    return <div className="chart-wrap"><p className="pp-muted">No wellbeing snapshots for this period yet.</p></div>;
  }
  // Shared y-scale with a little padding so both lines stay inside the plot.
  const lo = Math.max(0, Math.floor(Math.min(...values) - 5));
  const hi = Math.ceil(Math.max(...values) + 5);
  const x = (i: number) => (series.length > 1 ? (i / (series.length - 1)) * 620 + 10 : 320);
  const y = (v: number) => 170 - ((v - lo) / Math.max(1, hi - lo)) * 140;
  const toPoints = (key: "wellbeing" | "workload") =>
    series
      .map((p, i) => (p[key] == null ? null : `${x(i)},${y(p[key]!)}`))
      .filter(Boolean)
      .join(" ");
  const workload = toPoints("workload");
  const firstX = series.findIndex((p) => p.workload != null);
  const lastX = series.length - 1 - [...series].reverse().findIndex((p) => p.workload != null);
  const step = Math.max(1, Math.ceil(series.length / 6));
  const fmt = (d: Date) => d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        <span><i className="workload-dot" /> Workload (hours vs contract, %)</span>
        <span><i className="wellbeing-dot" /> Wellbeing score</span>
      </div>
      <svg viewBox="0 0 640 190" role="img" aria-label="Weekly team workload and average wellbeing score">
        {[30, 70, 110, 150].map((gy) => (
          <line key={gy} x1="10" y1={gy} x2="630" y2={gy} className="grid-line" />
        ))}
        <defs>
          <linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2764e7" stopOpacity=".18" />
            <stop offset="100%" stopColor="#2764e7" stopOpacity="0" />
          </linearGradient>
        </defs>
        {workload && firstX >= 0 && (
          <polygon points={`${x(firstX)},178 ${workload} ${x(lastX)},178`} fill="url(#area-fill)" />
        )}
        <polyline className="chart-line workload-line" points={workload} />
        <polyline className="chart-line wellbeing-line" points={toPoints("wellbeing")} />
        {series.map((p, i) => (
          <g key={i}>
            {p.workload != null && (
              <circle cx={x(i)} cy={y(p.workload)} r="3" className="chart-point workload">
                <title>{`Week of ${fmt(p.weekStart)}: workload ${p.workload.toFixed(0)}%`}</title>
              </circle>
            )}
            {p.wellbeing != null && (
              <circle cx={x(i)} cy={y(p.wellbeing)} r="3" className="chart-point wellbeing">
                <title>{`Week of ${fmt(p.weekStart)}: wellbeing ${p.wellbeing.toFixed(0)}`}</title>
              </circle>
            )}
          </g>
        ))}
      </svg>
      <div className="chart-axis">
        {series.map((p, i) =>
          i % step === 0 || i === series.length - 1 ? <span key={i}>{fmt(p.weekStart)}</span> : null,
        )}
      </div>
    </div>
  );
}

/** Roster-derived weekly figures for the drawer (from the latest risk snapshot + shifts). */
function useMemberStats(memberId: string) {
  return useAsync(async () => {
    const since = new Date(Date.now() - 30 * 86400000).toISOString();
    const [snapshots, shifts] = await Promise.all([
      api.list<RiskSnapshot>("/risk-snapshots/", { employee: memberId, ordering: "-snapshot_date" }),
      api.get<{ count: number }>("/shifts/", { employee: memberId, shift_start__gte: since }),
    ]);
    const snap = snapshots[0];
    if (!snap) return null;
    const perWeek = 7 / 30;
    const shiftCount = shifts.count ?? 0;
    return {
      hours: Math.round(Number(snap.actual_hours_worked_30d) * perWeek),
      overtime: Math.round(Number(snap.overtime_hours_30d) * perWeek),
      breaks: shiftCount ? Math.max(0, Math.round(((shiftCount - snap.missed_breaks_30d) / shiftCount) * 100)) : null,
      date: snap.snapshot_date,
    };
  }, [memberId]);
}

function TeamMemberDrawer({
  member,
  onClose,
}: {
  member: TeamMember | null;
  onClose: () => void;
}) {
  if (!member) return null;
  return <TeamMemberDrawerBody key={member.id} member={member} onClose={onClose} />;
}

function TeamMemberDrawerBody({
  member,
  onClose,
}: {
  member: TeamMember;
  onClose: () => void;
}) {
  const stats = useMemberStats(member.id);
  const employee = useAsync(() => api.get<Employee>(`/employees/${member.id}/`), [member.id]);
  const s = stats.data;

  return (
    <>
      <button className="drawer-backdrop" aria-label="Close team member details" onClick={onClose} />
      <aside className="member-drawer">
        <div className="drawer-top">
          <div className="avatar avatar-large" style={{ background: member.color }}>
            {member.initials}
          </div>
          <div>
            <span className="section-kicker">Team member overview</span>
            <h2>{member.name}</h2>
            <p>{member.role} · {member.department ?? "No department"}</p>
          </div>
          <button className="ghost-icon" onClick={onClose} aria-label="Close">
            <X size={20} />
          </button>
        </div>
        <div className="drawer-score">
          <div>
            <span>Current risk signal</span>
            <strong>{member.risk}<small>/100</small></strong>
          </div>
          <StatusPill level={member.level} />
        </div>
        <div className="drawer-section">
          <span className="section-kicker">What’s contributing</span>
          <h3>Explainable factors</h3>
          <ul className="factor-list">
            {member.factors.map((factor, index) => (
              <li key={factor}>
                <span>{index + 1}</span>
                <div>
                  <strong>{factor}</strong>
                  <small>Based on aggregated patterns over recent weeks</small>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="drawer-stat-grid">
          <div><span>Hours this week</span><strong>{s ? `${s.hours}h` : stats.loading ? "…" : "—"}</strong></div>
          <div><span>Overtime</span><strong>{s ? `${s.overtime}h` : stats.loading ? "…" : "—"}</strong></div>
          <div><span>Break compliance</span><strong>{s && s.breaks !== null ? `${s.breaks}%` : stats.loading ? "…" : "—"}</strong></div>
        </div>
        <div className="privacy-boundary">
          <LockKeyhole size={20} />
          <div>
            <strong>Privacy boundary</strong>
            <p>
              Raw check-in responses are not available. This view combines
              roster signals with anonymised, rolling wellbeing trends.
            </p>
          </div>
        </div>
        {employee.data && (
          <div style={{ marginTop: 16 }}>
            <Relations employee={employee.data} onChanged={(updated) => employee.setData(updated)} />
          </div>
        )}
      </aside>
    </>
  );
}

function ManagerView({ recentUpdate }: { recentUpdate: boolean }) {
  const { user } = useAuth();
  const { byId } = useEmployees();
  const team = useAsync(() => api.get<WellbeingSummary[]>("/wellbeing/team/"), []);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState<"All" | "Needs attention" | "Keep an eye">("All");
  const [weeks, setWeeks] = useState(12);
  const [department, setDepartment] = useState("All");
  const snapshots = useAsync(
    () =>
      api.listAll<RiskSnapshot>("/risk-snapshots/", {
        snapshot_date__gte: isoDate(new Date(Date.now() - weeks * 7 * 86400000)),
        // No is_training_record filter: every snapshot the Supabase pipeline wrote is flagged as training.
        ordering: "-snapshot_date",
      }),
    [weeks],
  );
  // Last 7 days of model predictions, anchored on the newest snapshot so stale data still shows.
  const predictionsFrom = useMemo(
    () => (snapshots.data ? daysBeforeLatest(snapshots.data, 7) : null),
    [snapshots.data],
  );
  const predictions = useAsync(
    () =>
      predictionsFrom
        ? api.listAll<RiskPrediction>("/risk-predictions/", { predicted_at__gte: predictionsFrom, ordering: "predicted_at" })
        : Promise.resolve([] as RiskPrediction[]),
    [predictionsFrom],
  );
  const riskSeries = useMemo(() => riskSeriesByEmployee(predictions.data ?? []), [predictions.data]);

  const members = useMemo(
    () =>
      (team.data ?? [])
        .filter((s) => s.employee_id !== user?.employee_id)
        .map((s) => withSupabaseRows(s, snapshots.data ?? [], predictions.data ?? []))
        .map((s) => toMember(s, byId.get(s.employee_id), riskSeries.get(s.employee_id)))
        .sort((a, b) => b.risk - a.risk),
    [team.data, byId, user?.employee_id, riskSeries, snapshots.data, predictions.data],
  );
  const departments = useMemo(
    () => [...new Set(members.map((m) => m.department).filter((d): d is string => Boolean(d)))].sort(),
    [members],
  );
  const teamMembers = useMemo(
    () => members.filter((m) => department === "All" || m.department === department),
    [members, department],
  );
  const visibleMembers = teamMembers.filter(
    (member) => filter === "All" || member.level === filter,
  );
  const series = useMemo(() => {
    const ids = new Set(teamMembers.map((m) => m.id));
    return weeklySeries((snapshots.data ?? []).filter((snap) => ids.has(snap.employee_id)), weeks);
  }, [snapshots.data, teamMembers, weeks]);
  const insight = trendInsight(series);
  const factors = leadingFactors(teamMembers.map((m) => m.drivers), series);
  const selected = members.find((m) => m.id === selectedId) ?? null;

  const counts = useMemo(
    () => ({
      high: teamMembers.filter((member) => member.level === "Needs attention").length,
      watch: teamMembers.filter((member) => member.level === "Keep an eye").length,
      well: teamMembers.filter((member) => member.level === "Doing well").length,
      highRising: teamMembers.filter((m) => m.level === "Needs attention" && m.delta > 0).length,
      watchRising: teamMembers.filter((m) => m.level === "Keep an eye" && m.delta > 0).length,
      improving: teamMembers.filter((m) => m.delta < 0).length,
    }),
    [teamMembers],
  );

  return (
    <main className="manager-page page-shell">
      <section className="manager-title-row">
        <div>
          <span className="section-kicker">{user?.department ?? "Your team"} · Team overview</span>
          <h1>Team wellbeing</h1>
          <p>Understand changing patterns early, without exposing private responses.</p>
        </div>
        <div className="manager-controls">
          <label className="secondary-button select-pill">
            <span className="sr-only">Time range</span>
            <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}>
              <option value={4}>Last 4 weeks</option>
              <option value={12}>Last 12 weeks</option>
              <option value={26}>Last 26 weeks</option>
            </select>
            <ChevronDown size={15} />
          </label>
          <label className="secondary-button select-pill">
            <span className="sr-only">Team</span>
            <select value={department} onChange={(e) => setDepartment(e.target.value)}>
              <option value="All">All teams</option>
              {departments.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </select>
            <ChevronDown size={15} />
          </label>
        </div>
      </section>

      {recentUpdate && (
        <div className="update-banner">
          <Sparkles size={18} />
          <div>
            <strong>Aggregated signal updated</strong>
            <span>A new private check-in has been included in the team trend.</span>
          </div>
          <span className="live-pill">Demo update</span>
        </div>
      )}

      <section className="summary-grid">
        <article className="summary-card red">
          <div className="summary-icon"><Activity size={20} /></div>
          <div><span>Needs attention</span><strong>{counts.high}</strong><small>People with rising indicators</small></div>
          {counts.highRising > 0 ? (
            <span className="summary-change"><ArrowUpRight size={14} /> {counts.highRising} rising</span>
          ) : (
            <span className="summary-change neutral">No change</span>
          )}
        </article>
        <article className="summary-card amber">
          <div className="summary-icon"><CircleHelp size={20} /></div>
          <div><span>Keep an eye</span><strong>{counts.watch}</strong><small>Patterns worth monitoring</small></div>
          {counts.watchRising > 0 ? (
            <span className="summary-change"><ArrowUpRight size={14} /> {counts.watchRising} rising</span>
          ) : (
            <span className="summary-change neutral">No change</span>
          )}
        </article>
        <article className="summary-card green">
          <div className="summary-icon"><Leaf size={20} /></div>
          <div><span>Doing well</span><strong>{counts.well}</strong><small>Stable or improving patterns</small></div>
          {counts.improving > 0 ? (
            <span className="summary-change positive"><ArrowDownRight size={14} /> {counts.improving} improving</span>
          ) : (
            <span className="summary-change neutral">No change</span>
          )}
        </article>
      </section>

      <ReturnToWorkTeam
        members={(team.data ?? [])
          .filter((s) => s.employee_id !== user?.employee_id)
          .map((s) => byId.get(s.employee_id))
          .filter((e): e is Employee => Boolean(e))}
        snapshots={snapshots.data ?? []}
      />

      <div className="manager-grid">
        <section className="surface chart-surface">
          <div className="surface-heading">
            <div>
              <span className="section-kicker">Signal movement</span>
              <h2>Team trend</h2>
            </div>
            <div className="insight-chip"><Sparkles size={14} /> Auto insight</div>
          </div>
          <ErrorNote message={snapshots.error} onRetry={snapshots.reload} />
          <OverviewChart series={series} loading={snapshots.loading} />
          {insight && (
            <div className="chart-insight">
              <TrendingUp size={19} />
              <p>
                <strong>{insight.title}</strong> {insight.text}
              </p>
            </div>
          )}
        </section>
        <section className="surface factor-surface">
          <div className="surface-heading">
            <div>
              <span className="section-kicker">Across the team</span>
              <h2>Leading factors</h2>
            </div>
            <Info size={18} />
          </div>
          <div className="factor-bars">
            {factors.length === 0 ? (
              <p className="pp-muted">No risk-increasing factors recorded for this team yet.</p>
            ) : (
              factors.map((f, i) => (
                <div className="factor-bar-row" key={f.label}>
                  <div>
                    <span>{f.label}</span>
                    <strong className={f.change != null && f.change < 0 ? "down" : ""}>
                      {f.change != null ? `${f.change > 0 ? "+" : ""}${f.change}%` : `${f.count} of ${teamMembers.length}`}
                    </strong>
                  </div>
                  <div className="bar-track">
                    <i className={["red", "amber", "violet", "blue"][i % 4]} style={{ width: `${Math.max(4, f.share)}%` }} />
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="privacy-inline">
            <ShieldCheck size={18} />
            <p><strong>Aggregated only.</strong> No individual answers or images are shown.</p>
          </div>
        </section>
      </div>

      <section className="surface team-surface">
        <div className="team-table-header">
          <div>
            <span className="section-kicker">Ranked by changing pattern</span>
            <h2>Team members</h2>
          </div>
          <div className="filter-tabs" aria-label="Filter team members">
            {(["All", "Needs attention", "Keep an eye"] as const).map((item) => (
              <button
                key={item}
                className={filter === item ? "active" : ""}
                onClick={() => setFilter(item)}
              >
                {item}
              </button>
            ))}
          </div>
        </div>
        {team.error && <ErrorNote message={team.error} onRetry={team.reload} />}
        {team.loading && <Loading text="Loading team wellbeing…" />}
        {!team.loading && !team.error && visibleMembers.length === 0 && (
          <div className="pp-state">No team members to show.</div>
        )}
        <div className="team-table" role="table">
          <div className="table-row table-head" role="row">
            <span>Team member</span><span>Risk signal</span><span>12-week trend</span><span>Contributing factors</span><span />
          </div>
          {visibleMembers.map((member) => (
            <button className="table-row member-row" key={member.id} onClick={() => setSelectedId(member.id)} role="row">
              <div className="member-identity">
                <div className="avatar" style={{ background: member.color }}>{member.initials}</div>
                <div><strong>{member.name}</strong><span>{member.role}</span></div>
              </div>
              <div className="risk-cell"><StatusPill level={member.level} /><span className={member.delta < 0 ? "delta down" : "delta"}>{member.delta < 0 ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}{Math.abs(member.delta)}%</span></div>
              <MiniTrend values={member.trend} level={member.level} />
              <FactorsCell factors={member.factors} />
              <ArrowRight size={18} className="row-arrow" />
            </button>
          ))}
        </div>
        <div className="mobile-member-list">
          {visibleMembers.map((member) => (
            <button className="mobile-member-card" key={member.id} onClick={() => setSelectedId(member.id)}>
              <div className="member-identity">
                <div className="avatar" style={{ background: member.color }}>{member.initials}</div>
                <div><strong>{member.name}</strong><span>{member.role}</span></div>
              </div>
              <StatusPill level={member.level} />
              <div className="mobile-factor"><span>Primary factor</span><strong>{member.factors[0]}</strong></div>
              <div className="mobile-risk-row">
                <MiniTrend values={member.trend} level={member.level} />
                <span className={member.delta < 0 ? "delta down" : "delta"}>{member.delta < 0 ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}{Math.abs(member.delta)}%</span>
                <ArrowRight size={17} />
              </div>
            </button>
          ))}
        </div>
      </section>

      <TeamMemberDrawer member={selected} onClose={() => setSelectedId(null)} />
    </main>
  );
}

// ---------------------------------------------------------------------------
// app shell
// ---------------------------------------------------------------------------
function Shell() {
  const { user, loading, isManager, isStaff } = useAuth();
  const { page, navigate } = usePage();
  const [recentUpdate, setRecentUpdate] = useState(false);

  if (loading) {
    return (
      <main className="pp-auth">
        <Loading text="Restoring your session…" />
      </main>
    );
  }
  if (!user) return <AuthPage />;

  // Role-gated pages fall back to "My shift".
  const allowed =
    (page !== "manager" && page !== "team-roster") || isManager
      ? page !== "admin" || isStaff
      : false;
  const current: PageId = allowed ? page : "employee";

  return (
    <div className="app">
      <AppHeader page={current} navigate={navigate} />
      {current === "employee" && <EmployeeView onCheckIn={() => setRecentUpdate(true)} navigate={navigate} />}
      {current === "manager" && <ManagerView recentUpdate={recentUpdate} />}
      {current === "profile" && <ProfilePage />}
      {current === "wellbeing" && <WellbeingPage />}
      {current === "roster" && <RosterPage key="roster" />}
      {current === "team-roster" && <RosterPage key="team-roster" initialTab="shifts" />}
      {current === "leave" && <LeavePage />}
      {current === "admin" && <AdminPage />}
    </div>
  );
}

export default function App() {
  return (
    <DaypartProvider>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </DaypartProvider>
  );
}
