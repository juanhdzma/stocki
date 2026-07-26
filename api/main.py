import logging
import os
import hashlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.routers import refresh, lookup, watchlist, system, portfolio, status, history
from db.cache import init_db, engine
from core.fetchers.yahoo import init_auth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_auth()
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title="Stocki", lifespan=lifespan)

app.include_router(portfolio.router, prefix="/api")
app.include_router(refresh.router,   prefix="/api")
app.include_router(lookup.router,    prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(system.router,    prefix="/api")
app.include_router(status.router,    prefix="/api")
app.include_router(history.router,   prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


def _asset_version(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        return "0"


@app.get("/")
def root():
    js_v  = _asset_version("static/app.js")
    css_v = _asset_version("static/style.css")
    html = open("static/index.html").read()
    html = html.replace("/static/app.js",   f"/static/app.js?v={js_v}")
    html = html.replace("/static/style.css", f"/static/style.css?v={css_v}")
    return HTMLResponse(html)
