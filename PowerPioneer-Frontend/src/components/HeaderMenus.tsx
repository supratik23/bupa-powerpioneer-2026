import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  Bell,
  CalendarDays,
  ChevronDown,
  ClipboardList,
  HeartPulse,
  LogOut,
  MessagesSquare,
  Plane,
  Settings2,
  UserRound,
  UsersRound,
} from "lucide-react";
import { api } from "../api/client";
import type { Intervention } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { avatarColor, formatDateTime, initials, label } from "../lib/format";
import { useEmployees } from "../lib/useEmployees";
import { useSocket } from "../lib/useSocket";
import { InterventionActions, describeIntervention } from "../pages/InterventionsPage";
import type { PageId } from "../lib/nav";

function useClickOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

// ---------------------------------------------------------------------------
// profile chip + menu
// ---------------------------------------------------------------------------
export function ProfileMenu({ page, navigate }: { page: PageId; navigate: (page: PageId) => void }) {
  const { user, isManager, isStaff, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(open, close);
  if (!user) return null;

  const item = (id: PageId, icon: ReactNode, text: string) => (
    <button
      className={page === id ? "active" : ""}
      onClick={() => {
        navigate(id);
        setOpen(false);
      }}
    >
      {icon}
      {text}
    </button>
  );

  return (
    <div className="pp-anchor" ref={ref}>
      <button
        className="profile-chip pp-chip-button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <div className="avatar avatar-blue">{initials(user.full_name)}</div>
        <div>
          <strong>{user.full_name}</strong>
          <span>{user.job_role}</span>
        </div>
        <ChevronDown size={15} />
      </button>
      {open && (
        <div className="pp-menu" role="menu">
          <div className="pp-menu-head">
            <strong>{user.full_name}</strong>
            <span>{user.email}</span>
          </div>
          {item("profile", <UserRound size={16} />, "My profile")}
          {item("wellbeing", <HeartPulse size={16} />, "My wellbeing")}
          {item("roster", <CalendarDays size={16} />, "Full roster")}
          {item("leave", <Plane size={16} />, "Leave requests")}
          {item("interventions", <ClipboardList size={16} />, "Interventions")}
          {item("chat", <MessagesSquare size={16} />, "Team chat")}
          {isManager && (
            <>
              <span className="pp-menu-label">Manage</span>
              {item("team-roster", <UsersRound size={16} />, "Team roster & attendance")}
            </>
          )}
          {isStaff && item("admin", <Settings2 size={16} />, "Administration")}
          <hr />
          <button className="danger" onClick={() => void logout()}>
            <LogOut size={16} />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// notifications bell
// ---------------------------------------------------------------------------
interface LiveNotification {
  id: string;
  kind: "direct_message" | "intervention" | string;
  title: string;
  text: string;
  fromId?: string;
  fromName?: string;
}

type PushFrame = {
  type: "notification";
  kind?: string;
  from?: { employee_id: string; full_name: string };
  preview?: string;
  action_type?: string;
  employee_name?: string;
  risk_band?: string;
};

export function NotificationsMenu({
  navigate,
  openDirectChat,
}: {
  navigate: (page: PageId) => void;
  openDirectChat: (employeeId: string, name: string) => void;
}) {
  const { user } = useAuth();
  const { nameOf } = useEmployees();
  const [open, setOpen] = useState(false);
  const [live, setLive] = useState<LiveNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Intervention[]>([]);
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(open, close);
  const meId = user?.employee_id;

  const load = useCallback(async () => {
    if (!meId) return;
    try {
      const list = await api.list<Intervention>("/interventions/", { target_employee: meId, ordering: "-triggered_at" });
      setItems(list.filter((iv) => iv.action_status === "PENDING" || iv.action_status === "IN_PROGRESS"));
    } catch {
      setItems([]);
    }
  }, [meId]);

  useEffect(() => {
    void load();
  }, [load]);

  useSocket<PushFrame>(meId ? "/ws/notifications/" : null, (frame) => {
    if (frame.type !== "notification") return;
    const id = `${Date.now()}-${Math.random()}`;
    if (frame.kind === "direct_message" && frame.from) {
      setLive((prev) => [
        { id, kind: "direct_message", title: `Message from ${frame.from!.full_name}`, text: frame.preview ?? "", fromId: frame.from!.employee_id, fromName: frame.from!.full_name },
        ...prev,
      ].slice(0, 20));
    } else {
      setLive((prev) => [
        { id, kind: frame.kind ?? "intervention", title: frame.action_type ? label(String(frame.action_type)) : "New support action", text: frame.employee_name
            ? `${frame.employee_name}'s wellbeing is ${label(frame.risk_band ?? "").toLowerCase()} risk. A follow-up was assigned to you.`
            : "A new wellbeing follow-up was assigned to you." },
        ...prev,
      ].slice(0, 20));
      void load();
    }
    setUnread((n) => n + 1);
  });

  const toggle = () => {
    if (!open) {
      setUnread(0);
      void load();
    }
    setOpen(!open);
  };

  const hasDot = unread > 0 || items.length > 0;

  return (
    <div className="pp-anchor" ref={ref}>
      <button className="icon-button notification-button" aria-label="Notifications" aria-expanded={open} onClick={toggle}>
        <Bell size={19} />
        {hasDot && <span />}
      </button>
      {open && (
        <div className="pp-menu pp-notifications" role="dialog" aria-label="Notifications">
          <div className="pp-menu-head">
            <strong>Notifications</strong>
            <span>{items.length} open action(s) assigned to you</span>
          </div>
          {live.map((n) => (
            <div key={n.id} className="pp-note-item live">
              <strong>{n.title}</strong>
              <p>{n.text}</p>
              {n.kind === "direct_message" && n.fromId && (
                <div className="pp-inline-actions">
                  <button
                    onClick={() => {
                      openDirectChat(n.fromId!, n.fromName ?? "Direct message");
                      setOpen(false);
                    }}
                  >
                    Reply
                  </button>
                </div>
              )}
            </div>
          ))}
          {items.map((iv) => (
            <div key={iv.intervention_id} className="pp-note-item">
              <div className="member-identity" style={{ marginBottom: 4 }}>
                <div className="avatar" style={{ background: avatarColor(iv.employee_id), width: 28, height: 28 }}>
                  {initials(nameOf(iv.employee_id))}
                </div>
                <div>
                  <strong>{label(iv.action_type)}</strong>
                  <span>{formatDateTime(iv.triggered_at)}</span>
                </div>
              </div>
              <p>{describeIntervention(iv, nameOf)}</p>
              <InterventionActions iv={iv} compact onChanged={() => void load()} />
            </div>
          ))}
          {live.length === 0 && items.length === 0 && <div className="pp-state">You’re all caught up.</div>}
          <hr />
          <button
            onClick={() => {
              navigate("interventions");
              setOpen(false);
            }}
          >
            <ClipboardList size={16} /> View all interventions
          </button>
        </div>
      )}
    </div>
  );
}

