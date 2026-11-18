import { HeartHandshake, Sparkles, X } from "lucide-react";
import type { SupportNudge } from "../api/types";

/**
 * Popup in the same style as the check-in panel, with two buttons (acknowledge / skip).
 * The choice only closes the popup: nothing is sent to the backend.
 */
export function SupportNudgePopup({ nudge, onClose }: { nudge: SupportNudge | null; onClose: () => void }) {
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
