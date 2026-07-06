import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routers import portfolio, refresh, lookup, watchlist, system
from db.cache import init_db, engine
from scheduler.worker import start_scheduler, stop_scheduler
from core.fetchers.yahoo import init_auth

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_auth()
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()
    await engine.dispose()


app = FastAPI(title="StockDesk", lifespan=lifespan)

app.include_router(portfolio.router, prefix="/api")
app.include_router(refresh.router,   prefix="/api")
app.include_router(lookup.router,    prefix="/api")
app.include_router(watchlist.router, prefix="/api")
app.include_router(system.router,   prefix="/api")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")
