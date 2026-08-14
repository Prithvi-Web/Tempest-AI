import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import tempest
from tempest_api.db import Base, create_engine_and_factory
from tempest_api.errors import install_error_handlers
from tempest_api.routers import divergences, health, runs, targets


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine, factory = create_engine_and_factory()
    if engine.dialect.name == "sqlite":
        # Local dev/tests (aiosqlite): create the schema directly; the migration/model parity
        # test keeps this equivalent to `alembic upgrade head`. Postgres runs Alembic (ADR-0009).
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    app.state.db_engine = engine
    app.state.db_sessionmaker = factory
    try:
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
        allow_origins=os.environ.get("TEMPEST_CORS_ORIGINS", "http://localhost:3000").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(targets.router)
    app.include_router(divergences.router)
    return app
