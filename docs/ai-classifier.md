# AI classifier and ranking (Dev 3)

Branch: `feature/ai-classifier`. Converts a normalized Outlook message into validated
opportunity data and ranks it against student preferences.

## What is built

| File | Purpose |
|---|---|
| `backend/app/schemas/classification.py` | Category/Priority enums, `Classification` (model output), `ClassifiedMessage` (result), `Preferences`, `RankResult`, `NormalizedMessage` (input) |
| `backend/app/services/ai_classifier.py` | `classify_email()`: sanitize → OpenAI Structured Outputs (or stub) → validate → rule fallback on failure → time grounding → trust policy |
| `backend/app/services/ranking_service.py` | `rank()`, `rank_tags()`, `feed_sort_key()`: deterministic 35/25/20/10/10 scoring and lane ordering |
| `backend/app/services/demo_feed.py` | `build_demo_feed()`, `rerank_feed()`, `to_public()`: demo-mode feed of `Opportunity`-shaped records from the fixtures, no API calls |
| `demo/sample_emails.json` | 13 labeled synthetic emails, each with a recorded model output |
| `demo/sample_preferences.json` | Synthetic student profiles |
| `demo/try_classifier.py` | Hands-on tester (below) |
| `backend/tests/` | pytest suite, no network or API key needed |

## Setup (once)

Needs Python 3.9 or newer (`zoneinfo`). From the repo root:

```
py -3.9 -m venv backend/.venv            # Windows; on Mac/Linux: python3 -m venv backend/.venv
backend/.venv/Scripts/python -m pip install -r backend/requirements-ai.txt
```

On Mac/Linux use `backend/.venv/bin/python` wherever this guide says `backend/.venv/Scripts/python`.

## Ways to test

**1. Automated tests**

```
backend/.venv/Scripts/python -m pytest backend -q
```

Covers labels on every fixture (model path and fallback), spoofed emergency, prompt
injection, forged urgency, invalid / refused / incomplete / timed-out provider output,
keeping a prior result on transient errors, fabricated-time removal, sanitizing, the
OpenAI request shape (no tools, strict schema, `store=False`), and ranking order.

**2. Scorecard against the labels**

```
backend/.venv/Scripts/python demo/try_classifier.py eval                 # rule fallback
backend/.venv/Scripts/python demo/try_classifier.py eval --mode canned   # recorded model outputs
backend/.venv/Scripts/python demo/try_classifier.py eval --mode live     # real provider, see below
```

**3. Inspect one fixture**

```
backend/.venv/Scripts/python demo/try_classifier.py list
backend/.venv/Scripts/python demo/try_classifier.py show intern-001 --profile cs_internship
```

**4. See the ranked feed and how preferences change it**

```
backend/.venv/Scripts/python demo/try_classifier.py feed --profile cs_internship
backend/.venv/Scripts/python demo/try_classifier.py feed --profile me_research
```

Edit `demo/sample_preferences.json` to try your own profile.

**5. Classify your own synthetic email**

```
backend/.venv/Scripts/python demo/try_classifier.py try --subject "Robotics talk" --body "Talk on December 9, 2026 at 4 p.m. ET in McNair Hall." --profile cs_internship
backend/.venv/Scripts/python demo/try_classifier.py try --file my_email.txt
```

Add `--verified` to simulate trusted emergency provenance.

**6. Live provider (hours 12–16)**

Use synthetic text only. Copy `backend/.env.example` to `backend/.env` (git-ignored) and fill in
`OPENAI_MODEL` and `OPENAI_API_KEY` there, never in `.env.example`. Shell variables override the file.

```
backend/.venv/Scripts/python demo/try_classifier.py eval --mode live --delay 6
```

The `answered` column must say `model` for every row; a `fallback` row means the provider call
failed (quota, rate limit, wrong model) and counts as a failure. One run costs 13 requests;
`--delay` spaces calls for accounts with low rate limits.

**Backup demo walkthrough:** `backend/.venv/Scripts/python demo/try_classifier.py present`
steps through the three demo moments (80-point match and re-rank, spoofed emergency, prompt
injection), pausing for Enter between them. Options: `--profile`, `--switch-to` (default
`cs_research`: the same Computer Science student, interested in research instead of internships),
`--no-pause`, `--mode canned|fallback`.

**Demo / presentation:** use `--mode canned`. It replays the recorded schema-valid outputs in
`sample_emails.json` through the same validation, grounding and trust policy, with no API calls.

## Contract for teammates

```python
classify_email(normalized_message, provider=None, previous=None) -> ClassifiedMessage
rank(classification, preferences) -> RankResult          # or rank_tags(stored_tags, preferences)
feed_sort_key(priority, relevance_score, received_at, id, verified_source)
```

Live classification for the site's "Try any announcement" panel: `POST /api/classify`
(`backend/app/routers/classify.py`, approved by Dev 4) takes `{subject, body, sender?}`, returns the
classified, ranked result plus `classified_by` and `safety_notes` (`ai_classifier.safety_signals`),
and stores nothing. It uses the rule-based classifier unless `OPENAI_API_KEY` and `OPENAI_MODEL` are
set in the server's process environment. A message asking for credentials is filed as `other`, never
as an opportunity.

Demo mode (seed a user's feed without OpenAI):

```python
from app.services.demo_feed import build_demo_feed, rerank_feed, to_public
items = build_demo_feed(user_id, preferences)   # sorted, each has user_id, id (UUID, stable per user)
items = rerank_feed(items, new_preferences)     # after PUT /me/preferences; keeps saved/calendar state
public = [to_public(x) for x in items]          # exactly the Opportunity contract fields
```

Fixtures load from a copy bundled at `backend/app/data/sample_emails.json`, so a deploy rooted at
`backend/` (Render) needs no extra setup. `demo/sample_emails.json` is the canonical file: after
editing it, copy it over the bundled one (a test fails if they differ). `AGGIECONNECT_DEMO_FIXTURES`
overrides the path.

- `provider=None` → labeled rule fallback (`source="fallback"`). Use `provider_from_env()` for
  live, `CannedProvider` for demo mode.
- Cache on `(content_hash, classifier_version)`. Pass the stored result as `previous` so a
  timeout keeps it (`source="previous"`).
- `priority` on the result is the final lane. `classification.suggested_priority` is the model's
  advisory suggestion and must not be used for sorting.
- `verified_source` comes only from `NormalizedMessage.verified_emergency_source`, set by
  trusted pipeline code (fixture metadata in the prototype).

## Trust and grounding rules

- Unverified emergency → `deadline` if a validated deadline exists, else `general`, with `needs_review`.
  An unverified `emergency` category becomes `general`.
- `urgent` needs urgency language plus a stated date within 72 hours, or a verified source.
- `deadline` needs a deadline value.
- If the message states no time of day, model-supplied times are removed (a deadline keeps its date).
- Prompt-injection phrasing and credential requests set `needs_review`.
- Model-supplied dates are cleared when the message states no explicit calendar date
  (relative wording like "within 1 hour" or "Thursday" is left for the student).
- Unverified messages that ask for credentials or identity checks stay in the `general` lane.
- A stated date that no field captured (e.g. an event date with no time) sets `needs_review`.

## Live validation

`gpt-6-luna`, 2026-11-13: 13/13 fixtures passed with every answer from the model, after fixing
three findings from earlier live runs (spoofed lockdown routed to the deadline lane via an
inferred date, missing-time review left to the model, an over-strict location label).

## Open items needing input

- `docs/api-contract.md` (Dev 4): add the classifier input (`NormalizedMessage`) and stored result
  (`ClassifiedMessage`) shapes, and confirm an unverified `emergency` category becomes `general`.
- Shared types: `Category`, `Priority` and `Preferences` exist in both `schemas/opportunity.py`
  and `schemas/classification.py`; keep one (preference list limits differ: 50 vs 20).
- Python version: the backend starter needs 3.10+; this module needs 3.9+.
- `config.py` and Render: add `OPENAI_MODEL` and `OPENAI_API_KEY`.
- Final alias list for majors, interests and organizations in `ranking_service.ALIASES`.
