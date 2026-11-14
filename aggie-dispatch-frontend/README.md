# Aggie Dispatch Frontend

This is a standalone HTML, CSS, and JavaScript export of the Aggie Dispatch student hub. It does not require Fluxscape or a build step.

## Run locally

1. Open index.html in a modern browser, or serve this folder with any static web server.
2. With Python, run python -m http.server 8000 from this folder and open http://localhost:8000.

## Run with the AggieConnect API (live demo feed)

`api-bridge.js` replaces the static Home digest with the AI-ranked feed from the backend.
If the API is unreachable, the static sample content stays on screen.

1. Start the backend (Python 3.11): from `backend/`, run
   `.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000` (Windows) or
   `.venv/bin/python -m uvicorn app.main:app --reload --port 8000`.
2. Serve this folder on port 5173 (the backend's `FRONTEND_ORIGIN`):
   `python -m http.server 5173`, then open **http://localhost:5173** (use `localhost`, not
   `127.0.0.1`, or the browser blocks the API calls).

What is connected:

- **Feed:** a demo session is created automatically, and the Home digest shows all ranked opportunities with lane, match score, reason and dates.
- **Persona switcher:** in the sidebar, it saves that student's preferences and re-ranks the feed.
- **Save:** the button saves or unsaves the opportunity in the API.
- **+ Google Calendar:** opens Google Calendar in a new tab with the event filled in (title, time in campus time, location, summary and match reason). The student reviews it and clicks Save. No Google setup or API keys are needed, and it works with any Google account.
- **Simulate Outlook add:** asks for a confirming second click, then records a simulated event through `POST /api/calendar/events` and adds it to the page's November calendar. Live Outlook needs NC A&T app registration.
- **Loading and offline states:** "Ranking your announcements…" shows until the feed arrives. If the API can't be reached, the sample digest appears labeled "Sample digest • AggieConnect is offline".

## Offline-ready styling

- **Fonts:** bundled in `fonts/` and declared in `fonts.css` (latin subset, SIL Open Font License), so Google Fonts isn't needed at runtime.
- **Tailwind:** the page still loads Tailwind from its CDN. To remove that last internet dependency, build a local stylesheet with the same theme:
  `npx tailwindcss@3.4.17 -c tailwind.config.js -i tailwind.input.css -o tailwind.css --minify`
  Then replace the `cdn.tailwindcss.com` script and the inline `tailwind.config` script in `index.html` with `<link href="tailwind.css" rel="stylesheet" />`, placed after the page's `<style>` block so the cascade stays the same.
- **Refresh inbox:** the button calls `POST /api/sync`.

Options:

- `?api=https://your-backend/api` points the page at another backend. If you use it, set that backend's `FRONTEND_ORIGIN` to this page's origin.
- `?persona=cs|biz|bio` preselects a student.

## Edit

The page markup, styles, and client-side interactions are in index.html. The bulldog mark is embedded as a PNG data URL, so no separate image asset is needed.

## External assets

The page currently loads Tailwind CSS and the Inter, JetBrains Mono, and Newsreader fonts from public CDNs. Internet access is needed for those assets; the page content and inline interactions remain in the exported HTML.
