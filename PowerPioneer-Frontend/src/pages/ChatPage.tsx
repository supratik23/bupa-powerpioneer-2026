import { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Hash, Send } from "lucide-react";
import { api } from "../api/client";
import type { Employee, EmployeeBrief } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { avatarColor, formatTime, initials } from "../lib/format";
import { useAsync } from "../lib/useAsync";
import { useEmployees } from "../lib/useEmployees";
import { useSocket } from "../lib/useSocket";
import { ErrorNote, PageHeader, Panel, TextField } from "../components/ui";

interface Sender {
  employee_id: string;
  full_name: string;
  email: string;
}

type Frame =
  | { type: "message"; room: string; message: string; sender: Sender; timestamp: string }
  | { type: "join" | "leave" | "typing"; room: string; sender: Sender }
  | { type: "error"; error: string };

type Line =
  | { kind: "message"; id: string; text: string; sender: Sender; at: string }
  | { kind: "system"; id: string; text: string };

export type Conversation = { kind: "room"; id: string; title: string } | { kind: "direct"; id: string; title: string };

interface Contact {
  employee_id: string;
  full_name: string;
  relation: string;
}

function useContacts(): Contact[] {
  const { user, isStaff } = useAuth();
  const { employees } = useEmployees();
  const meId = user?.employee_id ?? "";
  const team = useAsync(() => (meId ? api.get<Employee[]>(`/employees/${meId}/team/`) : Promise.resolve([])), [meId]);
  const buddies = useAsync(
    () => (meId ? api.get<Employee[]>(`/employees/${meId}/buddy-assignees/`) : Promise.resolve([])),
    [meId],
  );

  return useMemo(() => {
    const map = new Map<string, Contact>();
    const add = (p: EmployeeBrief | Employee | null | undefined, relation: string) => {
      if (p && p.employee_id !== meId && !map.has(p.employee_id)) {
        map.set(p.employee_id, { employee_id: p.employee_id, full_name: p.full_name, relation });
      }
    };
    add(user?.manager, "Your manager");
    add(user?.buddy, "Your buddy");
    (team.data ?? []).forEach((p) => add(p, "Direct report"));
    (buddies.data ?? []).forEach((p) => add(p, "You buddy them"));
    if (isStaff) employees.filter((e) => e.is_active).forEach((p) => add(p, p.job_role));
    return [...map.values()];
  }, [user, meId, team.data, buddies.data, isStaff, employees]);
}

function ChatWindow({ conversation }: { conversation: Conversation }) {
  const { user } = useAuth();
  const [lines, setLines] = useState<Line[]>([]);
  const [typing, setTyping] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const typingTimer = useRef<number>();
  const lastTypingSent = useRef(0);
  const meId = user?.employee_id;

  const path =
    conversation.kind === "room" ? `/ws/chat/${conversation.id}/` : `/ws/chat/direct/${conversation.id}/`;

  const { status, closeReason, send } = useSocket<Frame>(path, (frame) => {
    if (frame.type === "message") {
      setTyping(null);
      setLines((prev) => [
        ...prev,
        { kind: "message", id: `${frame.timestamp}-${prev.length}`, text: frame.message, sender: frame.sender, at: frame.timestamp },
      ]);
    } else if (frame.type === "join" || frame.type === "leave") {
      if (frame.sender.employee_id === meId) return;
      setLines((prev) => [
        ...prev,
        { kind: "system", id: `${frame.type}-${Date.now()}-${prev.length}`, text: `${frame.sender.full_name} ${frame.type === "join" ? "joined" : "left"}` },
      ]);
    } else if (frame.type === "typing") {
      setTyping(`${frame.sender.full_name} is typing…`);
      window.clearTimeout(typingTimer.current);
      typingTimer.current = window.setTimeout(() => setTyping(null), 2500);
    } else if (frame.type === "error") {
      setError(frame.error);
    }
  });

  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight });
  }, [lines]);

  useEffect(() => () => window.clearTimeout(typingTimer.current), []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    if (send({ type: "message", message: text })) {
      setDraft("");
      setError(null);
    } else {
      setError("Not connected yet. Please wait a moment.");
    }
  };

  const onDraft = (value: string) => {
    setDraft(value);
    if (Date.now() - lastTypingSent.current > 2000) {
      lastTypingSent.current = Date.now();
      send({ type: "typing" });
    }
  };

  const statusText =
    status === "open" ? "Connected" : status === "connecting" ? "Connecting…" : status === "denied" ? "Unavailable" : "Reconnecting…";

  return (
    <Panel
      className="pp-chat-window"
      kicker={conversation.kind === "room" ? "Group room" : "Direct message"}
      title={conversation.title}
      actions={
        <span className={`pp-chat-status ${status === "open" ? "online" : ""}`}>
          <i /> {statusText}
        </span>
      }
    >
      <ErrorNote message={status === "denied" ? closeReason : error} />
      <div className="pp-chat-messages" ref={listRef}>
        {lines.length === 0 && (
          <div className="pp-system-line">Messages are live and not stored. Say hello 👋</div>
        )}
        {lines.map((line) =>
          line.kind === "system" ? (
            <div key={line.id} className="pp-system-line">{line.text}</div>
          ) : (
            <div key={line.id} className={`pp-bubble ${line.sender.employee_id === meId ? "mine" : ""}`}>
              <small>
                {line.sender.employee_id === meId ? "You" : line.sender.full_name} · {formatTime(line.at)}
              </small>
              {line.text}
            </div>
          ),
        )}
        {typing && <div className="pp-system-line">{typing}</div>}
      </div>
      <form className="pp-chat-compose" onSubmit={submit}>
        <input
          value={draft}
          maxLength={2000}
          placeholder={status === "open" ? "Write a message…" : "Waiting for connection…"}
          disabled={status === "denied"}
          onChange={(e) => onDraft(e.target.value)}
          aria-label="Message"
        />
        <button className="primary-button" type="submit" disabled={status !== "open" || !draft.trim()}>
          <Send size={16} /> Send
        </button>
      </form>
    </Panel>
  );
}

export default function ChatPage({ initial }: { initial?: Conversation | null }) {
  const contacts = useContacts();
  const [rooms, setRooms] = useState<string[]>(["general", "ward-team"]);
  const [newRoom, setNewRoom] = useState("");
  const [active, setActive] = useState<Conversation>(
    initial ?? { kind: "room", id: "general", title: "# general" },
  );

  const addRoom = (e: FormEvent) => {
    e.preventDefault();
    const name = newRoom.trim().replace(/\s+/g, "-").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 50);
    if (!name) return;
    if (!rooms.includes(name)) setRooms([...rooms, name]);
    setActive({ kind: "room", id: name, title: `# ${name}` });
    setNewRoom("");
  };

  return (
    <main className="page-shell">
      <PageHeader
        kicker="Stay connected"
        title="Team chat"
        description="Live chat with your team, your manager and your buddy. Messages are not stored."
      />
      <div className="pp-chat">
        <Panel kicker="Conversations" title="Rooms">
          <div className="pp-chat-list">
            {rooms.map((room) => (
              <button
                key={room}
                className={active.kind === "room" && active.id === room ? "active" : ""}
                onClick={() => setActive({ kind: "room", id: room, title: `# ${room}` })}
              >
                <span className="metric-icon blue" style={{ width: 32, height: 32 }}>
                  <Hash size={15} />
                </span>
                <div className="member-identity">
                  <div>
                    <strong>{room}</strong>
                    <span>Group room</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
          <form className="pp-form" onSubmit={addRoom} style={{ marginTop: 10 }}>
            <TextField full label="Join or create a room" value={newRoom} onChange={setNewRoom} placeholder="e.g. icu-nights" />
          </form>

          <span className="pp-menu-label" style={{ paddingLeft: 0, marginTop: 14 }}>Direct messages</span>
          <div className="pp-chat-list">
            {contacts.length === 0 && <p className="pp-muted">No manager, buddy or reports linked to you yet.</p>}
            {contacts.map((c) => (
              <button
                key={c.employee_id}
                className={active.kind === "direct" && active.id === c.employee_id ? "active" : ""}
                onClick={() => setActive({ kind: "direct", id: c.employee_id, title: c.full_name })}
              >
                <div className="member-identity">
                  <div className="avatar" style={{ background: avatarColor(c.employee_id) }}>{initials(c.full_name)}</div>
                  <div>
                    <strong>{c.full_name}</strong>
                    <span>{c.relation}</span>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </Panel>
        <ChatWindow key={`${active.kind}-${active.id}`} conversation={active} />
      </div>
    </main>
  );
}
