"""
Human-in-the-loop approval for outward / hard-to-undo tool calls (emails, roster changes, leave decisions, buddies).

The graph's approval_gate node calls LangGraph `interrupt()` with a reviewable description of the pending actions.
The run pauses (state kept by the checkpointer) until POST /agent/stream (or /agent/invoke) resumes it with
{"approved": true|false, "comment": "..."}.
"""
from __future__ import annotations

import json
import logging
from datetime import timezone

logger = logging.getLogger(__name__)


def _email_preview(args: dict) -> dict:
    from mcp_server.notifsend_tool import build_notification_content

    try:
        data = json.loads(args.get("input_data") or "{}")
        to = data.get("to")
        recipients = [to] if isinstance(to, str) else list(to or [])
        subject, text, _ = build_notification_content(data.get("notification_type"), data.get("data") or {},
                                                      data.get("organization_name"))
        return {"title": f"Send email to {', '.join(recipients) or 'nobody'}",
                "details": {"To": ", ".join(recipients), "Subject": subject}, "preview": text}
    except Exception as e:    # invalid input: show it raw, the tool will report the error if approved
        return {"title": "Send email", "details": {"Problem": str(e)}, "preview": args.get("input_data")}


def _shift_text(db, shift_id: str) -> str:
    row = db.fetch_one(
        "SELECT s.shift_start, s.shift_type, e.first_name || ' ' || e.last_name AS name FROM shift_roster s "
        "JOIN employee e ON e.employee_id = s.employee_id WHERE s.shift_id = %s", (shift_id,))
    if not row:
        return shift_id
    when = row["shift_start"].astimezone(timezone.utc).strftime("%a %d %b, %H:%M UTC")
    return f"{row['name']}'s {row['shift_type'].lower()} shift ({when})"


def _describe_sync(name: str, args: dict) -> dict:
    if name == "send_notification_email":
        return _email_preview(args)
    from services.db_service import SupabaseDBConnectionManager

    with SupabaseDBConnectionManager() as db:
        if name == "reassign_shift":
            return {"title": "Reassign a shift",
                    "details": {"Shift": _shift_text(db, args.get("shift_id", "")),
                                "New employee": args.get("new_employee"), "Reason": args.get("reason")}}
        if name == "decide_leave_request":
            leave = db.fetch_one(
                "SELECT l.leave_type, l.start_date, l.end_date, e.first_name || ' ' || e.last_name AS name "
                "FROM leave_request l JOIN employee e ON e.employee_id = l.employee_id WHERE l.leave_request_id = %s",
                (args.get("leave_request_id"),))
            what = (f"{leave['name']}: {leave['leave_type'].lower()} leave {leave['start_date']} to {leave['end_date']}"
                    if leave else args.get("leave_request_id"))
            decision = (args.get("decision") or "").upper()
            return {"title": f"{'Approve' if decision == 'APPROVED' else 'Reject'} a leave request",
                    "details": {"Request": what, "Decision": decision, "Note to employee": args.get("comment") or "-"}}
        if name == "assign_buddy":
            return {"title": "Assign a peer-support buddy",
                    "details": {"Employee": args.get("employee"), "Buddy": args.get("buddy"),
                                "Reason": args.get("reason") or "-"}}
    return {"title": name, "details": {k: str(v) for k, v in args.items()}}


def describe_action(name: str, args: dict) -> dict:
    try:
        described = _describe_sync(name, args)
    except Exception as e:
        logger.warning("Could not describe %s for approval: %s", name, e)
        described = {"title": name, "details": {k: str(v) for k, v in args.items()}}
    return {"tool": name, **described}
