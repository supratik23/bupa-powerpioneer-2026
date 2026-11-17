import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { api } from "../api/client";
import { ACTION_STATUSES, ACTION_TYPES } from "../api/types";
import type { ActionStatus, ActionType, Intervention } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDateTime, label } from "../lib/format";
import { useAction, useAsync } from "../lib/useAsync";
import { useEmployees } from "../lib/useEmployees";
import {
  AsyncBlock,
  DataTable,
  ErrorNote,
  PageHeader,
  Panel,
  Pill,
  SelectField,
  SidePanel,
  Tabs,
  TextArea,
  enumOptions,
} from "../components/ui";
import type { Tone } from "../components/ui";

// eslint-disable-next-line react-refresh/only-export-components
export const actionTone: Record<ActionStatus, Tone> = {
  PENDING: "warning",
  IN_PROGRESS: "info",
  COMPLETED: "healthy",
  FAILED: "danger",
  CANCELLED: "neutral",
};

/** Human readable one-liner for an intervention. */
// eslint-disable-next-line react-refresh/only-export-components
export function describeIntervention(iv: Intervention, nameOf: (id: string | null) => string): string {
  const who = nameOf(iv.employee_id);
  switch (iv.action_type) {
    case "NOTIFY_MANAGER":
      return `${who}'s wellbeing needs attention. Please check in with them.`;
    case "NOTIFY_BUDDY":
      return `Your buddy ${who} could use some peer support.`;
    case "SCHEDULE_CHECKIN":
      return `Schedule a supportive check-in with ${who}.`;
    case "SUGGEST_BUDDY":
      return `${who} has no buddy. Consider assigning one.`;
    default:
      return `${label(iv.action_type)} for ${who}.`;
  }
}

/** Transition buttons shown for open interventions. */
export function InterventionActions({
  iv,
  onChanged,
  compact = false,
}: {
  iv: Intervention;
  onChanged: () => void;
  compact?: boolean;
}) {
  const { busy, error, run } = useAction();
  const go = (verb: "start" | "complete" | "fail" | "cancel") => {
    let body: Record<string, string> = {};
    if (verb === "fail") {
      const reason = window.prompt("Why could this not be completed?");
      if (reason === null) return;
      body = { failure_reason: reason };
    }
    void run(async () => {
      await api.post(`/interventions/${iv.intervention_id}/${verb}/`, body);
      onChanged();
    });
  };
  const open = iv.action_status === "PENDING" || iv.action_status === "IN_PROGRESS";
  if (!open) return null;
  const cls = `secondary-button ${compact ? "" : "small"}`;
  return (
    <>
      <div className="pp-inline-actions">
        {iv.action_status === "PENDING" && (
          <button className={cls} disabled={busy} onClick={() => go("start")}>Start</button>
        )}
        <button className={cls} disabled={busy} onClick={() => go("complete")}>Complete</button>
        <button className={cls} disabled={busy} onClick={() => go("fail")}>Fail</button>
        <button className={`${cls} danger`} disabled={busy} onClick={() => go("cancel")}>Cancel</button>
      </div>
      {error && <small style={{ color: "var(--red)" }}>{error}</small>}
    </>
  );
}

function InterventionEditor({
  record,
  onClose,
  onSaved,
}: {
  record: Intervention | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const { user } = useAuth();
  const { employees } = useEmployees();
  const existing = record === "new" ? null : record;
  const [form, setForm] = useState(() => ({
    employee_id: existing?.employee_id ?? "",
    target_employee_id: existing?.target_employee_id ?? user?.employee_id ?? "",
    action_type: (existing?.action_type ?? "SCHEDULE_CHECKIN") as ActionType,
    action_status: (existing?.action_status ?? "PENDING") as ActionStatus,
    note: typeof existing?.action_payload?.note === "string" ? (existing.action_payload.note as string) : "",
  }));
  const { busy, error, run } = useAction();
  const people = employees.filter((e) => e.is_active).map((e) => ({ value: e.employee_id, label: e.full_name }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = {
      employee_id: form.employee_id,
      target_employee_id: form.target_employee_id || null,
      action_type: form.action_type,
      action_status: form.action_status,
      action_payload: { ...(existing?.action_payload ?? {}), note: form.note || undefined },
    };
    const saved = await run(() =>
      existing
        ? api.patch<Intervention>(`/interventions/${existing.intervention_id}/`, body)
        : api.post<Intervention>("/interventions/", body),
    );
    if (saved) onSaved();
  };

  return (
    <SidePanel open kicker="Support action" title={existing ? "Edit intervention" : "New intervention"} onClose={onClose}>
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <SelectField label="Concerns" value={form.employee_id} onChange={(v) => setForm({ ...form, employee_id: v })} options={people} required placeholder="Select employee" />
        <SelectField label="Assigned to" value={form.target_employee_id} onChange={(v) => setForm({ ...form, target_employee_id: v })} options={people} placeholder="Nobody" />
        <SelectField label="Action" value={form.action_type} onChange={(v) => setForm({ ...form, action_type: v as ActionType })} options={enumOptions(ACTION_TYPES, label)} required />
        <SelectField label="Status" value={form.action_status} onChange={(v) => setForm({ ...form, action_status: v as ActionStatus })} options={enumOptions(ACTION_STATUSES, label)} required />
        <TextArea label="Note" value={form.note} onChange={(v) => setForm({ ...form, note: v })} />
        <ErrorNote message={error} />
        <div className="pp-form-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
          <button type="submit" className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        </div>
      </form>
    </SidePanel>
  );
}

type TabId = "assigned" | "about-me" | "all";

export default function InterventionsPage() {
  const { user, isManager, isStaff } = useAuth();
  const { nameOf } = useEmployees();
  const [tab, setTab] = useState<TabId>("assigned");
  const [status, setStatus] = useState("");
  const [editing, setEditing] = useState<Intervention | "new" | null>(null);
  const action = useAction();
  const meId = user?.employee_id ?? "";

  const query = {
    action_status: status || undefined,
    ordering: "-triggered_at",
    target_employee: tab === "assigned" ? meId : undefined,
    employee: tab === "about-me" ? meId : undefined,
  };
  const list = useAsync(() => api.listAll<Intervention>("/interventions/", query), [tab, status, meId]);

  const remove = (iv: Intervention) => {
    if (!window.confirm("Delete this intervention?")) return;
    void action.run(async () => {
      await api.delete(`/interventions/${iv.intervention_id}/`);
      await list.reload();
    });
  };

  const tabs: Array<{ id: TabId; label: string }> = [
    { id: "assigned", label: "Assigned to me" },
    { id: "about-me", label: "About me" },
    ...(isManager ? [{ id: "all" as const, label: isStaff ? "All" : "My team" }] : []),
  ];

  return (
    <main className="page-shell">
      <PageHeader
        kicker="Support actions"
        title="Interventions"
        description="Follow-ups raised by the wellbeing score, plus manager and buddy changes."
        actions={
          isManager && (
            <button className="primary-button" onClick={() => setEditing("new")}>
              <Plus size={16} /> New intervention
            </button>
          )
        }
      />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      <Panel
        title="Actions"
        actions={
          <select className="secondary-button" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by status">
            <option value="">All statuses</option>
            {ACTION_STATUSES.map((s) => (
              <option key={s} value={s}>{label(s)}</option>
            ))}
          </select>
        }
      >
        <ErrorNote message={action.error} />
        <AsyncBlock loading={list.loading} error={list.error} onRetry={list.reload}>
          <DataTable
            rows={list.data ?? []}
            rowKey={(iv) => iv.intervention_id}
            empty="No interventions."
            columns={[
              {
                header: "Action",
                width: "minmax(0, 1.6fr)",
                render: (iv) => (
                  <>
                    <strong>{label(iv.action_type)}</strong>
                    <small>{describeIntervention(iv, nameOf)}</small>
                  </>
                ),
              },
              { header: "Concerns", render: (iv) => nameOf(iv.employee_id) },
              { header: "Assigned to", render: (iv) => nameOf(iv.target_employee_id) },
              {
                header: "Status",
                render: (iv) => (
                  <>
                    <Pill tone={actionTone[iv.action_status]}>{label(iv.action_status)}</Pill>
                    {iv.failure_reason && <small>{iv.failure_reason}</small>}
                  </>
                ),
              },
              { header: "Raised", render: (iv) => formatDateTime(iv.triggered_at) },
              {
                header: "Manage",
                width: "minmax(190px, 1.5fr)",
                render: (iv) => (
                  <>
                    <InterventionActions iv={iv} onChanged={() => void list.reload()} />
                    {isManager && iv.employee_id !== meId && (
                      <div className="pp-inline-actions" style={{ marginTop: 6 }}>
                        <button className="secondary-button small" onClick={() => setEditing(iv)}>Edit</button>
                        <button className="secondary-button small danger" disabled={action.busy} onClick={() => remove(iv)}>Delete</button>
                      </div>
                    )}
                  </>
                ),
              },
            ]}
          />
        </AsyncBlock>
      </Panel>

      {editing !== null && (
        <InterventionEditor
          key={editing === "new" ? "new" : editing.intervention_id}
          record={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void list.reload();
          }}
        />
      )}
    </main>
  );
}
