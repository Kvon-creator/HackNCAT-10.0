"""Deterministic relevance scoring and feed ordering (Dev 3).

Score = sum of weights for preference fields that match the opportunity's tags,
each field counted at most once: interest 35, major 25, career goal 20,
academic level 10, organization 10 (max 100). No model involvement.

Dev 4 calls rank() at read time from stored tags, so a preference edit reranks
without reclassification.
"""

import re
from datetime import datetime
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from app.schemas.classification import (
    PRIORITY_LANE_ORDER,
    Classification,
    Preferences,
    Priority,
    RankResult,
)

# (field name, label used in explanations, weight) in explanation order.
WEIGHTS: Tuple[Tuple[str, str, int], ...] = (
    ("interest", "interest", 35),
    ("major", "major", 25),
    ("career_goal", "career goal", 20),
    ("academic_level", "academic level", 10),
    ("organization", "organization", 10),
)

NO_MATCH_REASON = "No preference match yet."

MAX_TOKEN_LEN = 40

# Small, explicit alias map: normalized variant -> canonical token.
ALIASES = {
    # Majors offered in the frontend: Computer Science, Theatre, Biology.
    "theater": "theatre",
    "theatre arts": "theatre",
    "theater arts": "theatre",
    "drama": "theatre",
    "performing arts": "theatre",
    "bio": "biology",
    "biological sciences": "biology",
    "biological science": "biology",
    "biology sciences": "biology",
    "cs": "computer science",
    "comp sci": "computer science",
    "compsci": "computer science",
    "computer sci": "computer science",
    "ce": "computer engineering",
    "cpe": "computer engineering",
    "ee": "electrical engineering",
    "ece": "electrical engineering",
    "me": "mechanical engineering",
    "mech e": "mechanical engineering",
    "ie": "industrial engineering",
    "swe": "software engineering",
    "software engineer": "software engineering",
    "software development": "software engineering",
    "internships": "internship",
    "co op": "internship",
    "coop": "internship",
    "scholarships": "scholarship",
    "research opportunities": "research",
    "undergrad": "undergraduate",
    "grad": "graduate",
    "grad school": "graduate school",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "cybersecurity": "cyber security",
    "cyber": "cyber security",
    "nsbe": "national society of black engineers",
    "swe society": "society of women engineers",
}

# Academic levels: preference value -> tags that count as a match.
LEVEL_EQUIVALENTS = {
    "freshman": {"freshman", "first year", "undergraduate"},
    "sophomore": {"sophomore", "undergraduate"},
    "junior": {"junior", "undergraduate"},
    "senior": {"senior", "undergraduate"},
    "undergraduate": {"undergraduate", "freshman", "sophomore", "junior", "senior"},
    "graduate": {"graduate", "masters", "phd", "graduate school"},
}

_SEP = re.compile(r"[\s_\-/]+")
_STRIP = re.compile(r"[^a-z0-9 +#.&]")


def normalize_token(value: str) -> str:
    """Lowercase, collapse separators, drop punctuation, apply alias map."""
    token = _SEP.sub(" ", value.lower()).strip()
    token = _STRIP.sub("", token).strip(" .")
    token = " ".join(token.split())[:MAX_TOKEN_LEN]
    return ALIASES.get(token, token)


def normalize_tags(values: Iterable[str]) -> Set[str]:
    return {t for t in (normalize_token(v) for v in values) if t}


def _first_match(prefs: Sequence[str], tags: Set[str]) -> Optional[str]:
    for pref in prefs:
        token = normalize_token(pref)
        if token and token in tags:
            return token
    return None


def _match_fields(tags: Set[str], prefs: Preferences) -> List[Tuple[str, str, int, str]]:
    matches = []
    for field, label, weight in WEIGHTS:
        hit = None
        if field == "interest":
            hit = _first_match(prefs.interests, tags)
        elif field == "major" and prefs.major:
            hit = _first_match([prefs.major], tags)
        elif field == "career_goal":
            hit = _first_match(prefs.career_goals, tags)
        elif field == "academic_level" and prefs.academic_level:
            level = normalize_token(prefs.academic_level)
            if tags & LEVEL_EQUIVALENTS.get(level, {level}):
                hit = level
        elif field == "organization":
            hit = _first_match(prefs.organizations, tags)
        if hit:
            matches.append((field, label, weight, hit))
    return matches


def _explain(matches: List[Tuple[str, str, int, str]]) -> str:
    if not matches:
        return NO_MATCH_REASON
    parts = ["%s (%s)" % (label, value) for _, label, _, value in matches]
    if len(parts) == 1:
        joined = parts[0]
    elif len(parts) == 2:
        joined = "%s and %s" % (parts[0], parts[1])
    else:
        joined = "%s, and %s" % (", ".join(parts[:-1]), parts[-1])
    return "Matches your %s." % joined


def rank_tags(tags: Iterable[str], preferences: Preferences) -> RankResult:
    """Score from stored tags alone (what Dev 4 has at read time)."""
    matches = _match_fields(normalize_tags(tags), preferences)
    return RankResult(
        relevance_score=min(100, sum(m[2] for m in matches)),
        relevance_reason=_explain(matches),
        matched_fields=[m[0] for m in matches],
    )


def rank(classification: Classification, preferences: Preferences) -> RankResult:
    """Public contract: rank(classification, preferences)."""
    return rank_tags(classification.tags, preferences)


def feed_sort_key(
    priority: Priority,
    relevance_score: int,
    received_at: datetime,
    opportunity_id: str,
    verified_source: bool = False,
):
    """Sort key for the feed: priority lane, then score desc, received_at desc, id.

    Only a verified source can occupy the emergency lane; an unverified emergency
    sorts as general (the trust policy in ai_classifier should already have
    demoted it, this is defense in depth).
    """
    if priority == Priority.emergency and not verified_source:
        priority = Priority.general
    return (
        PRIORITY_LANE_ORDER[priority],
        -relevance_score,
        -received_at.timestamp(),
        str(opportunity_id),
    )
