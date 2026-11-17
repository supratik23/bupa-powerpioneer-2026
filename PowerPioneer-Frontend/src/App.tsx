import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Bell,
  CalendarDays,
  Check,
  ChevronDown,
  CircleHelp,
  Clock3,
  Coffee,
  Download,
  Heart,
  Info,
  Leaf,
  LockKeyhole,
  Menu,
  MessageCircleHeart,
  MoreHorizontal,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  TrendingUp,
  UserRound,
  UsersRound,
  X,
} from "lucide-react";

type Role = "employee" | "manager";
type RiskLevel = "Needs attention" | "Keep an eye" | "Doing well";
type NudgeCategory =
  | "Emotional check-in"
  | "Energy & fatigue"
  | "Break & recovery"
  | "Hydration & physical comfort";

type Nudge = {
  id: string;
  category: NudgeCategory;
  time: string;
  context: string;
  question: string;
  helper: string;
  status: "completed" | "now" | "later";
  tone: "blue" | "amber" | "violet" | "teal";
  options: Array<{
    id: string;
    score: number;
    emoji: string;
    title: string;
  }>;
};

type TeamMember = {
  id: number;
  name: string;
  initials: string;
  role: string;
  risk: number;
  delta: number;
  level: RiskLevel;
  factors: string[];
  hours: number;
  overtime: number;
  breaks: number;
  trend: number[];
  color: string;
};

const schedule = [
  {
    time: "08:30",
    duration: "30 min",
    title: "Morning handover",
    detail: "Cedar Ward · Team briefing",
    kind: "handover",
    done: true,
  },
  {
    time: "09:15",
    duration: "45 min",
    title: "Patient consultation",
    detail: "Room 4 · General care",
    kind: "care",
    done: true,
  },
  {
    time: "10:15",
    duration: "30 min",
    title: "Follow-up review",
    detail: "Room 2 · Care plan review",
    kind: "review",
    active: true,
  },
  {
    time: "11:00",
    duration: "15 min",
    title: "Protected break",
    detail: "Staff lounge",
    kind: "break",
  },
  {
    time: "11:30",
    duration: "45 min",
    title: "Patient consultation",
    detail: "Room 3 · General care",
    kind: "care",
  },
  {
    time: "12:30",
    duration: "30 min",
    title: "Clinical notes",
    detail: "Admin time",
    kind: "notes",
  },
];

const initialMembers: TeamMember[] = [
  {
    id: 1,
    name: "Alex Morgan",
    initials: "AM",
    role: "Senior Care Assistant",
    risk: 82,
    delta: 9,
    level: "Needs attention",
    factors: ["High overtime for 3 weeks", "Fewer protected breaks"],
    hours: 51,
    overtime: 9,
    breaks: 62,
    trend: [48, 52, 55, 62, 68, 74, 82],
    color: "#7c3aed",
  },
  {
    id: 2,
    name: "Priya Shah",
    initials: "PS",
    role: "Registered Nurse",
    risk: 74,
    delta: 5,
    level: "Needs attention",
    factors: ["4 consecutive shifts", "Workload trend increasing"],
    hours: 47,
    overtime: 6,
    breaks: 71,
    trend: [45, 48, 51, 56, 62, 69, 74],
    color: "#1677ff",
  },
  {
    id: 3,
    name: "Jamie Taylor",
    initials: "JT",
    role: "Care Assistant",
    risk: 56,
    delta: 3,
    level: "Keep an eye",
    factors: ["Rising overtime", "Leave balance below average"],
    hours: 43,
    overtime: 3,
    breaks: 78,
    trend: [42, 43, 47, 45, 49, 53, 56],
    color: "#00a69c",
  },
  {
    id: 4,
    name: "Maria Lewis",
    initials: "ML",
    role: "Dental Nurse",
    risk: 31,
    delta: -4,
    level: "Doing well",
    factors: ["Good break compliance", "Workload remains balanced"],
    hours: 38,
    overtime: 0,
    breaks: 94,
    trend: [46, 44, 43, 40, 37, 35, 31],
    color: "#f59e0b",
  },
  {
    id: 5,
    name: "Tom King",
    initials: "TK",
    role: "Care Assistant",
    risk: 24,
    delta: -2,
    level: "Doing well",
    factors: ["Consistent shift pattern", "Protected breaks taken"],
    hours: 36,
    overtime: 0,
    breaks: 97,
    trend: [32, 30, 31, 28, 29, 26, 24],
    color: "#14b8a6",
  },
];

const wellbeingNudges: Nudge[] = [
  {
    id: "emotional-morning",
    category: "Emotional check-in",
    time: "08:45",
    context: "Starting your day",
    question: "How are you feeling?",
    helper: "Choose the mood that feels closest right now.",
    status: "now",
    tone: "blue",
    options: [
      { id: "stressed", score: 1, emoji: "😣", title: "Stressed" },
      { id: "tired", score: 2, emoji: "😴", title: "Tired" },
      { id: "anxious", score: 1, emoji: "😟", title: "Anxious" },
      { id: "happy", score: 4, emoji: "😊", title: "Happy" },
      { id: "calm", score: 3, emoji: "😌", title: "Calm" },
    ],
  },
  {
    id: "energy-midmorning",
    category: "Energy & fatigue",
    time: "10:30",
    context: "After your morning appointments",
    question: "How is your energy right now?",
    helper: "A quick check before the next part of your shift.",
    status: "later",
    tone: "amber",
    options: [
      { id: "running-low", score: 1, emoji: "🪫", title: "Running low" },
      { id: "tired", score: 2, emoji: "🥱", title: "A little tired" },
      { id: "okay", score: 3, emoji: "🙂", title: "Doing okay" },
      { id: "energised", score: 4, emoji: "⚡", title: "Energised" },
    ],
  },
  {
    id: "recovery-lunch",
    category: "Break & recovery",
    time: "12:15",
    context: "After a demanding block",
    question: "That was a demanding block. How are you doing?",
    helper: "Take a moment before moving into the rest of your day.",
    status: "later",
    tone: "violet",
    options: [
      { id: "need-break", score: 1, emoji: "🫶", title: "I need a break" },
      { id: "need-moment", score: 2, emoji: "🌿", title: "Need a moment" },
      { id: "doing-okay", score: 3, emoji: "🙂", title: "Doing okay" },
      { id: "ready", score: 4, emoji: "👍", title: "Ready to continue" },
    ],
  },
  {
    id: "hydration-afternoon",
    category: "Hydration & physical comfort",
    time: "14:30",
    context: "Before your afternoon appointments",
    question: "What would help you feel more comfortable?",
    helper: "Choose a small action for the next natural pause.",
    status: "later",
    tone: "teal",
    options: [
      { id: "water", score: 2, emoji: "💧", title: "Some water" },
      { id: "stretch", score: 2, emoji: "🙆", title: "A quick stretch" },
      { id: "sit", score: 2, emoji: "🪑", title: "A short sit" },
      { id: "comfortable", score: 4, emoji: "✨", title: "I’m comfortable" },
    ],
  },
];

function BrandMark() {
  return (
    <div className="brand-mark" aria-label="ShiftGuard home">
      <div className="pulse-mark">
        <Activity size={23} strokeWidth={2.3} />
      </div>
      <div>
        <strong>ShiftGuard</strong>
        <span>Frontline wellbeing</span>
      </div>
    </div>
  );
}

function RoleSwitch({
  role,
  setRole,
}: {
  role: Role;
  setRole: (role: Role) => void;
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
      <button
        className={role === "manager" ? "active" : ""}
        onClick={() => setRole("manager")}
      >
        <UsersRound size={16} />
        Team view
      </button>
    </div>
  );
}

function AppHeader({
  role,
  setRole,
}: {
  role: Role;
  setRole: (role: Role) => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return (
    <header className="app-header">
      <BrandMark />
      <div className="desktop-role-switch">
        <RoleSwitch role={role} setRole={setRole} />
      </div>
      <div className="header-actions">
        <a
          className="download-source"
          href="/Bupa-ShiftGuard-Source.zip"
          download="Bupa-ShiftGuard-Source.zip"
        >
          <Download size={16} />
          <span>Download source</span>
        </a>
        <button className="icon-button notification-button" aria-label="Notifications">
          <Bell size={19} />
          <span />
        </button>
        <div className="profile-chip">
          <div className="avatar avatar-blue">AR</div>
          <div>
            <strong>{role === "employee" ? "Amelia Reed" : "Daniel Brooks"}</strong>
            <span>{role === "employee" ? "Care assistant" : "Team lead"}</span>
          </div>
          <ChevronDown size={15} />
        </div>
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
            setRole={(nextRole) => {
              setRole(nextRole);
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

function ScheduleItem({
  item,
}: {
  item: (typeof schedule)[number];
}) {
  const KindIcon =
    item.kind === "break"
      ? Coffee
      : item.kind === "handover"
        ? UsersRound
        : item.kind === "notes"
          ? CalendarDays
          : Stethoscope;
  return (
    <li className={`schedule-item ${item.active ? "active" : ""}`}>
      <div className="schedule-time">
        <strong>{item.time}</strong>
        <span>{item.duration}</span>
      </div>
      <div className={`schedule-symbol ${item.kind}`}>
        {item.done ? <Check size={18} /> : <KindIcon size={18} />}
      </div>
      <div className="schedule-copy">
        <div>
          <strong>{item.title}</strong>
          {item.active && <span className="live-pill">In progress</span>}
        </div>
        <span>{item.detail}</span>
      </div>
      <button className="ghost-icon" aria-label={`More options for ${item.title}`}>
        <MoreHorizontal size={19} />
      </button>
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
  onSubmit: (value: number) => void;
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
            <span>{nudge.context}</span>
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
                disabled={selected !== null}
                onClick={() => {
                  setSelected(option.id);
                  window.setTimeout(() => onSubmit(option.score), 120);
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
            One tap saves your private response and closes this check-in.
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

function EmployeeView({
  onCheckIn,
}: {
  onCheckIn: (value: number) => void;
}) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [demoIndex, setDemoIndex] = useState<number | null>(null);
  const [selectedNudge, setSelectedNudge] = useState<Nudge>(wellbeingNudges[0]);

  const openNudge = (nudge: Nudge) => {
    const nudgeIndex = wellbeingNudges.findIndex(
      (item) => item.id === nudge.id,
    );
    setDemoIndex(nudgeIndex >= 0 ? nudgeIndex : null);
    setSelectedNudge(nudge);
    setPanelOpen(true);
  };

  const startDemo = () => {
    setDemoIndex(0);
    setSelectedNudge(wellbeingNudges[0]);
    setPanelOpen(true);
  };

  return (
    <main className="employee-page page-shell">
      <section className="welcome-row">
        <div>
          <span className="section-kicker">Monday, 18 May</span>
          <h1>Good morning, Amelia.</h1>
          <p>You have a steady morning ahead. Your next protected break is at 11:00.</p>
        </div>
        <div className="shift-status">
          <span className="status-dot" />
          Shift in progress
          <strong>08:30–17:00</strong>
        </div>
      </section>

      <section className="employee-metrics">
        <MetricCard
          icon={<Clock3 size={20} />}
          label="Today’s shift"
          value="8h 30m"
          helper="On track · 2h 15m complete"
          tone="blue"
        />
        <MetricCard
          icon={<Coffee size={20} />}
          label="Next break"
          value="11:00"
          helper="In 32 minutes · 15 min protected"
          tone="teal"
        />
        <MetricCard
          icon={<CalendarDays size={20} />}
          label="Appointments"
          value="4 remaining"
          helper="2 completed · next at 11:30"
          tone="violet"
        />
      </section>

      <div className="employee-layout">
        <section className="surface schedule-surface">
          <div className="surface-heading">
            <div>
              <span className="section-kicker">Your day</span>
              <h2>Today’s schedule</h2>
            </div>
            <button className="secondary-button">
              <CalendarDays size={16} />
              Full roster
            </button>
          </div>
          <ol className="schedule-list">
            {schedule.map((item) => (
              <ScheduleItem key={`${item.time}-${item.title}`} item={item} />
            ))}
          </ol>
        </section>

        <aside className="employee-side">
          <section className="surface moments-card">
            <div className="moments-heading">
              <div>
                <span className="section-kicker">For you today</span>
                <h2>Your wellbeing rhythm</h2>
              </div>
              <button className="demo-button" onClick={startDemo}>
                <Sparkles size={13} />
                Demo all 4
              </button>
            </div>
            <p className="moments-intro">
              Small check-ins placed around natural pauses in your day.
            </p>
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
              <button className="inline-link">
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
            setDemoIndex(0);
            setSelectedNudge(wellbeingNudges[0]);
          } else {
            setDemoIndex(null);
          }
          setPanelOpen(!panelOpen);
        }}
      >
        {panelOpen ? <X size={23} /> : <Heart size={23} fill="currentColor" />}
        {!panelOpen && <span>1</span>}
      </button>
      <WellbeingPanel
        key={selectedNudge.id}
        open={panelOpen}
        nudge={selectedNudge}
        onClose={() => {
          setPanelOpen(false);
          setDemoIndex(null);
        }}
        onSubmit={(value) => {
          onCheckIn(value);
          setPanelOpen(false);
          if (
            demoIndex !== null &&
            demoIndex < wellbeingNudges.length - 1
          ) {
            const nextIndex = demoIndex + 1;
            window.setTimeout(() => {
              setDemoIndex(nextIndex);
              setSelectedNudge(wellbeingNudges[nextIndex]);
              setPanelOpen(true);
            }, 450);
          } else {
            setDemoIndex(null);
          }
        }}
      />
    </main>
  );
}

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

function MiniTrend({ values, level }: { values: number[]; level: RiskLevel }) {
  const points = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 78 + 2;
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

function OverviewChart() {
  const lines = {
    workload: [39, 44, 46, 51, 55, 58, 64, 66, 72, 75, 78, 82],
    wellbeing: [74, 71, 75, 68, 67, 61, 63, 55, 51, 49, 44, 40],
  };
  const toPoints = (values: number[]) =>
    values
      .map((v, i) => `${(i / (values.length - 1)) * 620 + 10},${178 - v * 1.55}`)
      .join(" ");
  return (
    <div className="chart-wrap">
      <div className="chart-legend">
        <span><i className="workload-dot" /> Workload pressure</span>
        <span><i className="wellbeing-dot" /> Wellbeing signal</span>
      </div>
      <svg viewBox="0 0 640 190" role="img" aria-label="Team workload pressure rising as aggregated wellbeing signal falls over twelve weeks">
        {[30, 70, 110, 150].map((y) => (
          <line key={y} x1="10" y1={y} x2="630" y2={y} className="grid-line" />
        ))}
        <defs>
          <linearGradient id="area-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#2764e7" stopOpacity=".18" />
            <stop offset="100%" stopColor="#2764e7" stopOpacity="0" />
          </linearGradient>
        </defs>
        <polygon
          points={`10,178 ${toPoints(lines.workload)} 630,178`}
          fill="url(#area-fill)"
        />
        <polyline className="chart-line workload-line" points={toPoints(lines.workload)} />
        <polyline className="chart-line wellbeing-line" points={toPoints(lines.wellbeing)} />
      </svg>
      <div className="chart-axis">
        <span>Wk 1</span><span>Wk 3</span><span>Wk 5</span><span>Wk 7</span><span>Wk 9</span><span>Wk 12</span>
      </div>
    </div>
  );
}

function TeamMemberDrawer({
  member,
  onClose,
}: {
  member: TeamMember | null;
  onClose: () => void;
}) {
  if (!member) return null;
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
            <p>{member.role} · Cedar Ward</p>
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
          <div><span>Hours this week</span><strong>{member.hours}h</strong></div>
          <div><span>Overtime</span><strong>{member.overtime}h</strong></div>
          <div><span>Break compliance</span><strong>{member.breaks}%</strong></div>
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
        <button className="primary-button full">
          Plan a supportive conversation
          <ArrowRight size={17} />
        </button>
      </aside>
    </>
  );
}

function ManagerView({
  members,
  recentUpdate,
}: {
  members: TeamMember[];
  recentUpdate: boolean;
}) {
  const [selected, setSelected] = useState<TeamMember | null>(null);
  const [filter, setFilter] = useState<"All" | "Needs attention" | "Keep an eye">("All");
  const visibleMembers = members.filter(
    (member) => filter === "All" || member.level === filter,
  );

  const counts = useMemo(
    () => ({
      high: members.filter((member) => member.level === "Needs attention").length,
      watch: members.filter((member) => member.level === "Keep an eye").length,
      well: members.filter((member) => member.level === "Doing well").length,
    }),
    [members],
  );

  return (
    <main className="manager-page page-shell">
      <section className="manager-title-row">
        <div>
          <span className="section-kicker">Cedar Ward · Team overview</span>
          <h1>Team wellbeing</h1>
          <p>Understand changing patterns early, without exposing private responses.</p>
        </div>
        <div className="manager-controls">
          <button className="secondary-button">
            Last 12 weeks <ChevronDown size={15} />
          </button>
          <button className="secondary-button">
            All teams <ChevronDown size={15} />
          </button>
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
          <span className="summary-change"><ArrowUpRight size={14} /> 1 this week</span>
        </article>
        <article className="summary-card amber">
          <div className="summary-icon"><CircleHelp size={20} /></div>
          <div><span>Keep an eye</span><strong>{counts.watch}</strong><small>Patterns worth monitoring</small></div>
          <span className="summary-change neutral">No change</span>
        </article>
        <article className="summary-card green">
          <div className="summary-icon"><Leaf size={20} /></div>
          <div><span>Doing well</span><strong>{counts.well}</strong><small>Stable or improving patterns</small></div>
          <span className="summary-change positive"><ArrowUpRight size={14} /> 2 improving</span>
        </article>
        <article className="summary-card blue">
          <div className="summary-icon"><MessageCircleHeart size={20} /></div>
          <div><span>Check-in participation</span><strong>84%</strong><small>Rolling 4-week response rate</small></div>
          <span className="summary-change positive"><ArrowUpRight size={14} /> 6%</span>
        </article>
      </section>

      <div className="manager-grid">
        <section className="surface chart-surface">
          <div className="surface-heading">
            <div>
              <span className="section-kicker">Signal movement</span>
              <h2>Team trend</h2>
            </div>
            <div className="insight-chip"><Sparkles size={14} /> AI insight</div>
          </div>
          <OverviewChart />
          <div className="chart-insight">
            <TrendingUp size={19} />
            <p>
              <strong>Workload pressure is increasing.</strong> Overtime has risen
              for three consecutive weeks while break compliance has declined.
            </p>
          </div>
        </section>
        <section className="surface factor-surface">
          <div className="surface-heading">
            <div>
              <span className="section-kicker">This week</span>
              <h2>Leading factors</h2>
            </div>
            <Info size={18} />
          </div>
          <div className="factor-bars">
            {[
              ["Overtime hours", 78, "+12%", "red"],
              ["Consecutive shifts", 64, "+8%", "amber"],
              ["Missed breaks", 51, "+6%", "violet"],
              ["Low leave balance", 33, "-2%", "blue"],
            ].map(([label, width, change, tone]) => (
              <div className="factor-bar-row" key={label}>
                <div><span>{label}</span><strong className={String(change).startsWith("-") ? "down" : ""}>{change}</strong></div>
                <div className="bar-track"><i className={String(tone)} style={{ width: `${width}%` }} /></div>
              </div>
            ))}
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
        <div className="team-table" role="table">
          <div className="table-row table-head" role="row">
            <span>Team member</span><span>Risk signal</span><span>12-week trend</span><span>Contributing factors</span><span />
          </div>
          {visibleMembers.map((member) => (
            <button className="table-row member-row" key={member.id} onClick={() => setSelected(member)} role="row">
              <div className="member-identity">
                <div className="avatar" style={{ background: member.color }}>{member.initials}</div>
                <div><strong>{member.name}</strong><span>{member.role}</span></div>
              </div>
              <div className="risk-cell"><StatusPill level={member.level} /><span className={member.delta < 0 ? "delta down" : "delta"}>{member.delta < 0 ? <ArrowDownRight size={14} /> : <ArrowUpRight size={14} />}{Math.abs(member.delta)}%</span></div>
              <MiniTrend values={member.trend} level={member.level} />
              <div className="factors-cell">
                <strong>{member.factors[0]}</strong>
                <span>+ {member.factors[1]}</span>
              </div>
              <ArrowRight size={18} className="row-arrow" />
            </button>
          ))}
        </div>
        <div className="mobile-member-list">
          {visibleMembers.map((member) => (
            <button className="mobile-member-card" key={member.id} onClick={() => setSelected(member)}>
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

      <TeamMemberDrawer member={selected} onClose={() => setSelected(null)} />
    </main>
  );
}

export default function App() {
  const [role, setRole] = useState<Role>("employee");
  const [members, setMembers] = useState(initialMembers);
  const [recentUpdate, setRecentUpdate] = useState(false);

  const handleCheckIn = (value: number) => {
    setRecentUpdate(true);
    setMembers((current) =>
      current.map((member) =>
        member.id === 2
          ? {
              ...member,
              risk: Math.max(24, member.risk + (value <= 2 ? 3 : -3)),
              delta: value <= 2 ? 7 : 2,
              factors:
                value <= 2
                  ? ["4 consecutive shifts", "Aggregated wellbeing trend declined"]
                  : member.factors,
            }
          : member,
      ),
    );
  };

  return (
    <div className="app">
      <AppHeader role={role} setRole={setRole} />
      {role === "employee" ? (
        <EmployeeView onCheckIn={handleCheckIn} />
      ) : (
        <ManagerView members={members} recentUpdate={recentUpdate} />
      )}
    </div>
  );
}
