import glob
import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from api.routers import history, lookup, portfolio, refresh, status, system, watchlist
from core.fetchers.yahoo import init_auth
from db.cache import engine, init_db

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
app.include_router(refresh.router, prefix="/api")
app.include_router(lookup.router, prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(system.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(history.router, prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


def _asset_version(*paths: str) -> str:
    h = hashlib.md5()
    for path in paths:
        try:
            with open(path, "rb") as f:
                h.update(f.read())
        except OSError:
            h.update(b"0")
    return h.hexdigest()[:8]


def _build_index_html() -> str:
    # The ES-module entry (js/main.js) statically imports its siblings without a version
    # query, so hash the whole js/ tree into the entry's version — any module change bumps it.
    js_files = sorted(glob.glob("static/js/*.js"))
    js_v = _asset_version(*js_files)
    css_v = _asset_version("static/style.css")
    with open("static/index.html") as f:
        html = f.read()
    html = html.replace("/static/js/main.js", f"/static/js/main.js?v={js_v}")
    html = html.replace("/static/style.css", f"/static/style.css?v={css_v}")
    return html


# Cached after the first request: assets are baked into the image (or served under
# --reload, which restarts the process on change), so the hash never changes at runtime.
_index_html: str | None = None


@app.get("/")
async def root():
    global _index_html
    if _index_html is None:
        _index_html = _build_index_html()
    return HTMLResponse(_index_html)
