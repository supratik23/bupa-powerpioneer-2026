import { useState } from "react";
import { api } from "../../api/client";
import { RISK_BANDS } from "../../api/types";
import type {
  CalculateAllResult,
  RiskExplanation,
  RiskPrediction,
  RiskSnapshot,
  WellbeingResult,
} from "../../api/types";
import { featureLabel, formatDate, formatDateTime, isoDate, label, num } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";
import { useEmployees } from "../../lib/useEmployees";
import { bandTone } from "../WellbeingPage";
import { AsyncBlock, CheckField, DataTable, ErrorNote, Panel, Pill, SidePanel, SuccessNote } from "../../components/ui";

function CalculatePanel({ onDone }: { onDone: () => void }) {
  const { employees } = useEmployees();
  const [employee, setEmployee] = useState("");
  const [date, setDate] = useState(isoDate());
  const [interventions, setInterventions] = useState(true);
  const [notice, setNotice] = useState<string | null>(null);
  const { busy, error, run } = useAction();

  const calcOne = () =>
    run(async () => {
      const res = await api.post<WellbeingResult>("/wellbeing/calculate/", {
        employee_id: employee,
        snapshot_date: date,
        create_interventions: interventions,
      });
      setNotice(`Score ${num(res.snapshot.wellbeing_score)} · ${label(res.prediction.risk_band)} risk.`);
      onDone();
    });

  const calcAll = () =>
    run(async () => {
      const res = await api.post<CalculateAllResult>("/wellbeing/calculate-all/", {
        snapshot_date: date,
        create_interventions: interventions,
      });
      const bands = Object.entries(res.bands).map(([b, n]) => `${label(b)}: ${n}`).join(", ");
      setNotice(`Scored ${res.employees_scored} employees for ${formatDate(res.snapshot_date)}. ${bands}`);
      onDone();
    });

  return (
    <Panel kicker="Wellbeing engine" title="Run calculation">
      <div className="pp-inline-actions" style={{ alignItems: "center" }}>
        <select className="secondary-button" value={employee} onChange={(e) => setEmployee(e.target.value)} aria-label="Employee">
          <option value="">Choose employee…</option>
          {employees.filter((e) => e.is_active).map((e) => <option key={e.employee_id} value={e.employee_id}>{e.full_name}</option>)}
        </select>
        <input className="secondary-button" type="date" value={date} onChange={(e) => setDate(e.target.value)} aria-label="Snapshot date" />
        <CheckField label="Raise interventions" checked={interventions} onChange={setInterventions} />
        <button className="secondary-button" disabled={busy || !employee} onClick={() => void calcOne()}>Calculate one</button>
        <button className="primary-button" disabled={busy} onClick={() => void calcAll()}>{busy ? "Working…" : "Calculate all"}</button>
      </div>
      <ErrorNote message={error} />
      <SuccessNote message={notice} />
    </Panel>
  );
}

function ExplanationsPanel({ prediction, onClose }: { prediction: RiskPrediction; onClose: () => void }) {
  const list = useAsync(
    () => api.listAll<RiskExplanation>("/risk-explanations/", { prediction: prediction.prediction_id, ordering: "display_order" }),
    [prediction.prediction_id],
  );
  const action = useAction();
  const remove = (e: RiskExplanation) =>
    action.run(async () => {
      await api.delete(`/risk-explanations/${e.explanation_id}/`);
      await list.reload();
    });

  return (
    <SidePanel open kicker="/risk-explanations/" title="Prediction explanation" onClose={onClose}>
      <div className="drawer-score">
        <div>
          <span>Risk score · {prediction.model_name} v{prediction.model_version}</span>
          <strong>{num(prediction.risk_score)}<small>/100</small></strong>
        </div>
        <Pill tone={bandTone[prediction.risk_band]}>{label(prediction.risk_band)}</Pill>
      </div>
      <ErrorNote message={action.error} />
      <AsyncBlock loading={list.loading} error={list.error} onRetry={list.reload}>
        <ul className="factor-list">
          {(list.data ?? []).map((e, i) => (
            <li key={e.explanation_id}>
              <span>{i + 1}</span>
              <div style={{ flex: 1 }}>
                <strong>{featureLabel(e.feature_name)}</strong>
                <small>
                  {e.contribution_direction === "INCREASES_RISK" ? "+" : "−"}{num(Math.abs(e.shap_value), 2)} points
                  {e.feature_value !== null ? ` · value ${num(e.feature_value, 2)}` : ""}
                </small>
              </div>
              <button className="secondary-button small danger" disabled={action.busy} onClick={() => void remove(e)}>Delete</button>
            </li>
          ))}
          {list.data?.length === 0 && <li><div><small>No explanation rows.</small></div></li>}
        </ul>
      </AsyncBlock>
    </SidePanel>
  );
}

export default function RiskAdmin() {
  const { nameOf, employees } = useEmployees();
  const [employee, setEmployee] = useState("");
  const [band, setBand] = useState("");
  const [selected, setSelected] = useState<RiskPrediction | null>(null);
  const action = useAction();

  const snapshots = useAsync(
    () => api.list<RiskSnapshot>("/risk-snapshots/", { employee: employee || undefined, risk_label: band || undefined, ordering: "-snapshot_date" }),
    [employee, band],
  );
  const predictions = useAsync(
    () => api.list<RiskPrediction>("/risk-predictions/", { employee: employee || undefined, risk_band: band || undefined, ordering: "-predicted_at" }),
    [employee, band],
  );

  const reloadAll = () => {
    void snapshots.reload();
    void predictions.reload();
  };

  const patchSnapshot = (s: RiskSnapshot, body: Partial<RiskSnapshot>) =>
    action.run(async () => {
      await api.patch(`/risk-snapshots/${s.risk_snapshot_id}/`, body);
      await snapshots.reload();
    });

  const removeSnapshot = (s: RiskSnapshot) => {
    if (!window.confirm("Delete this snapshot and its predictions?")) return;
    void action.run(async () => {
      await api.delete(`/risk-snapshots/${s.risk_snapshot_id}/`);
      reloadAll();
    });
  };

  const removePrediction = (p: RiskPrediction) => {
    if (!window.confirm("Delete this prediction?")) return;
    void action.run(async () => {
      await api.delete(`/risk-predictions/${p.prediction_id}/`);
      await predictions.reload();
    });
  };

  const filters = (
    <>
      <select className="secondary-button" value={employee} onChange={(e) => setEmployee(e.target.value)} aria-label="Filter by employee">
        <option value="">All employees</option>
        {employees.map((e) => <option key={e.employee_id} value={e.employee_id}>{e.full_name}</option>)}
      </select>
      <select className="secondary-button" value={band} onChange={(e) => setBand(e.target.value)} aria-label="Filter by band">
        <option value="">All bands</option>
        {RISK_BANDS.map((b) => <option key={b} value={b}>{label(b)}</option>)}
      </select>
    </>
  );

  return (
    <>
      <CalculatePanel onDone={reloadAll} />
      <ErrorNote message={action.error} />

      <Panel kicker="/risk-snapshots/ (latest 25)" title="Risk snapshots" actions={filters}>
        <AsyncBlock loading={snapshots.loading} error={snapshots.error} onRetry={snapshots.reload}>
          <DataTable
            rows={snapshots.data ?? []}
            rowKey={(s) => s.risk_snapshot_id}
            empty="No snapshots."
            columns={[
              { header: "Employee", render: (s) => <><strong>{nameOf(s.employee_id)}</strong><small>{formatDate(s.snapshot_date)}</small></> },
              { header: "Score", render: (s) => <><strong>{num(s.wellbeing_score)}</strong>{s.risk_label && <Pill tone={bandTone[s.risk_label]}>{label(s.risk_label)}</Pill>}</> },
              { header: "Hours / overtime", render: (s) => <>{num(s.actual_hours_worked_30d)}h<small>{num(s.overtime_hours_30d)}h overtime</small></> },
              { header: "Nights / long", render: (s) => `${s.night_shifts_30d} / ${s.long_shifts_30d}` },
              {
                header: "ML labels",
                width: "minmax(170px, 1.3fr)",
                render: (s) => (
                  <div className="pp-inline-actions">
                    <select
                      className="secondary-button small"
                      value={s.risk_outcome_within_30d === null ? "" : String(s.risk_outcome_within_30d)}
                      onChange={(e) => void patchSnapshot(s, { risk_outcome_within_30d: e.target.value === "" ? null : e.target.value === "true" })}
                      aria-label="Risk outcome within 30 days"
                    >
                      <option value="">Outcome unknown</option>
                      <option value="true">Risk event</option>
                      <option value="false">No event</option>
                    </select>
                    <CheckField label="Training" checked={s.is_training_record} onChange={(v) => void patchSnapshot(s, { is_training_record: v })} />
                  </div>
                ),
              },
              { header: "", width: "80px", render: (s) => <button className="secondary-button small danger" disabled={action.busy} onClick={() => removeSnapshot(s)}>Delete</button> },
            ]}
          />
        </AsyncBlock>
      </Panel>

      <Panel kicker="/risk-predictions/ (latest 25)" title="Risk predictions">
        <AsyncBlock loading={predictions.loading} error={predictions.error} onRetry={predictions.reload}>
          <DataTable
            rows={predictions.data ?? []}
            rowKey={(p) => p.prediction_id}
            empty="No predictions."
            columns={[
              { header: "Employee", render: (p) => <><strong>{nameOf(p.employee_id)}</strong><small>{formatDateTime(p.predicted_at)}</small></> },
              { header: "Band", render: (p) => <Pill tone={bandTone[p.risk_band]}>{label(p.risk_band)}</Pill> },
              { header: "Risk", render: (p) => num(p.risk_score) },
              { header: "Top factor", render: (p) => (p.explanations[0] ? featureLabel(p.explanations[0].feature_name) : "—") },
              {
                header: "Actions",
                width: "minmax(160px, 1.2fr)",
                render: (p) => (
                  <div className="pp-inline-actions">
                    <button className="secondary-button small" onClick={() => setSelected(p)}>Explain</button>
                    <button className="secondary-button small danger" disabled={action.busy} onClick={() => removePrediction(p)}>Delete</button>
                  </div>
                ),
              },
            ]}
          />
        </AsyncBlock>
      </Panel>

      {selected && (
        <ExplanationsPanel
          prediction={selected}
          onClose={() => {
            setSelected(null);
            void predictions.reload();
          }}
        />
      )}
    </>
  );
}
