import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { api } from "../api/client";
import { LEAVE_STATUSES, LEAVE_TYPES } from "../api/types";
import type { LeaveRequest, LeaveStatus, LeaveType } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDate, formatDateTime, isoDate, label } from "../lib/format";
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
  TextField,
  enumOptions,
} from "../components/ui";
import type { Tone } from "../components/ui";

const statusTone: Record<LeaveStatus, Tone> = {
  PENDING: "warning",
  APPROVED: "healthy",
  REJECTED: "danger",
  CANCELLED: "neutral",
};

interface LeaveForm {
  leave_type: LeaveType;
  start_date: string;
  end_date: string;
}

function LeaveEditor({
  editing,
  onClose,
  onSaved,
}: {
  editing: LeaveRequest | "new" | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isNew = editing === "new";
  const existing = editing && editing !== "new" ? editing : null;
  const [form, setForm] = useState<LeaveForm>(() => ({
    leave_type: existing?.leave_type ?? "ANNUAL",
    start_date: existing?.start_date ?? isoDate(),
    end_date: existing?.end_date ?? isoDate(),
  }));
  const { busy, error, run } = useAction();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const saved = await run(() =>
      existing
        ? api.patch<LeaveRequest>(`/leave-requests/${existing.leave_request_id}/`, form)
        : api.post<LeaveRequest>("/leave-requests/", form),
    );
    if (saved) onSaved();
  };

  return (
    <SidePanel
      open={editing !== null}
      kicker="Leave request"
      title={isNew ? "Request leave" : "Edit leave request"}
      onClose={onClose}
    >
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <SelectField
          label="Leave type"
          value={form.leave_type}
          onChange={(v) => setForm({ ...form, leave_type: v as LeaveType })}
          options={enumOptions(LEAVE_TYPES, label)}
          required
        />
        <TextField
          label="First day"
          type="date"
          value={form.start_date}
          onChange={(v) => setForm({ ...form, start_date: v })}
          required
        />
        <TextField
          label="Last day"
          type="date"
          value={form.end_date}
          onChange={(v) => setForm({ ...form, end_date: v })}
          required
        />
        <ErrorNote message={error} />
        <div className="pp-form-actions">
          <button type="button" className="secondary-button" onClick={onClose}>
            Close
          </button>
          <button type="submit" className="primary-button" disabled={busy}>
            {busy ? "Saving…" : isNew ? "Submit request" : "Save changes"}
          </button>
        </div>
      </form>
    </SidePanel>
  );
}

export default function LeavePage() {
  const { user, isManager } = useAuth();
  const { nameOf } = useEmployees();
  const [tab, setTab] = useState<"mine" | "team">("mine");
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [editing, setEditing] = useState<LeaveRequest | "new" | null>(null);
  const action = useAction();
  const meId = user?.employee_id ?? "";

  const leave = useAsync(
    () =>
      api.listAll<LeaveRequest>("/leave-requests/", {
        status: statusFilter || undefined,
        ordering: "-requested_at",
      }),
    [statusFilter],
  );

  const rows = (leave.data ?? []).filter((r) => (tab === "mine" ? r.employee_id === meId : r.employee_id !== meId));

  const decide = (row: LeaveRequest, verb: "approve" | "reject" | "cancel") =>
    action.run(async () => {
      await api.post(`/leave-requests/${row.leave_request_id}/${verb}/`, {});
      await leave.reload();
    });

  const remove = (row: LeaveRequest) => {
    if (!window.confirm("Delete this leave request permanently?")) return;
    void action.run(async () => {
      await api.delete(`/leave-requests/${row.leave_request_id}/`);
      await leave.reload();
    });
  };

  return (
    <main className="page-shell">
      <PageHeader
        kicker="Time away"
        title="Leave requests"
        description="Request time off and track decisions. Regular breaks are one of the strongest protective factors."
        actions={
          <button className="primary-button" onClick={() => setEditing("new")}>
            <Plus size={16} /> Request leave
          </button>
        }
      />

      {isManager && (
        <Tabs
          tabs={[
            { id: "mine", label: "My requests" },
            { id: "team", label: "Team requests" },
          ]}
          value={tab}
          onChange={setTab}
        />
      )}

      <Panel
        kicker={tab === "mine" ? "Your history" : "Awaiting your decision"}
        title={tab === "mine" ? "My leave" : "Team leave"}
        actions={
          <select
            className="secondary-button"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            {LEAVE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        }
      >
        <ErrorNote message={action.error} />
        <AsyncBlock loading={leave.loading} error={leave.error} onRetry={leave.reload}>
          <DataTable
            rows={rows}
            rowKey={(r) => r.leave_request_id}
            empty={tab === "mine" ? "You have no leave requests yet." : "No team leave requests."}
            columns={[
              ...(tab === "team"
                ? [{ header: "Employee", render: (r: LeaveRequest) => <strong>{nameOf(r.employee_id)}</strong> }]
                : []),
              { header: "Type", render: (r) => <strong>{label(r.leave_type)}</strong> },
              {
                header: "Dates",
                render: (r) => (
                  <>
                    {formatDate(r.start_date)} – {formatDate(r.end_date)}
                    <small>{r.duration_days} day(s)</small>
                  </>
                ),
              },
              { header: "Status", render: (r) => <Pill tone={statusTone[r.status]}>{label(r.status)}</Pill> },
              {
                header: "Requested",
                render: (r) => (
                  <>
                    {formatDateTime(r.requested_at)}
                    {r.decision_at && <small>Decided {formatDateTime(r.decision_at)}</small>}
                  </>
                ),
              },
              {
                header: "Actions",
                width: "minmax(170px, 1.3fr)",
                render: (r) => (
                  <div className="pp-inline-actions">
                    {tab === "team" && r.status === "PENDING" && (
                      <>
                        <button className="primary-button small" disabled={action.busy} onClick={() => void decide(r, "approve")}>
                          Approve
                        </button>
                        <button className="secondary-button small danger" disabled={action.busy} onClick={() => void decide(r, "reject")}>
                          Reject
                        </button>
                      </>
                    )}
                    {tab === "mine" && r.status === "PENDING" && (
                      <button className="secondary-button small" onClick={() => setEditing(r)}>
                        Edit
                      </button>
                    )}
                    {(r.status === "PENDING" || r.status === "APPROVED") && (
                      <button className="secondary-button small" disabled={action.busy} onClick={() => void decide(r, "cancel")}>
                        Cancel
                      </button>
                    )}
                    {tab === "mine" && r.status === "PENDING" && (
                      <button className="secondary-button small danger" disabled={action.busy} onClick={() => remove(r)}>
                        Delete
                      </button>
                    )}
                  </div>
                ),
              },
            ]}
          />
        </AsyncBlock>
      </Panel>

      {editing !== null && (
        <LeaveEditor
          key={editing === "new" ? "new" : editing.leave_request_id}
          editing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            void leave.reload();
          }}
        />
      )}
    </main>
  );
}
