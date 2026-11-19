# ShiftGuard Agent: how to use it

The ShiftGuard agent is a FastAPI + LangGraph service that answers questions about staff wellbeing risk and acts on them. Gemini (`gemini-3.8-flash`) reads each request and decides which MCP tool to call. The tools compute the 26 risk-model features from Supabase, run the XGBoost model, and save the result in the same tables the Django backend and the React frontend read. No keyword routing is involved.

The tools follow [ShiftGuard Risk Model: Input Specification](https://claude.ai/artifact/PKWDVNJ3nvDqFmRrYZB2oz).

## Main flow: check-in after a completed appointment

This is the flow the ShiftGuard app uses. It doesn't go through the chat agent: two dedicated endpoints run fixed steps in code, and Gemini only writes the next question, in the background.

```
Employee ticks an appointment done
  Frontend ──POST /api/appointments/{id}/complete/──> Django      (status = COMPLETED)
  Frontend ──POST :8001/checkin/appointment-completed──> agent
              ├─ returns the question + 4 options now ──> check-in panel opens
              └─ background: Gemini writes the NEXT question, saved hidden (QUEUED)
Employee taps an answer
  Frontend ──POST :8001/checkin/answer──> agent
              1. employee_response row
              2. wellbeing_score = mean answer score (1-4), last 7 days
              3. 26 features → XGBoost → snapshot, prediction, explanations
              4. follow-up by band → intervention rows; emails sent in the background
```

**`POST /checkin/appointment-completed`** with `{"appointment_id": "<uuid>"}` returns the question in the same shape as Django's `/api/questions/`.

The question is chosen in this order:

1. The employee's open, unanswered question (`served_from: "open"`). So five completions in a row show the same question rather than five new ones.
2. Otherwise, the QUEUED question, which is activated now and expires after 24 hours (`"queued"`).
3. Otherwise, the first time only, a question from the built-in template bank (`"template"`).

When nothing is queued yet, the next question is generated in the background. If every Gemini model is unavailable, a template question is queued instead. Queued questions are saved with `is_active = false` and `context_data.queue_status = 'QUEUED'`, so they stay out of `/api/questions/pending/` until they are served. Every question has exactly 4 options, scored 1–4 from worst to best.

The endpoint returns 409 if the appointment isn't COMPLETED, and returns `question: null` if the appointment belongs to someone else, for example when a manager ticked it.

**`POST /checkin/answer`** with `{"question_id": "<uuid>", "option_id": "<uuid>"}` returns `wellbeing_score_7d`, `risk` (band, score, prediction_id, top factors) and `actions`.

| Error | When |
| --- | --- |
| 409 | The question was already answered, or hasn't been served yet |
| 403 | The question belongs to someone else |
| 400 | The option doesn't belong to the question |

Employees with no shifts in the last 30 days get `risk: null`, with a reason in `risk_skipped_reason`.

**Follow-up by risk band.** An action is skipped if the same one was recorded for the employee in the last 7 days, unless that earlier one failed or was cancelled.

| Band | Actions (`intervention.action_type`) | Email |
| --- | --- | --- |
| CRITICAL | `EMAIL_MANAGER`, `EMAIL_BUDDY`, `SCHEDULE_CHECKIN` (manager, within 48 h) | Manager: band, score, drivers, "1:1 within 48 hours". Buddy: a friendly nudge with no scores. |
| HIGH | `EMAIL_MANAGER` | Manager: "check-in this week" |
| MEDIUM | `EMAIL_BUDDY`; if there is no buddy, recorded as `SKIPPED` | Buddy nudge |
| LOW | none | – |

Email interventions start as `PENDING` and become `COMPLETED`, or `FAILED` with the SMTP error. Check-in answers are never included in any email. The policy is the `ESCALATION_POLICY` dict in `app/services/escalation_service.py`.

**Auth.** The frontend sends its Django access token (`Authorization: Bearer …`). The agent checks it with Django `GET /api/auth/me/`, so the backend must be running, and it acts only for that employee. For local Swagger or curl tests, set `AGENT_REQUIRE_AUTH=false` in `.env` and pass `employee_id` in the body instead.

**Frontend wiring** (`PowerPioneer-Frontend`):

- Set the agent URL with `VITE_AGENT_BASE_URL`; the default is `http://127.0.0.1:8001`.
- `App.tsx` calls `/checkin/appointment-completed` after a successful "mark complete", then opens the check-in panel with the returned question.
- Answers go to `/checkin/answer`. If the agent is unreachable, the answer is saved through Django instead, so it isn't lost, and the next scoring run picks it up.
- The frontend no longer calls Django's rule-based `/wellbeing/calculate/`.

## Supportive nudges (popup every minute)

Supportive nudges are small prompts such as "Time for some water" or "Stretch your legs", with two buttons (an acknowledge button whose label Gemini writes, and Skip). The choice is sent to `POST /nudges/{nudge_id}/response` (`{"choice": "acknowledge" | "skip"}`) and stored on that nudge's `context_data` (`response`, `responded_at`), never as an `employee_response`, so it doesn't affect the wellbeing score. The next pool refill tells Gemini which categories the person usually acts on or skips (last 30 days).

- **Stored in `question`.** Every nudge served is saved in a background thread: one `question` row (`question_id` = `nudge_id`, `trigger_type = 'ADHOC'`, `source` `GEMINI` or `TEMPLATE`, `model_name`, `prompt_version = 'shiftguard-nudge-v1'`, `is_active = false`, `context_data = {kind: "SUPPORT_NUDGE", category, emoji, title, message, generated_by}`) plus the two buttons as `question_option` rows. Because they are inactive, nudges never show up as pending check-ins, and since no `employee_response` is written they never affect the wellbeing score. Query them with `context_data ->> 'kind' = 'SUPPORT_NUDGE'`. A failed save is only logged; the popup is still shown.

- **Agent: `GET /nudges/next`**, with the same login token as the check-in endpoints. It returns `{nudge_id, category, emoji, title, message, options: [{id: "acknowledge", label}, {id: "skip", label: "Skip"}], generated_by}`.
- **No Gemini call per request.** Each employee has an in-memory pool of 8 Gemini-written nudges. When fewer than 3 remain, one background Gemini call refills it, using the employee's role and current shift (e.g. "6 h into a day shift, 2.5 h left") and avoiding recent repeats. The first call, or any call made while Gemini is down, gets a built-in nudge. Requests take a few milliseconds. The pool is lost on restart, which is harmless.
- **Login cache.** Verified tokens are cached for 2 minutes, so per-minute polling doesn't call Django `/auth/me/` every time.
- **Frontend.** `src/lib/useSupportNudges.ts` starts a timer when the user signs in, and again after a reload. It runs on every page and calls the agent every `VITE_NUDGE_INTERVAL_MS` (default 60000 ms). A tick is skipped while the tab is hidden, while a nudge is still showing, or while a check-in question is open, so popups never stack. `src/components/SupportNudge.tsx` renders the popup in the same style as the check-in panel.

## Context-aware check-ins

- **End-of-life care.** Completing an `END_OF_LIFE_CARE` appointment serves a debrief question straight away (`served_from: "end_of_life_care"`, `trigger_type = 'POST_SHIFT'`, `context_data.focus = 'end_of_life_care'`). Any queued question stays queued for the next appointment.
- **Maternity return / onboarding.** For people back from maternity leave in the last 12 weeks, or hired in the last 90 days, Gemini's next question focuses on that (`MATERNITY_RETURN` / `ONBOARDING` trigger type).
- **Support after a low answer.** When the answer scores 1-2, `/checkin/answer` returns `support: {title, message}` (EAP, take your break, talk to your manager, with end-of-life and maternity variants). The app shows it under "Your wellbeing rhythm". It never mentions risk.

## Manager copilot (chat agent)

Managers (anyone with direct reports) and HR (`is_staff`) see an **Ask ShiftGuard AI** button on the Team, Team roster and Admin pages (`src/components/AgentCopilot.tsx`).

- **`POST /agent/stream`** (Server-Sent Events) with `{"session_id", "query"}` streams `step` (tool start/end, with a friendly label), `token`, `approval`, `message`, `error` and `done` events. `POST /agent/invoke` is the same agent as one JSON response (`pending_approval` is set while paused).
- **Login and scope.** Both need the Django token; employees without reports get 403. Managers only see their own team: every tool checks it (`services/access_scope.py`), and HR sees everyone. The conversation thread is keyed by caller and `session_id`.
- **Approval before acting.** `send_notification_email`, `reassign_shift`, `decide_leave_request` and `assign_buddy` pause the graph (LangGraph `interrupt()` in `approval_gate`). The UI shows what will happen, including the full email text, and the manager approves or declines: `{"session_id", "resume": {"approved": true|false, "comment"}}`. A declined action reaches the model as a tool result containing the manager's note. Asking a new question while an approval is pending declines it.
- **In-process tools.** The 23 tools are the same functions as the MCP servers, but called directly (`app/tools/registry.py`), so a tool call takes milliseconds instead of ~10 s. To go back to stdio MCP, set `AGENT_TOOL_MODE=mcp`; in that mode team scoping isn't enforced.

New tools (`app/mcp_server/planning_tool.py`; the simulations never save anything):

| Tool | What it does |
| --- | --- |
| `simulate_risk` | What-if: remove shifts (`remove_shift_ids`) and/or change features (`{"overtime_hours_30d": "-10"}`), then compare baseline and scenario band and score. Removing a future shift projects to that date. |
| `review_upcoming_roster` | Projects each team member's risk N days ahead on the planned rota; flags who moves up a band |
| `list_shifts` | Rota with `shift_id` and weekday, to resolve "Thursday's night shift" |
| `suggest_shift_cover` / `reassign_shift`* | Free colleagues (11 h rest preferred, HIGH/CRITICAL excluded) / move the shift, notify both people |
| `list_leave_requests` / `review_leave_request` / `decide_leave_request`* | Leave with risk now, if rejected, and after the leave / approve or reject |
| `suggest_buddy` / `assign_buddy`* | Buddy match on shift overlap, role and capacity, never showing candidates' risk / assign |
| `search_wellbeing_guidance` | Searches `app/knowledge/wellbeing_guidance.md` (prototype guidance: replace it with approved policy) |

\* needs the manager's approval.

## Daily briefing

`POST /briefing/run` (`{"rescore": false}`) builds the caller's briefing. It covers who changed band since the previous scoring and why, who is still HIGH/CRITICAL, return-to-work guideline breaches and open follow-ups. Gemini writes it, with a template fallback. `GET /briefing/latest` returns the last one. `rescore: true` first re-runs and saves the team's risk scores, like the daily batch. With `BRIEFING_ENABLED=true`, every manager's briefing is built at `BRIEFING_HOUR_UTC` each day; `BRIEFING_SEND_EMAIL=true` also emails it. Briefings are kept in memory.

## Real-time bell

After the agent records an intervention, moves a shift, decides leave, assigns a buddy or builds a briefing, it calls Django `POST /api/internal/notify/` with header `X-Agent-Key: <AGENT_INTERNAL_KEY>`. Django pushes the event on `ws/notifications/`, and the bell (`NotificationBell.tsx`) reloads at once instead of waiting for its 30 s poll. The key defaults to the same local value on both sides; set `AGENT_INTERNAL_KEY` in both `.env` files outside a local demo.

## How it fits with the other services

```
PowerPioneer-Frontend (5173) ──REST / WS──> PowerPioneer-Backend-Core (Django, 8000) ──┐
     │                                            ▲ /api/internal/notify/ (bell push)  ├──> Supabase Postgres
     └─ /agent/stream, /checkin, /nudges, /briefing ──> langgraph-agent (FastAPI, 8001) │
                                     └─ Gemini ⇄ in-process tools ──psycopg─────────────┘
                                                      └─ XGBoost model (PowerPioneer-AI/model_artifacts)
```

- The agent writes straight to the shared Supabase tables, so its results show up in the backend API and the frontend without any extra wiring. It calls Django only to verify logins and to push bell notifications.
- Risk predictions are saved with `model_name = 'XGBOOST'`. The Admin → Risk page and `/api/risk-predictions/` show them.
- Check-in questions are saved with `generated_for_employee_id`, so they appear in that employee's pending check-ins (`/api/questions/pending/`). The employee's answers become the model's `wellbeing_score` on the next run.
- Interventions show in `/api/interventions/` and Django admin.
- Run the agent on **port 8001**, because the Django backend uses 8000.

## Tools

| MCP server (file) | Tool | What it does | Writes |
| --- | --- | --- | --- |
| `employee_tool.py` | `find_employees` | Search by name, email or employee number; returns ids, manager and buddy | – |
| | `get_employee_details` | Profile, 30-day roster summary, next 7 days of shifts, latest risk | – |
| `risk_tool.py` | `predict_employee_risk` | 26 features → XGBoost → band and top 5 factors for one employee | `employee_risk_snapshot`, `risk_prediction`, `risk_explanation` |
| | `predict_risk_for_all_employees` | Daily batch for everyone with shifts in the last 30 days | same three tables |
| | `list_at_risk_employees` | Latest saved prediction per employee at or above a band | – |
| | `get_employee_risk_history` | Past predictions and the latest explanation factors | – |
| `intervention_tool.py` | `create_intervention` | Follow-up action linked to the latest prediction; manager or buddy target filled in automatically; skips duplicates within 7 days | `intervention` |
| | `update_intervention_status` | Mark as COMPLETED (sets `completed_at`), FAILED and so on | `intervention` |
| | `list_interventions` | Recent interventions, filterable by employee and status | – |
| `checkin_tool.py` | `create_checkin_question` | Personalised question with exactly 4 options scored 1–4 | `question`, `question_option` |
| | `get_checkin_responses` | Recent answers plus the 7-day wellbeing score | – |
| `notifsend_tool.py` | `send_notification_email` | SMTP email; templates `risk_alert`, `checkin_reminder`, `general` | – |

Every tool that takes an `employee` argument accepts an `employee_id`, email, `employee_number` or name. A name that matches several people returns an error listing the matches, and the agent then asks the user which one they mean.

### What a prediction writes

The tool writes three tables in this order, in one transaction:

1. **`employee_risk_snapshot`**: an upsert on `(employee_id, snapshot_date, is_training_record)` with the 26 values, `is_training_record = false`, `risk_label = risk_band` and `risk_outcome_within_30d = NULL`. Re-running for the same date updates the same row.
2. **`risk_prediction`**: `risk_score = round(probability × 100, 2)`, `risk_band`, `model_name = 'XGBOOST'`, and `model_version` from `model_config.json`. Each run adds a row, so history is kept.
3. **`risk_explanation`**: one row per top factor, with `display_order` 1–5.

Risk bands use the calibrated probability: LOW < 0.30 ≤ MEDIUM < 0.60 ≤ HIGH < 0.80 ≤ CRITICAL. These are prototype thresholds on synthetic data, not a clinical assessment.

How the features are computed:

- Everything is computed from the app tables in UTC.
- `wellbeing_score` is the mean check-in answer over the last 7 days, on the 1–4 scale.
- `end_of_life_care_7d` counts the employee's shifts with `shift_roster.end_of_life_care_flag = true` that started in the 7 days ending on the scoring date.
- Employees with no shifts in the last 30 days, such as managers, are skipped.
- Features #1–#19 and #21–#25 were checked against Django's `extract_features` for all 20 operational employees on 2026-11-18 and match exactly.

## Setup

1. **Install the dependencies** (Python 3.14 `.venv`, Windows or Linux):
   ```
   cd PowerPioneer-AI/langgraph-agent
   .venv\Scripts\python -m pip install -r requirements.txt
   ```
   This includes `xgboost`, `pandas` and `scikit-learn` at the versions the model was trained with.

2. **Fill in `.env`** in `langgraph-agent/`. The file is git-ignored.

   | Variable | Needed for | Note |
   | --- | --- | --- |
   | `GEMINI_API_KEY` | everything | Required: the app does not start without it |
   | `SUPABASE_DB_HOST`, `SUPABASE_DB_PORT`, `SUPABASE_DB_USER`, `SUPABASE_DB_PASSWORD` | all database tools | Same values as the backend's `.env`. Session pooler is port 5432. |
   | `SUPABASE_DB_URL` | optional | Takes priority when set. Leave it empty, or fill in the real password: a value still containing `[YOUR-PASSWORD]` is ignored with a warning. |
   | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` | emails only | For Gmail, `SMTP_USERNAME` is the full Gmail address and `SMTP_PASSWORD` is a 16-character app password |
   | `RISK_MODEL_ARTIFACT_DIR` | optional | Defaults to `PowerPioneer-AI/model_artifacts` |
   | `INTERVENTION_DEDUP_DAYS`, `CHECKIN_QUESTION_EXPIRY_HOURS` | optional | Defaults are 7 and 24 |

3. **Run it** from `langgraph-agent/`. Don't use `--reload`: the MCP servers are child processes.
   ```
   .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
   ```
   At startup the log should list 23 in-process tools. Swagger is at `http://127.0.0.1:8001/docs`.

4. **Optional test UI.** In `frontend/med-agent`, run `npm install`, then `npm run dev`. It calls `http://localhost:8001/agent/invoke`, or `VITE_AGENT_API_URL` if that is set.

## Calling the agent

`POST /agent/invoke`

```json
{
  "query": "Who is at high risk today and why?",
  "session_id": "manager-sonia-2026-11-18",
  "user_id": "<employee_id of the person asking>",
  "organization_id": "bupa",
  "organization_name": "Bupa"
}
```

Send the Django access token as `Authorization: Bearer <token>` (or set `AGENT_REQUIRE_AUTH=false` for local curl tests, which runs as HR). Response: `{"response": "<answer>", "token_usage": "...", "pending_approval": null}`.

The conversation memory is kept per `session_id`, in memory only, so it is lost on restart. Reuse the same `session_id` for follow-up questions.

```
curl -X POST http://127.0.0.1:8001/agent/invoke -H "Content-Type: application/json" ^
  -d "{\"query\":\"Run today's risk scoring for everyone\",\"session_id\":\"s1\",\"user_id\":\"u1\",\"organization_id\":\"bupa\",\"organization_name\":\"Bupa\"}"
```

## Example requests and the tools Gemini picks

| Ask | Tools called |
| --- | --- |
| "Run today's risk scoring for everyone" | `predict_risk_for_all_employees` |
| "Who is high risk today?" | `list_at_risk_employees` |
| "Why is Priya Arora's risk critical?" | `get_employee_risk_history` (and possibly `get_employee_details`) |
| "Recalculate Vikram's risk for 2026-11-18" | `predict_employee_risk` |
| "How has Aditi been feeling this week?" | `get_checkin_responses` |
| "Email Priya's manager and set up a check-in for her" | `find_employees` → `create_intervention` (EMAIL_MANAGER) → `create_checkin_question` → `send_notification_email` (`risk_alert`) → `update_intervention_status` (COMPLETED) |
| "Show pending interventions" | `list_interventions` |

The agent asks before taking outward or bulk actions the user didn't request, such as emails or interventions for many people.

## Daily routine for the demo

1. Run the scoring for everyone. The demo data covers 2026-08-20 to 2026-11-25, so use 2026-11-18.
2. Ask who is HIGH or CRITICAL.
3. For each flagged person, ask the agent to notify the manager and create a check-in.
4. The employee answers in the ShiftGuard app. The next scoring run picks up the new `wellbeing_score`.

## Things to watch

- **Two scorers share `risk_prediction`.** Django's `calculate_wellbeing` writes `model_name = 'wellbeing-rules'` to the same live snapshot row and overwrites `wellbeing_score` with a 0–100 value. Don't run it for a date the agent scores. Dashboards should filter on `model_name = 'XGBOOST'`.
- **Check-in options must be scored 1–4.** The check-in tool enforces this. Questions created elsewhere must follow the same scale.
- **Training rows are never used as input.** The agent always writes `is_training_record = false` and reads only live rows.
- **Wellbeing data is personal.** The agent's prompt keeps risk scores out of messages sent to employees.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `GEMINI_API_KEY Field required` at startup | `.env` is missing, or the key is empty |
| `password authentication failed` | Wrong `SUPABASE_DB_PASSWORD`, or a `SUPABASE_DB_URL` with a stale password. Empty the URL to use the individual fields. |
| `Skipped: ... no shifts` | The employee has no shifts in the 30 days before the date. This is expected for managers. |
| `SMTP authentication failed` | Use the full Gmail address as `SMTP_USERNAME` and an app password |
| Port 8000 already in use | The Django backend is running there. Start the agent on 8001. |
| Each tool call takes about 10 s | `AGENT_TOOL_MODE=mcp` is set: each MCP call starts a server process. Remove it to use the in-process tools. |
| `503 UNAVAILABLE ... high demand` from Gemini | Google-side overload. Retry later; the agent returns the error text instead of an answer. |
