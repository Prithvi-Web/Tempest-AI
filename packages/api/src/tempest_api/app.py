import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import tempest
from tempest_api.db import create_engine_and_factory, database_url
from tempest_api.db.local_store import check_not_newer, prepare_local_store
from tempest_api.errors import install_error_handlers
from tempest_api.routers import (
    divergences,
    health,
    local,
    logs,
    runs,
    search,
    settings,
    sync,
    targets,
    uierrors,
    watch,
)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    url = database_url()
    engine, factory = create_engine_and_factory(url)
    try:
        if engine.dialect.name == "sqlite":
            # The local store is versioned (ADR-0016): refuse-newer is checked read-only BEFORE
            # any connection can touch the file, then create/adopt/forward-migrate + stamp.
            # WAL + FK pragmas are installed by create_engine_and_factory on every sqlite
            # engine (review C2). Postgres runs Alembic (ADR-0009).
            check_not_newer(url)
            await prepare_local_store(engine)
        app.state.db_engine = engine
        app.state.db_sessionmaker = factory
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Tempest AI API",
        version=tempest.__version__,
        description="Ingests CLI-produced run bundles and serves them to the dashboard. "
        "One producer, many renderers — this API never re-derives verdicts.",
        lifespan=_lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.environ.get(
            "TEMPEST_CORS_ORIGINS",
            "http://localhost:3000,http://localhost:1420,tauri://localhost,http://tauri.localhost",
        ).split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(targets.router)
    app.include_router(divergences.router)
    app.include_router(local.router)
    app.include_router(search.router)
    app.include_router(logs.router)
    app.include_router(sync.router)
    app.include_router(settings.router)
    app.include_router(uierrors.router)
    app.include_router(watch.router)
    return app
