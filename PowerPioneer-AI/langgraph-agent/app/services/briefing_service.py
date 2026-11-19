"""
Daily manager briefing: what changed in my team since the last scoring, in five lines.

For each team member it compares the latest two saved XGBoost predictions (on different snapshot dates), so the
briefing is about CHANGES ("Vikram moved LOW -> HIGH, driven by 3 extra night shifts"), not absolute bands. It also
checks the return-to-work guidelines for people back from maternity leave in the last 12 weeks, and counts open
follow-up actions. Gemini writes the digest from that structured data; a template is used when Gemini is unavailable.

Run on demand (POST /briefing/run) or every day at BRIEFING_HOUR_UTC when BRIEFING_ENABLED. The latest briefing per
manager is kept in memory (GET /briefing/latest), pushed to the bell over WebSocket, and optionally emailed.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from config import settings
from services.escalation_service import FEATURE_LABELS
from services.shiftguard_repository import EMPLOYEE_COLUMNS, EMPLOYEE_FROM, RISK_BAND_ORDER, XGBOOST_MODEL_NAME, to_jsonable

logger = logging.getLogger(__name__)

RETURN_PLAN_DAYS = 84               # 12-week phased return (same as the frontend's returnToWork.ts)
MAX_VARIANCE_HOURS = 4
MAX_OVERTIME_HOURS = 5

_latest: dict[str, dict] = {}
_lock = threading.Lock()


def latest_briefing(manager_id: str) -> dict | None:
    with _lock:
        return _latest.get(str(manager_id))


def _team(db, manager_id: str, everyone: bool) -> list[dict]:
    where = "e.is_active = true" + ("" if everyone else " AND e.manager_employee_id = %s")
    params = () if everyone else (manager_id,)
    return db.fetch_all(f"SELECT {EMPLOYEE_COLUMNS} {EMPLOYEE_FROM} WHERE {where} ORDER BY e.last_name, e.first_name", params)


def _last_two(db, employee_id) -> list[dict]:
    return db.fetch_all(
        """
        SELECT * FROM (
            SELECT DISTINCT ON (s.snapshot_date) s.snapshot_date, p.prediction_id, p.risk_band, p.risk_score,
                   s.days_since_maternity_return, s.nursing_or_recovery_breaks_missed_30d,
                   s.return_schedule_variance_hours_30d, s.overtime_hours_since_maternity_return,
                   s.maternity_adjustments_fulfilment_ratio
            FROM risk_prediction p JOIN employee_risk_snapshot s ON s.risk_snapshot_id = p.risk_snapshot_id
            WHERE p.employee_id = %s AND p.model_name = %s AND s.is_training_record = false
            ORDER BY s.snapshot_date DESC, p.predicted_at DESC
        ) t ORDER BY snapshot_date DESC LIMIT 2
        """,
        (employee_id, XGBOOST_MODEL_NAME),
    )


def _drivers(db, prediction_id) -> list[str]:
    rows = db.fetch_all(
        "SELECT feature_name FROM risk_explanation WHERE prediction_id = %s AND contribution_direction = 'INCREASES_RISK' "
        "ORDER BY display_order LIMIT 3", (prediction_id,))
    return [FEATURE_LABELS.get(r["feature_name"], r["feature_name"].replace("_", " ")) for r in rows]


def _return_to_work_alerts(name: str, snap: dict) -> list[str]:
    days = snap.get("days_since_maternity_return")
    if days is None or days > RETURN_PLAN_DAYS:
        return []
    alerts = []
    if (snap.get("nursing_or_recovery_breaks_missed_30d") or 0) > 0:
        alerts.append(f"{name}: {snap['nursing_or_recovery_breaks_missed_30d']} protected nursing/recovery break(s) missed")
    if float(snap.get("return_schedule_variance_hours_30d") or 0) > MAX_VARIANCE_HOURS:
        alerts.append(f"{name}: shift pattern less predictable than agreed "
                      f"({float(snap['return_schedule_variance_hours_30d']):.1f} h variance)")
    if float(snap.get("overtime_hours_since_maternity_return") or 0) > MAX_OVERTIME_HOURS:
        alerts.append(f"{name}: {float(snap['overtime_hours_since_maternity_return']):.1f} h overtime since returning")
    return alerts


def _collect(manager_id: str, rescore: bool, everyone: bool) -> dict:
    from services.db_service import SupabaseDBConnectionManager
    from services.risk_feature_service import NoShiftsInWindow
    from services.risk_model_service import score_employee

    today = datetime.now(timezone.utc).date()
    changes, steady_high, rtw, scored = [], [], [], 0
    with SupabaseDBConnectionManager() as db:
        manager = db.fetch_one("SELECT first_name, last_name, email FROM employee WHERE employee_id = %s", (manager_id,))
        team = _team(db, manager_id, everyone)
        for emp in team:
            name = f"{emp['first_name']} {emp['last_name']}"
            if rescore:
                try:
                    score_employee(db, emp, today, save=True)
                    scored += 1
                except NoShiftsInWindow:
                    pass
                except Exception:
                    logger.exception("Briefing rescoring failed for %s", emp["employee_id"])
            rows = _last_two(db, emp["employee_id"])
            if not rows:
                continue
            latest = rows[0]
            rtw += _return_to_work_alerts(emp["first_name"], latest)
            previous = rows[1] if len(rows) > 1 else None
            moved = previous is not None and latest["risk_band"] != previous["risk_band"]
            if moved:
                changes.append({
                    "name": name, "from": previous["risk_band"], "to": latest["risk_band"],
                    "direction": "up" if RISK_BAND_ORDER.get(latest["risk_band"], 0) > RISK_BAND_ORDER.get(previous["risk_band"], 0) else "down",
                    "score_change": round(float(latest["risk_score"]) - float(previous["risk_score"]), 1),
                    "since": previous["snapshot_date"], "drivers": _drivers(db, latest["prediction_id"]),
                })
            elif latest["risk_band"] in ("HIGH", "CRITICAL"):
                steady_high.append({"name": name, "band": latest["risk_band"], "drivers": _drivers(db, latest["prediction_id"])})
        open_actions = db.fetch_one(
            "SELECT count(*) AS n FROM intervention i JOIN employee e ON e.employee_id = i.employee_id "
            "WHERE i.action_status IN ('PENDING', 'IN_PROGRESS') AND i.triggered_at >= now() - interval '14 days'"
            + ("" if everyone else " AND e.manager_employee_id = %s"),
            () if everyone else (manager_id,),
        )["n"]
    changes.sort(key=lambda c: (c["direction"] != "up", -abs(c["score_change"])))
    return {
        "manager": f"{manager['first_name']} {manager['last_name']}" if manager else "",
        "manager_email": manager["email"] if manager else None,
        "date": today, "team_size": len(team), "rescored": scored,
        "changes": changes, "still_high": steady_high, "return_to_work_alerts": rtw, "open_follow_ups": open_actions,
    }


def _template_text(data: dict) -> tuple[str, str]:
    up = [c for c in data["changes"] if c["direction"] == "up"]
    down = [c for c in data["changes"] if c["direction"] == "down"]
    if up:
        headline = f"{len(up)} team member{'s' if len(up) > 1 else ''} moved into a higher risk band"
    elif data["still_high"]:
        headline = f"{len(data['still_high'])} team member{'s' if len(data['still_high']) > 1 else ''} still need attention"
    else:
        headline = "No worrying changes in your team"
    lines = []
    for c in up:
        lines.append(f"- **{c['name']}** {c['from']} -> {c['to']}" + (f", driven by {', '.join(c['drivers'][:2])}" if c["drivers"] else ""))
    for s in data["still_high"][:3]:
        lines.append(f"- **{s['name']}** remains {s['band']}" + (f" ({s['drivers'][0]})" if s["drivers"] else ""))
    for c in down[:2]:
        lines.append(f"- {c['name']} improved {c['from']} -> {c['to']}")
    for alert in data["return_to_work_alerts"][:2]:
        lines.append(f"- Return to work: {alert}")
    if data["open_follow_ups"]:
        lines.append(f"- {data['open_follow_ups']} follow-up action(s) still open")
    return headline, "\n".join(lines) or "- Everyone is stable. A good day to thank the team."


def _gemini_text(data: dict) -> tuple[str, str] | None:
    from pydantic import BaseModel, Field
    from services.llm_service import get_gemini_fallback_models, get_gemini_llm

    class Briefing(BaseModel):
        headline: str = Field(description="One sentence, max 90 characters, the single most important point")
        bullets: list[str] = Field(description="3-6 short Markdown bullet texts (no leading dash), most urgent first, "
                                               "each with a concrete suggested action")

    prompt = f"""You write a short morning briefing for a healthcare team manager about their team's burnout risk.
Use ONLY this data (risk bands from a prototype model; never invent people or numbers):
{to_jsonable(data)}

Focus on changes since the last scoring, then people still HIGH/CRITICAL, then return-to-work alerts and open
follow-ups. For each person moving up, name the main drivers in plain language and suggest one practical action
(e.g. a 1:1 this week, protect breaks, avoid more night shifts). Warm, concise, no jargon, no scores.
If nothing changed, say so and suggest one small team-wide action."""
    for model in [settings.GEMINI_MODEL, *get_gemini_fallback_models()]:
        try:
            result = get_gemini_llm(model=model).with_structured_output(Briefing).invoke(prompt)
            result = result if isinstance(result, Briefing) else Briefing(**result)
            bullets = [b.strip().lstrip("-• ").strip() for b in result.bullets if b.strip()]
            if result.headline.strip() and bullets:
                return result.headline.strip(), "\n".join(f"- {b}" for b in bullets)
        except Exception as e:
            logger.warning("Gemini %s could not write the briefing: %s", model, e)
    return None


def build_briefing(manager_id: str, rescore: bool = False, everyone: bool = False, send_email: bool | None = None) -> dict:
    """Collect, write, store, notify (and optionally email) the briefing for one manager."""
    data = _collect(str(manager_id), rescore, everyone)
    written = _gemini_text(data) if (data["changes"] or data["still_high"] or data["return_to_work_alerts"]) else None
    generated_by = "gemini" if written else "template"
    headline, text = written or _template_text(data)
    briefing = to_jsonable({
        "manager_id": str(manager_id), "manager": data["manager"], "generated_at": datetime.now(timezone.utc),
        "headline": headline, "text": text, "generated_by": generated_by,
        "changes": data["changes"], "still_high": data["still_high"],
        "return_to_work_alerts": data["return_to_work_alerts"], "open_follow_ups": data["open_follow_ups"],
        "team_size": data["team_size"], "rescored": data["rescored"],
    })
    with _lock:
        _latest[str(manager_id)] = briefing

    from services.notify_service import notify_employee_async
    notify_employee_async(manager_id, {"kind": "briefing", "headline": headline})

    if (settings.BRIEFING_SEND_EMAIL if send_email is None else send_email) and data["manager_email"]:
        try:
            from mcp_server.notifsend_tool import build_notification_content, send_email as smtp_send
            subject, body, html = build_notification_content("general", {
                "subject": f"Your team briefing: {headline}", "message": text.replace("**", "")})
            smtp_send([data["manager_email"]], subject, body, html)
            briefing["emailed"] = True
        except Exception as e:
            logger.warning("Briefing email to %s failed: %s", data["manager_email"], e)
            briefing["emailed"] = False
    return briefing


def run_all_briefings(rescore: bool = True) -> int:
    """Daily job: one briefing per manager with active direct reports. Returns how many were built."""
    from services.db_service import SupabaseDBConnectionManager

    with SupabaseDBConnectionManager() as db:
        managers = db.fetch_all(
            "SELECT DISTINCT manager_employee_id AS id FROM employee WHERE manager_employee_id IS NOT NULL AND is_active")
    built = 0
    for row in managers:
        try:
            build_briefing(str(row["id"]), rescore=rescore)
            built += 1
        except Exception:
            logger.exception("Briefing failed for manager %s", row["id"])
    logger.info("Daily briefings built for %d managers", built)
    return built


def seconds_until(hour_utc: int) -> float:
    now = datetime.now(timezone.utc)
    nxt = now.replace(hour=hour_utc % 24, minute=0, second=0, microsecond=0)
    if nxt <= now:
        nxt += timedelta(days=1)
    return (nxt - now).total_seconds()
