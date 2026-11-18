import { useState } from "react";
import type { FormEvent } from "react";
import { CalendarDays, List, Plus } from "lucide-react";
import { api } from "../api/client";
import { ABSENCE_TYPES, RECORDABLE_ATTENDANCE_STATUSES, SHIFT_TYPES } from "../api/types";
import type { AbsenceType, Attendance, AttendanceStatus, Employee, Shift, ShiftType } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { formatDate, formatTime, fromLocalInput, isoDate, label, num, toLocalInput } from "../lib/format";
import { useAction, useAsync } from "../lib/useAsync";
import { useEmployees } from "../lib/useEmployees";
import { shiftKind } from "../lib/shifts";
import { RosterCalendar, TeamCalendar, monthGrid } from "../components/RosterCalendar";
import type { CalendarItem } from "../components/RosterCalendar";
import {
  AsyncBlock,
  CheckField,
  DataTable,
  ErrorNote,
  PageHeader,
  Panel,
  Pill,
  SelectField,
  SidePanel,
  Tabs,
  TextArea,
  TextField,
  enumOptions,
} from "../components/ui";
import type { Tone } from "../components/ui";

export type RosterTab = TabId;
type TabId = "my-shifts" | "my-attendance" | "shifts" | "attendance";

const attendanceTone: Record<AttendanceStatus, Tone> = {
  PRESENT: "healthy",
  LATE: "warning",
  ABSENT: "danger",
  ON_LEAVE: "info",
  NOT_SCHEDULED: "neutral",
};

function shiftFlags(s: Shift) {
  const flags = [
    s.understaffed_flag && "Understaffed",
    s.missed_break_flag && "Missed break",
    s.short_notice_change_flag && "Short notice",
    s.redeployment_flag && "Redeployed",
  ].filter(Boolean) as string[];
  return flags.length ? flags.join(" · ") : "—";
}

/** Employees the current user may manage: everyone for staff, direct reports for managers. */
function useManagedEmployees(enabled: boolean) {
  const { user, isStaff } = useAuth();
  const { employees } = useEmployees();
  const team = useAsync(
    () =>
      enabled && user && !isStaff
        ? api.get<Employee[]>(`/employees/${user.employee_id}/team/`)
        : Promise.resolve([] as Employee[]),
    [enabled, user?.employee_id, isStaff],
  );
  return isStaff ? employees.filter((e) => e.is_active) : team.data ?? [];
}

// ---------------------------------------------------------------------------
// shift editor
// ---------------------------------------------------------------------------
interface ShiftForm {
  employee_id: string;
  shift_start: string;
  shift_end: string;
  shift_type: ShiftType;
  planned_hours: string;
  actual_hours: string;
  location: string;
  expected_patient_load: string;
  actual_patient_load: string;
  planned_staff_count: string;
  actual_staff_count: string;
  understaffed_flag: boolean;
  missed_break_flag: boolean;
  short_notice_change_flag: boolean;
  redeployment_flag: boolean;
}

const str = (v: number | string | null | undefined) => (v === null || v === undefined ? "" : String(v));
const numOrNull = (v: string) => (v.trim() === "" ? null : Number(v));

function ShiftEditor({
  shift,
  employees,
  onClose,
  onSaved,
}: {
  shift: Shift | "new";
  employees: Employee[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const existing = shift === "new" ? null : shift;
  const today = isoDate();
  const [form, setForm] = useState<ShiftForm>(() => ({
    employee_id: existing?.employee_id ?? employees[0]?.employee_id ?? "",
    shift_start: existing ? toLocalInput(existing.shift_start) : `${today}T08:00`,
    shift_end: existing ? toLocalInput(existing.shift_end) : `${today}T16:00`,
    shift_type: existing?.shift_type ?? "DAY",
    planned_hours: str(existing?.planned_hours),
    actual_hours: str(existing?.actual_hours),
    location: existing?.location ?? "",
    expected_patient_load: str(existing?.expected_patient_load),
    actual_patient_load: str(existing?.actual_patient_load),
    planned_staff_count: str(existing?.planned_staff_count),
    actual_staff_count: str(existing?.actual_staff_count),
    understaffed_flag: existing?.understaffed_flag ?? false,
    missed_break_flag: existing?.missed_break_flag ?? false,
    short_notice_change_flag: existing?.short_notice_change_flag ?? false,
    redeployment_flag: existing?.redeployment_flag ?? false,
  }));
  const { busy, error, run } = useAction();
  const set = <K extends keyof ShiftForm>(key: K, value: ShiftForm[K]) => setForm((f) => ({ ...f, [key]: value }));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = {
      employee_id: form.employee_id,
      shift_start: fromLocalInput(form.shift_start),
      shift_end: fromLocalInput(form.shift_end),
      shift_type: form.shift_type,
      actual_hours: numOrNull(form.actual_hours),
      location: form.location || null,
      expected_patient_load: numOrNull(form.expected_patient_load),
      actual_patient_load: numOrNull(form.actual_patient_load),
      planned_staff_count: numOrNull(form.planned_staff_count),
      actual_staff_count: numOrNull(form.actual_staff_count),
      missed_break_flag: form.missed_break_flag,
      short_notice_change_flag: form.short_notice_change_flag,
      redeployment_flag: form.redeployment_flag,
    };
    // Let the backend derive planned hours / understaffing on create when left blank.
    if (form.planned_hours.trim() !== "") body.planned_hours = Number(form.planned_hours);
    if (existing || form.understaffed_flag) body.understaffed_flag = form.understaffed_flag;

    const saved = await run(() =>
      existing ? api.patch<Shift>(`/shifts/${existing.shift_id}/`, body) : api.post<Shift>("/shifts/", body),
    );
    if (saved) onSaved();
  };

  return (
    <SidePanel open kicker="Shift roster" title={existing ? "Edit shift" : "Add shift"} onClose={onClose}>
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <SelectField
          label="Employee"
          value={form.employee_id}
          onChange={(v) => set("employee_id", v)}
          options={employees.map((e) => ({ value: e.employee_id, label: e.full_name }))}
          required
          placeholder="Select employee"
        />
        <SelectField
          label="Shift type"
          value={form.shift_type}
          onChange={(v) => set("shift_type", v as ShiftType)}
          options={enumOptions(SHIFT_TYPES, label)}
          required
        />
        <TextField label="Start" type="datetime-local" value={form.shift_start} onChange={(v) => set("shift_start", v)} required />
        <TextField label="End" type="datetime-local" value={form.shift_end} onChange={(v) => set("shift_end", v)} required />
        <TextField
          label="Planned hours"
          type="number"
          step="0.25"
          min={0}
          value={form.planned_hours}
          onChange={(v) => set("planned_hours", v)}
          hint="Leave blank to use the shift length."
        />
        <TextField label="Actual hours" type="number" step="0.25" min={0} value={form.actual_hours} onChange={(v) => set("actual_hours", v)} />
        <TextField label="Location" value={form.location} onChange={(v) => set("location", v)} />
        <TextField label="Expected patient load" type="number" step="0.1" min={0} value={form.expected_patient_load} onChange={(v) => set("expected_patient_load", v)} />
        <TextField label="Actual patient load" type="number" step="0.1" min={0} value={form.actual_patient_load} onChange={(v) => set("actual_patient_load", v)} />
        <TextField label="Planned staff" type="number" min={0} value={form.planned_staff_count} onChange={(v) => set("planned_staff_count", v)} />
        <TextField label="Actual staff" type="number" min={0} value={form.actual_staff_count} onChange={(v) => set("actual_staff_count", v)} />
        <div className="pp-check-row">
          <CheckField label="Understaffed" checked={form.understaffed_flag} onChange={(v) => set("understaffed_flag", v)} />
          <CheckField label="Missed break" checked={form.missed_break_flag} onChange={(v) => set("missed_break_flag", v)} />
          <CheckField label="Short-notice change" checked={form.short_notice_change_flag} onChange={(v) => set("short_notice_change_flag", v)} />
          <CheckField label="Redeployed" checked={form.redeployment_flag} onChange={(v) => set("redeployment_flag", v)} />
        </div>
        <ErrorNote message={error} />
        <div className="pp-form-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
          <button type="submit" className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save shift"}</button>
        </div>
      </form>
    </SidePanel>
  );
}

// ---------------------------------------------------------------------------
// attendance editor
// ---------------------------------------------------------------------------
function AttendanceEditor({
  record,
  employees,
  onClose,
  onSaved,
}: {
  record: Attendance | "new";
  employees: Employee[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const existing = record === "new" ? null : record;
  const [form, setForm] = useState(() => ({
    employee_id: existing?.employee_id ?? employees[0]?.employee_id ?? "",
    attendance_date: existing?.attendance_date ?? isoDate(),
    attendance_status: (existing?.attendance_status ?? "PRESENT") as AttendanceStatus,
    late_minutes: str(existing?.late_minutes ?? 0),
    absence_type: (existing?.absence_type ?? "") as AbsenceType | "",
    absence_episode_id: existing?.absence_episode_id ?? "",
    notes: existing?.notes ?? "",
  }));
  const { busy, error, run } = useAction();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const absent = form.attendance_status === "ABSENT";
    const body = {
      employee_id: form.employee_id,
      attendance_date: form.attendance_date,
      attendance_status: form.attendance_status,
      late_minutes: Number(form.late_minutes || 0),
      absence_type: absent ? form.absence_type || null : null,
      absence_episode_id: absent && form.absence_episode_id ? form.absence_episode_id : null,
      notes: form.notes || null,
    };
    const saved = await run(() =>
      existing
        ? api.patch<Attendance>(`/attendance/${existing.attendance_id}/`, body)
        : api.post<Attendance>("/attendance/", body),
    );
    if (saved) onSaved();
  };

  return (
    <SidePanel open kicker="Attendance" title={existing ? "Edit attendance" : "Record attendance"} onClose={onClose}>
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <SelectField
          label="Employee"
          value={form.employee_id}
          onChange={(v) => setForm({ ...form, employee_id: v })}
          options={employees.map((e) => ({ value: e.employee_id, label: e.full_name }))}
          required
          placeholder="Select employee"
        />
        <TextField label="Date" type="date" value={form.attendance_date} onChange={(v) => setForm({ ...form, attendance_date: v })} required />
        <SelectField
          label="Status"
          value={form.attendance_status}
          onChange={(v) => setForm({ ...form, attendance_status: v as AttendanceStatus })}
          options={enumOptions(RECORDABLE_ATTENDANCE_STATUSES, label)}
          required
        />
        <TextField label="Late minutes" type="number" min={0} value={form.late_minutes} onChange={(v) => setForm({ ...form, late_minutes: v })} />
        {form.attendance_status === "ABSENT" && (
          <>
            <SelectField
              label="Absence type"
              value={form.absence_type}
              onChange={(v) => setForm({ ...form, absence_type: v as AbsenceType })}
              options={enumOptions(ABSENCE_TYPES, label)}
              required
              placeholder="Select type"
            />
            <TextField
              label="Absence episode id"
              value={form.absence_episode_id}
              onChange={(v) => setForm({ ...form, absence_episode_id: v })}
              hint="Optional UUID grouping days of the same absence."
            />
          </>
        )}
        <TextArea label="Notes" value={form.notes} onChange={(v) => setForm({ ...form, notes: v })} />
        <ErrorNote message={error} />
        <div className="pp-form-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
          <button type="submit" className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save record"}</button>
        </div>
      </form>
    </SidePanel>
  );
}

// ---------------------------------------------------------------------------
// list / calendar view preference (per browser)
// ---------------------------------------------------------------------------
type ViewMode = "list" | "calendar";
const VIEW_KEY = "pp-roster-view";

function readView(): ViewMode {
  try {
    return window.localStorage.getItem(VIEW_KEY) === "calendar" ? "calendar" : "list";
  } catch {
    return "list";
  }
}

function saveView(view: ViewMode) {
  try {
    window.localStorage.setItem(VIEW_KEY, view);
  } catch {
    // storage unavailable: the choice just won't persist
  }
}

const attendanceChipTone: Record<AttendanceStatus, string> = {
  PRESENT: "present",
  LATE: "late",
  ABSENT: "absent",
  ON_LEAVE: "leave",
  NOT_SCHEDULED: "unscheduled",
};

const attendanceShort: Record<AttendanceStatus, string> = {
  PRESENT: "In",
  LATE: "Late",
  ABSENT: "Off",
  ON_LEAVE: "Leave",
  NOT_SCHEDULED: "—",
};

const SHIFT_LEGEND = [
  { tone: "day", label: "Day / early / late" },
  { tone: "long", label: "Long day" },
  { tone: "night", label: "Night" },
  { tone: "oncall", label: "On call" },
];
const ATTENDANCE_LEGEND = [
  { tone: "present", label: "Present" },
  { tone: "late", label: "Late" },
  { tone: "absent", label: "Absent" },
  { tone: "leave", label: "On leave" },
  { tone: "unscheduled", label: "Not scheduled" },
];

const firstName = (name: string) => name.split(" ")[0] ?? name;

// ---------------------------------------------------------------------------
// page
// ---------------------------------------------------------------------------
export default function RosterPage({ initialTab = "my-shifts" }: { initialTab?: TabId }) {
  const { user, isManager } = useAuth();
  const { nameOf } = useEmployees();
  const [tab, setTab] = useState<TabId>(initialTab);
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [from, setFrom] = useState(() => isoDate(new Date(Date.now() - 14 * 86400000)));
  const [to, setTo] = useState(() => isoDate(new Date(Date.now() + 28 * 86400000)));
  const [view, setViewState] = useState<ViewMode>(readView);
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [editingShift, setEditingShift] = useState<Shift | "new" | null>(null);
  const [editingAttendance, setEditingAttendance] = useState<Attendance | "new" | null>(null);
  const action = useAction();
  const managed = useManagedEmployees(isManager);
  const meId = user?.employee_id ?? "";

  const mine = tab === "my-shifts" || tab === "my-attendance";
  const employee = mine ? meId : employeeFilter;
  const isShifts = tab === "my-shifts" || tab === "shifts";
  const calendar = view === "calendar";
  const setView = (next: ViewMode) => {
    setViewState(next);
    saveView(next);
  };

  // Calendar view loads the whole visible month grid; list view uses the date inputs.
  const grid = monthGrid(month);
  // Team calendar rows: the people being managed (or just the filtered one), never the manager.
  const people = managed
    .filter((e) => e.employee_id !== meId && (!employeeFilter || e.employee_id === employeeFilter))
    .map((e) => ({ id: e.employee_id, name: e.full_name, role: e.job_role }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const rangeFrom = calendar ? isoDate(grid.start) : from;
  const rangeTo = calendar ? isoDate(grid.end) : to;

  const shifts = useAsync(
    () =>
      isShifts
        ? api.listAll<Shift>("/shifts/", {
            employee: employee || undefined,
            shift_start__gte: new Date(`${rangeFrom}T00:00:00`).toISOString(),
            shift_start__lte: new Date(`${rangeTo}T23:59:59`).toISOString(),
            ordering: "shift_start",
          })
        : Promise.resolve([] as Shift[]),
    [tab, employee, rangeFrom, rangeTo],
  );

  const attendance = useAsync(
    () =>
      !isShifts
        ? api.listAll<Attendance>("/attendance/", {
            employee: employee || undefined,
            attendance_date__gte: rangeFrom,
            attendance_date__lte: rangeTo,
            ordering: "-attendance_date",
          })
        : Promise.resolve([] as Attendance[]),
    [tab, employee, rangeFrom, rangeTo],
  );

  // Team tabs: never list the manager's own rows.
  const shiftRows = (shifts.data ?? []).filter((s) => mine || s.employee_id !== meId);
  const attendanceRows = (attendance.data ?? []).filter((a) => mine || a.employee_id !== meId);

  const removeShift = (s: Shift) => {
    if (!window.confirm("Delete this shift?")) return;
    void action.run(async () => {
      await api.delete(`/shifts/${s.shift_id}/`);
      await shifts.reload();
    });
  };
  const removeAttendance = (a: Attendance) => {
    if (!window.confirm("Delete this attendance record?")) return;
    void action.run(async () => {
      await api.delete(`/attendance/${a.attendance_id}/`);
      await attendance.reload();
    });
  };

  const shiftItems: CalendarItem<Shift>[] = shiftRows.map((s) => ({
    id: s.shift_id,
    day: new Date(s.shift_start),
    chip: mine
      ? `${formatTime(s.shift_start)} ${label(s.shift_type)}`
      : `${formatTime(s.shift_start)} ${firstName(nameOf(s.employee_id))}`,
    tone: shiftKind(s.shift_type),
    alert: s.understaffed_flag,
    personId: s.employee_id,
    short: formatTime(s.shift_start),
    row: s,
  }));
  const attendanceItems: CalendarItem<Attendance>[] = attendanceRows.map((a) => ({
    id: a.attendance_id,
    day: new Date(`${a.attendance_date}T00:00:00`),
    chip: mine
      ? `${label(a.attendance_status)}${a.late_minutes ? ` ${a.late_minutes}m` : ""}`
      : `${firstName(nameOf(a.employee_id))} · ${label(a.attendance_status)}`,
    tone: attendanceChipTone[a.attendance_status],
    personId: a.employee_id,
    short: a.attendance_status === "LATE" && a.late_minutes ? `${a.late_minutes}m` : attendanceShort[a.attendance_status],
    row: a,
  }));

  const shiftDetail = (s: Shift) => (
    <>
      <div>
        {!mine && <strong>{nameOf(s.employee_id)}</strong>}
        <span>
          {formatTime(s.shift_start)}–{formatTime(s.shift_end)} · {num(s.planned_hours)}h planned
          {s.actual_hours !== null ? ` · ${num(s.actual_hours)}h actual` : ""}
          {s.location ? ` · ${s.location}` : ""}
        </span>
        {shiftFlags(s) !== "—" && <small>{shiftFlags(s)}</small>}
      </div>
      <Pill tone={s.shift_type === "NIGHT" ? "info" : "neutral"}>{label(s.shift_type)}</Pill>
      {!mine && (
        <div className="pp-inline-actions">
          <button className="secondary-button small" onClick={() => setEditingShift(s)}>Edit</button>
          <button className="secondary-button small danger" disabled={action.busy} onClick={() => removeShift(s)}>
            Delete
          </button>
        </div>
      )}
    </>
  );
  const attendanceDetail = (a: Attendance) => (
    <>
      <div>
        {!mine && <strong>{nameOf(a.employee_id)}</strong>}
        <span>
          {a.late_minutes ? `${a.late_minutes} min late` : "On time"}
          {a.absence_type ? ` · ${label(a.absence_type)}` : ""}
        </span>
        {a.notes && <small>{a.notes}</small>}
      </div>
      <Pill tone={attendanceTone[a.attendance_status]}>{label(a.attendance_status)}</Pill>
      {!mine && (
        <div className="pp-inline-actions">
          <button className="secondary-button small" onClick={() => setEditingAttendance(a)}>Edit</button>
          <button className="secondary-button small danger" disabled={action.busy} onClick={() => removeAttendance(a)}>
            Delete
          </button>
        </div>
      )}
    </>
  );

  const tabs: Array<{ id: TabId; label: string }> = [
    { id: "my-shifts", label: "My shifts" },
    { id: "my-attendance", label: "My attendance" },
    ...(isManager
      ? [
          { id: "shifts" as const, label: "Team shifts" },
          { id: "attendance" as const, label: "Team attendance" },
        ]
      : []),
  ];

  return (
    <main className="page-shell">
      <PageHeader
        kicker="Rostering"
        title={mine ? "Full roster" : "Team roster"}
        description="Shifts and attendance recorded for the selected period."
        actions={
          !mine && (
            <button
              className="primary-button"
              disabled={!managed.length}
              onClick={() => (tab === "shifts" ? setEditingShift("new") : setEditingAttendance("new"))}
            >
              <Plus size={16} /> {tab === "shifts" ? "Add shift" : "Record attendance"}
            </button>
          )
        }
      />
      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      <Panel
        kicker={isShifts ? "Shift roster" : "Attendance"}
        title={isShifts ? "Shifts" : "Attendance records"}
        actions={
          <>
            <div className="filter-tabs view-toggle" role="group" aria-label="View">
              <button className={!calendar ? "active" : ""} aria-pressed={!calendar} onClick={() => setView("list")}>
                <List size={14} /> List
              </button>
              <button className={calendar ? "active" : ""} aria-pressed={calendar} onClick={() => setView("calendar")}>
                <CalendarDays size={14} /> Calendar
              </button>
            </div>
            {!mine && (
              <select
                className="secondary-button"
                value={employeeFilter}
                onChange={(e) => setEmployeeFilter(e.target.value)}
                aria-label="Filter by employee"
              >
                <option value="">All team members</option>
                {managed.map((e) => (
                  <option key={e.employee_id} value={e.employee_id}>
                    {e.full_name}
                  </option>
                ))}
              </select>
            )}
            {!calendar && (
              <>
                <input className="secondary-button" type="date" value={from} onChange={(e) => setFrom(e.target.value)} aria-label="From" />
                <input className="secondary-button" type="date" value={to} onChange={(e) => setTo(e.target.value)} aria-label="To" />
              </>
            )}
          </>
        }
      >
        <ErrorNote message={action.error} />
        {calendar && !mine ? (
          isShifts ? (
            <AsyncBlock loading={shifts.loading && !shifts.data} error={shifts.error} onRetry={shifts.reload}>
              <TeamCalendar
                month={month}
                onMonthChange={setMonth}
                people={people}
                items={shiftItems}
                renderDetail={shiftDetail}
                emptyDay="No shift for this person on this day."
                legend={SHIFT_LEGEND}
              />
            </AsyncBlock>
          ) : (
            <AsyncBlock loading={attendance.loading && !attendance.data} error={attendance.error} onRetry={attendance.reload}>
              <TeamCalendar
                month={month}
                onMonthChange={setMonth}
                people={people}
                items={attendanceItems}
                renderDetail={attendanceDetail}
                emptyDay="No attendance recorded for this person on this day."
                legend={ATTENDANCE_LEGEND}
              />
            </AsyncBlock>
          )
        ) : calendar ? (
          isShifts ? (
            <AsyncBlock loading={shifts.loading && !shifts.data} error={shifts.error} onRetry={shifts.reload}>
              <RosterCalendar
                month={month}
                onMonthChange={setMonth}
                items={shiftItems}
                renderDetail={shiftDetail}
                emptyDay="No shifts on this day."
                legend={SHIFT_LEGEND}
              />
            </AsyncBlock>
          ) : (
            <AsyncBlock loading={attendance.loading && !attendance.data} error={attendance.error} onRetry={attendance.reload}>
              <RosterCalendar
                month={month}
                onMonthChange={setMonth}
                items={attendanceItems}
                renderDetail={attendanceDetail}
                emptyDay="No attendance recorded on this day."
                legend={ATTENDANCE_LEGEND}
              />
            </AsyncBlock>
          )
        ) : isShifts ? (
          <AsyncBlock loading={shifts.loading} error={shifts.error} onRetry={shifts.reload}>
            <DataTable
              rows={shiftRows}
              rowKey={(s) => s.shift_id}
              empty="No shifts in this period."
              columns={[
                ...(!mine ? [{ header: "Employee", render: (s: Shift) => <strong>{nameOf(s.employee_id)}</strong> }] : []),
                {
                  header: "Date",
                  render: (s: Shift) => (
                    <>
                      <strong>{formatDate(s.shift_start)}</strong>
                      <small>
                        {formatTime(s.shift_start)}–{formatTime(s.shift_end)}
                      </small>
                    </>
                  ),
                },
                { header: "Type", render: (s: Shift) => <Pill tone={s.shift_type === "NIGHT" ? "info" : "neutral"}>{label(s.shift_type)}</Pill> },
                {
                  header: "Hours",
                  render: (s: Shift) => (
                    <>
                      {num(s.planned_hours)}h planned
                      <small>{s.actual_hours !== null ? `${num(s.actual_hours)}h actual` : "Not recorded"}</small>
                    </>
                  ),
                },
                { header: "Location", render: (s: Shift) => s.location ?? "—" },
                { header: "Flags", render: (s: Shift) => <small>{shiftFlags(s)}</small> },
                ...(!mine
                  ? [
                      {
                        header: "Actions",
                        render: (s: Shift) => (
                          <div className="pp-inline-actions">
                            <button className="secondary-button small" onClick={() => setEditingShift(s)}>Edit</button>
                            <button className="secondary-button small danger" disabled={action.busy} onClick={() => removeShift(s)}>
                              Delete
                            </button>
                          </div>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </AsyncBlock>
        ) : (
          <AsyncBlock loading={attendance.loading} error={attendance.error} onRetry={attendance.reload}>
            <DataTable
              rows={attendanceRows}
              rowKey={(a) => a.attendance_id}
              empty="No attendance records in this period."
              columns={[
                ...(!mine ? [{ header: "Employee", render: (a: Attendance) => <strong>{nameOf(a.employee_id)}</strong> }] : []),
                { header: "Date", render: (a: Attendance) => <strong>{formatDate(a.attendance_date)}</strong> },
                {
                  header: "Status",
                  render: (a: Attendance) => (
                    <Pill tone={attendanceTone[a.attendance_status]}>{label(a.attendance_status)}</Pill>
                  ),
                },
                { header: "Late", render: (a: Attendance) => (a.late_minutes ? `${a.late_minutes} min` : "—") },
                { header: "Absence", render: (a: Attendance) => label(a.absence_type) },
                { header: "Notes", render: (a: Attendance) => <small>{a.notes ?? "—"}</small> },
                ...(!mine
                  ? [
                      {
                        header: "Actions",
                        render: (a: Attendance) => (
                          <div className="pp-inline-actions">
                            <button className="secondary-button small" onClick={() => setEditingAttendance(a)}>Edit</button>
                            <button className="secondary-button small danger" disabled={action.busy} onClick={() => removeAttendance(a)}>
                              Delete
                            </button>
                          </div>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </AsyncBlock>
        )}
      </Panel>

      {editingShift !== null && (
        <ShiftEditor
          key={editingShift === "new" ? "new" : editingShift.shift_id}
          shift={editingShift}
          employees={managed}
          onClose={() => setEditingShift(null)}
          onSaved={() => {
            setEditingShift(null);
            void shifts.reload();
          }}
        />
      )}
      {editingAttendance !== null && (
        <AttendanceEditor
          key={editingAttendance === "new" ? "new" : editingAttendance.attendance_id}
          record={editingAttendance}
          employees={managed}
          onClose={() => setEditingAttendance(null)}
          onSaved={() => {
            setEditingAttendance(null);
            void attendance.reload();
          }}
        />
      )}
    </main>
  );
}
