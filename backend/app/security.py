from datetime import datetime, timedelta, timezone
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
    claims = {"sub": str(uuid4()), "tid": "aggieconnect-demo", "oid": str(uuid4()),
              "mode": "demo", "iat": now, "exp": expires}
    token = jwt.encode(claims, settings.demo_session_secret, algorithm=ALGORITHM)
    return token, settings.demo_session_minutes * 60

def current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        claims = jwt.decode(token, settings.demo_session_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid or expired token")
    if claims.get("mode") != "demo" or not settings.demo_mode:
        # Live Entra JWT validation is intentionally not faked by this demo verifier.
        raise HTTPException(401, "Token is not valid for this runtime")
    return claims
