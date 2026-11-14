"""Ranking tests: deterministic weights, explanations, aliases and feed ordering."""

from datetime import datetime, timedelta, timezone

import pytest

from app.schemas.classification import Preferences, Priority
from app.services.ai_classifier import CannedProvider, classify_email
from app.services.ranking_service import (
    NO_MATCH_REASON,
    feed_sort_key,
    normalize_token,
    rank,
    rank_tags,
)
from conftest import FIXTURES, FIXTURES_BY_ID, to_message

CANNED = {f["id"]: f["model_output"] for f in FIXTURES}


def test_reference_example_scores_80(profiles):
    """Master plan: CS major + internship interest + matching career goal = 80."""
    result = classify_email(to_message(FIXTURES_BY_ID["intern-001"]), provider=CannedProvider(CANNED))
    ranked = rank(result.classification, profiles["cs_internship"])
    assert ranked.relevance_score == 80
    assert ranked.matched_fields == ["interest", "major", "career_goal"]
    assert ranked.relevance_reason == (
        "Matches your interest (internship), major (computer science), and career goal (software engineering)."
    )


def test_reference_example_scores_80_on_fallback_too(profiles):
    result = classify_email(to_message(FIXTURES_BY_ID["intern-001"]))
    assert rank(result.classification, profiles["cs_internship"]).relevance_score == 80


def test_no_match_gives_zero_and_stable_reason(profiles):
    ranked = rank_tags(["internship", "computer science"], profiles["empty"])
    assert ranked.relevance_score == 0
    assert ranked.relevance_reason == NO_MATCH_REASON
    assert ranked.matched_fields == []


def test_each_field_counts_once():
    prefs = Preferences(interests=["robotics", "machine learning", "research"])
    ranked = rank_tags(["robotics", "machine learning", "research"], prefs)
    assert ranked.relevance_score == 35
    assert ranked.matched_fields == ["interest"]


def test_all_fields_sum_to_100():
    prefs = Preferences(
        major="Computer Science", academic_level="Junior", interests=["internship"],
        organizations=["NSBE"], career_goals=["software engineering"],
    )
    tags = ["internship", "computer science", "software engineering", "junior",
            "national society of black engineers"]
    ranked = rank_tags(tags, prefs)
    assert ranked.relevance_score == 100
    assert ranked.relevance_reason == (
        "Matches your interest (internship), major (computer science), career goal (software engineering), "
        "academic level (junior), and organization (national society of black engineers)."
    )


def test_two_matches_use_and():
    ranked = rank_tags(["internship", "computer science"], Preferences(major="CS", interests=["Internships"]))
    assert ranked.relevance_reason == "Matches your interest (internship) and major (computer science)."
    assert ranked.relevance_score == 60


@pytest.mark.parametrize(
    "raw, token",
    [
        ("CS", "computer science"),
        ("Comp-Sci", "computer science"),
        ("  Software_Engineer ", "software engineering"),
        ("Internships", "internship"),
        ("co-op", "internship"),
        ("ML", "machine learning"),
        ("Robotics!", "robotics"),
    ],
)
def test_normalization_and_aliases(raw, token):
    assert normalize_token(raw) == token


@pytest.mark.parametrize(
    "major, tag",
    [
        ("Computer Science", "computer science"),
        ("Theatre", "theatre"),
        ("Theater", "theatre"),
        ("Theatre Arts", "theatre"),
        ("Biology", "biology"),
        ("Bio", "biology"),
        ("Biological Sciences", "biology"),
    ],
)
def test_frontend_majors_match(major, tag):
    ranked = rank_tags([tag], Preferences(major=major))
    assert ranked.matched_fields == ["major"]
    assert ranked.relevance_score == 25


def test_undergraduate_tag_matches_class_year():
    ranked = rank_tags(["research", "undergraduate"], Preferences(academic_level="Sophomore"))
    assert ranked.matched_fields == ["academic_level"]
    assert ranked.relevance_score == 10


def test_preference_change_reranks_without_reclassification(profiles):
    classified = {
        f["id"]: classify_email(to_message(f), provider=CannedProvider(CANNED)) for f in FIXTURES
    }

    def top(prefs):
        scored = sorted(
            classified.values(),
            key=lambda r: feed_sort_key(
                r.priority, rank(r.classification, prefs).relevance_score,
                r.received_at, r.message_id, r.verified_source,
            ),
        )
        general = [r for r in scored if r.priority == Priority.general]
        return general[0].message_id

    assert top(profiles["cs_internship"]) == "intern-001"
    assert top(profiles["me_research"]) != "intern-001"


def test_lanes_sort_before_score():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    rows = [
        ("general-high", Priority.general, 100, now, False),
        ("deadline-low", Priority.deadline, 0, now, False),
        ("urgent", Priority.urgent, 10, now, False),
        ("emergency", Priority.emergency, 0, now, True),
    ]
    ordered = sorted(rows, key=lambda r: feed_sort_key(r[1], r[2], r[3], r[0], r[4]))
    assert [r[0] for r in ordered] == ["emergency", "urgent", "deadline-low", "general-high"]


def test_unverified_emergency_sorts_as_general():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    spoof = feed_sort_key(Priority.emergency, 0, now, "spoof", verified_source=False)
    deadline = feed_sort_key(Priority.deadline, 0, now, "d")
    assert deadline < spoof


def test_ties_break_by_received_desc_then_id():
    now = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
    rows = [("b", now), ("a", now), ("newer", now + timedelta(minutes=1))]
    ordered = sorted(rows, key=lambda r: feed_sort_key(Priority.general, 50, r[1], r[0]))
    assert [r[0] for r in ordered] == ["newer", "a", "b"]


def test_rank_is_deterministic(profiles):
    tags = ["research", "robotics", "undergraduate"]
    first = rank_tags(tags, profiles["me_research"])
    assert all(rank_tags(tags, profiles["me_research"]) == first for _ in range(5))
    assert first.relevance_score == 45  # interest 35 + academic level 10
