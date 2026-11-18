import { useMemo } from "react";
import { RefreshCw } from "lucide-react";
import { api } from "../api/client";
import type {
  Question,
  RiskBand,
  RiskSnapshot,
  WellbeingResult,
  WellbeingSummary,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { featureLabel, formatDate, label, num } from "../lib/format";
import { useAction, useAsync } from "../lib/useAsync";
import { AsyncBlock, ErrorNote, Loading, PageHeader, Panel, Pill } from "../components/ui";
import { MoodTrend } from "../components/MoodTrend";
import type { Tone } from "../components/ui";

// eslint-disable-next-line react-refresh/only-export-components
export const bandTone: Record<RiskBand, Tone> = {
  LOW: "healthy",
  MODERATE: "warning",
  HIGH: "danger",
  CRITICAL: "danger",
};

export default function WellbeingPage() {
  const { user } = useAuth();
  const meId = user?.employee_id ?? "";
  const action = useAction();

  const summary = useAsync(() => api.get<WellbeingSummary>("/wellbeing/me/"), []);
  const snapshot = useAsync(
    async () =>
      (await api.list<RiskSnapshot>("/risk-snapshots/", { employee: meId, ordering: "-snapshot_date" }))[0] ?? null,
    [meId],
  );
  const questions = useAsync(() => api.listAll<Question>("/questions/"), []);

  const questionById = useMemo(
    () => new Map((questions.data ?? []).map((q) => [q.question_id, q])),
    [questions.data],
  );

  const recalculate = () =>
    action.run(async () => {
      await api.post<WellbeingResult>("/wellbeing/calculate/", { employee_id: meId });
      await Promise.all([summary.reload(), snapshot.reload()]);
    });

  const s = summary.data;
  const snap = snapshot.data;

  return (
    <main className="page-shell">
      <PageHeader
        kicker="Private to you"
        title="My wellbeing"
        description="Your score combines roster patterns, attendance, leave and your check-ins. Higher is better."
        actions={
          <button className="primary-button" disabled={action.busy} onClick={() => void recalculate()}>
            <RefreshCw size={16} /> {action.busy ? "Calculating…" : "Recalculate now"}
          </button>
        }
      />
      <ErrorNote message={action.error} />

      <div className="pp-two-col">
        <Panel kicker="Latest result" title="Wellbeing score">
          <AsyncBlock loading={summary.loading} error={summary.error} onRetry={summary.reload}>
            {s && (
              <>
                <div className="drawer-score" style={{ paddingTop: 0 }}>
                  <div>
                    <span>As of {formatDate(s.latest_snapshot_date)}</span>
                    <strong>
                      {num(s.latest_wellbeing_score, 0)}
                      <small>/100</small>
                    </strong>
                  </div>
                  {s.latest_risk_band ? (
                    <Pill tone={bandTone[s.latest_risk_band]}>{label(s.latest_risk_band)} risk</Pill>
                  ) : (
                    <Pill tone="neutral">Not calculated yet</Pill>
                  )}
                </div>
                <div className="pp-stat-grid">
                  <div className="pp-stat">
                    <span>Change since last</span>
                    <strong>{s.trend === null ? "—" : `${s.trend > 0 ? "+" : ""}${num(s.trend)}`}</strong>
                  </div>
                  <div className="pp-stat">
                    <span>Open support actions</span>
                    <strong>{s.open_interventions}</strong>
                  </div>
                  <div className="pp-stat">
                    <span>Snapshots</span>
                    <strong>{s.history.length}</strong>
                  </div>
                </div>
                <div className="drawer-section" style={{ marginTop: 16 }}>
                  <span className="section-kicker">What’s contributing</span>
                  <h3>Top drivers</h3>
                  {s.top_drivers.length ? (
                    <ul className="factor-list">
                      {s.top_drivers.map((d, i) => (
                        <li key={d.feature_name}>
                          <span>{i + 1}</span>
                          <div>
                            <strong>{featureLabel(d.feature_name)}</strong>
                            <small>
                              {d.contribution_direction === "INCREASES_RISK" ? "Adds" : "Reduces"}{" "}
                              {num(Math.abs(d.shap_value))} risk points
                              {d.feature_value !== null ? ` · value ${num(d.feature_value, 2)}` : ""}
                            </small>
                          </div>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="pp-muted">No contributing factors recorded.</p>
                  )}
                </div>
              </>
            )}
          </AsyncBlock>
        </Panel>

        <Panel kicker="Last 30 days" title="Work pattern signals">
          <AsyncBlock loading={snapshot.loading} error={snapshot.error} onRetry={snapshot.reload}>
            {snap ? (
              <div className="pp-stat-grid">
                <div className="pp-stat"><span>Hours worked</span><strong>{num(snap.actual_hours_worked_30d)}h</strong></div>
                <div className="pp-stat"><span>Overtime</span><strong>{num(snap.overtime_hours_30d)}h</strong></div>
                <div className="pp-stat"><span>Night shifts</span><strong>{snap.night_shifts_30d}</strong></div>
                <div className="pp-stat"><span>Long shifts</span><strong>{snap.long_shifts_30d}</strong></div>
                <div className="pp-stat"><span>Max consecutive days</span><strong>{snap.max_consecutive_work_days}</strong></div>
                <div className="pp-stat"><span>Missed breaks</span><strong>{snap.missed_breaks_30d}</strong></div>
                <div className="pp-stat"><span>Shortest rest</span><strong>{num(snap.minimum_rest_hours_between_shifts)}h</strong></div>
                <div className="pp-stat"><span>Days since real break</span><strong>{snap.days_since_last_meaningful_leave ?? "—"}</strong></div>
              </div>
            ) : (
              <p className="pp-muted">No snapshot yet. Use “Recalculate now”.</p>
            )}
          </AsyncBlock>
        </Panel>
      </div>

      <Panel kicker="Private check-ins" title="How my mood has shifted">
        {questions.error ? (
          <ErrorNote message={questions.error} />
        ) : questions.loading ? (
          <Loading text="Loading your check-ins…" />
        ) : (
          <MoodTrend employeeId={meId} questionById={questionById} />
        )}
      </Panel>

    </main>
  );
}
