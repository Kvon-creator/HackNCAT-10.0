# AggieConnect API contract (starter)

All routes are prefixed with `/api`. Live mode will require an AggieConnect API access token.
Synthetic mode uses `POST /demo/session`; the demo session must be disabled in live deployment.

| Method | Route | Contract |
|---|---|---|
| GET | `/health` | `200 {"status":"ok"}` |
| POST | `/demo/session` | `201 {"access_token":"…","expires_in":3600}` |
| GET | `/me` | Verified user ID, display name, preferences, runtime mode |
| PUT | `/me/preferences` | Accept major, academic_level, interests, organizations, career_goals, show_reminders |
| GET | `/opportunities` | Filters `q`, `category`, `priority`, `saved`; limit 1–50; offset >= 0 |
| GET | `/opportunities/{id}` | Opportunity; return 404 for absent/foreign IDs |
| POST | `/opportunities/{id}/save` | Idempotent save; 204 |
| DELETE | `/opportunities/{id}/save` | Idempotent unsave; 204 |

Errors must use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`.
The starter currently uses FastAPI's default HTTP error shape; standard error middleware is
a remaining implementation task before contract sign-off.

Opportunity category values: internship, scholarship, research, event, academic, emergency,
general, other. Priority values: emergency, urgent, deadline, general.
