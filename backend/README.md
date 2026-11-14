# AggieConnect Backend (Developer 4)

## Status
This is a starter vertical slice for local synthetic/demo development. It includes health,
short-lived demo sessions, preferences, opportunity list/detail/save routes, and the
PostgreSQL schema. It is **not production-ready**: repositories are currently in-memory,
live Entra JWT validation, Graph OBO, sync orchestration, calendar idempotency, migrations,
and integration tests still need implementation.

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
`/api/me/preferences`, and `/api/opportunities`.

## Database
Apply `database/schema.sql` with a migration/database-owner role to a disposable PostgreSQL
database. Do not use the runtime credential for migrations. The schema is isolated in
`aggieconnect`; configure the runtime role with only the required schema/table privileges.
