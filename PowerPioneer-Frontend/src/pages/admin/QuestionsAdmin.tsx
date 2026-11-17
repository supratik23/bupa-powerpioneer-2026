import { useMemo, useState } from "react";
import type { FormEvent } from "react";
import { Plus, Trash2 } from "lucide-react";
import { api } from "../../api/client";
import { QUESTION_SOURCES, TRIGGER_TYPES } from "../../api/types";
import type {
  EmployeeResponse,
  NestedOption,
  Question,
  QuestionOption,
  QuestionSource,
  TriggerType,
} from "../../api/types";
import { formatDateTime, fromLocalInput, label, toLocalInput } from "../../lib/format";
import { useAction, useAsync } from "../../lib/useAsync";
import { useEmployees } from "../../lib/useEmployees";
import {
  AsyncBlock,
  CheckField,
  DataTable,
  ErrorNote,
  Panel,
  Pill,
  SelectField,
  SidePanel,
  TextArea,
  TextField,
  enumOptions,
} from "../../components/ui";

const DEFAULT_OPTIONS: NestedOption[] = [
  { option_text: "Very poor", normalized_score: 1, display_order: 0 },
  { option_text: "Poor", normalized_score: 2, display_order: 1 },
  { option_text: "Okay", normalized_score: 3, display_order: 2 },
  { option_text: "Good", normalized_score: 4, display_order: 3 },
  { option_text: "Very good", normalized_score: 5, display_order: 4 },
];

/** Individually edits options of a question that already has responses (/question-options/). */
function OptionRows({ question, onChanged }: { question: Question; onChanged: () => void }) {
  const options = useAsync(
    () => api.listAll<QuestionOption>("/question-options/", { question: question.question_id, ordering: "display_order" }),
    [question.question_id],
  );
  const [draft, setDraft] = useState({ option_text: "", normalized_score: "3" });
  const { busy, error, run } = useAction();

  const save = (o: QuestionOption, patch: Partial<QuestionOption>) =>
    run(async () => {
      await api.patch(`/question-options/${o.option_id}/`, patch);
      await options.reload();
      onChanged();
    });

  const add = () =>
    run(async () => {
      await api.post("/question-options/", {
        question_id: question.question_id,
        option_text: draft.option_text,
        normalized_score: Number(draft.normalized_score),
        display_order: options.data?.length ?? 0,
      });
      setDraft({ option_text: "", normalized_score: "3" });
      await options.reload();
      onChanged();
    });

  const remove = (o: QuestionOption) => {
    if (!window.confirm(`Delete option "${o.option_text}"? Responses using it are deleted too.`)) return;
    void run(async () => {
      await api.delete(`/question-options/${o.option_id}/`);
      await options.reload();
      onChanged();
    });
  };

  return (
    <div className="drawer-section">
      <span className="section-kicker">/question-options/</span>
      <h3>Answer options</h3>
      <ErrorNote message={error} />
      <AsyncBlock loading={options.loading} error={options.error}>
        <ul className="factor-list">
          {(options.data ?? []).map((o) => (
            <li key={o.option_id}>
              <span>{o.normalized_score}</span>
              <div style={{ flex: 1 }}>
                <input
                  className="secondary-button"
                  defaultValue={o.option_text}
                  aria-label="Option text"
                  onBlur={(e) => e.target.value !== o.option_text && void save(o, { option_text: e.target.value })}
                />
              </div>
              <input
                className="secondary-button"
                type="number"
                style={{ width: 64 }}
                defaultValue={o.normalized_score}
                aria-label="Score"
                onBlur={(e) => Number(e.target.value) !== o.normalized_score && void save(o, { normalized_score: Number(e.target.value) })}
              />
              <button className="ghost-icon" disabled={busy} aria-label="Delete option" onClick={() => remove(o)}>
                <Trash2 size={15} />
              </button>
            </li>
          ))}
        </ul>
      </AsyncBlock>
      <div className="pp-inline-actions" style={{ marginTop: 12 }}>
        <input className="secondary-button" placeholder="New option" value={draft.option_text} onChange={(e) => setDraft({ ...draft, option_text: e.target.value })} aria-label="New option text" />
        <input className="secondary-button" type="number" style={{ width: 64 }} value={draft.normalized_score} onChange={(e) => setDraft({ ...draft, normalized_score: e.target.value })} aria-label="New option score" />
        <button className="secondary-button small" disabled={busy || !draft.option_text.trim()} onClick={() => void add()}>Add</button>
      </div>
    </div>
  );
}

function QuestionEditor({
  record,
  onClose,
  onSaved,
}: {
  record: Question | "new";
  onClose: () => void;
  onSaved: () => void;
}) {
  const { employees } = useEmployees();
  const existing = record === "new" ? null : record;
  const [form, setForm] = useState(() => ({
    question_text: existing?.question_text ?? "",
    source: (existing?.source ?? "MANUAL") as QuestionSource,
    trigger_type: (existing?.trigger_type ?? "SCHEDULED") as TriggerType,
    generated_for_employee_id: existing?.generated_for_employee_id ?? "",
    is_active: existing?.is_active ?? true,
    expires_at: toLocalInput(existing?.expires_at),
    model_name: existing?.model_name ?? "",
    prompt_version: existing?.prompt_version ?? "",
  }));
  const [options, setOptions] = useState<NestedOption[]>(() =>
    existing ? existing.options.map((o) => ({ ...o })) : DEFAULT_OPTIONS.map((o) => ({ ...o })),
  );
  const [editOptionsInline, setEditOptionsInline] = useState(!existing);
  const { busy, error, run } = useAction();

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body: Record<string, unknown> = {
      ...form,
      generated_for_employee_id: form.generated_for_employee_id || null,
      expires_at: fromLocalInput(form.expires_at),
      model_name: form.model_name || null,
      prompt_version: form.prompt_version || null,
    };
    if (editOptionsInline) {
      body.options = options.map((o, i) => ({
        option_text: o.option_text,
        normalized_score: Number(o.normalized_score),
        display_order: i,
      }));
    }
    const saved = await run(() =>
      existing
        ? api.patch<Question>(`/questions/${existing.question_id}/`, body)
        : api.post<Question>("/questions/", body),
    );
    if (saved) onSaved();
  };

  const setOption = (i: number, patch: Partial<NestedOption>) =>
    setOptions((list) => list.map((o, idx) => (idx === i ? { ...o, ...patch } : o)));

  return (
    <SidePanel open kicker="Pulse survey" title={existing ? "Edit question" : "New question"} onClose={onClose}>
      <form className="pp-form" onSubmit={(e) => void submit(e)}>
        <TextArea label="Question" value={form.question_text} onChange={(v) => setForm({ ...form, question_text: v })} />
        <SelectField label="Source" value={form.source} onChange={(v) => setForm({ ...form, source: v as QuestionSource })} options={enumOptions(QUESTION_SOURCES, label)} required />
        <SelectField label="Trigger" value={form.trigger_type} onChange={(v) => setForm({ ...form, trigger_type: v as TriggerType })} options={enumOptions(TRIGGER_TYPES, label)} required />
        <SelectField
          label="Only for employee"
          value={form.generated_for_employee_id}
          onChange={(v) => setForm({ ...form, generated_for_employee_id: v })}
          options={employees.map((e) => ({ value: e.employee_id, label: e.full_name }))}
          placeholder="Everyone"
        />
        <TextField label="Expires" type="datetime-local" value={form.expires_at} onChange={(v) => setForm({ ...form, expires_at: v })} />
        <TextField label="Model name" value={form.model_name} onChange={(v) => setForm({ ...form, model_name: v })} />
        <TextField label="Prompt version" value={form.prompt_version} onChange={(v) => setForm({ ...form, prompt_version: v })} />
        <div className="pp-check-row">
          <CheckField label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
          {existing && (
            <CheckField label="Replace all options (only if unanswered)" checked={editOptionsInline} onChange={setEditOptionsInline} />
          )}
        </div>

        {editOptionsInline && (
          <div className="drawer-section full">
            <span className="section-kicker">Inline options</span>
            <h3>Answers (higher score = better wellbeing)</h3>
            <ul className="factor-list">
              {options.map((o, i) => (
                <li key={i}>
                  <span>{i + 1}</span>
                  <div style={{ flex: 1 }}>
                    <input className="secondary-button" value={o.option_text} onChange={(e) => setOption(i, { option_text: e.target.value })} aria-label="Option text" required />
                  </div>
                  <input className="secondary-button" type="number" style={{ width: 64 }} value={o.normalized_score} onChange={(e) => setOption(i, { normalized_score: Number(e.target.value) })} aria-label="Score" />
                  <button type="button" className="ghost-icon" aria-label="Remove option" onClick={() => setOptions(options.filter((_, idx) => idx !== i))}>
                    <Trash2 size={15} />
                  </button>
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="secondary-button small"
              style={{ marginTop: 12 }}
              onClick={() => setOptions([...options, { option_text: "", normalized_score: 3, display_order: options.length }])}
            >
              <Plus size={13} /> Add option
            </button>
          </div>
        )}

        <ErrorNote message={error} />
        <div className="pp-form-actions">
          <button type="button" className="secondary-button" onClick={onClose}>Close</button>
          <button type="submit" className="primary-button" disabled={busy}>{busy ? "Saving…" : "Save question"}</button>
        </div>
      </form>
      {existing && !editOptionsInline && <OptionRows question={existing} onChanged={onSaved} />}
    </SidePanel>
  );
}

export function QuestionsAdmin() {
  const [editing, setEditing] = useState<Question | "new" | null>(null);
  const action = useAction();
  const list = useAsync(() => api.listAll<Question>("/questions/", { ordering: "-created_at" }), []);
  const { nameOf } = useEmployees();

  const remove = (q: Question) => {
    if (!window.confirm("Delete this question and all its answers?")) return;
    void action.run(async () => {
      await api.delete(`/questions/${q.question_id}/`);
      await list.reload();
    });
  };

  const toggle = (q: Question) =>
    action.run(async () => {
      await api.patch(`/questions/${q.question_id}/`, { is_active: !q.is_active });
      await list.reload();
    });

  return (
    <Panel
      kicker="Pulse surveys"
      title="Questions"
      actions={
        <button className="primary-button small" onClick={() => setEditing("new")}>
          <Plus size={14} /> New question
        </button>
      }
    >
      <ErrorNote message={action.error} />
      <AsyncBlock loading={list.loading} error={list.error} onRetry={list.reload}>
        <DataTable
          rows={list.data ?? []}
          rowKey={(q) => q.question_id}
          empty="No questions yet."
          columns={[
            {
              header: "Question",
              width: "minmax(0, 2.2fr)",
              render: (q) => (
                <>
                  <strong>{q.question_text}</strong>
                  <small>{q.options.map((o) => `${o.option_text} (${o.normalized_score})`).join(" · ")}</small>
                </>
              ),
            },
            { header: "Trigger", render: (q) => <><strong>{label(q.trigger_type)}</strong><small>{label(q.source)}</small></> },
            { header: "Audience", render: (q) => (q.generated_for_employee_id ? nameOf(q.generated_for_employee_id) : "Everyone") },
            { header: "Status", render: (q) => <Pill tone={q.is_open ? "healthy" : "neutral"}>{q.is_open ? "Open" : q.is_active ? "Expired" : "Inactive"}</Pill> },
            {
              header: "Actions",
              width: "minmax(200px, 1.5fr)",
              render: (q) => (
                <div className="pp-inline-actions">
                  <button className="secondary-button small" onClick={() => setEditing(q)}>Edit</button>
                  <button className="secondary-button small" disabled={action.busy} onClick={() => void toggle(q)}>
                    {q.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button className="secondary-button small danger" disabled={action.busy} onClick={() => remove(q)}>Delete</button>
                </div>
              ),
            },
          ]}
        />
      </AsyncBlock>
      {editing !== null && (
        <QuestionEditor
          key={editing === "new" ? "new" : editing.question_id}
          record={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            void list.reload();
            if (editing === "new") setEditing(null);
          }}
        />
      )}
    </Panel>
  );
}

export function ResponsesAdmin() {
  const { nameOf } = useEmployees();
  const [employee, setEmployee] = useState("");
  const { employees } = useEmployees();
  const action = useAction();
  const responses = useAsync(
    () => api.list<EmployeeResponse>("/employee-responses/", { employee: employee || undefined, ordering: "-responded_at" }),
    [employee],
  );
  const questions = useAsync(() => api.listAll<Question>("/questions/"), []);
  const byId = useMemo(() => new Map((questions.data ?? []).map((q) => [q.question_id, q])), [questions.data]);

  const remove = (r: EmployeeResponse) => {
    if (!window.confirm("Delete this response?")) return;
    void action.run(async () => {
      await api.delete(`/employee-responses/${r.response_id}/`);
      await responses.reload();
    });
  };

  return (
    <Panel
      kicker="Survey answers (latest 25)"
      title="Employee responses"
      actions={
        <select className="secondary-button" value={employee} onChange={(e) => setEmployee(e.target.value)} aria-label="Filter by employee">
          <option value="">All employees</option>
          {employees.map((e) => <option key={e.employee_id} value={e.employee_id}>{e.full_name}</option>)}
        </select>
      }
    >
      <ErrorNote message={action.error} />
      <AsyncBlock loading={responses.loading} error={responses.error} onRetry={responses.reload}>
        <DataTable
          rows={responses.data ?? []}
          rowKey={(r) => r.response_id}
          empty="No responses."
          columns={[
            { header: "Employee", render: (r) => <strong>{nameOf(r.employee_id)}</strong> },
            { header: "Question", width: "minmax(0, 2fr)", render: (r) => byId.get(r.question_id)?.question_text ?? "—" },
            { header: "Answer", render: (r) => byId.get(r.question_id)?.options.find((o) => o.option_id === r.option_id)?.option_text ?? "—" },
            { header: "Answered", render: (r) => formatDateTime(r.responded_at) },
            { header: "", width: "90px", render: (r) => <button className="secondary-button small danger" disabled={action.busy} onClick={() => remove(r)}>Delete</button> },
          ]}
        />
      </AsyncBlock>
    </Panel>
  );
}
