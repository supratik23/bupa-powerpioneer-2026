import type { RiskPrediction, RiskSnapshot, WellbeingSummary } from "../api/types";

/**
 * The backend's /wellbeing/me|team|summary endpoints ignore snapshots with
 * is_training_record = true. Every snapshot the XGBoost pipeline wrote to
 * Supabase carries that flag, so those summaries come back empty. This fills
 * the gaps from the raw /risk-snapshots/ and /risk-predictions/ rows instead.
 * A summary the backend already populated is returned unchanged.
 */
export function withSupabaseRows(
  base: WellbeingSummary,
  snapshots: RiskSnapshot[],
  predictions: RiskPrediction[],
  historySize = 10,
): WellbeingSummary {
  if (base.latest_snapshot_date && base.latest_risk_band) return base;

  const snaps = snapshots
    .filter((s) => s.employee_id === base.employee_id)
    .sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date))
    .slice(-historySize);
  const preds = predictions
    .filter((p) => p.employee_id === base.employee_id)
    .sort((a, b) => a.predicted_at.localeCompare(b.predicted_at));
  if (!snaps.length && !preds.length) return base;

  const latest = snaps[snaps.length - 1];
  const previous = snaps[snaps.length - 2];
  const latestPrediction = preds[preds.length - 1];
  // Only some predictions carry SHAP explanations; use the most recent one that does.
  const explained = [...preds].reverse().find((p) => p.explanations?.length);

  return {
    ...base,
    latest_wellbeing_score: latest?.wellbeing_score ?? base.latest_wellbeing_score,
    latest_risk_band: latestPrediction?.risk_band ?? latest?.risk_label ?? base.latest_risk_band,
    latest_snapshot_date: latest?.snapshot_date ?? latestPrediction?.predicted_at.slice(0, 10) ?? null,
    trend:
      latest?.wellbeing_score != null && previous?.wellbeing_score != null
        ? Number(latest.wellbeing_score) - Number(previous.wellbeing_score)
        : base.trend,
    history: snaps.map((s) => ({
      snapshot_date: s.snapshot_date,
      wellbeing_score: s.wellbeing_score,
      risk_label: s.risk_label,
    })),
    top_drivers: base.top_drivers.length
      ? base.top_drivers
      : [...(explained?.explanations ?? [])].sort((a, b) => a.display_order - b.display_order).slice(0, 5),
  };
}
