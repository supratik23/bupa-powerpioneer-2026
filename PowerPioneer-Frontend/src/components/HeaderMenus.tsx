import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import {
  CalendarDays,
  ChevronDown,
  HeartPulse,
  LogOut,
  Plane,
  Settings2,
  UserRound,
  UsersRound,
} from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { initials } from "../lib/format";
import type { PageId } from "../lib/nav";

export function useClickOutside(open: boolean, close: () => void) {
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
