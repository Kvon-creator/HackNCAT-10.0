# AI classifier and ranking (Dev 3)

Branch: `feature/ai-classifier`. Converts a normalized Outlook message into validated
opportunity data and ranks it against student preferences.

## What is built

| File | Purpose |
|---|---|
| `backend/app/schemas/classification.py` | Category/Priority enums, `Classification` (model output), `ClassifiedMessage` (result), `Preferences`, `RankResult`, `NormalizedMessage` (input) |
| `backend/app/services/ai_classifier.py` | `classify_email()`: sanitize → OpenAI Structured Outputs (or stub) → validate → rule fallback on failure → time grounding → trust policy |
| `backend/app/services/ranking_service.py` | `rank()`, `rank_tags()`, `feed_sort_key()`: deterministic 35/25/20/10/10 scoring and lane ordering |
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

Use synthetic text only. Set the variables in your shell, never in source:

```
# PowerShell
$env:OPENAI_API_KEY = "<key>"; $env:OPENAI_MODEL = "<structured-outputs model>"
backend/.venv/Scripts/python demo/try_classifier.py eval --mode live
```

## Contract for teammates

```python
classify_email(normalized_message, provider=None, previous=None) -> ClassifiedMessage
rank(classification, preferences) -> RankResult          # or rank_tags(stored_tags, preferences)
feed_sort_key(priority, relevance_score, received_at, id, verified_source)
```

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

## Open items needing input

- `docs/api-contract.md` (Dev 4): freeze field names, the `NormalizedMessage` input shape, and
  whether an unverified `emergency` category should become `general` or `other`.
- `OPENAI_MODEL` choice and a key for the live run.
- Python version for CI/Render (this code needs 3.9 or newer).
- Final alias list for majors, interests and organizations in `ranking_service.ALIASES`.
