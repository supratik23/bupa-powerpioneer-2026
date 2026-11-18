import { useEffect } from "react";
import { ArrowRight, CalendarDays, Check, Moon, PhoneCall, Sun, Sunrise, X } from "lucide-react";
import type { Shift } from "../api/types";
import { formatHours } from "../lib/format";
import {
  SHIFT_KIND_LABEL,
  dayLabel,
  shiftFlags,
  shiftHours,
  shiftKind,
  shiftRange,
  shiftState,
  shiftTitle,
  startOfDay,
  untilLabel,
} from "../lib/shifts";
import type { ShiftKind } from "../lib/shifts";

const KIND_ORDER: ShiftKind[] = ["day", "long", "night", "oncall"];

function KindIcon({ kind, size }: { kind: ShiftKind; size: number }) {
  if (kind === "night") return <Moon size={size} />;
  if (kind === "oncall") return <PhoneCall size={size} />;
  if (kind === "long") return <Sunrise size={size} />;
  return <Sun size={size} />;
}

/** "Full roster" drawer: the logged-in user's shifts for the next 7 days, from /shifts/. */
export function RosterTimelineDrawer({
  open,
  shifts,
  loading,
  error,
  onClose,
  onOpenRoster,
}: {
  open: boolean;
  shifts: Shift[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onOpenRoster: () => void;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const now = new Date();
  const from = startOfDay(now);
  const to = new Date(from.getTime() + 7 * 86400000);
  const week = shifts
    .filter((s) => new Date(s.shift_end) > from && new Date(s.shift_start) < to)
    .sort((a, b) => +new Date(a.shift_start) - +new Date(b.shift_start));

  const plannedHours = week.reduce((sum, s) => sum + Number(s.planned_hours || 0), 0);
  const nights = week.filter((s) => s.shift_type === "NIGHT").length;
  const current = week.find((s) => shiftState(s, now) === "active");
  const next = week.find((s) => shiftState(s, now) === "upcoming");

  const days = new Map<string, Shift[]>();
  week.forEach((s) => {
    const key = startOfDay(new Date(s.shift_start)).toISOString();
    days.set(key, [...(days.get(key) ?? []), s]);
  });

  const location = (current ?? next ?? week[0])?.location;

  return (
    <>
      <button className="drawer-backdrop" aria-label="Close roster" onClick={onClose} />
      <aside className="member-drawer tl-drawer" role="dialog" aria-label="Your roster this week">
        <div className="tl-head">
          <div>
            <span className="section-kicker">Next 7 days</span>
            <h2>Your roster</h2>
            <p>Your shifts at a glance{location ? ` · ${location}` : ""}</p>
          </div>
          <button className="ghost-icon" aria-label="Close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="tl-stats">
          <div>
            <span>Shifts</span>
            <strong>{loading ? "…" : week.length}</strong>
          </div>
          <div>
            <span>Planned hours</span>
            <strong>{loading ? "…" : formatHours(plannedHours)}</strong>
          </div>
          <div>
            <span>Night shifts</span>
            <strong>{loading ? "…" : nights}</strong>
          </div>
        </div>

        {(current || next) && (
          <div className="tl-now">
            <div className="tl-now-icon">
              <KindIcon kind={shiftKind((current ?? next)!.shift_type)} size={20} />
            </div>
            <div>
              <span>
                {current ? "On shift now" : "Next shift"} · {shiftRange((current ?? next)!)}
              </span>
              <strong>
                {shiftTitle((current ?? next)!)}
                {(current ?? next)!.location ? ` · ${(current ?? next)!.location}` : ""}
              </strong>
              <small>
                {current ? `Ends in ${untilLabel(current.shift_end, now)}` : `Starts in ${untilLabel(next!.shift_start, now)}`}
              </small>
            </div>
          </div>
        )}

        <div className="tl-legend">
          {KIND_ORDER.map((k) => (
            <span key={k}>
              <i className={`tl-dot ${k}`} />
              {SHIFT_KIND_LABEL[k]}
            </span>
          ))}
        </div>

        {error && <p className="pp-muted">Could not load your roster: {error}</p>}
        {!loading && !error && week.length === 0 && (
          <p className="pp-muted">No shifts rostered in the next 7 days.</p>
        )}

        {[...days.entries()].map(([key, list]) => (
          <section className="tl-group" key={key}>
            <div className="tl-group-head">
              <h3>
                {dayLabel(key, now)}{" "}
                <small>{new Date(key).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}</small>
              </h3>
              <span>
                {list.length} {list.length === 1 ? "shift" : "shifts"}
              </span>
            </div>
            <ol className="tl-list">
              {list.map((shift) => {
                const state = shiftState(shift, now);
                const kind = shiftKind(shift.shift_type);
                const load = shift.actual_patient_load ?? shift.expected_patient_load;
                return (
                  <li key={shift.shift_id} className={`tl-item ${state}`}>
                    <div className="tl-time">
                      <strong>{shiftRange(shift).split("–")[0]}</strong>
                      <span>{shiftHours(shift)}</span>
                    </div>
                    <div className={`tl-node ${kind}`}>
                      {state === "done" ? <Check size={14} strokeWidth={3} /> : <KindIcon kind={kind} size={15} />}
                    </div>
                    <div className="tl-copy">
                      <div>
                        <strong>{shiftTitle(shift)}</strong>
                        {state === "active" && <span className="live-pill">Now</span>}
                      </div>
                      <span>
                        {shiftRange(shift)}
                        {shift.location ? ` · ${shift.location}` : ""}
                        {load != null ? ` · ${Number(load)} patients` : ""}
                      </span>
                      {shiftFlags(shift).length > 0 && (
                        <div className="tl-tags">
                          {shiftFlags(shift).map((f) => (
                            <em key={f.id} className={`shift-tag ${f.id}`}>
                              {f.text}
                            </em>
                          ))}
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        ))}

        <button className="secondary-button tl-footer" onClick={onOpenRoster}>
          <CalendarDays size={16} />
          Open roster &amp; shift history
          <ArrowRight size={15} />
        </button>
      </aside>
    </>
  );
}
