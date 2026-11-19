import { useEffect, useRef, useState } from "react";
import { agentApi } from "../api/client";
import { NUDGE_INTERVAL_MS, NUDGE_VISIBLE_MS } from "../api/config";
import type { SupportNudge } from "../api/types";

/** A check-in question panel (not a support nudge) is on screen: never stack two popups. */
const checkInOpen = () => document.querySelector(".wellbeing-panel:not(.support-nudge-panel)") !== null;

/**
 * Session-wide timer for supportive nudges ("drink some water", "stretch your legs"...).
 * Starts when the user is signed in (also after a page reload) and asks the AI agent for a nudge every
 * NUDGE_INTERVAL_MS (1 minute by default). Skips a tick while the tab is hidden, a nudge is already showing
 * or a check-in question is open. If the agent is offline it simply tries again on the next tick.
 * A nudge nobody responds to hides itself after NUDGE_VISIBLE_MS (10 s). Check-in questions have no such timeout.
 */
export function useSupportNudges(enabled: boolean, intervalMs = NUDGE_INTERVAL_MS, visibleMs = NUDGE_VISIBLE_MS) {
  const [nudge, setNudge] = useState<SupportNudge | null>(null);
  const showingRef = useRef(false);
  showingRef.current = nudge !== null;

  useEffect(() => {
    if (!enabled) {
      setNudge(null);
      return;
    }
    let cancelled = false;
    let inFlight = false;
    const tick = async () => {
      if (inFlight || showingRef.current || document.visibilityState !== "visible" || checkInOpen()) return;
      inFlight = true;
      try {
        const next = await agentApi.get<SupportNudge>("/nudges/next");
        if (!cancelled && !showingRef.current && !checkInOpen()) setNudge(next);
      } catch {
        /* agent unreachable: try again on the next tick */
      } finally {
        inFlight = false;
      }
    };
    const id = window.setInterval(() => void tick(), intervalMs);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [enabled, intervalMs]);

  // Auto-hide: each new nudge gets its own timer; answering/closing earlier clears it.
  useEffect(() => {
    if (!nudge) return;
    const id = window.setTimeout(() => setNudge(null), visibleMs);
    return () => window.clearTimeout(id);
  }, [nudge, visibleMs]);

  /** Acknowledge / skip: hide the nudge and tell the agent (used to personalise later nudges; best effort). */
  const respond = (choice: "acknowledge" | "skip") => {
    if (nudge) {
      void agentApi.post(`/nudges/${nudge.nudge_id}/response`, { choice }).catch(() => undefined);
    }
    setNudge(null);
  };

  return { nudge, visibleMs, dismiss: () => setNudge(null), respond };
}
