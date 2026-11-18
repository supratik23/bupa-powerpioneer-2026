import { HeartHandshake, Sparkles, X } from "lucide-react";
import type { SupportNudge } from "../api/types";

/**
 * Popup in the same style as the check-in panel, with two buttons (acknowledge / skip).
 * The choice only closes the popup: nothing is sent to the backend.
 * Without a response it hides itself after `visibleMs` (the bar under the header shows the time left).
 */
export function SupportNudgePopup({
  nudge,
  onClose,
  visibleMs,
}: {
  nudge: SupportNudge | null;
  onClose: () => void;
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
              <button key={option.id} onClick={onClose}>
                <span className="checkin-emoji" aria-hidden="true">
                  {option.id === "skip" ? "⏭️" : "✅"}
                </span>
                <strong>{option.label}</strong>
              </button>
            ))}
          </div>
          <p className="one-tap-note">
            <Sparkles size={13} />
            Just for you - your choice isn't recorded.
          </p>
        </div>
      </aside>
    </>
  );
}
