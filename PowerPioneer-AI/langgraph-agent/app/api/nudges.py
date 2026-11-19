"""
GET /nudges/next - one supportive on-screen nudge (drink water, stretch, breathe...) for the logged-in employee.

Called by PowerPioneer-Frontend on a timer (every minute). Each nudge served is saved as an inactive `question`
(question_id = nudge_id, trigger_type ADHOC, context_data.kind = SUPPORT_NUDGE) with its two buttons as
`question_option`.

POST /nudges/{nudge_id}/response - the acknowledge / skip choice, stored on the nudge (never on employee_response, so
it does not affect the wellbeing score) and used to personalise future nudges.
"""
from __future__ import annotations

import logging
from uuid import UUID

from typing import Literal

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from .checkin import resolve_caller   # also puts app/ on sys.path for `services.*`
from services.nudge_service import (  # noqa: E402
    next_nudge, record_nudge_response, refill_in_background, save_nudge_in_background,
)

logger = logging.getLogger(__name__)
nudge_router = APIRouter()


@nudge_router.get("/next")
def get_next_nudge(employee_id: UUID | None = None, authorization: str | None = Header(default=None)) -> dict:
    """Return the next supportive nudge. `employee_id` is only used when AGENT_REQUIRE_AUTH=false and no token is sent."""
    caller = resolve_caller(authorization, employee_id)
    try:
        nudge, start_refill, model_name = next_nudge(caller)
    except Exception as e:
        logger.exception("next nudge failed")
        raise HTTPException(500, f"Could not create a nudge: {e}") from e
    save_nudge_in_background(caller, nudge, model_name)   # question + question_option; failures are only logged
    if start_refill:
        refill_in_background(caller)
    return nudge


class NudgeResponse(BaseModel):
    choice: Literal["acknowledge", "skip"]
    employee_id: UUID | None = None   # only used when AGENT_REQUIRE_AUTH=false and no token is sent


@nudge_router.post("/{nudge_id}/response")
def post_nudge_response(nudge_id: UUID, body: NudgeResponse, authorization: str | None = Header(default=None)) -> dict:
    """Record the employee's acknowledge / skip choice for a nudge they were shown."""
    caller = resolve_caller(authorization, body.employee_id)
    try:
        saved = record_nudge_response(caller, str(nudge_id), body.choice)
    except Exception as e:
        logger.exception("Saving the nudge response failed")
        raise HTTPException(500, f"Could not save the response: {e}") from e
    return {"nudge_id": str(nudge_id), "choice": body.choice, "saved": saved}
