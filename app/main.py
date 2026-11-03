"""FastAPI application factory."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.auth import init_admin
from app.routes.api import router as api_router
from app.routes.auth_routes import auth_router
from app.websocket import get_recent, log as ws_log, set_event_loop, subscribe, unsubscribe
from core.scheduler import start_scheduler, stop_scheduler
from db.database import init_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    set_event_loop(asyncio.get_running_loop())
    init_db()
    init_admin()
    start_scheduler()
    ws_log("ChiefMailVault started")
    yield
    stop_scheduler()
    ws_log("ChiefMailVault stopped")


app = FastAPI(title="ChiefMailVault", version="1.0.0", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(api_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = TEMPLATES_DIR / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    queue = subscribe()
    try:
        for entry in get_recent():
            await websocket.send_json(entry)
        while True:
            entry = await queue.get()
            await websocket.send_json(entry)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe(queue)
