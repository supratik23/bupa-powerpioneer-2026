import { HeartHandshake, Sparkles, X } from "lucide-react";
import type { SupportNudge } from "../api/types";

/**
 * Popup in the same style as the check-in panel, with two buttons (acknowledge / skip).
 * The choice is sent to the agent (onRespond), which uses it to pick nudges this person finds useful.
 * It never affects the wellbeing score. Closing the popup (X / backdrop) sends nothing.
 * Without a response it hides itself after `visibleMs` (the bar under the header shows the time left).
 */
export function SupportNudgePopup({
  nudge,
  onClose,
  onRespond,
  visibleMs,
}: {
  nudge: SupportNudge | null;
  onClose: () => void;
  onRespond?: (choice: "acknowledge" | "skip") => void;
  visibleMs: number;
}) {
  if (!nudge) return null;
  return (
    <>
      <button className="panel-backdrop" aria-label="Close nudge" onClick={onClose} />
      <aside className="wellbeing-panel support-nudge-panel" aria-live="polite" role="dialog" aria-label={nudge.title}>
        <div className="panel-header">
          <div>
            <div className="sparkle-label">
              <Sparkles size={14} />
              ShiftGuard
            </div>
            <span>A small moment for you</span>
          </div>
          <button className="ghost-icon" onClick={onClose} aria-label="Close">
            <X size={19} />
          </button>
        </div>
        {/* key restarts the countdown animation for every new nudge */}
        <div className="nudge-countdown" aria-hidden="true">
          <span key={nudge.nudge_id} style={{ animationDuration: `${visibleMs}ms` }} />
        </div>

        <div className="panel-body">
          <div className="question-heading">
            <div className="question-icon teal">
              <HeartHandshake size={22} />
            </div>
            <span>Supportive nudge</span>
            <h2>
              <span aria-hidden="true">{nudge.emoji} </span>
              {nudge.title}
            </h2>
            <p>{nudge.message}</p>
          </div>
          <div className="checkin-options" style={{ gridTemplateColumns: `repeat(${nudge.options.length}, minmax(58px, 1fr))` }}>
            {nudge.options.map((option) => (
              <button key={option.id} onClick={() => (onRespond ? onRespond(option.id) : onClose())}>
                <span className="checkin-emoji" aria-hidden="true">
                  {option.id === "skip" ? "⏭️" : "✅"}
                </span>
                <strong>{option.label}</strong>
              </button>
            ))}
          </div>
          <p className="one-tap-note">
            <Sparkles size={13} />
            Just for you - your choice only helps us suggest nudges you find useful.
          </p>
        </div>
      </aside>
    </>
  );
}
