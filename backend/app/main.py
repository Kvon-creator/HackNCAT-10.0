from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from uuid import uuid4
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.errors import ApiError, api_error_handler
from app.routers import health, demo, me, opportunities, sync, calendar

app = FastAPI(title="AggieConnect API", version="0.1.0")

if settings.frontend_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["Retry-After", "WWW-Authenticate", "X-Request-ID"],
    )

app.add_exception_handler(ApiError, api_error_handler)


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    code_by_status = {401: "unauthorized", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_request"}
    message = exc.detail if isinstance(exc.detail, str) else "The request could not be completed"
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code_by_status.get(exc.status_code, "request_failed"), "message": message, "request_id": request_id}},
        headers={**(exc.headers or {}), "X-Request-ID": request_id},
    )

app.include_router(health.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(opportunities.router, prefix="/api")
app.include_router(sync.router, prefix="/api")
app.include_router(calendar.router, prefix="/api")


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "invalid_request", "message": "The request contains invalid fields", "request_id": request_id}},
        headers={"X-Request-ID": request_id},
    )
