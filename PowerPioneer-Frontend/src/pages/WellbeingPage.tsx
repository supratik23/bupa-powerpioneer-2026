import { useMemo } from "react";
import { api } from "../api/client";
import type {
  Question,
  RiskBand,
  RiskPrediction,
  RiskSnapshot,
  WellbeingSummary,
} from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { withSupabaseRows } from "../lib/wellbeingData";
import { useAsync } from "../lib/useAsync";
import { AsyncBlock, ErrorNote, Loading, PageHeader, Panel } from "../components/ui";
import { MoodTrend } from "../components/MoodTrend";
import { WellbeingOverview, WorkPatternSignals } from "../components/WellbeingAtAGlance";
import { ReturnToWorkCard } from "../components/ReturnToWork";
import { isReturning } from "../lib/returnToWork";
import type { Tone } from "../components/ui";

// eslint-disable-next-line react-refresh/only-export-components
export const bandTone: Record<RiskBand, Tone> = {
  LOW: "healthy",
  MEDIUM: "warning",
  MODERATE: "warning",
  HIGH: "danger",
  CRITICAL: "danger",
};

export default function WellbeingPage() {
  const { user } = useAuth();
  const meId = user?.employee_id ?? "";

  // /wellbeing/me/ skips training-flagged snapshots (all Supabase rows are), so it is
  // topped up from the latest raw snapshots and predictions.
  const summary = useAsync(async () => {
    const [base, snaps, preds] = await Promise.all([
      api.get<WellbeingSummary>("/wellbeing/me/"),
      api.list<RiskSnapshot>("/risk-snapshots/", { employee: meId, ordering: "-snapshot_date" }),
      api.list<RiskPrediction>("/risk-predictions/", { employee: meId, ordering: "-predicted_at" }),
    ]);
    return withSupabaseRows(base, snaps, preds);
  }, [meId]);
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

  const s = summary.data;
  const snap = snapshot.data;

  return (
    <main className="page-shell">
      <PageHeader
        kicker="Private to you"
        title="My wellbeing"
        description="Your score combines roster patterns, attendance, leave and your check-ins. Higher is better."
      />

      {/* Maternity return-to-work support: shown while within the phased-return window */}
      {user && isReturning(user) && !snapshot.loading && <ReturnToWorkCard employee={user} snapshot={snapshot.data ?? null} />}

      <div className="pp-two-col">
        <Panel kicker="Latest result" title="How you’re doing">
          <AsyncBlock loading={summary.loading} error={summary.error} onRetry={summary.reload}>
            {s && <WellbeingOverview summary={s} />}
          </AsyncBlock>
        </Panel>

        <Panel kicker="Last 30 days" title="Your work pattern">
          <AsyncBlock loading={snapshot.loading} error={snapshot.error} onRetry={snapshot.reload}>
            {snap ? (
              <WorkPatternSignals snapshot={snap} />
            ) : (
              <p className="pp-muted">No snapshot yet.</p>
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
