"""Hands-on tester for the AggieConnect classifier and ranking (Dev 3).

Run from the repo root with the backend venv's Python:

  backend/.venv/Scripts/python demo/try_classifier.py list
  backend/.venv/Scripts/python demo/try_classifier.py show intern-001 --profile cs_internship
  backend/.venv/Scripts/python demo/try_classifier.py eval                  # labeled scorecard
  backend/.venv/Scripts/python demo/try_classifier.py feed --profile me_research
  backend/.venv/Scripts/python demo/try_classifier.py try --subject "..." --body "..."
  backend/.venv/Scripts/python demo/try_classifier.py try --file my_email.txt

--mode chooses the extractor:
  fallback  rule-based classifier only (default; no key needed)
  canned    recorded model outputs from sample_emails.json (fixtures only)
  live      real OpenAI call; needs OPENAI_API_KEY and OPENAI_MODEL set.
            Use SYNTHETIC text only, never real email.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

from app.schemas.classification import NormalizedMessage, Preferences  # noqa: E402
from app.services.ai_classifier import CannedProvider, classify_email, provider_from_env  # noqa: E402
from app.services.ranking_service import feed_sort_key, rank  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

FIXTURES = json.loads((REPO / "demo" / "sample_emails.json").read_text(encoding="utf-8"))["messages"]
PROFILES = json.loads((REPO / "demo" / "sample_preferences.json").read_text(encoding="utf-8"))["profiles"]
BY_ID = {f["id"]: f for f in FIXTURES}


def to_message(f) -> NormalizedMessage:
    return NormalizedMessage(
        id=f["id"], subject=f["subject"], body=f["body"], sender=f.get("sender"),
        received_at=f["received_at"], verified_emergency_source=f.get("verified_emergency_source", False),
    )


ENV_FILE = REPO / "backend" / ".env"


def load_env_file(path=ENV_FILE):
    """Load KEY=VALUE lines from backend/.env into os.environ.

    Variables already set in the shell win. Values are never printed.
    """
    if not path.exists():
        return []
    loaded = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def make_provider(mode):
    if mode == "fallback":
        return None
    if mode == "canned":
        return CannedProvider({f["id"]: f["model_output"] for f in FIXTURES})
    load_env_file()
    provider = provider_from_env()
    if provider is None:
        missing = [k for k in ("OPENAI_API_KEY", "OPENAI_MODEL") if not os.environ.get(k)]
        sys.exit(
            "live mode needs %s. Put them in backend/.env (copy backend/.env.example) "
            "or set them in your shell." % " and ".join(missing)
        )
    print("Live provider: model=%s (key loaded, not shown)" % provider.model)
    return provider


def load_profile(name):
    if name not in PROFILES:
        sys.exit("Unknown profile %r. Choose from: %s" % (name, ", ".join(PROFILES)))
    return Preferences(**PROFILES[name])


def fmt(value):
    if value is None:
        return "-"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)


def print_result(result, prefs=None):
    c = result.classification
    print("  source        : %s%s" % (result.source.value,
                                       "  (reason: %s)" % result.fallback_reason if result.fallback_reason else ""))
    print("  category      : %s" % c.category.value)
    print("  priority lane : %s   (model suggested: %s)" % (result.priority.value, c.suggested_priority.value))
    print("  verified      : %s" % result.verified_source)
    print("  needs review  : %s" % result.needs_review)
    print("  title         : %s" % c.title)
    print("  summary       : %s" % c.summary)
    print("  tags          : %s" % ", ".join(c.tags))
    print("  event         : %s -> %s" % (fmt(c.event_start), fmt(c.event_end)))
    print("  deadline      : at %s | date %s" % (fmt(c.deadline_at), fmt(c.deadline_date)))
    print("  location      : %s" % fmt(c.location))
    print("  confidence    : %.2f" % c.confidence)
    if prefs is not None:
        r = rank(c, prefs)
        print("  relevance     : %d / 100" % r.relevance_score)
        print("  reason        : %s" % r.relevance_reason)


def compare(result, expected, lenient_review):
    """Return list of (field, expected, actual) mismatches."""
    c = result.classification
    misses = []

    def check(field, want, got):
        if want != got:
            misses.append((field, want, got))

    if "category" in expected:
        check("category", expected["category"], c.category.value)
    if "priority" in expected:
        check("priority", expected["priority"], result.priority.value)
    if "verified_source" in expected:
        check("verified_source", expected["verified_source"], result.verified_source)
    if "needs_review" in expected:
        if not lenient_review:
            check("needs_review", expected["needs_review"], result.needs_review)
        elif expected["needs_review"] and not result.needs_review:
            misses.append(("needs_review", True, False))
    for key in ("event_start", "event_end", "deadline_at"):
        if key in expected:
            want = expected[key] and datetime.fromisoformat(expected[key])
            check(key, want, getattr(c, key))
    if "deadline_date" in expected:
        want = expected["deadline_date"] and date.fromisoformat(expected["deadline_date"])
        check("deadline_date", want, c.deadline_date)
    if "location" in expected:
        check("location", expected["location"], c.location)
    missing_tags = [t for t in expected.get("tags_include", []) if t not in c.tags]
    if missing_tags:
        misses.append(("tags_include", missing_tags, c.tags))
    return misses


def cmd_list(args):
    for f in FIXTURES:
        print("%-24s %s" % (f["id"], f.get("label", f["subject"])))


def cmd_show(args):
    if args.id not in BY_ID:
        sys.exit("Unknown fixture %r. Run 'list' to see ids." % args.id)
    f = BY_ID[args.id]
    print("%s  [%s]" % (f["id"], f.get("label", "")))
    print("  subject       : %s" % f["subject"])
    print("  expected      : %s" % json.dumps(f["expected"]))
    print()
    result = classify_email(to_message(f), provider=make_provider(args.mode))
    print_result(result, load_profile(args.profile) if args.profile else None)
    misses = compare(result, f["expected"], lenient_review=args.mode == "fallback")
    print()
    print("  label check   : %s" % ("PASS" if not misses else "FAIL"))
    for field, want, got in misses:
        print("    %-14s expected %s, got %s" % (field, fmt(want), fmt(got)))


def cmd_eval(args):
    provider = make_provider(args.mode)
    passed = 0
    field_misses = {}
    print("%-24s %-6s %-12s %-10s %s" % ("fixture", "result", "category", "lane", "mismatches"))
    for f in FIXTURES:
        result = classify_email(to_message(f), provider=provider)
        misses = compare(result, f["expected"], lenient_review=args.mode == "fallback")
        passed += not misses
        for field, _, _ in misses:
            field_misses[field] = field_misses.get(field, 0) + 1
        print("%-24s %-6s %-12s %-10s %s" % (
            f["id"], "PASS" if not misses else "FAIL", result.classification.category.value,
            result.priority.value, ", ".join(m[0] for m in misses) or "",
        ))
    print()
    print("mode=%s  passed %d/%d fixtures" % (args.mode, passed, len(FIXTURES)))
    if field_misses:
        print("mismatches by field: %s" % ", ".join("%s=%d" % kv for kv in sorted(field_misses.items())))
    print("Run 'show <id> --mode %s' to see details for a failing fixture." % args.mode)
    return 0 if passed == len(FIXTURES) else 1


def cmd_feed(args):
    prefs = load_profile(args.profile)
    provider = make_provider(args.mode)
    rows = []
    for f in FIXTURES:
        result = classify_email(to_message(f), provider=provider)
        r = rank(result.classification, prefs)
        rows.append((feed_sort_key(result.priority, r.relevance_score, result.received_at,
                                   result.message_id, result.verified_source), result, r))
    rows.sort(key=lambda row: row[0])
    print("Feed for profile %r (mode=%s): %s" % (args.profile, args.mode, json.dumps(PROFILES[args.profile])))
    print()
    print("%-3s %-10s %-5s %-24s %s" % ("#", "lane", "score", "fixture", "reason"))
    for i, (_, result, r) in enumerate(rows, 1):
        flag = " [review]" if result.needs_review else ""
        print("%-3d %-10s %-5d %-24s %s%s" % (i, result.priority.value, r.relevance_score,
                                            result.message_id, r.relevance_reason, flag))


def cmd_try(args):
    if args.file:
        body = Path(args.file).read_text(encoding="utf-8")
    elif args.body is not None:
        body = args.body
    else:
        print("Paste the email body, then Ctrl+Z Enter (Windows) or Ctrl+D (Mac/Linux):")
        body = sys.stdin.read()
    received = args.received or datetime.now(timezone.utc).isoformat()
    message = NormalizedMessage(
        id="custom", subject=args.subject or "", body=body, sender=args.sender,
        received_at=received, verified_emergency_source=args.verified,
    )
    if args.mode == "canned":
        sys.exit("canned mode only works for fixtures; use fallback or live.")
    result = classify_email(message, provider=make_provider(args.mode))
    print_result(result, load_profile(args.profile) if args.profile else None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def add_mode(p, default="fallback"):
        p.add_argument("--mode", choices=["fallback", "canned", "live"], default=default)

    sub.add_parser("list", help="list fixture ids")
    p = sub.add_parser("show", help="classify one fixture and check it against its labels")
    p.add_argument("id")
    p.add_argument("--profile", help="also rank against a profile from sample_preferences.json")
    add_mode(p)
    p = sub.add_parser("eval", help="scorecard of every fixture against its labels")
    add_mode(p)
    p = sub.add_parser("feed", help="show the ranked feed for a profile")
    p.add_argument("--profile", default="cs_internship")
    add_mode(p)
    p = sub.add_parser("try", help="classify your own (synthetic) email")
    p.add_argument("--subject")
    p.add_argument("--body")
    p.add_argument("--file", help="read the body from a text file")
    p.add_argument("--sender")
    p.add_argument("--received", help="ISO timestamp with offset, default now")
    p.add_argument("--verified", action="store_true", help="simulate trusted emergency provenance")
    p.add_argument("--profile")
    add_mode(p)

    args = parser.parse_args(argv)
    handler = {"list": cmd_list, "show": cmd_show, "eval": cmd_eval, "feed": cmd_feed, "try": cmd_try}
    return handler[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())
