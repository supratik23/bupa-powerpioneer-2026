import { Baby, Check, CircleAlert, Heart, LockKeyhole } from "lucide-react";
import { api } from "../api/client";
import type { Employee, RiskSnapshot, Shift } from "../api/types";
import { avatarColor, initials } from "../lib/format";
import {
  buildReturnPlan,
  checkInLabel,
  isReturning,
  todaysPattern,
  weekPattern,
} from "../lib/returnToWork";
import type { Guideline, ReturnPlan } from "../lib/returnToWork";
import { useAsync } from "../lib/useAsync";

function GuidelineChips({ guidelines }: { guidelines: Guideline[] }) {
  return (
    <div className="rtw-chips">
      {guidelines.map((g) => (
        <span key={g.label} className={`rtw-chip ${g.met === false ? "off" : g.met ? "on" : "unknown"}`} title={g.detail}>
          {g.met === false ? <CircleAlert size={12} /> : <Check size={12} strokeWidth={3} />}
          {g.label}
          {g.met === false && <small>· {g.detail}</small>}
        </span>
      ))}
    </div>
  );
}

function Progress({ plan }: { plan: ReturnPlan }) {
  return (
    <div
      className="rtw-progress"
      role="progressbar"
      aria-label="Return-to-work progress"
      aria-valuemin={0}
      aria-valuemax={plan.totalWeeks}
      aria-valuenow={plan.week}
    >
      <b style={{ width: `${Math.round(plan.progress * 100)}%` }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Employee: "Welcome back" card on My wellbeing
// ---------------------------------------------------------------------------
export function ReturnToWorkCard({ employee, snapshot }: { employee: Employee; snapshot: RiskSnapshot | null }) {
  const today = new Date();
  const shifts = useAsync(
    () =>
      api.list<Shift>("/shifts/", {
        employee: employee.employee_id,
        shift_start__gte: new Date(new Date().setHours(0, 0, 0, 0)).toISOString(),
        ordering: "shift_start",
      }),
    [employee.employee_id],
  );
  const plan = buildReturnPlan(employee, snapshot, today);
  if (!plan) return null;
  const pattern = todaysPattern(shifts.data ?? [], today);
  const offTrack = plan.guidelines.filter((g) => g.met === false);

  return (
    <section className="surface rtw-card">
      <div className="rtw-head">
        <div className="rtw-icon"><Baby size={24} /></div>
        <div>
          <span className="section-kicker">We’re glad you’re back</span>
          <h2>Welcome back, {employee.first_name}</h2>
        </div>
        <span className="rtw-week">Week {plan.week} of {plan.totalWeeks}</span>
      </div>

      <p className="rtw-intro">
        Take things at your pace. Your return-to-work adjustments are here to make each shift feel supported,
        predictable and manageable.
      </p>

      <div className="rtw-note">
        <Heart size={14} fill="currentColor" />
        {offTrack.length === 0
          ? "You’re not expected to do everything at once. Your plan builds up gradually, one shift at a time."
          : `${offTrack.map((g) => g.label.toLowerCase()).join(" and ")} ${offTrack.length === 1 ? "isn’t" : "aren’t"} being fully met right now. Your manager can see this too — it’s fine to raise it at your check-in.`}
      </div>

      <Progress plan={plan} />
      <small className="rtw-progress-label">
        Returned {plan.returnDate.toLocaleDateString("en-GB", { day: "numeric", month: "long" })} · day {plan.daysSince + 1} of your{" "}
        {plan.totalWeeks}-week phased return
      </small>

      <div className="rtw-stats">
        <div>
          <span>Today’s supported pattern</span>
          <strong>{shifts.loading ? "…" : pattern.value}</strong>
          <small>{shifts.loading ? "" : pattern.helper}</small>
        </div>
        <div>
          <span>Support check-in</span>
          <strong>{checkInLabel(plan.nextCheckIn, today)}</strong>
          <small>Weekly, with your manager</small>
        </div>
        {plan.adjustmentsPct !== null && (
          <div>
            <span>Adjustments honoured</span>
            <strong>{plan.adjustmentsPct}%</strong>
            <small>Last 30 days</small>
          </div>
        )}
      </div>

      <span className="rtw-label">Your adjustments</span>
      <GuidelineChips guidelines={plan.guidelines} />

      <div className="rtw-foot">
        <LockKeyhole size={14} /> Only you and your manager can see this plan.
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Manager: "Maternity return-to-work" section on Team view
// ---------------------------------------------------------------------------
function TeamMemberPlan({ employee, snapshot }: { employee: Employee; snapshot: RiskSnapshot | null }) {
  const today = new Date();
  const shifts = useAsync(
    () => {
      const d = new Date(new Date().setHours(0, 0, 0, 0));
      const monday = new Date(d.getTime() - ((d.getDay() + 6) % 7) * 86400000);
      return api.list<Shift>("/shifts/", {
        employee: employee.employee_id,
        shift_start__gte: monday.toISOString(),
        ordering: "shift_start",
      });
    },
    [employee.employee_id],
  );
  const plan = buildReturnPlan(employee, snapshot, today);
  if (!plan) return null;
  return (
    <article className={`rtw-member ${plan.onTrack ? "" : "attention"}`}>
      <div className="rtw-member-head">
        <span className="rtw-avatar" style={{ background: avatarColor(employee.employee_id) }}>{initials(employee.full_name)}</span>
        <div>
          <strong>{employee.full_name}</strong>
          <small>{employee.job_role}</small>
        </div>
        <span className="rtw-week">Week {plan.week} of {plan.totalWeeks}</span>
      </div>
      <Progress plan={plan} />
      <div className="rtw-member-stats">
        <div>
          <span>Current pattern</span>
          <strong>{shifts.loading ? "…" : weekPattern(shifts.data ?? [], today)}</strong>
        </div>
        <div>
          <span>Next check-in</span>
          <strong>{checkInLabel(plan.nextCheckIn, today)}</strong>
        </div>
        <div>
          <span>Adjustments honoured</span>
          <strong>{plan.adjustmentsPct === null ? "—" : `${plan.adjustmentsPct}%`}</strong>
        </div>
      </div>
      <GuidelineChips guidelines={plan.guidelines} />
    </article>
  );
}

export function ReturnToWorkTeam({
  members,
  snapshots,
}: {
  /** Team members (direct reports) — only those inside the return window are shown. */
  members: Employee[];
  /** Recent risk snapshots for the team (any order); the latest per person is used. */
  snapshots: RiskSnapshot[];
}) {
  const returning = members.filter((m) => isReturning(m));
  if (!returning.length) return null;
  const latest = new Map<string, RiskSnapshot>();
  snapshots.forEach((s) => {
    const cur = latest.get(s.employee_id);
    if (!cur || s.snapshot_date > cur.snapshot_date) latest.set(s.employee_id, s);
  });
  const attention = returning.filter((m) => !buildReturnPlan(m, latest.get(m.employee_id) ?? null)?.onTrack).length;

  return (
    <section className="surface rtw-team">
      <div className="surface-heading">
        <div>
          <span className="section-kicker">People support</span>
          <h2>Maternity return-to-work</h2>
          <p className="rtw-sub">
            Phased returns for {returning.length} team member{returning.length === 1 ? "" : "s"}
            {attention ? ` · ${attention} with adjustments not being met` : " · all adjustments on track"}.
          </p>
        </div>
        <span className="rtw-auth"><LockKeyhole size={13} /> Authorised view</span>
      </div>
      <div className="rtw-grid">
        {returning.map((m) => (
          <TeamMemberPlan key={m.employee_id} employee={m} snapshot={latest.get(m.employee_id) ?? null} />
        ))}
      </div>
      <div className="rtw-foot">
        <LockKeyhole size={14} /> Visible only to each employee and their manager. Shown separately from wellbeing risk.
      </div>
    </section>
  );
}
