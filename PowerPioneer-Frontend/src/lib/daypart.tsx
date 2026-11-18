import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

/** Time-of-day colour themes. Purely visual — no data or API involvement. */
export type Daypart = "morning" | "afternoon" | "evening";
/** "auto" follows the clock; otherwise the user has pinned a theme. */
export type DaypartMode = "auto" | Daypart;

export const DAYPARTS: readonly Daypart[] = ["morning", "afternoon", "evening"];
const STORAGE_KEY = "pp-daypart-mode";

/** Morning 05:00–11:59, afternoon 12:00–17:59, evening 18:00–04:59. */
export function daypartFor(date = new Date()): Daypart {
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 18) return "afternoon";
  return "evening";
}

function readMode(): DaypartMode {
  try {
    const saved = window.localStorage.getItem(STORAGE_KEY);
    if (saved && (saved === "auto" || DAYPARTS.includes(saved as Daypart))) return saved as DaypartMode;
  } catch {
    // storage unavailable (private window etc.) — fall back to auto
  }
  return "auto";
}

function saveMode(mode: DaypartMode) {
  try {
    window.localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // ignore — the choice just won't survive a reload
  }
}

interface DaypartState {
  /** The theme currently shown. */
  daypart: Daypart;
  /** What the user picked: "auto" or a pinned theme. */
  mode: DaypartMode;
  setMode: (mode: DaypartMode) => void;
}

const DaypartContext = createContext<DaypartState | null>(null);

/**
 * Applies the theme to the whole app as `<html data-daypart="…">` (styled in
 * daypart.css). In auto mode it re-checks the clock every minute so the theme
 * moves on by itself; a pinned choice is remembered in this browser.
 */
export function DaypartProvider({ children }: { children: ReactNode }) {
  const [mode, setModeState] = useState<DaypartMode>(readMode);
  const [clock, setClock] = useState<Daypart>(() => daypartFor());

  useEffect(() => {
    if (mode !== "auto") return;
    setClock(daypartFor());
    const timer = window.setInterval(() => setClock(daypartFor()), 60_000);
    return () => window.clearInterval(timer);
  }, [mode]);

  const daypart = mode === "auto" ? clock : mode;

  useEffect(() => {
    document.documentElement.dataset.daypart = daypart;
  }, [daypart]);

  const setMode = useCallback((next: DaypartMode) => {
    setModeState(next);
    saveMode(next);
  }, []);

  const value = useMemo(() => ({ daypart, mode, setMode }), [daypart, mode, setMode]);
  return <DaypartContext.Provider value={value}>{children}</DaypartContext.Provider>;
}

export function useDaypart(): DaypartState {
  const ctx = useContext(DaypartContext);
  if (!ctx) throw new Error("useDaypart must be used inside <DaypartProvider>");
  return ctx;
}
