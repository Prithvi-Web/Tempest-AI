from fastapi import FastAPI

import tempest
from tempest_api.routers import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tempest AI API",
        version=tempest.__version__,
        description="Ingests CLI-produced run bundles and serves them to the dashboard. "
        "One producer, many renderers — this API never re-derives verdicts.",
    )
    app.include_router(health.router)
    return app
