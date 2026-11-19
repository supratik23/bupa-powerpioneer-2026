"""
Supportive on-screen nudges ("drink some water", "take a short walk"...). The employee's response triggers nothing.

The frontend asks for one nudge every minute, so Gemini is NOT called per request. Each employee has a small
in-memory pool of Gemini-written nudges, refilled in the background when it runs low (one Gemini call per ~8
nudges). When the pool is empty (first call, Gemini unavailable) a built-in nudge is served instead.

Every nudge served is saved (background thread, so the request stays fast) as:
    question         question_id = nudge_id, trigger_type ADHOC, source GEMINI/TEMPLATE,
                     is_active = false (never shows up as a pending check-in),
                     context_data = {kind: SUPPORT_NUDGE, category, emoji, title, message, generated_by}
    question_option  the two buttons: acknowledge (display_order 1), skip (display_order 2)
No employee_response is written, so nudges never affect the wellbeing score or the risk model.

The acknowledge / skip choice (POST /nudges/{nudge_id}/response) is stored on that question's context_data
(response, responded_at). The next refill tells Gemini which categories this person tends to act on or skip.
"""
from __future__ import annotations

import logging
import random
import threading
import uuid
from collections import deque
from datetime import datetime, timezone

from pydantic import BaseModel, Field, field_validator

from config import settings
from services.shiftguard_repository import SUPPORT_NUDGE_KIND

logger = logging.getLogger(__name__)

PROMPT_VERSION = "shiftguard-nudge-v1"
TRIGGER_TYPE = "ADHOC"       # allowed by chk_question_trigger_type (Supabase) and Django's TriggerType
OPTION_SCORES = {"acknowledge": 2, "skip": 1}   # stored only to describe the buttons; never used for scoring

POOL_TARGET = 8         # nudges generated per Gemini call
REFILL_BELOW = 3         # refill in the background when fewer remain
RECENT_MEMORY = 6        # do not repeat the last N titles for an employee
CATEGORIES = ("hydration", "movement", "breathing", "rest", "nutrition", "posture", "eyes", "connection", "mindfulness")

FALLBACK_NUDGES = [
    ("hydration", "💧", "Time for some water", "A few sips of water now helps you stay sharp for the rest of your shift.", "I'll grab some"),
    ("movement", "🚶", "Stretch your legs", "If you can, take a 2-minute walk or stretch between tasks.", "Good idea"),
    ("breathing", "🌬️", "Three slow breaths", "Breathe in for 4, hold for 4, out for 6. Three times. Notice your shoulders drop.", "Done"),
    ("posture", "🧍", "Quick posture check", "Roll your shoulders back and unclench your jaw. Small resets add up.", "Done"),
    ("eyes", "👀", "Rest your eyes", "Look at something far away for 20 seconds to give your eyes a break.", "Done"),
    ("nutrition", "🍎", "Have you eaten?", "If it's been a while, a quick snack can keep your energy steady.", "I'll have something"),
    ("connection", "🤝", "Check in with a colleague", "A quick 'how are you doing?' to a teammate helps you both.", "Will do"),
    ("mindfulness", "🌿", "One kind thought", "Notice one thing that went well today, however small.", "Got it"),
    ("rest", "☕", "Take your break", "If your break is due, try to take it fully - you've earned it.", "Okay"),
]


class SupportNudge(BaseModel):
    category: str = Field(description=f"One of: {', '.join(CATEGORIES)}")
    emoji: str = Field(description="A single fitting emoji")
    title: str = Field(description="Max 40 characters, friendly")
    message: str = Field(description="One or two short sentences, max 140 characters, practical and kind")
    action_label: str = Field(description="Positive button label, 1-4 words, e.g. 'Done', 'I'll grab some'")

    @field_validator("category")
    @classmethod
    def _category(cls, v: str) -> str:
        v = v.strip().lower()
        return v if v in CATEGORIES else "mindfulness"

    @field_validator("title", "message", "action_label", "emoji")
    @classmethod
    def _text(cls, v: str) -> str:
        v = " ".join(v.split())
        if not v:
            raise ValueError("empty")
        return v


class NudgeBatch(BaseModel):
    nudges: list[SupportNudge] = Field(description=f"{POOL_TARGET} varied nudges")


_pools: dict[str, deque] = {}
_recent: dict[str, deque] = {}
_refilling: set[str] = set()
_lock = threading.Lock()


def _shape(employee_id: str, n: SupportNudge | tuple, generated_by: str) -> dict:
    if isinstance(n, tuple):
        n = SupportNudge(category=n[0], emoji=n[1], title=n[2], message=n[3], action_label=n[4])
    return {
        "nudge_id": str(uuid.uuid4()),
        "category": n.category,
        "emoji": n.emoji,
        "title": n.title[:60],
        "message": n.message[:200],
        "options": [
            {"id": "acknowledge", "label": n.action_label[:30]},
            {"id": "skip", "label": "Skip"},
        ],
        "generated_by": generated_by,
    }


def _context(employee_id: str) -> dict:
    """Light context for the prompt: role and current/next shift. No wellbeing data is used."""
    from services.db_service import SupabaseDBConnectionManager

    with SupabaseDBConnectionManager() as db:
        emp = db.fetch_one("SELECT job_role FROM employee WHERE employee_id = %s", (employee_id,))
        shift = db.fetch_one(
            "SELECT shift_type, shift_start, shift_end FROM shift_roster WHERE employee_id = %s "
            "AND shift_end > now() AND shift_start < now() + interval '12 hours' ORDER BY shift_start LIMIT 1",
            (employee_id,),
        )
        prefs = db.fetch_all(
            "SELECT context_data ->> 'category' AS category, context_data ->> 'response' AS response, count(*) AS n "
            "FROM question WHERE generated_for_employee_id = %s AND context_data ->> 'kind' = %s "
            "AND context_data ? 'response' AND created_at >= now() - interval '30 days' GROUP BY 1, 2",
            (employee_id, SUPPORT_NUDGE_KIND),
        )
    now = datetime.now(timezone.utc)
    if shift and shift["shift_start"] <= now:
        hours_in = (now - shift["shift_start"]).total_seconds() / 3600
        hours_left = (shift["shift_end"] - now).total_seconds() / 3600
        shift_text = f"on a {shift['shift_type']} shift, {hours_in:.1f} h in, {hours_left:.1f} h left"
    elif shift:
        shift_text = f"starting a {shift['shift_type']} shift in {(shift['shift_start'] - now).total_seconds() / 3600:.1f} h"
    else:
        shift_text = "not on shift right now"
    return {"role": (emp or {}).get("job_role") or "healthcare worker", "shift": shift_text,
            "utc_time": now.strftime("%H:%M"), "preferences": _preference_text(prefs)}


def _preference_text(rows: list[dict]) -> str:
    """'acts on: hydration, breathing; often skips: posture' from the last 30 days of responses."""
    stats: dict[str, list[int]] = {}
    for r in rows:
        if r["category"]:
            ack_skip = stats.setdefault(r["category"], [0, 0])
            ack_skip[0 if r["response"] == "acknowledge" else 1] += int(r["n"])
    liked = [c for c, (a, k) in stats.items() if a > k]
    skipped = [c for c, (a, k) in stats.items() if k > a and k >= 2]
    parts = []
    if liked:
        parts.append(f"usually acts on: {', '.join(sorted(liked))}")
    if skipped:
        parts.append(f"often skips: {', '.join(sorted(skipped))}")
    return "; ".join(parts)


def record_nudge_response(employee_id: str, nudge_id: str, choice: str) -> bool:
    """Store acknowledge/skip on the saved nudge. Returns False if the nudge isn't (yet) saved for this employee."""
    from psycopg.types.json import Jsonb
    from services.db_service import SupabaseDBConnectionManager

    with SupabaseDBConnectionManager() as db:
        affected = db.execute(
            "UPDATE question SET context_data = coalesce(context_data, '{}'::jsonb) || %s "
            "WHERE question_id = %s AND generated_for_employee_id = %s AND context_data ->> 'kind' = %s",
            (Jsonb({"response": choice, "responded_at": datetime.now(timezone.utc).isoformat()}), nudge_id,
             employee_id, SUPPORT_NUDGE_KIND),
        )
    return affected > 0


def _refill(employee_id: str) -> None:
    """Background job: one Gemini call -> POOL_TARGET nudges for this employee."""
    try:
        from langchain_google_genai.chat_models import GoogleAPIError, GoogleRateLimitError
        from services.llm_service import get_gemini_fallback_models, get_gemini_llm

        ctx = _context(employee_id)
        recent = list(_recent.get(employee_id, []))
        prompt = f"""Write {POOL_TARGET} short, supportive on-screen nudges for a {ctx['role']} who is {ctx['shift']}
(current UTC time {ctx['utc_time']}). They pop up during work, so each must be doable in under 2 minutes.

Rules:
- Vary the categories: {', '.join(CATEGORIES)}. Fit the moment (e.g. hydration and rest late in a long or night shift).
- Warm, practical, non-clinical. Never mention stress scores, risk, burnout, AI or that they are being monitored.
- Do not repeat these recent titles: {recent or 'none'}.
- Their past responses: {ctx['preferences'] or 'none yet'}. Lean towards what they act on; offer what they skip
  rarely and in a fresh way.
- title max 40 characters, message max 140 characters, action_label 1-4 words (the "I did it" button).
"""
        batch, used_model = None, None
        for model in [settings.GEMINI_MODEL, *get_gemini_fallback_models()]:
            try:
                result = get_gemini_llm(model=model).with_structured_output(NudgeBatch).invoke(prompt)
                batch = result if isinstance(result, NudgeBatch) else NudgeBatch(**result)
                used_model = model
                break
            except (GoogleAPIError, GoogleRateLimitError) as e:
                logger.warning("Gemini %s unavailable for nudges: %s", model, e)
            except Exception as e:
                logger.warning("Gemini %s returned unusable nudges: %s", model, e)
        if batch and batch.nudges:
            with _lock:
                pool = _pools.setdefault(employee_id, deque())
                for n in batch.nudges:
                    if n.title not in recent:
                        pool.append((n, used_model))
            logger.info("Nudge pool refilled for %s (%d)", employee_id, len(batch.nudges))
    except Exception:
        logger.exception("Nudge refill failed for %s", employee_id)
    finally:
        with _lock:
            _refilling.discard(employee_id)


def next_nudge(employee_id: str) -> tuple[dict, bool, str | None]:
    """
    Return (nudge, start_refill, model_name). start_refill=True means the caller should run _refill in the
    background. model_name is the Gemini model that wrote the nudge (None for a built-in one).
    """
    with _lock:
        pool = _pools.setdefault(employee_id, deque())
        recent = _recent.setdefault(employee_id, deque(maxlen=RECENT_MEMORY))
        if pool:
            n, model_name = pool.popleft()
            nudge = _shape(employee_id, n, "gemini")
        else:
            options = [f for f in FALLBACK_NUDGES if f[2] not in recent] or FALLBACK_NUDGES
            nudge, model_name = _shape(employee_id, random.choice(options), "template"), None
        recent.append(nudge["title"])
        start_refill = len(pool) < REFILL_BELOW and employee_id not in _refilling
        if start_refill:
            _refilling.add(employee_id)
    return nudge, start_refill, model_name


def refill_in_background(employee_id: str) -> None:
    threading.Thread(target=_refill, args=(employee_id,), daemon=True, name=f"nudge-refill-{employee_id[:8]}").start()


def save_nudge(employee_id: str, nudge: dict, model_name: str | None) -> None:
    """Store a served nudge as an inactive `question` (id = nudge_id) with its two buttons as `question_option`."""
    from psycopg.types.json import Jsonb
    from services.db_service import SupabaseDBConnectionManager

    context = {
        "kind": SUPPORT_NUDGE_KIND,
        "category": nudge["category"],
        "emoji": nudge["emoji"],
        "title": nudge["title"],
        "message": nudge["message"],
        "generated_by": nudge["generated_by"],
    }
    source = "GEMINI" if nudge["generated_by"] == "gemini" else "TEMPLATE"
    try:
        with SupabaseDBConnectionManager() as db:
            connection = db.db_connection()
            if connection is None:
                raise ConnectionError("Unable to connect to the Supabase database.")
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO question (question_id, question_text, source, trigger_type,
                                              generated_for_employee_id, context_data, model_name, prompt_version,
                                              is_active, expires_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, false, NULL)
                        """,
                        (nudge["nudge_id"], f"{nudge['title']} - {nudge['message']}", source, TRIGGER_TYPE,
                         employee_id, Jsonb(context), model_name, PROMPT_VERSION),
                    )
                    for order, option in enumerate(nudge["options"], start=1):
                        cursor.execute(
                            "INSERT INTO question_option (question_id, option_text, normalized_score, display_order) "
                            "VALUES (%s, %s, %s, %s)",
                            (nudge["nudge_id"], option["label"], OPTION_SCORES[option["id"]], order),
                        )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        logger.info("Saved nudge %s for employee %s", nudge["nudge_id"], employee_id)
    except Exception:
        logger.exception("Could not save nudge %s for employee %s", nudge["nudge_id"], employee_id)


def save_nudge_in_background(employee_id: str, nudge: dict, model_name: str | None) -> None:
    threading.Thread(target=save_nudge, args=(employee_id, nudge, model_name), daemon=True,
                     name=f"nudge-save-{employee_id[:8]}").start()
