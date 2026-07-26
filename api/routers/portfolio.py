from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter
from sqlalchemy import select

from db.cache import AsyncSessionLocal
from db.models import PortfolioHolding, PortfolioPrice
from scheduler.worker import is_pf_refresh_running, refresh_portfolio_prices

router = APIRouter()


@router.get("/portfolio/prices")
async def get_portfolio_prices():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(PortfolioPrice).where(PortfolioPrice.ticker.in_(select(PortfolioHolding.ticker)))
        )
        rows = result.scalars().all()

    out: dict = {"_running": is_pf_refresh_running()}
    for row in rows:
        out[row.ticker] = {**json.loads(row.data_json), "refreshed_at": row.refreshed_at}
    return out


@router.post("/portfolio/refresh")
async def trigger_portfolio_refresh():
    asyncio.create_task(refresh_portfolio_prices())
    return {"status": "started"}
