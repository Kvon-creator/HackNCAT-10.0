import base64
import re
from fastapi import Request
from fastapi.responses import JSONResponse
from uuid import uuid4

class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, headers: dict | None = None):
        self.status_code, self.code, self.message = status_code, code, message
        self.headers = headers or {}


def graph_api_error(error) -> ApiError:
    """Map a sanitized Graph adapter failure into the shared REST contract."""
    headers = {}
    if error.retry_after is not None:
        headers["Retry-After"] = str(error.retry_after)
    if error.code == "graph_claims_challenge" and error.claims:
        claims = error.claims
        if not re.fullmatch(r"[A-Za-z0-9_+/=-]+", claims):
            claims = base64.b64encode(claims.encode("utf-8")).decode("ascii")
        headers["WWW-Authenticate"] = f'Bearer claims="{claims}"'
    return ApiError(error.status_code, error.code, error.message, headers)

async def api_error_handler(request: Request, exc: ApiError):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "request_id": request_id}},
        headers={**exc.headers, "X-Request-ID": request_id},
    )
