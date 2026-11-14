from datetime import datetime, timedelta, timezone
from functools import lru_cache
from uuid import uuid4

import jwt
from fastapi import Header, HTTPException

from app.config import settings

ALGORITHM = "HS256"


def create_demo_token() -> tuple[str, int]:
    if not settings.demo_mode:
        raise HTTPException(404, "Not found")
    now = datetime.now(timezone.utc)
    expires = now + timedelta(minutes=settings.demo_session_minutes)
    claims = {
        "sub": str(uuid4()),
        "tid": "aggieconnect-demo",
        "oid": str(uuid4()),
        "mode": "demo",
        "iat": now,
        "exp": expires,
    }
    token = jwt.encode(claims, settings.demo_session_secret, algorithm=ALGORITHM)
    return token, settings.demo_session_minutes * 60


def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()

    if settings.demo_mode:
        try:
            claims = jwt.decode(token, settings.demo_session_secret, algorithms=[ALGORITHM])
        except jwt.PyJWTError:
            raise HTTPException(401, "Invalid or expired token") from None
        if claims.get("mode") != "demo":
            raise HTTPException(401, "Token is not valid for demo mode")
        return claims

    tenant_id = settings.entra_tenant_id.strip()
    audience = settings.entra_api_client_id.strip()
    if not tenant_id or not audience:
        raise HTTPException(503, "Live Microsoft authentication is not configured")
    issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
    try:
        key = _jwks_client(tenant_id).get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "iss", "aud", "tid", "oid", "scp"]},
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired Microsoft access token") from None
    except Exception:
        raise HTTPException(503, "Microsoft sign-in validation is temporarily unavailable") from None

    if str(claims.get("tid", "")).lower() != tenant_id.lower() or not claims.get("oid"):
        raise HTTPException(401, "Microsoft token is not valid for this tenant")
    if "access_as_user" not in set(str(claims.get("scp", "")).split()):
        raise HTTPException(403, "Microsoft access token is missing the required API permission")
    user_id = f"{claims['tid']}:{claims['oid']}"
    return {
        **claims,
        "sub": user_id,
        "tid": claims["tid"],
        "oid": claims["oid"],
        "display_name": claims.get("name"),
        "mode": "live",
        # Request-scoped assertion for OBO only; handlers must never serialize it.
        "_assertion": token,
    }


@lru_cache(maxsize=4)
def _jwks_client(tenant_id: str):
    return jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys",
        timeout=5,
        cache_keys=True,
    )
