# Bupa ShiftGuard Source

React + Vite frontend for ShiftGuard, integrated with the Django REST API in `../PowerPioneer-Backend-Core`.

## Run locally

1. Start the backend (see `../PowerPioneer-Backend-Core/README.md`):
   `python manage.py migrate`, `python manage.py seed_data`, `python manage.py runserver`.
2. Install Node.js 20 or newer.
3. Run `npm install`.
4. Run `npm run dev` and open http://localhost:5173.
5. Sign in with a demo account, such as `jordan.reyes@powerpioneer.local` / `Password@123`, or create one on the **Sign up** tab.

## Backend URL (single point of configuration)

Every request uses a **partial URL** (for example `api.get("/shifts/")`), which is joined onto one base URL defined in
[`src/api/config.ts`](src/api/config.ts). WebSocket paths such as `/ws/notifications/` are joined the same way.

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000/api` | REST base URL |
| `VITE_WS_BASE_URL` | Derived from the API URL (`ws://127.0.0.1:8000`) | WebSocket base URL |

To override them, copy `.env.example` to `.env.local`. The backend must allow the frontend's origin through CORS. Set it
with `DJANGO_CORS_ALLOWED_ORIGINS`. The default covers `localhost:5173` and `localhost:4173`.

## Code layout

```
src/api/config.ts        base URLs (the only place they are defined)
src/api/client.ts        fetch wrapper: JWT header, auto refresh on 401, DRF error formatting, pagination
src/api/types.ts         types mirroring the backend serializers
src/auth/AuthContext.tsx login, register, logout, session restore
src/lib/                 formatting, data-loading hooks, WebSocket hook, hash router
src/components/          UI kit (reuses the existing styles), header menus, manager/buddy panel
src/pages/               Login/Sign up, profile, wellbeing, roster, leave, interventions, chat, admin
src/App.tsx              original "My shift" and "Team view" screens, now backed by the API
src/integration.css      styles for the new pages (additive only; styles.css is unchanged)
```

## Pages and the APIs they use

| Page | Endpoints |
|------|-----------|
| Sign in / Sign up | `/auth/token/`, `/auth/register/`, `/auth/token/verify/`, `/auth/token/refresh/`, `/auth/logout/` |
| My shift | `/auth/me/`, `/shifts/`, `/questions/pending/`, `/questions/{id}/answer/`, `/wellbeing/calculate/` |
| Team view (managers and staff) | `/wellbeing/team/`, `/risk-snapshots/`, `/shifts/`, `/interventions/` (create and transitions), `/employees/{id}/` and its assign/remove manager, assign/remove buddy and suggest-buddies actions |
| My profile | `/auth/me/`, `/auth/change-password/`, `/employees/{id}/buddy-assignees/` |
| My wellbeing | `/wellbeing/me/`, `/wellbeing/calculate/`, `/risk-predictions/`, `/risk-snapshots/`, `/employee-responses/`, `/questions/` |
| Full roster / Team roster | `/shifts/` and `/attendance/` (full CRUD for managers), `/employees/{id}/team/` |
| Leave requests | `/leave-requests/` CRUD plus `approve`, `reject` and `cancel` |
| Interventions + bell | `/interventions/` CRUD plus `start`, `complete`, `fail` and `cancel`; live pushes from `ws/notifications/` |
| Team chat | `ws/chat/<room>/` and `ws/chat/direct/<employee_id>/` |
| Administration (staff) | `/employees/` CRUD plus `deactivate`, `/questions/` and `/question-options/` CRUD, `/employee-responses/`, `/risk-snapshots/`, `/risk-predictions/`, `/risk-explanations/`, `/wellbeing/calculate-all/` |

The extra pages open from the profile chip menu in the header. "Team view" appears only for managers (employees with
direct reports) and staff, and "Administration" only for staff.

These widgets stay static because the backend has no data for them: the appointment-level schedule, next break, the
12-week team chart, the leading-factor bars and the check-in participation figure.

## Build

Run `npm run build`. The output is written to `dist/`.
