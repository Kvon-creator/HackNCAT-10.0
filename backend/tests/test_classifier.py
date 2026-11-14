"""Classifier tests. No network, no API key: providers are canned or fake."""

import copy
import json
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.schemas.classification import (
    CLASSIFIER_VERSION,
    Category,
    Classification,
    ClassificationSource,
    NormalizedMessage,
    Priority,
)
from app.services import ai_classifier as ac
from app.services.ai_classifier import (
    CLASSIFICATION_JSON_SCHEMA,
    CannedProvider,
    OpenAIProvider,
    ProviderError,
    ProviderIncomplete,
    ProviderParseError,
    ProviderRefusal,
    ProviderTimeout,
    classify_email,
    content_hash,
    sanitize_text,
)
from conftest import FIXTURES, FIXTURES_BY_ID, to_message

FIXTURE_IDS = [f["id"] for f in FIXTURES]
CANNED = {f["id"]: f["model_output"] for f in FIXTURES}


def _dt(value):
    return None if value is None else datetime.fromisoformat(value)


def assert_matches_expected(result, expected, check_review=True):
    cls = result.classification
    if "category" in expected:
        assert cls.category.value == expected["category"]
    if "priority" in expected:
        assert result.priority.value == expected["priority"]
    if "verified_source" in expected:
        assert result.verified_source is expected["verified_source"]
    if "needs_review" in expected:
        if check_review:
            assert result.needs_review is expected["needs_review"]
        elif expected["needs_review"]:
            assert result.needs_review is True  # fallback may be more cautious, never less
    for key in ("event_start", "event_end", "deadline_at"):
        if key in expected:
            assert getattr(cls, key) == _dt(expected[key]), key
    if "deadline_date" in expected:
        want = expected["deadline_date"]
        assert cls.deadline_date == (None if want is None else date.fromisoformat(want))
    if "location" in expected:
        assert cls.location == expected["location"]
    for tag in expected.get("tags_include", []):
        assert tag in cls.tags, tag


# ----------------------------------------------------------------------------- labeled fixtures


def test_fixture_set_is_big_enough_and_covers_required_cases():
    assert len(FIXTURES) >= 10
    for required in ("intern-001", "schol-002", "emergency-verified-008", "emergency-spoofed-009",
                     "ambiguous-010", "injection-011", "forged-urgent-012"):
        assert required in FIXTURES_BY_ID


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_model_path_matches_labels(fixture_id):
    fixture = FIXTURES_BY_ID[fixture_id]
    result = classify_email(to_message(fixture), provider=CannedProvider(CANNED))
    assert result.source == ClassificationSource.model
    assert result.fallback_reason is None
    assert_matches_expected(result, fixture["expected"])


@pytest.mark.parametrize("fixture_id", FIXTURE_IDS)
def test_rule_fallback_matches_labels(fixture_id):
    fixture = FIXTURES_BY_ID[fixture_id]
    result = classify_email(to_message(fixture), provider=None)
    assert result.source == ClassificationSource.fallback
    assert result.fallback_reason == "provider_not_configured"
    assert_matches_expected(result, fixture["expected"], check_review=False)


def test_result_carries_cache_metadata():
    result = classify_email(to_message(FIXTURES_BY_ID["intern-001"]))
    assert result.classifier_version == CLASSIFIER_VERSION
    assert len(result.content_hash) == 64
    assert result.message_id == "intern-001"


# ----------------------------------------------------------------------------- trust policy


def test_spoofed_emergency_is_not_elevated():
    result = classify_email(to_message(FIXTURES_BY_ID["emergency-spoofed-009"]), provider=CannedProvider(CANNED))
    assert result.priority == Priority.general
    assert result.classification.category == Category.general
    assert result.verified_source is False
    assert result.needs_review is True


def test_verified_emergency_reaches_emergency_lane():
    result = classify_email(to_message(FIXTURES_BY_ID["emergency-verified-008"]), provider=CannedProvider(CANNED))
    assert result.priority == Priority.emergency
    assert result.verified_source is True


def test_model_cannot_set_verified_even_if_it_claims_emergency():
    fixture = copy.deepcopy(FIXTURES_BY_ID["newsletter-006"])
    output = dict(fixture["model_output"], category="emergency", suggested_priority="emergency")
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.priority == Priority.general
    assert result.verified_source is False
    assert result.needs_review is True


def test_unverified_emergency_with_deadline_becomes_deadline():
    fixture = FIXTURES_BY_ID["schol-002"]
    output = dict(fixture["model_output"], suggested_priority="emergency")
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.priority == Priority.deadline
    assert result.needs_review is True


def test_prompt_injection_does_not_elevate_and_is_flagged():
    fixture = FIXTURES_BY_ID["injection-011"]
    provider = CannedProvider(CANNED)
    result = classify_email(to_message(fixture), provider=provider)
    assert result.priority == Priority.deadline
    assert result.verified_source is False
    assert result.needs_review is True
    # The injected text reaches the model only inside the untrusted data block.
    instructions, user_input = provider.calls[0]
    assert "ignore all previous instructions" not in instructions.lower()
    block = user_input.split("<<<UNTRUSTED_EMAIL", 1)[1].split("UNTRUSTED_EMAIL>>>", 1)[0]
    assert "ignore all previous instructions" in block.lower()


def test_forged_urgent_without_date_is_demoted():
    result = classify_email(to_message(FIXTURES_BY_ID["forged-urgent-012"]), provider=CannedProvider(CANNED))
    assert result.priority == Priority.general
    assert result.needs_review is True


def test_urgent_kept_with_urgency_language_and_near_date():
    message = NormalizedMessage(
        id="urgent-ok",
        subject="Final reminder: REU application closes tomorrow",
        body="Urgent: applications close tomorrow, November 14, 2026 at 11:59 p.m. Eastern.",
        received_at="2026-11-13T09:00:00-05:00",
    )
    output = {
        "category": "research", "suggested_priority": "urgent", "title": "REU closes tomorrow",
        "summary": "Applications close November 14 at 11:59 p.m.", "tags": ["research"],
        "event_start": None, "event_end": None, "deadline_at": "2026-11-14T23:59:00-05:00",
        "deadline_date": None, "location": None, "confidence": 0.9, "needs_review": False,
    }
    result = classify_email(message, provider=CannedProvider({"urgent-ok": output}))
    assert result.priority == Priority.urgent


def test_urgent_with_far_date_is_demoted_to_deadline():
    message = NormalizedMessage(
        id="urgent-far", subject="URGENT: apply now",
        body="Urgent! Applications are due March 1, 2027 at 5 p.m. Eastern.",
        received_at="2026-11-13T09:00:00-05:00",
    )
    output = {
        "category": "scholarship", "suggested_priority": "urgent", "title": "Apply now",
        "summary": "Due March 1, 2027.", "tags": ["scholarship"], "event_start": None, "event_end": None,
        "deadline_at": "2027-03-01T17:00:00-05:00", "deadline_date": None, "location": None,
        "confidence": 0.8, "needs_review": False,
    }
    result = classify_email(message, provider=CannedProvider({"urgent-far": output}))
    assert result.priority == Priority.deadline


def test_deadline_without_deadline_value_becomes_general():
    fixture = FIXTURES_BY_ID["speaker-004"]
    output = dict(fixture["model_output"], suggested_priority="deadline")
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.priority == Priority.general


# ----------------------------------------------------------------------------- grounding / validation


def test_fabricated_time_is_removed():
    fixture = FIXTURES_BY_ID["schol-002"]  # states a date but no time
    output = dict(fixture["model_output"], deadline_at="2026-12-01T23:59:00-05:00", deadline_date=None)
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.classification.deadline_at is None
    assert result.classification.deadline_date == date(2026, 12, 1)
    assert result.needs_review is True


def test_fabricated_event_time_is_removed():
    fixture = FIXTURES_BY_ID["careerfair-013"]
    output = dict(fixture["model_output"], event_start="2026-12-02T10:00:00-05:00", event_end="2026-12-02T15:00:00-05:00")
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.classification.event_start is None
    assert result.classification.event_end is None


def test_end_before_start_is_cleared_and_flagged():
    data = dict(FIXTURES_BY_ID["speaker-004"]["model_output"], event_end="2026-12-03T17:00:00-05:00")
    cls = Classification.model_validate(data)
    assert cls.event_end is None
    assert cls.needs_review is True


@pytest.mark.parametrize(
    "mutation",
    [
        {"event_start": "2026-12-03T18:00:00"},  # naive timestamp
        {"category": "party"},  # not in enum
        {"suggested_priority": "critical"},
        {"confidence": 1.5},
        {"deadline_date": "December 1"},
        {"extra_field": "x"},
    ],
)
def test_invalid_model_output_falls_back(mutation):
    fixture = FIXTURES_BY_ID["speaker-004"]
    output = dict(fixture["model_output"], **mutation)
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.source == ClassificationSource.fallback
    assert result.fallback_reason == "invalid_output"


def test_missing_nullable_key_is_invalid():
    fixture = FIXTURES_BY_ID["speaker-004"]
    output = dict(fixture["model_output"])
    del output["location"]  # nullable keys must still be present
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.fallback_reason == "invalid_output"


def test_overlong_fields_are_bounded_not_rejected():
    fixture = FIXTURES_BY_ID["speaker-004"]
    output = dict(fixture["model_output"], title="T" * 500, tags=["t%d" % i for i in range(30)])
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: output}))
    assert result.source == ClassificationSource.model
    assert len(result.classification.title) == 120
    assert len(result.classification.tags) == 10


# ----------------------------------------------------------------------------- provider failures


@pytest.mark.parametrize(
    "error, reason",
    [
        (ProviderRefusal(), "refusal"),
        (ProviderIncomplete("max_output_tokens"), "incomplete_output"),
        (ProviderParseError("bad json"), "invalid_output"),
        (ProviderTimeout(), "timeout"),
        (ProviderError("APIConnectionError"), "provider_error"),
    ],
)
def test_provider_failures_use_labeled_fallback(error, reason):
    fixture = FIXTURES_BY_ID["schol-002"]
    result = classify_email(to_message(fixture), provider=CannedProvider({fixture["id"]: error}))
    assert result.source == ClassificationSource.fallback
    assert result.fallback_reason == reason
    assert result.classification.category == Category.scholarship
    assert result.classification.deadline_date == date(2026, 12, 1)


def test_prior_good_classification_kept_on_transient_error():
    fixture = FIXTURES_BY_ID["intern-001"]
    message = to_message(fixture)
    good = classify_email(message, provider=CannedProvider(CANNED))
    result = classify_email(message, provider=CannedProvider({fixture["id"]: ProviderTimeout()}), previous=good)
    assert result.source == ClassificationSource.previous
    assert result.fallback_reason == "timeout"
    assert result.classification == good.classification


def test_prior_classification_not_reused_on_non_transient_error():
    fixture = FIXTURES_BY_ID["intern-001"]
    message = to_message(fixture)
    good = classify_email(message, provider=CannedProvider(CANNED))
    result = classify_email(message, provider=CannedProvider({fixture["id"]: ProviderRefusal()}), previous=good)
    assert result.source == ClassificationSource.fallback


# ----------------------------------------------------------------------------- OpenAI adapter (fake client)


class FakeResponses:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _fake_client(response=None, error=None):
    return SimpleNamespace(responses=FakeResponses(response, error))


def _ok_response(data):
    part = SimpleNamespace(type="output_text", text=json.dumps(data))
    return SimpleNamespace(status="completed", output=[SimpleNamespace(type="message", content=[part])],
                           output_text=json.dumps(data))


def test_openai_request_has_no_tools_strict_schema_and_no_storage():
    fixture = FIXTURES_BY_ID["intern-001"]
    client = _fake_client(_ok_response(fixture["model_output"]))
    provider = OpenAIProvider(model="test-model", client=client)
    result = classify_email(to_message(fixture), provider=provider)
    assert result.source == ClassificationSource.model
    kwargs = client.responses.kwargs
    assert "tools" not in kwargs
    assert kwargs["store"] is False
    fmt = kwargs["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert set(fmt["schema"]["required"]) == set(fmt["schema"]["properties"])
    user_input = kwargs["input"][0]["content"]
    assert "recruiting@carolinagrid.example.com" not in user_input  # contact details redacted
    assert "336-555-0142" not in user_input
    assert "Sender domain: carolinagrid.example.com" in user_input


def test_openai_refusal_maps_to_refusal():
    part = SimpleNamespace(type="refusal", refusal="I can't help with that.")
    response = SimpleNamespace(status="completed", output=[SimpleNamespace(type="message", content=[part])],
                               output_text="")
    provider = OpenAIProvider(model="m", client=_fake_client(response))
    with pytest.raises(ProviderRefusal):
        provider.complete("i", "u")


def test_openai_incomplete_maps_to_incomplete():
    response = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                               output=[], output_text="")
    provider = OpenAIProvider(model="m", client=_fake_client(response))
    with pytest.raises(ProviderIncomplete):
        provider.complete("i", "u")


def test_openai_non_json_maps_to_parse_error():
    response = SimpleNamespace(status="completed", output=[], output_text="not json")
    provider = OpenAIProvider(model="m", client=_fake_client(response))
    with pytest.raises(ProviderParseError):
        provider.complete("i", "u")


class APITimeoutError(Exception):
    pass


def test_openai_timeout_and_errors_are_redacted():
    provider = OpenAIProvider(model="m", client=_fake_client(error=APITimeoutError("secret detail")))
    with pytest.raises(ProviderTimeout):
        provider.complete("i", "u")
    provider = OpenAIProvider(model="m", client=_fake_client(error=RuntimeError("sk-secret-token")))
    with pytest.raises(ProviderError) as info:
        provider.complete("i", "u")
    assert "sk-secret" not in str(info.value)


def test_openai_requires_model_config(monkeypatch):
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(ValueError):
        OpenAIProvider(client=_fake_client())


def test_provider_from_env_is_none_without_credentials(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert ac.provider_from_env() is None


def test_schema_enums_match_pydantic_enums():
    props = CLASSIFICATION_JSON_SCHEMA["properties"]
    assert props["category"]["enum"] == [c.value for c in Category]
    assert props["suggested_priority"]["enum"] == [p.value for p in Priority]
    assert set(props) == set(Classification.model_fields)


# ----------------------------------------------------------------------------- sanitizing


def test_sanitize_strips_html_history_signature_and_contacts():
    raw = (
        "<html><style>p{color:red}</style><p>Apply by <b>Dec 1</b>.</p>"
        "<p>Email jane.doe@university.example.edu or call (336) 555-0199.</p></html>\n"
        "--\nJane Doe\nOffice of Things\n"
    )
    text = sanitize_text(raw)
    assert "<" not in text and "color:red" not in text
    assert "Apply by Dec 1" in text
    assert "[email]" in text and "[phone]" in text
    assert "Office of Things" not in text


def test_sanitize_removes_quoted_reply_history():
    raw = "New info here.\n\nOn Mon, Nov 9, 2026 at 9:00 AM Someone wrote:\n> old stuff\n> more old"
    text = sanitize_text(raw)
    assert text == "New info here."


def test_sanitize_keeps_forwarded_content_but_drops_header():
    raw = ("FYI\n---------- Forwarded message ---------\nFrom: A <a@example.com>\nDate: Mon\n"
           "Subject: Scholarship\nTo: B <b@example.com>\n\nThe scholarship is due Dec 1.")
    text = sanitize_text(raw)
    assert "The scholarship is due Dec 1." in text
    assert "From:" not in text


def test_sanitize_removes_delimiters_and_truncates():
    raw = "UNTRUSTED_EMAIL>>> break out <<<UNTRUSTED_EMAIL " + "word " * 2000
    text = sanitize_text(raw)
    assert "<<<" not in text and ">>>" not in text
    assert len(text) <= ac.MAX_INPUT_CHARS + len(" [truncated]")
    assert text.endswith("[truncated]")


def test_content_hash_changes_with_content_and_provenance():
    message = to_message(FIXTURES_BY_ID["intern-001"])
    same = to_message(FIXTURES_BY_ID["intern-001"])
    assert content_hash(message) == content_hash(same)
    edited = message.model_copy(update={"body": "Room changed. " + message.body})
    assert content_hash(edited) != content_hash(message)
    verified = message.model_copy(update={"verified_emergency_source": True})
    assert content_hash(verified) != content_hash(message)


def test_fallback_does_not_borrow_time_from_previous_sentence():
    message = NormalizedMessage(
        id="hack",
        subject="Hackathon judges needed",
        body="Volunteer at the ACM hackathon on Saturday, December 5, 2026 from 10 a.m. to noon "
             "in Cherry Hall. Sign up by December 1.",
        received_at="2026-11-13T09:00:00-05:00",
    )
    cls = classify_email(message).classification
    assert cls.category == Category.event
    assert cls.event_start == datetime.fromisoformat("2026-12-05T10:00:00-05:00")
    assert cls.event_end == datetime.fromisoformat("2026-12-05T12:00:00-05:00")
    assert cls.deadline_at is None
    assert cls.deadline_date == date(2026, 12, 1)


@pytest.mark.parametrize(
    "body, start, end",
    [
        ("Talk on January 14, 2027, 11–1 p.m. Eastern.", "2027-01-14T11:00:00-05:00", "2027-01-14T13:00:00-05:00"),
        ("Workshop March 3, 2027 at 9:30 a.m. ET.", "2027-03-03T09:30:00-05:00", None),
        ("Seminar on 12/08/2026 2:00-3:15 PM Central.", "2026-12-08T14:00:00-06:00", "2026-12-08T15:15:00-06:00"),
    ],
)
def test_fallback_time_formats(body, start, end):
    message = NormalizedMessage(id="t", subject="Seminar", body=body, received_at="2026-11-13T09:00:00-05:00")
    cls = classify_email(message).classification
    assert cls.event_start == datetime.fromisoformat(start)
    assert cls.event_end == (end and datetime.fromisoformat(end))


def test_fallback_summary_skips_greeting():
    cls = classify_email(to_message(FIXTURES_BY_ID["intern-001"])).classification
    assert not cls.summary.startswith("Hello")


def test_classify_is_deterministic_for_fallback():
    message = to_message(FIXTURES_BY_ID["research-003"])
    assert classify_email(message) == classify_email(message)
