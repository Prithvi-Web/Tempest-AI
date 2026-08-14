import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import tempest
from tempest_api.routers import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tempest AI API",
        version=tempest.__version__,
        description="Ingests CLI-produced run bundles and serves them to the dashboard. "
        "One producer, many renderers — this API never re-derives verdicts.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get("TEMPEST_CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    return app
