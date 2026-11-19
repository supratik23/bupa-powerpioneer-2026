"""
Real-time bell notifications for things the agent does.

The agent writes straight to Supabase, so Django never sees those writes happen. This asks Django to push a
notification to the employee's WebSocket group (ws/notifications/), the same channel Django uses for its own
interventions: POST {BACKEND_API_BASE_URL}/internal/notify/ with the shared X-Agent-Key header.

Best effort: runs in a daemon thread, short timeout, failures are only logged (the bell also polls every 30 s).
"""
from __future__ import annotations

import logging
import threading

import httpx

from config import settings

logger = logging.getLogger(__name__)


def notify_employee(employee_id, payload: dict) -> bool:
    try:
        res = httpx.post(
            f"{settings.BACKEND_API_BASE_URL.rstrip('/')}/internal/notify/",
            json={"employee_id": str(employee_id), "payload": payload},
            headers={"X-Agent-Key": settings.AGENT_INTERNAL_KEY},
            timeout=5,
        )
        if res.status_code >= 300:
            logger.warning("Django notify returned %s: %s", res.status_code, res.text[:200])
            return False
        return True
    except httpx.HTTPError as e:
        logger.warning("Could not push a notification to %s: %s", employee_id, e)
        return False


def notify_employee_async(employee_id, payload: dict) -> None:
    if not employee_id:
        return
    threading.Thread(target=notify_employee, args=(employee_id, payload), daemon=True,
                     name="shiftguard-notify").start()
