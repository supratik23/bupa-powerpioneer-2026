import { useState } from "react";
import type { FormEvent } from "react";
import { api } from "../api/client";
import type { Employee } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { avatarColor, formatDate, initials, label, num } from "../lib/format";
import { useAction, useAsync } from "../lib/useAsync";
import { AsyncBlock, DataTable, ErrorNote, PageHeader, Panel, SuccessNote, TextField } from "../components/ui";

function ChangePassword() {
  const { busy, error, setError, run } = useAction();
  const [done, setDone] = useState<string | null>(null);
  const [form, setForm] = useState({ old_password: "", new_password: "", confirm: "" });

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setDone(null);
    if (form.new_password !== form.confirm) {
      setError("New passwords do not match.");
      return;
    }
    const ok = await run(async () => {
      await api.post("/auth/change-password/", {
        old_password: form.old_password,
        new_password: form.new_password,
      });
      return true;
    });
    if (ok) {
      setForm({ old_password: "", new_password: "", confirm: "" });
      setDone("Password updated.");
    }
  };

  return (
    <Panel kicker="Security" title="Change password">
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <TextField
          full
          label="Current password"
          type="password"
          value={form.old_password}
          onChange={(v) => setForm({ ...form, old_password: v })}
          required
          autoComplete="current-password"
        />
        <TextField
          label="New password"
          type="password"
          value={form.new_password}
          onChange={(v) => setForm({ ...form, new_password: v })}
          required
          autoComplete="new-password"
        />
        <TextField
          label="Confirm new password"
          type="password"
          value={form.confirm}
          onChange={(v) => setForm({ ...form, confirm: v })}
          required
          autoComplete="new-password"
        />
        <ErrorNote message={error} />
        <SuccessNote message={done} />
        <div className="pp-form-actions">
          <button className="primary-button" type="submit" disabled={busy}>
            {busy ? "Saving…" : "Update password"}
          </button>
        </div>
      </form>
    </Panel>
  );
}

export default function ProfilePage() {
  const { user } = useAuth();
  const me = useAsync(() => api.get<Employee>("/auth/me/"), []);
  const buddying = useAsync(
    () => (user ? api.get<Employee[]>(`/employees/${user.employee_id}/buddy-assignees/`) : Promise.resolve([])),
    [user?.employee_id],
  );
  const profile = me.data;

  return (
    <main className="page-shell">
      <PageHeader kicker="Account" title="My profile" description="Your employee record as held by ShiftGuard." />

      <div className="pp-two-col">
        <Panel kicker="Employee record" title="Details">
          <AsyncBlock loading={me.loading} error={me.error} onRetry={me.reload}>
            {profile && (
              <>
                <div className="member-identity" style={{ marginBottom: 18 }}>
                  <div className="avatar avatar-large" style={{ background: avatarColor(profile.employee_id) }}>
                    {initials(profile.full_name)}
                  </div>
                  <div>
                    <strong style={{ fontSize: 15 }}>{profile.full_name}</strong>
                    <span style={{ fontSize: 11 }}>
                      {profile.job_role} · {profile.department ?? "No department"}
                    </span>
                  </div>
                </div>
                <div className="pp-stat-grid">
                  <div className="pp-stat"><span>Email</span><strong style={{ fontSize: 13 }}>{profile.email}</strong></div>
                  <div className="pp-stat"><span>Employee number</span><strong>{profile.employee_number}</strong></div>
                  <div className="pp-stat"><span>Employment</span><strong style={{ fontSize: 15 }}>{label(profile.employment_type)}</strong></div>
                  <div className="pp-stat"><span>Weekly hours</span><strong>{num(profile.contracted_weekly_hours)}</strong></div>
                  <div className="pp-stat"><span>Location</span><strong style={{ fontSize: 15 }}>{profile.location ?? "—"}</strong></div>
                  <div className="pp-stat"><span>Hire date</span><strong style={{ fontSize: 15 }}>{formatDate(profile.hire_date)}</strong></div>
                  <div className="pp-stat"><span>Manager</span><strong style={{ fontSize: 15 }}>{profile.manager?.full_name ?? "Not assigned"}</strong></div>
                  <div className="pp-stat"><span>Buddy</span><strong style={{ fontSize: 15 }}>{profile.buddy?.full_name ?? "Not assigned"}</strong></div>
                </div>
              </>
            )}
          </AsyncBlock>
        </Panel>
        <ChangePassword />
      </div>

      <Panel kicker="Peer support" title="People I buddy">
        <AsyncBlock loading={buddying.loading} error={buddying.error} onRetry={buddying.reload}>
          <DataTable
            rows={buddying.data ?? []}
            rowKey={(r) => r.employee_id}
            empty="You are not a buddy for anyone yet."
            columns={[
              { header: "Name", render: (r) => <strong>{r.full_name}</strong> },
              { header: "Role", render: (r) => r.job_role },
              { header: "Department", render: (r) => r.department ?? "—" },
              { header: "Email", render: (r) => r.email },
            ]}
          />
        </AsyncBlock>
      </Panel>
    </main>
  );
}
