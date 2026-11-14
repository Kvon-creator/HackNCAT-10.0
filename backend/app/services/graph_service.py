"""Delegated Microsoft Graph adapter for Outlook mail and calendar operations.

Callers must validate the AggieConnect access token before passing its original
JWT assertion here. This module never accepts a Graph access token from a
browser and never logs credentials or raw Graph responses.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
import msal

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
GRAPH_HOST = "graph.microsoft.com"
INBOX_MESSAGES_PATH = "/v1.0/me/mailFolders/inbox/messages"
DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
MAX_MESSAGES = 25
MAX_RETRIES = 2
MAX_RETRY_WAIT_SECONDS = 2.0
OUTLOOK_HOSTS = {"outlook.office.com", "outlook.office365.com", "outlook.live.com"}


class GraphServiceError(Exception):
    """Safe, stable error suitable for mapping to the API error contract."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 503,
        claims: str | None = None,
        retry_after: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.claims = claims
        self.retry_after = retry_after


def _credentials() -> tuple[str, str, str]:
    names = ("ENTRA_TENANT_ID", "ENTRA_API_CLIENT_ID", "ENTRA_API_CLIENT_SECRET")
    values = tuple(os.getenv(name, "").strip() for name in names)
    if not all(values):
        raise GraphServiceError("graph_not_configured", "Microsoft Graph is not configured")
    return values  # type: ignore[return-value]


def _safe_graph_link(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    if (
        parsed.scheme == "https"
        and parsed.hostname in OUTLOOK_HOSTS
        and parsed.username is None
        and parsed.password is None
        and parsed.port in (None, 443)
    ):
        return value
    return None


def _validate_next_link(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname != GRAPH_HOST or parsed.port not in (None, 443):
        raise GraphServiceError("graph_invalid_paging_link", "Microsoft returned an invalid paging link")
    path = unquote(parsed.path)
    if not re.fullmatch(r"/v1\.0/me/mailfolders(?:/inbox|\('inbox'\))/messages", path, re.IGNORECASE):
        raise GraphServiceError("graph_invalid_paging_link", "Microsoft returned an invalid paging link")
    return value


def _raise_safe_response(response: httpx.Response) -> None:
    status = response.status_code
    if status == 401:
        challenge = response.headers.get("WWW-Authenticate", "")
        if "claims=" in challenge.lower():
            match = re.search(r'(?:^|[, ])claims="([^"\\]+)"', challenge, re.IGNORECASE)
            claims = match.group(1) if match else None
            raise GraphServiceError("graph_claims_challenge", "Microsoft requires additional account verification", 403, claims)
        raise GraphServiceError("graph_auth_failed", "Microsoft authentication needs to be refreshed", 401)
    if status == 403:
        raise GraphServiceError("graph_consent_required", "Microsoft access was denied; review account consent", 403)
    if status == 429:
        raise GraphServiceError("graph_throttled", "Microsoft Graph is temporarily throttling requests", 429)
    if status >= 500:
        raise GraphServiceError("graph_unavailable", "Microsoft Graph is temporarily unavailable", 503)
    raise GraphServiceError("graph_request_failed", "Microsoft Graph could not complete the request", 502)


def _retry_after_seconds(value: str | None) -> int:
    if not value:
        return 1
    try:
        seconds = float(value)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            seconds = (retry_at - datetime.now(timezone.utc)).total_seconds()
        except (TypeError, ValueError, OverflowError):
            return 1
    return max(0, int(seconds + 0.999))


def _get_obo_token(assertion: str, scopes: list[str]) -> str:
    if not assertion or not assertion.strip():
        raise GraphServiceError("invalid_assertion", "A validated user assertion is required", 401)
    tenant, client_id, secret = _credentials()
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=f"https://login.microsoftonline.com/{tenant}",
        client_credential=secret,
    )
    try:
        result = app.acquire_token_on_behalf_of(user_assertion=assertion, scopes=scopes)
    except Exception:
        raise GraphServiceError("graph_auth_failed", "Microsoft authentication is temporarily unavailable", 503) from None
    token = result.get("access_token") if isinstance(result, dict) else None
    if token:
        return token
    error = result.get("error") if isinstance(result, dict) else None
    suberror = str(result.get("suberror", "")).casefold() if isinstance(result, dict) else ""
    description = str(result.get("error_description", "")) if isinstance(result, dict) else ""
    aadsts_codes = set(re.findall(r"AADSTS(\d+)", description, re.IGNORECASE))
    if error == "consent_required" or suberror == "consent_required" or "65001" in aadsts_codes:
        raise GraphServiceError("graph_consent_required", "Microsoft access needs additional consent", 403)
    claims_needed = (
        error in {"insufficient_claims", "interaction_required"}
        or suberror in {"basic_action", "additional_action", "message_only", "user_password_expired"}
        or bool(aadsts_codes & {"50076", "50078", "50079", "50158", "53000", "53001", "53003", "53004", "53009", "53010", "53011"})
        or bool(result.get("claims"))
    ) if isinstance(result, dict) else False
    if claims_needed:
        raise GraphServiceError(
            "graph_claims_challenge",
            "Microsoft requires additional account verification",
            403,
            result.get("claims") if isinstance(result.get("claims"), str) and len(result["claims"]) <= 8192 else None,
        )
    if aadsts_codes & {"500133", "700024"}:
        raise GraphServiceError("invalid_assertion", "The Microsoft sign-in session has expired", 401)
    raise GraphServiceError("graph_auth_failed", "Microsoft authentication is temporarily unavailable", 503)


def _request(
    client: httpx.Client,
    method: str,
    url: str,
    headers: Mapping[str, str],
    *,
    json_body: dict[str, Any] | None = None,
) -> httpx.Response:
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.request(method, url, headers=headers, json=json_body)
        except httpx.TimeoutException as exc:
            if attempt < MAX_RETRIES:
                continue
            raise GraphServiceError("graph_timeout", "Microsoft Graph did not respond in time", 503) from exc
        except httpx.HTTPError as exc:
            raise GraphServiceError("graph_unavailable", "Microsoft Graph is temporarily unavailable", 503) from exc
        if response.status_code != 429:
            if response.is_error:
                _raise_safe_response(response)
            return response
        delay = _retry_after_seconds(response.headers.get("Retry-After"))
        # Stay within a small request budget; do not sleep for vendor supplied extremes.
        if attempt == MAX_RETRIES or delay > MAX_RETRY_WAIT_SECONDS:
            raise GraphServiceError(
                "graph_throttled",
                "Microsoft Graph is temporarily throttling requests",
                429,
                retry_after=delay,
            )
        time.sleep(delay)
    raise GraphServiceError("graph_unavailable", "Microsoft Graph is temporarily unavailable", 503)


def list_recent_messages(assertion: str, limit: int = MAX_MESSAGES) -> list[dict[str, Any]]:
    """Fetch up to 25 recent messages with immutable IDs and safe normalized fields."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_MESSAGES:
        raise ValueError(f"limit must be between 1 and {MAX_MESSAGES}")
    token = _get_obo_token(assertion, ["https://graph.microsoft.com/Mail.Read"])
    headers = {
        "Authorization": f"Bearer {token}",
        "Prefer": 'IdType="ImmutableId"',
        "Accept": "application/json",
    }
    params = {
        "$select": "id,subject,from,receivedDateTime,bodyPreview,webLink",
        "$orderby": "receivedDateTime desc",
        "$top": str(min(limit, 25)),
    }
    messages: list[dict[str, Any]] = []
    next_url: str | None = f"https://{GRAPH_HOST}{INBOX_MESSAGES_PATH}?{httpx.QueryParams(params)}"
    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=False) as client:
        while next_url and len(messages) < limit:
            next_url = _validate_next_link(next_url)
            response = _request(client, "GET", next_url, headers)
            try:
                payload = response.json()
            except ValueError as exc:
                raise GraphServiceError("graph_invalid_response", "Microsoft returned an invalid response", 502) from exc
            rows = payload.get("value") if isinstance(payload, dict) else None
            if not isinstance(rows, list):
                raise GraphServiceError("graph_invalid_response", "Microsoft returned an invalid response", 502)
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                    continue
                sender = ((row.get("from") or {}).get("emailAddress") or {})
                messages.append({
                    "id": row["id"],
                    "subject": row.get("subject") or "",
                    "sender": sender.get("address") or "",
                    "received_at": row.get("receivedDateTime"),
                    "body_preview": row.get("bodyPreview") or "",
                    "source_link": _safe_graph_link(row.get("webLink")),
                })
                if len(messages) >= limit:
                    break
            raw_next = payload.get("@odata.nextLink")
            next_url = _validate_next_link(raw_next) if raw_next and len(messages) < limit else None
    return messages


def _parse_timed(value: Any, zone_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timed event start and end must be ISO 8601 strings")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timed event start and end must include UTC offsets")
    try:
        zone = ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone must be a supported IANA time zone") from exc
    local = parsed.astimezone(zone)
    if local.utcoffset() != parsed.utcoffset():
        raise ValueError("event offset does not match time_zone")
    return parsed


def _calendar_payload(event: Mapping[str, Any], transaction_id: str) -> dict[str, Any]:
    if not transaction_id:
        raise ValueError("transaction_id is required")
    all_day = event.get("all_day") is True
    zone_name = event.get("time_zone")
    if not isinstance(zone_name, str) or not zone_name:
        raise ValueError("time_zone is required")
    try:
        ZoneInfo(zone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone must be a supported IANA time zone") from exc
    start, end = event.get("start"), event.get("end")
    if all_day:
        try:
            start_date, end_date = date.fromisoformat(start), date.fromisoformat(end)
        except (TypeError, ValueError) as exc:
            raise ValueError("all-day start and end must be YYYY-MM-DD dates") from exc
        if end_date <= start_date:
            raise ValueError("event end must be after start")
        # Graph all-day events require local midnight and an exclusive end date.
        start_value = f"{start_date.isoformat()}T00:00:00"
        end_value = f"{end_date.isoformat()}T00:00:00"
    else:
        parsed_start = _parse_timed(start, zone_name)
        parsed_end = _parse_timed(end, zone_name)
        if parsed_end <= parsed_start:
            raise ValueError("event end must be after start")
        start_value = parsed_start.astimezone(timezone.utc).replace(tzinfo=None).isoformat()
        end_value = parsed_end.astimezone(timezone.utc).replace(tzinfo=None).isoformat()

    subject = event.get("subject") or event.get("title") or "AggieConnect event"
    body = event.get("body") or event.get("summary") or ""
    if not isinstance(subject, str) or not isinstance(body, str):
        raise ValueError("event subject and body must be text")
    # Graph interprets dateTime as a wall-clock value in its timeZone field.
    # Timed events were converted to UTC above, so label them UTC to preserve
    # the instant instead of reinterpreting the UTC clock as local time.
    graph_zone = zone_name if all_day else "UTC"
    payload: dict[str, Any] = {
        "subject": subject[:255],
        "body": {"contentType": "text", "content": body[:4000]},
        "start": {"dateTime": start_value, "timeZone": graph_zone},
        "end": {"dateTime": end_value, "timeZone": graph_zone},
        "isAllDay": all_day,
        "transactionId": transaction_id,
    }
    location = event.get("location")
    if isinstance(location, str) and location.strip():
        payload["location"] = {"displayName": location.strip()[:255]}
    return payload


def create_event(assertion: str, event: Mapping[str, Any], transaction_id: str) -> dict[str, Any]:
    """Create or recover a confirmed event using a stable Graph transaction ID."""
    if event.get("confirmed") is not True:
        raise ValueError("event must be confirmed before writing to Outlook")
    payload = _calendar_payload(event, transaction_id)
    token = _get_obo_token(assertion, ["https://graph.microsoft.com/Calendars.ReadWrite"])
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"}
    with httpx.Client(timeout=DEFAULT_TIMEOUT, follow_redirects=False) as client:
        response = _request(client, "POST", f"{GRAPH_ROOT}/me/events", headers, json_body=payload)
    try:
        result = response.json()
    except ValueError as exc:
        raise GraphServiceError("graph_invalid_response", "Microsoft returned an invalid response", 502) from exc
    event_id = result.get("id") if isinstance(result, dict) else None
    link = _safe_graph_link(result.get("webLink")) if isinstance(result, dict) else None
    if not event_id:
        raise GraphServiceError("graph_invalid_response", "Microsoft returned an invalid event", 502)
    return {"graph_event_id": event_id, "web_link": link, "status": "added"}
