import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

/** One chip on the calendar. `row` is the underlying record, handed back to renderDetail. */
export interface CalendarItem<T> {
  id: string;
  day: Date;
  /** Short chip text, e.g. "08:00 Day" or "Casey · Late". */
  chip: string;
  /** Colour class: day | long | night | oncall | present | late | absent | leave */
  tone: string;
  /** Small red dot on the chip (e.g. understaffed shift). */
  alert?: boolean;
  /** Team calendar only: whose row the item sits on, and the compact cell text. */
  personId?: string;
  short?: string;
  row: T;
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const MAX_CHIPS = 3;

const startOfDay = (d: Date) => {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
};
const sameDay = (a: Date, b: Date) => startOfDay(a).getTime() === startOfDay(b).getTime();

/** First and last day shown for a month (whole weeks, Monday start). */
export function monthGrid(month: Date): { start: Date; end: Date } {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = new Date(first);
  start.setDate(first.getDate() - ((first.getDay() + 6) % 7));
  const last = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  const end = new Date(last);
  end.setDate(last.getDate() + (6 - ((last.getDay() + 6) % 7)));
  return { start, end };
}

export function RosterCalendar<T>({
  month,
  onMonthChange,
  items,
  renderDetail,
  emptyDay = "Nothing on this day.",
  legend,
}: {
  month: Date;
  onMonthChange: (month: Date) => void;
  items: CalendarItem<T>[];
  renderDetail: (row: T) => ReactNode;
  emptyDay?: string;
  legend: Array<{ tone: string; label: string }>;
}) {
  const [selected, setSelected] = useState<Date | null>(null);
  const { start, end } = monthGrid(month);
  const today = startOfDay(new Date());

  // At most 42 cells; step by calendar date (not +24h) so DST changes can't skip a day.
  const days: Date[] = [];
  for (let d = new Date(start); d <= end; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) days.push(d);

  const byDay = useMemo(() => {
    const map = new Map<number, CalendarItem<T>[]>();
    items.forEach((it) => {
      const key = +startOfDay(it.day);
      map.set(key, [...(map.get(key) ?? []), it]);
    });
    return map;
  }, [items]);

  const shift = (delta: number) => {
    setSelected(null);
    onMonthChange(new Date(month.getFullYear(), month.getMonth() + delta, 1));
  };

  const selectedItems = selected ? byDay.get(+startOfDay(selected)) ?? [] : [];

  return (
    <div className="rc">
      <div className="rc-toolbar">
        <button className="ghost-icon" aria-label="Previous month" onClick={() => shift(-1)}>
          <ChevronLeft size={20} />
        </button>
        <strong>{month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</strong>
        <button className="ghost-icon" aria-label="Next month" onClick={() => shift(1)}>
          <ChevronRight size={20} />
        </button>
        <button
          className="secondary-button small"
          onClick={() => {
            setSelected(today);
            onMonthChange(new Date(today.getFullYear(), today.getMonth(), 1));
          }}
        >
          Today
        </button>
        <div className="rc-legend">
          {legend.map((l) => (
            <span key={l.tone}>
              <i className={`rc-dot ${l.tone}`} />
              {l.label}
            </span>
          ))}
        </div>
      </div>

      <div className="rc-scroll">
        <div className="rc-grid" role="grid" aria-label={month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}>
          {WEEKDAYS.map((w) => (
            <div key={w} className="rc-weekday" role="columnheader">
              {w}
            </div>
          ))}
          {days.map((d) => {
            const list = byDay.get(+d) ?? [];
            const outside = d.getMonth() !== month.getMonth();
            const isToday = +d === +today;
            const isSelected = selected !== null && sameDay(d, selected);
            const weekend = d.getDay() === 0 || d.getDay() === 6;
            return (
              <button
                key={+d}
                role="gridcell"
                className={`rc-day ${outside ? "outside" : ""} ${isToday ? "today" : ""} ${isSelected ? "selected" : ""} ${weekend ? "weekend" : ""}`}
                onClick={() => setSelected(isSelected ? null : d)}
                aria-label={`${d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}: ${list.length} item${list.length === 1 ? "" : "s"}`}
                aria-pressed={isSelected}
              >
                <span className="rc-date">{d.getDate()}</span>
                <span className="rc-chips">
                  {list.slice(0, MAX_CHIPS).map((it) => (
                    <span key={it.id} className={`rc-chip ${it.tone}`}>
                      {it.alert && <i className="rc-alert" aria-label="flagged" />}
                      {it.chip}
                    </span>
                  ))}
                  {list.length > MAX_CHIPS && <span className="rc-more">+{list.length - MAX_CHIPS} more</span>}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {selected && (
        <div className="rc-detail" aria-live="polite">
          <div className="rc-detail-head">
            <strong>{selected.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}</strong>
            <span>
              {selectedItems.length} item{selectedItems.length === 1 ? "" : "s"}
            </span>
          </div>
          {selectedItems.length === 0 ? (
            <p className="pp-muted">{emptyDay}</p>
          ) : (
            <ul>
              {selectedItems.map((it) => (
                <li key={it.id} className={`rc-detail-item ${it.tone}`}>
                  {renderDetail(it.row)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Team calendar: one row per person (names on the left), one column per day.
// ---------------------------------------------------------------------------
export function TeamCalendar<T>({
  month,
  onMonthChange,
  people,
  items,
  renderDetail,
  legend,
  emptyDay = "Nothing recorded for this person on this day.",
}: {
  month: Date;
  onMonthChange: (month: Date) => void;
  people: Array<{ id: string; name: string; role?: string | null }>;
  items: CalendarItem<T>[];
  renderDetail: (row: T) => ReactNode;
  legend: Array<{ tone: string; label: string }>;
  emptyDay?: string;
}) {
  const [selected, setSelected] = useState<{ personId: string; day: Date } | null>(null);
  const today = startOfDay(new Date());
  const days: Date[] = [];
  for (
    let d = new Date(month.getFullYear(), month.getMonth(), 1);
    d.getMonth() === month.getMonth();
    d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)
  ) {
    days.push(d);
  }

  const cells = useMemo(() => {
    const map = new Map<string, CalendarItem<T>[]>();
    items.forEach((it) => {
      const key = `${it.personId}|${+startOfDay(it.day)}`;
      map.set(key, [...(map.get(key) ?? []), it]);
    });
    return map;
  }, [items]);

  const shift = (delta: number) => {
    setSelected(null);
    onMonthChange(new Date(month.getFullYear(), month.getMonth() + delta, 1));
  };

  const selectedItems = selected ? cells.get(`${selected.personId}|${+selected.day}`) ?? [] : [];
  const selectedName = selected ? people.find((p) => p.id === selected.personId)?.name ?? "" : "";
  const dayClass = (d: Date) =>
    `${+d === +today ? "today" : ""} ${d.getDay() === 0 || d.getDay() === 6 ? "weekend" : ""}`;

  return (
    <div className="rc">
      <div className="rc-toolbar">
        <button className="ghost-icon" aria-label="Previous month" onClick={() => shift(-1)}>
          <ChevronLeft size={20} />
        </button>
        <strong>{month.toLocaleDateString("en-GB", { month: "long", year: "numeric" })}</strong>
        <button className="ghost-icon" aria-label="Next month" onClick={() => shift(1)}>
          <ChevronRight size={20} />
        </button>
        <button
          className="secondary-button small"
          onClick={() => {
            setSelected(null);
            onMonthChange(new Date(today.getFullYear(), today.getMonth(), 1));
          }}
        >
          Today
        </button>
        <div className="rc-legend">
          {legend.map((l) => (
            <span key={l.tone}>
              <i className={`rc-dot ${l.tone}`} />
              {l.label}
            </span>
          ))}
        </div>
      </div>

      {people.length === 0 ? (
        <p className="pp-muted">No team members to show.</p>
      ) : (
        <div className="tc-scroll">
          <table className="tc-table">
            <thead>
              <tr>
                <th className="tc-name-head" scope="col">
                  Team member
                </th>
                {days.map((d) => (
                  <th key={+d} scope="col" className={dayClass(d)}>
                    <span>{d.toLocaleDateString("en-GB", { weekday: "narrow" })}</span>
                    <strong>{d.getDate()}</strong>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {people.map((person) => (
                <tr key={person.id}>
                  <th scope="row" className="tc-name">
                    <strong>{person.name}</strong>
                    {person.role && <small>{person.role}</small>}
                  </th>
                  {days.map((d) => {
                    const list = cells.get(`${person.id}|${+d}`) ?? [];
                    const isSelected = selected?.personId === person.id && +selected.day === +d;
                    const dayText = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
                    return (
                      <td key={+d} className={dayClass(d)}>
                        <button
                          className={`tc-cell ${isSelected ? "selected" : ""} ${list.length ? "" : "empty"}`}
                          onClick={() => setSelected(isSelected ? null : { personId: person.id, day: d })}
                          aria-label={`${person.name}, ${dayText}: ${
                            list.length ? list.map((it) => it.chip).join(", ") : "nothing recorded"
                          }`}
                          aria-pressed={isSelected}
                        >
                          {list.map((it) => (
                            <span key={it.id} className={`rc-chip tc-chip ${it.tone}`}>
                              {it.alert && <i className="rc-alert" aria-hidden="true" />}
                              {it.short ?? it.chip}
                            </span>
                          ))}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {selected && (
        <div className="rc-detail" aria-live="polite">
          <div className="rc-detail-head">
            <strong>
              {selectedName} · {selected.day.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" })}
            </strong>
            <span>
              {selectedItems.length} item{selectedItems.length === 1 ? "" : "s"}
            </span>
          </div>
          {selectedItems.length === 0 ? (
            <p className="pp-muted">{emptyDay}</p>
          ) : (
            <ul>
              {selectedItems.map((it) => (
                <li key={it.id} className={`rc-detail-item ${it.tone}`}>
                  {renderDetail(it.row)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
