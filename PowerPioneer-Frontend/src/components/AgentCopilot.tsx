import { useCallback, useEffect, useRef, useState } from "react";
import {
  CircleCheck,
  CircleX,
  Loader2,
  MessageSquarePlus,
  Newspaper,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  X,
} from "lucide-react";
import { agentApi, agentStream, errorMessage } from "../api/client";
import type { AgentStreamEvent, ApprovalAction, ManagerBriefing } from "../api/types";
import { Markdown } from "./Markdown";

type StepStatus = "running" | "done" | "failed" | "declined";
interface Step {
  id: string;
  label: string;
  status: StepStatus;
}
interface Turn {
  id: string;
  role: "user" | "assistant";
  text: string;
  steps: Step[];
  approval?: ApprovalAction[];
  approvalState?: "pending" | "approved" | "declined";
  error?: string;
  streaming?: boolean;
}

const SUGGESTIONS = [
  "Who in my team needs attention this week, and why?",
  "Is next week's rota safe for my team?",
  "What if my highest-risk team member skipped their next two night shifts?",
  "Are there leave requests I should look at?",
  "How should I support someone after an end-of-life care shift?",
];

const SESSION_KEY = "pp.copilot.session";
const newId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;

function loadSession(): string {
  try {
    const existing = window.sessionStorage.getItem(SESSION_KEY);
    if (existing) return existing;
    const id = newId();
    window.sessionStorage.setItem(SESSION_KEY, id);
    return id;
  } catch {
    return newId();
  }
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === "running") return <Loader2 size={14} className="copilot-spin" />;
  if (status === "done") return <CircleCheck size={14} className="ok" />;
  return <CircleX size={14} className={status === "declined" ? "muted" : "bad"} />;
}

function ApprovalCard({
  actions,
  state,
  busy,
  onDecide,
}: {
  actions: ApprovalAction[];
  state: Turn["approvalState"];
  busy: boolean;
  onDecide: (approved: boolean, comment: string) => void;
}) {
  const [comment, setComment] = useState("");
  return (
    <div className={`copilot-approval ${state ?? ""}`}>
      <div className="copilot-approval-head">
        <ShieldCheck size={16} />
        <strong>{state === "pending" ? "Your approval is needed" : state === "approved" ? "Approved" : "Declined"}</strong>
      </div>
      {actions.map((a) => (
        <div className="copilot-action" key={a.id}>
          <strong>{a.title}</strong>
          <dl>
            {Object.entries(a.details).map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{v ?? "-"}</dd>
              </div>
            ))}
          </dl>
          {a.preview && <pre className="copilot-preview">{a.preview}</pre>}
        </div>
      ))}
      {state === "pending" && (
        <>
          <input
            className="copilot-comment"
            placeholder="Optional note (e.g. why you're declining)"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            disabled={busy}
          />
          <div className="copilot-approval-buttons">
            <button className="secondary-button" disabled={busy} onClick={() => onDecide(false, comment)}>
              Decline
            </button>
            <button className="primary-button" disabled={busy} onClick={() => onDecide(true, comment)}>
              Approve
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function BriefingCard() {
  const [briefing, setBriefing] = useState<ManagerBriefing | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await agentApi.get<{ briefing: ManagerBriefing | null }>("/briefing/latest");
      setBriefing(res.briefing);
    } catch {
      /* agent offline: the card offers to generate one */
    }
  }, []);

  useEffect(() => {
    void load();
    const onPush = () => void load();
    window.addEventListener("shiftguard:briefing", onPush);
    return () => window.removeEventListener("shiftguard:briefing", onPush);
  }, [load]);

  const run = async (rescore: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await agentApi.post<{ briefing: ManagerBriefing }>("/briefing/run", { rescore });
      setBriefing(res.briefing);
      setOpen(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="copilot-briefing">
      <button className="copilot-briefing-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Newspaper size={16} />
        <span>
          <strong>Daily briefing</strong>
          {briefing && <small>{new Date(briefing.generated_at).toLocaleString()}</small>}
        </span>
      </button>
      {open && (
        <div className="copilot-briefing-body">
          {briefing ? (
            <>
              <p className="copilot-headline">{briefing.headline}</p>
              <Markdown text={briefing.text} />
            </>
          ) : (
            <p className="copilot-muted">What changed in your team since the last risk scoring, in a few lines.</p>
          )}
          {error && <p className="copilot-error">{error}</p>}
          <div className="copilot-briefing-actions">
            <button className="secondary-button small" disabled={busy} onClick={() => void run(false)}>
              {busy ? <Loader2 size={13} className="copilot-spin" /> : <Sparkles size={13} />}{" "}
              {briefing ? "Refresh" : "Generate briefing"}
            </button>
            <button
              className="secondary-button small"
              disabled={busy}
              onClick={() => void run(true)}
              title="Re-runs the risk model for your team first (saved, like the daily batch)"
            >
              <RefreshCw size={13} /> Rescore team &amp; brief
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * "Ask ShiftGuard AI": the manager copilot. Streams the LangGraph agent's work live (tool steps, then the answer),
 * and pauses for the manager's approval before emails, roster changes, leave decisions and buddy assignments.
 */
export function AgentCopilot() {
  const [open, setOpen] = useState(false);
  const [sessionId, setSessionId] = useState(loadSession);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
  }, [turns]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const updateTurn = (id: string, change: (t: Turn) => Turn) =>
    setTurns((all) => all.map((t) => (t.id === id ? change(t) : t)));

  const apply = (turnId: string) => (event: AgentStreamEvent) => {
    switch (event.type) {
      case "step":
        if (event.status === "start") {
          const step: Step = { id: event.id, label: event.label, status: "running" };
          updateTurn(turnId, (t) => ({ ...t, steps: [...t.steps, step] }));
        } else {
          const status: StepStatus = event.status === "declined" ? "declined" : event.ok ? "done" : "failed";
          updateTurn(turnId, (t) => ({ ...t, steps: t.steps.map((s) => (s.id === event.id ? { ...s, status } : s)) }));
        }
        break;
      case "token":
        updateTurn(turnId, (t) => ({ ...t, text: t.text + event.text }));
        break;
      case "thinking_reset":
        updateTurn(turnId, (t) => ({ ...t, text: "" }));
        break;
      case "approval":
        updateTurn(turnId, (t) => ({ ...t, text: "", approval: event.actions, approvalState: "pending" }));
        break;
      case "message":
        updateTurn(turnId, (t) => ({ ...t, text: event.text }));
        break;
      case "error":
        updateTurn(turnId, (t) => ({ ...t, error: event.message }));
        break;
      case "done":
        updateTurn(turnId, (t) => ({ ...t, streaming: false }));
        break;
    }
  };

  const run = async (body: { query?: string; resume?: { approved: boolean; comment?: string } }) => {
    const turnId = newId();
    setTurns((all) => [...all, { id: turnId, role: "assistant", text: "", steps: [], streaming: true }]);
    setBusy(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await agentStream({ session_id: sessionId, ...body }, apply(turnId), controller.signal);
    } catch (err) {
      if (!controller.signal.aborted) updateTurn(turnId, (t) => ({ ...t, error: errorMessage(err) }));
    } finally {
      updateTurn(turnId, (t) => ({
        ...t,
        streaming: false,
        steps: t.steps.map((s) => (s.status === "running" ? { ...s, status: "failed" } : s)),
      }));
      setBusy(false);
      abortRef.current = null;
    }
  };

  const ask = (text: string) => {
    const query = text.trim();
    if (!query || busy) return;
    setInput("");
    // A new question while an approval is pending: the agent declines it automatically.
    setTurns((all) => [
      ...all.map((t) => (t.approvalState === "pending" ? { ...t, approvalState: "declined" as const } : t)),
      { id: newId(), role: "user", text: query, steps: [] },
    ]);
    void run({ query });
  };

  const decide = (turnId: string, approved: boolean, comment: string) => {
    updateTurn(turnId, (t) => ({ ...t, approvalState: approved ? "approved" : "declined" }));
    void run({ resume: { approved, comment } });
  };

  const newChat = () => {
    abortRef.current?.abort();
    const id = newId();
    try {
      window.sessionStorage.setItem(SESSION_KEY, id);
    } catch {
      /* storage unavailable */
    }
    setSessionId(id);
    setTurns([]);
  };

  return (
    <>
      {!open && (
        <button className="copilot-launcher" onClick={() => setOpen(true)} aria-label="Ask ShiftGuard AI">
          <Sparkles size={18} />
          <span>Ask ShiftGuard AI</span>
        </button>
      )}
      {open && (
        <>
          <button className="panel-backdrop copilot-backdrop" aria-label="Close assistant" onClick={() => setOpen(false)} />
          <aside className="copilot-drawer" role="dialog" aria-label="ShiftGuard AI assistant">
            <header className="copilot-header">
              <div>
                <span className="copilot-kicker">
                  <Sparkles size={13} /> ShiftGuard AI
                </span>
                <strong>Manager copilot</strong>
              </div>
              <div className="copilot-header-actions">
                <button className="ghost-icon" onClick={newChat} title="New conversation" aria-label="New conversation">
                  <MessageSquarePlus size={18} />
                </button>
                <button className="ghost-icon" onClick={() => setOpen(false)} aria-label="Close">
                  <X size={19} />
                </button>
              </div>
            </header>

            <div className="copilot-body" ref={listRef}>
              <BriefingCard />
              {turns.length === 0 && (
                <div className="copilot-suggestions">
                  <p className="copilot-muted">Try asking:</p>
                  {SUGGESTIONS.map((s) => (
                    <button key={s} onClick={() => ask(s)} disabled={busy}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {turns.map((turn) =>
                turn.role === "user" ? (
                  <div className="copilot-msg user" key={turn.id}>
                    {turn.text}
                  </div>
                ) : (
                  <div className="copilot-msg assistant" key={turn.id}>
                    {turn.steps.length > 0 && (
                      <ul className="copilot-steps">
                        {turn.steps.map((s) => (
                          <li key={s.id} className={s.status}>
                            <StepIcon status={s.status} />
                            {s.label}
                            {s.status === "declined" && " (declined)"}
                          </li>
                        ))}
                      </ul>
                    )}
                    {turn.text && <Markdown text={turn.text} />}
                    {turn.streaming && !turn.text && turn.steps.every((s) => s.status !== "running") && (
                      <p className="copilot-muted">
                        <Loader2 size={13} className="copilot-spin" /> Thinking…
                      </p>
                    )}
                    {turn.approval && (
                      <ApprovalCard
                        actions={turn.approval}
                        state={turn.approvalState}
                        busy={busy}
                        onDecide={(approved, comment) => decide(turn.id, approved, comment)}
                      />
                    )}
                    {turn.error && <p className="copilot-error">{turn.error}</p>}
                  </div>
                ),
              )}
            </div>

            <form
              className="copilot-input"
              onSubmit={(e) => {
                e.preventDefault();
                ask(input);
              }}
            >
              <textarea
                rows={2}
                placeholder="Ask about your team, the rota, leave or what-if changes…"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    ask(input);
                  }
                }}
                disabled={busy}
              />
              {busy ? (
                <button type="button" className="copilot-send" onClick={() => abortRef.current?.abort()} aria-label="Stop">
                  <Square size={16} />
                </button>
              ) : (
                <button type="submit" className="copilot-send" disabled={!input.trim()} aria-label="Send">
                  <Send size={16} />
                </button>
              )}
            </form>
            <p className="copilot-footnote">
              Risk bands come from a prototype model on synthetic data, not a clinical assessment. Emails, rota changes
              and leave decisions always wait for your approval.
            </p>
          </aside>
        </>
      )}
    </>
  );
}
