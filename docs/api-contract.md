# AggieConnect API contract (starter)

All routes are prefixed with `/api`. Live mode requires a tenant-specific Entra API access
token with the delegated `access_as_user` scope. The API validates the token before passing
its assertion to the Graph OBO adapter. Synthetic mode uses `POST /demo/session`; demo mode
never calls Graph and uses fixtures plus a simulated calendar.

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
| POST | `/sync` | Bounded recent inbox refresh; 200 with `fetched`, `imported`, `unchanged`, `skipped`, `failed` counts |
| POST | `/calendar/events` | Confirmed calendar write or simulation; 201 created, 200 replay |

Calendar request: `{ "opportunity_id": "UUID", "confirmed": true, "all_day": false,
"start": "ISO-8601 with offset", "end": "ISO-8601 with offset", "time_zone": "IANA zone" }`.
All-day start/end are `YYYY-MM-DD`; the end date is exclusive. A live write reuses the same
server-generated Graph `transactionId` after a pending/uncertain result. Response:
`{ "id": "Graph event ID", "status": "added", "web_link": "validated Outlook URL", "simulated": false }`.
The adapter exposes retry delays through `Retry-After` and account claims challenges through
`WWW-Authenticate`; clients may pass the claims value to MSAL when reacquiring the API token.

Errors use `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`.
Raw Graph errors, access tokens, and assertions must never be returned or logged.

Opportunity category values: internship, scholarship, research, event, academic, emergency,
general, other. Priority values: emergency, urgent, deadline, general.
