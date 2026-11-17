import { useState } from "react";
import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import { api } from "../../api/client";
import { EMPLOYMENT_TYPES } from "../../api/types";
import type { DeactivateResult, Employee, EmploymentType } from "../../api/types";
import { avatarColor, initials, label } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";
import { invalidateEmployees } from "../../lib/useEmployees";
import { Relations } from "../../components/Relations";
import {
  AsyncBlock,
  CheckField,
  DataTable,
  ErrorNote,
  Panel,
  Pill,
  SelectField,
  SidePanel,
  SuccessNote,
  TextField,
  enumOptions,
} from "../../components/ui";

interface EmployeeForm {
  employee_number: string;
  first_name: string;
  last_name: string;
  email: string;
  job_role: string;
  department: string;
  location: string;
  employment_type: EmploymentType;
  contracted_weekly_hours: string;
  hire_date: string;
  maternity_return_date: string;
  is_active: boolean;
  is_staff: boolean;
  password: string;
}

function toForm(e: Employee | null): EmployeeForm {
  return {
    employee_number: e?.employee_number ?? "",
    first_name: e?.first_name ?? "",
    last_name: e?.last_name ?? "",
    email: e?.email ?? "",
    job_role: e?.job_role ?? "",
    department: e?.department ?? "",
    location: e?.location ?? "",
    employment_type: e?.employment_type ?? "FULL_TIME",
    contracted_weekly_hours: e?.contracted_weekly_hours != null ? String(e.contracted_weekly_hours) : "",
    hire_date: e?.hire_date ?? "",
    maternity_return_date: e?.maternity_return_date ?? "",
    is_active: e?.is_active ?? true,
    is_staff: e?.is_staff ?? false,
    password: "",
  };
}

function EmployeeEditor({
  record,
  onClose,
  onSaved,
}: {
  record: Employee | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const [current, setCurrent] = useState<Employee | null>(record === "new" ? null : record);
  const [form, setForm] = useState<EmployeeForm>(() => toForm(record === "new" ? null : record));
  const [notice, setNotice] = useState<string | null>(null);
  const { busy, error, run } = useAction();
  const set = <K extends keyof EmployeeForm>(k: K, v: EmployeeForm[K]) => setForm((f) => ({ ...f, [k]: v }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setNotice(null);
    const body: Record<string, unknown> = {
      ...form,
      department: form.department || null,
      location: form.location || null,
      contracted_weekly_hours: form.contracted_weekly_hours === "" ? null : Number(form.contracted_weekly_hours),
      hire_date: form.hire_date || null,
      maternity_return_date: form.maternity_return_date || null,
    };
    if (!form.password) delete body.password;
    const saved = await run(() =>
      current
        ? api.patch<Employee>(`/employees/${current.employee_id}/`, body)
        : api.post<Employee>("/employees/", body),
    );
    if (saved) {
      invalidateEmployees();
      setCurrent(saved);
      setForm(toForm(saved));
      setNotice(current ? "Employee updated." : "Employee created. You can now link a manager and buddy.");
      onSaved();
    }
  };

  return (
    <SidePanel open kicker="Employee record" title={current ? current.full_name : "New employee"} onClose={onClose}>
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <TextField label="First name" value={form.first_name} onChange={(v) => set("first_name", v)} required />
        <TextField label="Last name" value={form.last_name} onChange={(v) => set("last_name", v)} required />
        <TextField label="Email" type="email" value={form.email} onChange={(v) => set("email", v)} required />
        <TextField label="Employee number" value={form.employee_number} onChange={(v) => set("employee_number", v)} required />
        <TextField label="Job role" value={form.job_role} onChange={(v) => set("job_role", v)} required />
        <SelectField label="Employment type" value={form.employment_type} onChange={(v) => set("employment_type", v as EmploymentType)} options={enumOptions(EMPLOYMENT_TYPES, label)} required />
        <TextField label="Department" value={form.department} onChange={(v) => set("department", v)} />
        <TextField label="Location" value={form.location} onChange={(v) => set("location", v)} />
        <TextField label="Contracted weekly hours" type="number" step="0.5" min={0} value={form.contracted_weekly_hours} onChange={(v) => set("contracted_weekly_hours", v)} />
        <TextField label="Hire date" type="date" value={form.hire_date} onChange={(v) => set("hire_date", v)} />
        <TextField label="Maternity return date" type="date" value={form.maternity_return_date} onChange={(v) => set("maternity_return_date", v)} />
        <TextField
          label={current ? "Reset password" : "Password"}
          type="password"
          value={form.password}
          onChange={(v) => set("password", v)}
          autoComplete="new-password"
          hint={current ? "Leave blank to keep the current password." : "Optional. Without one, the employee cannot log in."}
        />
        <div className="pp-check-row">
          <CheckField label="Active" checked={form.is_active} onChange={(v) => set("is_active", v)} />
          <CheckField label="Staff (admin access)" checked={form.is_staff} onChange={(v) => set("is_staff", v)} />
        </div>
        <ErrorNote message={error} />
        <SuccessNote message={notice} />
        <div className="pp-form-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
          <button type="submit" className="primary-button" disabled={busy}>{busy ? "Saving…" : current ? "Save changes" : "Create employee"}</button>
        </div>
      </form>
      {current && (
        <div style={{ marginTop: 16 }}>
          <Relations
            employee={current}
            onChanged={(updated) => {
              setCurrent(updated);
              onSaved();
            }}
          />
        </div>
      )}
    </SidePanel>
  );
}

export default function EmployeesAdmin() {
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Employee | "new" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const action = useAction();

  const list = useAsync(
    () =>
      api.listAll<Employee>("/employees/", {
        search: search || undefined,
        is_active: showInactive ? undefined : true,
        ordering: "last_name",
      }),
    [search, showInactive],
  );

  const deactivate = (e: Employee) => {
    if (!window.confirm(`Deactivate ${e.full_name}? Their reports move to their manager and buddy links are cleared.`)) return;
    void action.run(async () => {
      const res = await api.post<DeactivateResult>(`/employees/${e.employee_id}/deactivate/`);
      setNotice(
        `${e.full_name} deactivated. ${res.direct_reports_reassigned.length} report(s) reassigned, ${res.buddy_assignments_removed.length} buddy link(s) removed.`,
      );
      invalidateEmployees();
      await list.reload();
    });
  };

  const remove = (e: Employee) => {
    if (!window.confirm(`Permanently delete ${e.full_name} and ALL their data? Prefer deactivate.`)) return;
    void action.run(async () => {
      await api.delete(`/employees/${e.employee_id}/`);
      setNotice(`${e.full_name} deleted.`);
      invalidateEmployees();
      await list.reload();
    });
  };

  return (
    <Panel
      kicker="Directory"
      title="Employees"
      actions={
        <>
          <input className="secondary-button" placeholder="Search name, email, role…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search employees" />
          <label className="pp-check">
            <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />
            <span>Show inactive</span>
          </label>
          <button className="primary-button small" onClick={() => setEditing("new")}>
            <Plus size={14} /> Add employee
          </button>
        </>
      }
    >
      <ErrorNote message={action.error} />
      <SuccessNote message={notice} />
      <AsyncBlock loading={list.loading} error={list.error} onRetry={list.reload}>
        <DataTable
          rows={list.data ?? []}
          rowKey={(e) => e.employee_id}
          empty="No employees match."
          columns={[
            {
              header: "Employee",
              width: "minmax(0, 1.6fr)",
              render: (e) => (
                <div className="member-identity">
                  <div className="avatar" style={{ background: avatarColor(e.employee_id) }}>{initials(e.full_name)}</div>
                  <div>
                    <strong>{e.full_name}</strong>
                    <span>{e.email}</span>
                  </div>
                </div>
              ),
            },
            { header: "Role", render: (e) => <><strong>{e.job_role}</strong><small>{e.department ?? "—"} · {e.location ?? "—"}</small></> },
            { header: "Manager", render: (e) => e.manager?.full_name ?? "—" },
            { header: "Buddy", render: (e) => e.buddy?.full_name ?? "—" },
            {
              header: "Status",
              render: (e) => (
                <div className="pp-inline-actions">
                  <Pill tone={e.is_active ? "healthy" : "neutral"}>{e.is_active ? "Active" : "Inactive"}</Pill>
                  {e.is_staff && <Pill tone="info">Staff</Pill>}
                </div>
              ),
            },
            {
              header: "Actions",
              width: "minmax(190px, 1.4fr)",
              render: (e) => (
                <div className="pp-inline-actions">
                  <button className="secondary-button small" onClick={() => setEditing(e)}>Edit</button>
                  {e.is_active && (
                    <button className="secondary-button small" disabled={action.busy} onClick={() => deactivate(e)}>Deactivate</button>
                  )}
                  <button className="secondary-button small danger" disabled={action.busy} onClick={() => remove(e)}>Delete</button>
                </div>
              ),
            },
          ]}
        />
      </AsyncBlock>

      {editing !== null && (
        <EmployeeEditor
          key={editing === "new" ? "new" : editing.employee_id}
          record={editing}
          onClose={() => setEditing(null)}
          onSaved={() => void list.reload()}
        />
      )}
    </Panel>
  );
}
