import { useCallback, useEffect, useState } from "react";
import { Bell, CheckCheck, Mail } from "lucide-react";
import { api } from "../api/client";
import type { Inbox, InboxItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import type { PageId } from "../lib/nav";
import { useClickOutside } from "./HeaderMenus";

/** How often the bell checks for new alerts (ms). Short so a manager sees an alert appear during a live demo. */
const POLL_MS = 30_000;

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

  const load = useCallback(async () => {
    try {
      setInbox(await api.get<Inbox>("/interventions/inbox/"));
    } catch {
      /* backend unreachable: keep the last result, try again on the next tick */
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void load();
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => window.clearInterval(id);
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
