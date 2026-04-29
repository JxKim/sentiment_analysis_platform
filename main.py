"""FastAPI main application — primary backend (Phase 3)."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from loguru import logger

from services.forum_service import init_forum_log, start_forum_log_monitor
from utils.knowledge_logger import init_knowledge_log

from routers import system, config, apps, forum, search, graph, events, report


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    init_forum_log()
    init_knowledge_log()
    start_forum_log_monitor()
    logger.info("FastAPI 服务器已启动，共享服务已初始化")
    yield


app = FastAPI(
    title="尚舆分析平台 API",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routers
app.include_router(system.router)
app.include_router(config.router)
app.include_router(apps.router)
app.include_router(forum.router)
app.include_router(search.router)
app.include_router(graph.router)
app.include_router(events.router)
app.include_router(report.router)

# ── SPA & static files ──────────────────────────────────────────────────

_BASE = Path(__file__).resolve().parent
_VUE_DIST = _BASE / "frontend" / "dist"
_TEMPLATE_DIR = _BASE / "templates"
_STATIC_DIR = _BASE / "static"
_OLD_INDEX = _TEMPLATE_DIR / "index.html"
_INDEX_HTML = _VUE_DIST / "index.html"


# Static files: frontend/dist/assets (Vue build) takes priority
if (_VUE_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_VUE_DIST / "assets"), name="vue_assets")

if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# Favicon / icons from Vue dist
@app.get("/favicon.svg")
async def serve_favicon():
    path = _VUE_DIST / "favicon.svg"
    if path.exists():
        return FileResponse(path)
    return Response(status_code=404)


@app.get("/icons.svg")
async def serve_icons():
    path = _VUE_DIST / "icons.svg"
    if path.exists():
        return FileResponse(path)
    return Response(status_code=404)


@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve Vue SPA — falls back to old template when dist is absent."""
    if _INDEX_HTML.exists():
        return FileResponse(_INDEX_HTML)
    if _OLD_INDEX.exists():
        return HTMLResponse(content=_OLD_INDEX.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>尚舆分析平台</h1>", status_code=200)


if __name__ == "__main__":
    import uvicorn
    from config import settings

    host = settings.HOST
    port = settings.PORT

    logger.info(f"FastAPI 服务器启动: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
