import json
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.schemas.classification import NormalizedMessage, Preferences  # noqa: E402

FIXTURES = json.loads((REPO / "demo" / "sample_emails.json").read_text(encoding="utf-8"))["messages"]
PROFILES = json.loads((REPO / "demo" / "sample_preferences.json").read_text(encoding="utf-8"))["profiles"]
FIXTURES_BY_ID = {f["id"]: f for f in FIXTURES}


def to_message(fixture) -> NormalizedMessage:
    return NormalizedMessage(
        id=fixture["id"],
        subject=fixture["subject"],
        body=fixture["body"],
        sender=fixture["sender"],
        received_at=fixture["received_at"],
        verified_emergency_source=fixture["verified_emergency_source"],
    )


@pytest.fixture
def fixture_by_id():
    return FIXTURES_BY_ID


@pytest.fixture
def profiles():
    return {name: Preferences(**data) for name, data in PROFILES.items()}
