import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bell, CheckCheck, Mail, X } from "lucide-react";
import { api, getFreshAccessToken } from "../api/client";
import { wsUrl } from "../api/config";
import type { Inbox, InboxItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import type { PageId } from "../lib/nav";
import { useClickOutside } from "./HeaderMenus";

/** How often the bell checks for new alerts (ms). Short so a manager sees an alert appear during a live demo. */
const POLL_MS = 30_000;
/** How long the in-app toast for a new notification stays on screen (ms). */
const TOAST_MS = 5_000;

function timeAgo(iso: string): string {
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60_000));
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  return days === 1 ? "yesterday" : `${days} days ago`;
}

/** Deliberately brief: who it is about and that an email was sent. The details stay in the email. */
function noteText(item: InboxItem): string {
  if (item.email_status === "failed") return `We couldn't email you about ${item.employee_first_name}. Please check in with them.`;
  if (item.email_status === "sending") return `An email about ${item.employee_first_name} is on its way to you.`;
  return `We've sent you an email about ${item.employee_first_name}. Please check your inbox.`;
}

/**
 * Bell next to the theme button. Shows the alerts the AI agent sent to me as a manager or buddy
 * (the same ones it emails), so they are visible in the app too. Buddies never see risk levels.
 */
export function NotificationBell({ navigate }: { navigate: (page: PageId) => void }) {
  const { user } = useAuth();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(open, close);

  const [toast, setToast] = useState<InboxItem | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  // Unread alerts already known (employee + latest alert time). null until the first load, so alerts
  // that were already waiting at login don't pop a toast - only ones that arrive while the app is open.
  const known = useRef<Set<string> | null>(null);

  const showToast = useCallback((item: InboxItem) => {
    window.clearTimeout(toastTimer.current);
    setToast(item);
    toastTimer.current = window.setTimeout(() => setToast(null), TOAST_MS);
  }, []);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  const load = useCallback(async () => {
    try {
      const next = await api.get<Inbox>("/interventions/inbox/");
      setInbox(next);
      const unreadItems = next.items.filter((i) => i.unread);
      const keys = unreadItems.map((i) => `${i.employee_id}:${i.latest_at}`);
      if (known.current) {
        const fresh = unreadItems.find((_, idx) => !known.current!.has(keys[idx]));
        if (fresh) showToast(fresh);
      } else {
        known.current = new Set();
      }
      keys.forEach((k) => known.current!.add(k));
    } catch {
      /* backend unreachable: keep the last result, try again on the next tick */
    }
  }, [showToast]);

  useEffect(() => {
    if (!user) return;
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [user, load]);

  // Real-time push (ws/notifications/): Django and the AI agent notify here the moment they act.
  // Polling above stays as the fallback when the socket is down.
  useEffect(() => {
    if (!user) return;
    let socket: WebSocket | null = null;
    let retry: number | undefined;
    let attempts = 0;
    let stopped = false;

    const connect = async () => {
      const token = await getFreshAccessToken();
      if (stopped || !token) return;
      socket = new WebSocket(wsUrl(`/ws/notifications/?token=${encodeURIComponent(token)}`));
      socket.onopen = () => {
        attempts = 0;
      };
      socket.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data as string) as { type?: string; kind?: string };
          if (data.type !== "notification") return;
          if (data.kind === "briefing") window.dispatchEvent(new Event("shiftguard:briefing"));
          void load();
        } catch {
          /* ignore malformed frames */
        }
      };
      socket.onclose = () => {
        if (stopped) return;
        attempts += 1;
        retry = window.setTimeout(() => void connect(), Math.min(30_000, 2_000 * attempts));
      };
    };
    void connect();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, [user, load]);

  const acknowledge = async (employeeId?: string) => {
    try {
      await api.post("/interventions/inbox/acknowledge/", employeeId ? { employee_id: employeeId } : {});
    } finally {
      await load();
    }
  };

  if (!user) return null;
  const unread = inbox?.unread_count ?? 0;
  const items = inbox?.items ?? [];
  const firstRead = items.findIndex((i) => !i.unread);

  return (
    <div className="pp-anchor" ref={ref}>
      {toast && createPortal(
        <div
          className="notif-toast"
          role="status"
          aria-live="polite"
          onClick={() => {
            setToast(null);
            void load();
            setOpen(true);
          }}
        >
          <span className="notif-toast-icon">
            <Bell size={20} fill="currentColor" />
          </span>
          <span className="notif-toast-text">
            <strong>New notification · {toast.employee_name}</strong>
            <span>{noteText(toast)}</span>
          </span>
          <button
            className="notif-toast-close"
            aria-label="Dismiss notification"
            onClick={(e) => {
              e.stopPropagation();
              window.clearTimeout(toastTimer.current);
              setToast(null);
            }}
          >
            <X size={16} />
          </button>
          <span key={`${toast.employee_id}:${toast.latest_at}`} className="notif-toast-timer" style={{ animationDuration: `${TOAST_MS}ms` }} />
        </div>,
        document.body,
      )}
      <button
        className="icon-button notif-bell"
        aria-label={unread ? `Notifications: ${unread} new` : "Notifications"}
        title="Notifications"
        aria-expanded={open}
        onClick={() => {
          if (!open) void load();
          setOpen(!open);
        }}
      >
        <Bell size={18} />
        {unread > 0 && <span className="notif-count">{unread > 9 ? "9+" : unread}</span>}
      </button>

      {open && (
        <div className="pp-menu pp-notifications" role="dialog" aria-label="Notifications">
          <div className="pp-menu-head notif-head">
            <div>
              <strong>Notifications</strong>
              <span>
                {unread
                  ? `${unread} new ${unread === 1 ? "email" : "emails"} about your colleagues`
                  : "You're all caught up"}
              </span>
            </div>
            {unread > 0 && (
              <button className="notif-link" onClick={() => void acknowledge()}>
                <CheckCheck size={13} /> Mark all as seen
              </button>
            )}
          </div>

          {items.length === 0 && (
            <p className="notif-empty">
              When a colleague you manage or buddy could use some support, you'll see it here.
            </p>
          )}

          {items.map((item, index) => (
              <div key={item.employee_id}>
                {index === firstRead && <span className="pp-menu-label">Earlier</span>}
                <div className={`pp-note-item notif-item ${item.unread ? "live" : "seen"}`}>
                  <div className="notif-title">
                    <span className={`notif-icon ${item.role}`}>
                      <Mail size={15} />
                    </span>
                    <strong>{item.employee_name}</strong>
                  </div>
                  <p>{noteText(item)}</p>
                  <div className="notif-foot">
                    <span>
                      {timeAgo(item.latest_at)}
                      {item.alert_count > 1 && ` · ${item.alert_count} alerts`}
                    </span>
                    {item.unread && (
                      <div className="pp-inline-actions">
                        {item.role === "manager" && (
                          <button
                            onClick={() => {
                              void acknowledge(item.employee_id);
                              setOpen(false);
                              navigate("manager");
                            }}
                          >
                            Open team view
                          </button>
                        )}
                        <button className="primary" onClick={() => void acknowledge(item.employee_id)}>
                          Got it
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
          ))}
        </div>
      )}
    </div>
  );
}
