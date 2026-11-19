"""
Manager briefing APIs (same login token and manager/HR check as the chat agent).

GET  /briefing/latest   The caller's latest briefing, or {"briefing": null}.
POST /briefing/run      Build it now. Body: {"rescore": false}. rescore=true first re-runs the risk model for the team
                        (saved, like the daily batch), so the briefing reflects today's roster and check-ins.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from services.briefing_service import build_briefing, latest_briefing
from ..mcp_client.agent import resolve_caller_async, _has_reports

logger = logging.getLogger(__name__)
briefing_router = APIRouter()


class BriefingRequest(BaseModel):
    rescore: bool = False


@briefing_router.get("/latest")
async def get_latest(authorization: str | None = Header(default=None)) -> dict:
    caller = await resolve_caller_async(authorization)
    return {"briefing": latest_briefing(caller.employee_id)}


@briefing_router.post("/run")
async def run_briefing(body: BriefingRequest, authorization: str | None = Header(default=None)) -> dict:
    caller = await resolve_caller_async(authorization)
    if caller.employee_id == "local-tester":
        raise HTTPException(400, "Briefings need a signed-in manager (send the login token).")
    try:
        # HR/staff without direct reports get a briefing for everyone.
        everyone = caller.is_staff and not await asyncio.to_thread(_has_reports, caller.employee_id)
        briefing = await asyncio.to_thread(build_briefing, caller.employee_id, body.rescore, everyone)
    except Exception as e:
        logger.exception("Briefing failed")
        raise HTTPException(500, f"Could not build the briefing: {e}") from e
    return {"briefing": briefing}
