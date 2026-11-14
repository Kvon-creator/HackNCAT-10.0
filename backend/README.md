# AggieConnect Backend (Developer 4)

## Status
This is a starter vertical slice for local synthetic/demo development. It includes health,
short-lived demo sessions, preferences, opportunity list/detail/save, inbox sync, calendar
write recovery, and the PostgreSQL schema. Feed and calendar repositories are still
process-local, so live data is not durable across restarts and this is not production-ready.

## Run locally
```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```
Open http://127.0.0.1:8000/docs.

## Quick demo
```bash
curl -X POST http://127.0.0.1:8000/api/demo/session
```
Use the returned `access_token` as `Authorization: Bearer <token>` for `/api/me`,
`/api/me/preferences`, `/api/opportunities`, `/api/sync`, and `/api/calendar/events`.
Demo refreshes use fixtures and demo calendar writes are simulated.

For a live tenant, set `DEMO_MODE=false`, configure the tenant, API application ID and
server-only API client secret in `.env`, and grant the API `access_as_user`, `Mail.Read`,
and `Calendars.ReadWrite` permissions with required tenant consent. The API validates the
incoming API access token before calling Graph through OBO.

## Database
Apply `database/schema.sql` with a migration/database-owner role to a disposable PostgreSQL
database. Do not use the runtime credential for migrations. The schema is isolated in
`aggieconnect`; configure the runtime role with only the required schema/table privileges.
