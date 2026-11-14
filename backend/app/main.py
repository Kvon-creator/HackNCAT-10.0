from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.routers import health, demo, me, opportunities

app = FastAPI(title="AggieConnect API", version="0.1.0")

if settings.frontend_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

app.include_router(health.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(me.router, prefix="/api")
app.include_router(opportunities.router, prefix="/api")
