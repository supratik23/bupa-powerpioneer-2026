import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { Clock3, Moon, Sun, Sunset } from "lucide-react";
import { useDaypart } from "../lib/daypart";
import type { Daypart } from "../lib/daypart";
import { useClickOutside } from "./HeaderMenus";

export const DAYPART_META: Record<Daypart, { label: string; icon: (size: number) => ReactNode }> = {
  morning: { label: "Morning", icon: (s) => <Sun size={s} /> },
  afternoon: { label: "Afternoon", icon: (s) => <Sunset size={s} /> },
  evening: { label: "Evening", icon: (s) => <Moon size={s} /> },
};

/** The Morning / Afternoon / Evening segmented control. */
export function DaypartSegments() {
  const { daypart, setMode } = useDaypart();
  return (
    <div className="dp-segments" role="radiogroup" aria-label="Colour theme">
      {(Object.keys(DAYPART_META) as Daypart[]).map((id) => (
        <button
          key={id}
          role="radio"
          aria-checked={daypart === id}
          className={daypart === id ? "active" : ""}
          onClick={() => setMode(id)}
        >
          {DAYPART_META[id].icon(16)}
          {DAYPART_META[id].label}
        </button>
      ))}
    </div>
  );
}

/** Header button + popover for switching the colour theme on any page. */
export function ThemeToggle() {
  const { daypart, mode, setMode } = useDaypart();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useClickOutside(open, close);

  return (
    <div className="pp-anchor" ref={ref}>
      <button
        className="icon-button dp-toggle"
        aria-label={`Colour theme: ${DAYPART_META[daypart].label}${mode === "auto" ? " (auto)" : ""}`}
        title="Change colour theme"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {DAYPART_META[daypart].icon(18)}
        {mode === "auto" && <span className="dp-auto-dot" />}
      </button>
      {open && (
        <div className="pp-menu dp-menu" role="dialog" aria-label="Colour theme">
          <span className="dp-menu-label">Shift theme preview</span>
          <DaypartSegments />
          <button
            className={`dp-auto ${mode === "auto" ? "active" : ""}`}
            onClick={() => setMode("auto")}
            aria-pressed={mode === "auto"}
          >
            <Clock3 size={15} />
            <span>
              <strong>Auto</strong>
              <small>Follow the time of day</small>
            </span>
            {mode === "auto" && <em>On</em>}
          </button>
        </div>
      )}
    </div>
  );
}
