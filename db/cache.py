from __future__ import annotations
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncSession, AsyncEngine, create_async_engine, async_sessionmaker,
)

from config import DATABASE_URL
from db.models import Base, FundamentalsHistory, MarketSnapshot, FetchTimestamp, Watchlist

logger = logging.getLogger(__name__)

engine: AsyncEngine = create_async_engine(DATABASE_URL, pool_size=10, max_overflow=5)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ── Fundamentals ──────────────────────────────────────────────────────────────

async def write_fundamentals(session: AsyncSession, ticker: str, period: str, data: dict) -> None:
    stmt = pg_insert(FundamentalsHistory).values(
        ticker=ticker,
        period=period,
        data_json=json.dumps(data),
        created_at=datetime.now(timezone.utc).isoformat(),
    ).on_conflict_do_nothing()
    await session.execute(stmt)
    await session.commit()


async def has_fundamentals(session: AsyncSession, ticker: str, period: str) -> bool:
    result = await session.execute(
        select(FundamentalsHistory.id).where(
            FundamentalsHistory.ticker == ticker,
            FundamentalsHistory.period == period,
        )
    )
    return result.first() is not None


async def read_all_fundamentals(session: AsyncSession, ticker: str) -> list[dict]:
    result = await session.execute(
        select(FundamentalsHistory)
        .where(FundamentalsHistory.ticker == ticker)
        .order_by(FundamentalsHistory.period.desc())
    )
    rows = result.scalars().all()
    return [{"period": r.period, **json.loads(r.data_json)} for r in rows]


# ── Market snapshot ───────────────────────────────────────────────────────────

async def write_snapshot(session: AsyncSession, ticker: str, data: dict) -> None:
    stmt = pg_insert(MarketSnapshot).values(
        ticker=ticker,
        data_json=json.dumps(data),
        refreshed_at=datetime.now(timezone.utc).isoformat(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker"],
        set_={"data_json": stmt.excluded.data_json, "refreshed_at": stmt.excluded.refreshed_at},
    )
    await session.execute(stmt)
    await session.commit()


async def read_snapshot(session: AsyncSession, ticker: str) -> dict | None:
    result = await session.execute(
        select(MarketSnapshot).where(MarketSnapshot.ticker == ticker)
    )
    row = result.scalars().first()
    return json.loads(row.data_json) if row else None


# ── Fetch timestamps ──────────────────────────────────────────────────────────

async def get_last_fetch(session: AsyncSession, ticker: str, data_type: str) -> datetime | None:
    result = await session.execute(
        select(FetchTimestamp).where(
            FetchTimestamp.ticker == ticker,
            FetchTimestamp.data_type == data_type,
        )
    )
    row = result.scalars().first()
    if not row:
        return None
    dt = datetime.fromisoformat(row.fetched_at)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def set_last_fetch(session: AsyncSession, ticker: str, data_type: str) -> None:
    stmt = pg_insert(FetchTimestamp).values(
        ticker=ticker,
        data_type=data_type,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "data_type"],
        set_={"fetched_at": stmt.excluded.fetched_at},
    )
    await session.execute(stmt)
    await session.commit()


async def should_fetch(
    session: AsyncSession, ticker: str, data_type: str, max_age: timedelta
) -> bool:
    last = await get_last_fetch(session, ticker, data_type)
    if last is None:
        return True
    return datetime.now(timezone.utc) - last > max_age
