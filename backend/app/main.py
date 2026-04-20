from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api import cases as cases_router
from app.api import documents as documents_router
from app.api import drafts as drafts_router
from app.api import evidence as evidence_router
from app.api import learning as learning_router
from app.api import processing as processing_router
from app.api import search as search_router
from app.api.deps import SessionDep
from app.config import settings
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: engine is lazy, nothing to do explicitly yet.
    yield
    # Shutdown: release DB pool connections cleanly.
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    lifespan=lifespan,
)

app.include_router(cases_router.router)
app.include_router(documents_router.router)
app.include_router(processing_router.router)
app.include_router(search_router.router)
app.include_router(evidence_router.router)
app.include_router(drafts_router.cases_router)
app.include_router(drafts_router.drafts_router)
app.include_router(learning_router.router)


@app.get("/health")
async def health(session: SessionDep) -> dict:
    try:
        result = await session.execute(text("SELECT 1"))
        db_ok = result.scalar() == 1
    except Exception:
        db_ok = False

    return {
        "ok": True,
        "db": db_ok,
        "version": settings.version,
        "name": settings.app_name,
    }
