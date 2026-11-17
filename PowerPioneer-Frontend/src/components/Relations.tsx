import { useState } from "react";
import { api } from "../api/client";
import type { BuddySuggestion, Employee } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { num } from "../lib/format";
import { useAction } from "../lib/useAsync";
import { invalidateEmployees, useEmployees } from "../lib/useEmployees";
import { ErrorNote } from "./ui";

/**
 * Manager / buddy management for one employee:
 *   POST /employees/{id}/assign-manager/   (staff)
 *   POST /employees/{id}/remove-manager/   (staff)
 *   POST /employees/{id}/assign-buddy/     (staff or manager)
 *   POST /employees/{id}/remove-buddy/     (staff or manager)
 *   GET  /employees/{id}/suggest-buddies/  (staff or manager)
 */
export function Relations({ employee, onChanged }: { employee: Employee; onChanged: (e: Employee) => void }) {
  const { isStaff } = useAuth();
  const { employees } = useEmployees();
  const { busy, error, run } = useAction();
  const [managerId, setManagerId] = useState("");
  const [buddyId, setBuddyId] = useState("");
  const [suggestions, setSuggestions] = useState<BuddySuggestion[] | null>(null);
  const id = employee.employee_id;

  const others = employees
    .filter((e) => e.is_active && e.employee_id !== id)
    .map((e) => ({ value: e.employee_id, label: e.full_name }));

  const post = (path: string, body: object) =>
    run(async () => {
      const updated = await api.post<Employee>(`/employees/${id}/${path}/`, body);
      invalidateEmployees();
      onChanged(updated);
      setSuggestions(null);
    });

  const suggest = () =>
    run(async () => setSuggestions(await api.get<BuddySuggestion[]>(`/employees/${id}/suggest-buddies/`, { limit: 5 })));

  return (
    <div className="drawer-section">
      <span className="section-kicker">Support network</span>
      <h3>Manager & buddy</h3>
      <ErrorNote message={error} />

      <div className="pp-form" style={{ marginTop: 6 }}>
        <div className="pp-field full">
          <span>Manager</span>
          <div className="pp-muted">{employee.manager?.full_name ?? "Not assigned"}</div>
          {isStaff && (
            <div className="pp-inline-actions">
              <select className="secondary-button" value={managerId} onChange={(e) => setManagerId(e.target.value)} aria-label="New manager">
                <option value="">Choose manager…</option>
                {others.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <button className="secondary-button small" disabled={busy || !managerId} onClick={() => void post("assign-manager", { manager_employee_id: managerId })}>
                Assign
              </button>
              {employee.manager_employee_id && (
                <button className="secondary-button small danger" disabled={busy} onClick={() => void post("remove-manager", { reason: "Removed from ShiftGuard UI" })}>
                  Remove
                </button>
              )}
            </div>
          )}
        </div>

        <div className="pp-field full">
          <span>Buddy</span>
          <div className="pp-muted">{employee.buddy?.full_name ?? "Not assigned"}</div>
          <div className="pp-inline-actions">
            <select className="secondary-button" value={buddyId} onChange={(e) => setBuddyId(e.target.value)} aria-label="New buddy">
              <option value="">Choose buddy…</option>
              {others.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <button className="secondary-button small" disabled={busy || !buddyId} onClick={() => void post("assign-buddy", { buddy_employee_id: buddyId })}>
              Assign
            </button>
            {employee.buddy_employee_id && (
              <button className="secondary-button small danger" disabled={busy} onClick={() => void post("remove-buddy", { reason: "Removed from ShiftGuard UI" })}>
                Remove
              </button>
            )}
            <button className="secondary-button small" disabled={busy} onClick={() => void suggest()}>
              Suggest buddies
            </button>
          </div>
        </div>
      </div>

      {suggestions && (
        <ul className="factor-list" style={{ marginTop: 14 }}>
          {suggestions.length === 0 && <li><div><small>No suitable buddies with spare capacity.</small></div></li>}
          {suggestions.map((s, i) => (
            <li key={s.employee_id}>
              <span>{i + 1}</span>
              <div style={{ flex: 1 }}>
                <strong>{s.full_name} · match {num(s.match_score)}</strong>
                <small>
                  {s.job_role} · supports {s.current_buddy_load} · {s.reasons.join(", ") || "Available peer"}
                </small>
              </div>
              <button className="secondary-button small" disabled={busy} onClick={() => void post("assign-buddy", { buddy_employee_id: s.employee_id })}>
                Assign
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
