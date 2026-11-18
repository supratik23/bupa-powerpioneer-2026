import { useEffect } from "react";
import { ArrowRight, CalendarDays, Check, Coffee, HeartPulse, Stethoscope, UsersRound, X } from "lucide-react";

/** One entry on the presentational day schedule (static UI data, not from the API). */
export interface TimelineItem {
  time: string;
  duration: string;
  title: string;
  detail: string;
  kind: string;
  done?: boolean;
  active?: boolean;
}

type Category = "care" | "break" | "handover" | "admin";

const CATEGORY: Record<string, Category> = {
  care: "care",
  review: "care",
  break: "break",
  handover: "handover",
  notes: "admin",
};

const LEGEND: Array<{ id: Category; label: string }> = [
  { id: "care", label: "Care" },
  { id: "break", label: "Break" },
  { id: "handover", label: "Handover" },
  { id: "admin", label: "Admin" },
];

const PERIODS = [
  { id: "Morning", from: 0, to: 13 * 60 },
  { id: "Afternoon", from: 13 * 60, to: 17 * 60 },
  { id: "Evening", from: 17 * 60, to: 24 * 60 },
];

const toMinutes = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};
const durationOf = (item: TimelineItem) => parseInt(item.duration, 10) || 0;
const endOf = (item: TimelineItem) => toMinutes(item.time) + durationOf(item);
const clock = (mins: number) =>
  `${String(Math.floor(mins / 60) % 24).padStart(2, "0")}:${String(mins % 60).padStart(2, "0")}`;
const hoursLabel = (mins: number) => `${Math.floor(mins / 60)}h${mins % 60 ? ` ${mins % 60}m` : ""}`;

function KindIcon({ kind, size }: { kind: string; size: number }) {
  if (kind === "break") return <Coffee size={size} />;
  if (kind === "handover") return <UsersRound size={size} />;
  if (kind === "notes") return <CalendarDays size={size} />;
  return <Stethoscope size={size} />;
}

export function DayTimelineDrawer({
  open,
  items,
  ward,
  onClose,
  onOpenRoster,
}: {
  open: boolean;
  items: TimelineItem[];
  ward: string;
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

  const sorted = [...items].sort((a, b) => toMinutes(a.time) - toMinutes(b.time));
  const appointments = sorted.filter((i) => CATEGORY[i.kind] === "care").length;
  const breaks = sorted.filter((i) => i.kind === "break").length;
  const shiftLength = sorted.length ? endOf(sorted[sorted.length - 1]) - toMinutes(sorted[0].time) : 0;

  const current = sorted.find((i) => i.active);
  const nextBreak = current && sorted.find((i) => i.kind === "break" && toMinutes(i.time) >= endOf(current));
  const breakGap = current && nextBreak ? toMinutes(nextBreak.time) - endOf(current) : null;

  const groups = PERIODS.map((p) => {
    const list = sorted.filter((i) => toMinutes(i.time) >= p.from && toMinutes(i.time) < p.to);
    return {
      ...p,
      list,
      range: list.length ? `${list[0].time}–${clock(endOf(list[list.length - 1]))}` : "",
    };
  }).filter((g) => g.list.length > 0);

  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });

  return (
    <>
      <button className="drawer-backdrop" aria-label="Close full day roster" onClick={onClose} />
      <aside className="member-drawer tl-drawer" role="dialog" aria-label="Full day roster">
        <div className="tl-head">
          <div>
            <span className="section-kicker">{today}</span>
            <h2>Full day roster</h2>
            <p>Your complete shift at a glance · {ward}</p>
          </div>
          <button className="ghost-icon" aria-label="Close" onClick={onClose}>
            <X size={20} />
          </button>
        </div>

        <div className="tl-stats">
          <div>
            <span>Appointments</span>
            <strong>{appointments}</strong>
          </div>
          <div>
            <span>Protected breaks</span>
            <strong>{breaks}</strong>
          </div>
          <div>
            <span>Shift length</span>
            <strong>{hoursLabel(shiftLength)}</strong>
          </div>
        </div>

        {current && (
          <div className="tl-now">
            <div className="tl-now-icon">
              <HeartPulse size={20} />
            </div>
            <div>
              <span>
                Happening now · {current.time}–{clock(endOf(current))}
              </span>
              <strong>{current.title}</strong>
              {breakGap !== null && (
                <small>
                  {breakGap === 0 ? "Protected break starts straight after" : `Protected break begins in ${breakGap} minutes`}
                </small>
              )}
            </div>
          </div>
        )}

        <div className="tl-legend">
          {LEGEND.map((l) => (
            <span key={l.id}>
              <i className={`tl-dot ${l.id}`} />
              {l.label}
            </span>
          ))}
        </div>

        {groups.map((g) => (
          <section className="tl-group" key={g.id}>
            <div className="tl-group-head">
              <h3>
                {g.id} <small>{g.range}</small>
              </h3>
              <span>
                {g.list.length} {g.list.length === 1 ? "activity" : "activities"}
              </span>
            </div>
            <ol className="tl-list">
              {g.list.map((item) => {
                const cat = CATEGORY[item.kind] ?? "care";
                return (
                  <li
                    key={`${item.time}-${item.title}`}
                    className={`tl-item ${item.active ? "active" : ""} ${item.done ? "done" : ""}`}
                  >
                    <div className="tl-time">
                      <strong>{item.time}</strong>
                      <span>{item.duration}</span>
                    </div>
                    <div className={`tl-node ${cat}`}>
                      {item.done ? <Check size={14} strokeWidth={3} /> : <KindIcon kind={item.kind} size={15} />}
                    </div>
                    <div className="tl-copy">
                      <div>
                        <strong>{item.title}</strong>
                        {item.active && <span className="live-pill">Now</span>}
                      </div>
                      <span>{item.detail}</span>
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
