"""Tests for the demo-mode feed helper (app/services/demo_feed.py)."""

import ast
import json
import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.services import demo_feed
from app.services.demo_feed import (
    INTERNAL_FIELDS,
    PUBLIC_FIELDS,
    build_demo_feed,
    rerank_feed,
    to_public,
)
from conftest import BACKEND, PROFILES

CATEGORIES = {"internship", "scholarship", "research", "event", "academic", "emergency", "general", "other"}
PRIORITIES = {"emergency", "urgent", "deadline", "general"}


def _opportunity_contract_fields():
    """Field names of Dev 4's Opportunity model, read without importing it
    (it uses Python 3.10+ syntax)."""
    tree = ast.parse((BACKEND / "app" / "schemas" / "opportunity.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Opportunity":
            return [s.target.id for s in node.body if isinstance(s, ast.AnnAssign)]
    raise AssertionError("Opportunity model not found")


def test_public_fields_match_dev4_opportunity_schema():
    assert list(PUBLIC_FIELDS) == _opportunity_contract_fields()


def test_feed_has_every_fixture_scoped_to_user():
    items = build_demo_feed("user-a", PROFILES["cs_internship"])
    assert len(items) == 13
    assert all(item["user_id"] == "user-a" for item in items)
    assert len({item["id"] for item in items}) == 13
    for item in items:
        uuid.UUID(item["id"])


def test_ids_are_stable_per_user_and_distinct_across_users():
    a1 = {i["message_id"]: i["id"] for i in build_demo_feed("user-a")}
    a2 = {i["message_id"]: i["id"] for i in build_demo_feed("user-a")}
    b = {i["message_id"]: i["id"] for i in build_demo_feed("user-b")}
    assert a1 == a2
    assert not set(a1.values()) & set(b.values())


def test_records_match_contract_types():
    for item in build_demo_feed("u", PROFILES["cs_internship"]):
        assert item["category"] in CATEGORIES
        assert item["priority"] in PRIORITIES
        assert isinstance(item["relevance_score"], int) and 0 <= item["relevance_score"] <= 100
        assert isinstance(item["relevance_reason"], str) and item["relevance_reason"]
        for key in ("event_start", "event_end", "deadline_at"):
            if item[key] is not None:
                assert datetime.fromisoformat(item[key]).tzinfo is not None
        if item["deadline_date"] is not None:
            date.fromisoformat(item["deadline_date"])
        assert item["saved"] is False
        assert item["calendar_status"] == "not_added"
    json.dumps(build_demo_feed("u"))  # JSON-ready as-is


def test_feed_order_and_reference_example():
    items = build_demo_feed("u", PROFILES["cs_internship"])
    assert items[0]["message_id"] == "emergency-verified-008"
    assert items[0]["priority"] == "emergency"
    lanes = [i["priority"] for i in items]
    order = {"emergency": 0, "urgent": 1, "deadline": 2, "general": 3}
    assert lanes == sorted(lanes, key=order.get)
    intern = next(i for i in items if i["message_id"] == "intern-001")
    assert intern["relevance_score"] == 80
    general = [i for i in items if i["priority"] == "general"]
    assert general[0]["message_id"] == "intern-001"


def test_spoofed_and_injected_messages_are_not_elevated():
    items = {i["message_id"]: i for i in build_demo_feed("u")}
    assert items["emergency-spoofed-009"]["priority"] == "general"
    assert items["emergency-spoofed-009"]["needs_review"] is True
    assert items["injection-011"]["priority"] == "deadline"
    assert items["injection-011"]["needs_review"] is True
    assert sum(1 for i in items.values() if i["priority"] == "emergency") == 1


def test_canned_mode_uses_model_path_and_fallback_mode_does_not():
    assert {i["classification_source"] for i in build_demo_feed("u")} == {"model"}
    assert {i["classification_source"] for i in build_demo_feed("u", mode="fallback")} == {"fallback"}


def test_rerank_changes_order_and_preserves_saved_state():
    items = build_demo_feed("u", PROFILES["cs_internship"])
    target = next(i for i in items if i["message_id"] == "research-003")
    target["saved"] = True
    target["calendar_status"] = "added"
    reranked = rerank_feed(items, PROFILES["me_research"])
    research = next(i for i in reranked if i["message_id"] == "research-003")
    assert research["saved"] is True and research["calendar_status"] == "added"
    # interest (research) 35 + major (mechanical engineering) 25 + academic level (sophomore) 10
    assert research["relevance_score"] == 70
    intern = next(i for i in reranked if i["message_id"] == "intern-001")
    assert intern["relevance_score"] == 0  # no overlap with me_research
    assert [i["id"] for i in reranked] != [i["id"] for i in items]
    assert items[0] is not reranked[0]  # returns new dicts


def test_to_public_strips_internal_fields():
    item = build_demo_feed("u")[0]
    public = to_public(item)
    assert list(public) == list(PUBLIC_FIELDS)
    assert not set(INTERNAL_FIELDS) & set(public)


@pytest.mark.parametrize(
    "prefs",
    [
        None,
        {},
        PROFILES["cs_internship"],
        SimpleNamespace(model_dump=lambda: dict(PROFILES["cs_internship"])),  # e.g. Dev 4's Preferences
        {"interests": ["internship"] * 45, "major": "Computer Science"},  # Dev 4 allows 50 per list
    ],
)
def test_accepts_preference_shapes(prefs):
    items = build_demo_feed("u", prefs)
    assert len(items) == 13


def test_fixture_path_override(tmp_path, monkeypatch):
    source = json.loads(demo_feed._DEFAULT_FIXTURES.read_text(encoding="utf-8"))
    source["messages"] = source["messages"][:2]
    custom = tmp_path / "fixtures.json"
    custom.write_text(json.dumps(source), encoding="utf-8")
    monkeypatch.setenv(demo_feed.FIXTURES_ENV, str(custom))
    assert len(build_demo_feed("u")) == 2


def test_rejects_bad_arguments():
    with pytest.raises(ValueError):
        build_demo_feed("")
    with pytest.raises(ValueError):
        build_demo_feed("u", mode="live")
