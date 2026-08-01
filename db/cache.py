from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import DATABASE_URL
from db.models import (
    Base,
    FetchTimestamp,
    FundamentalsHistory,
    MarketSnapshot,
    ScoreHistory,
)
from util import parse_iso_aware, utcnow_iso

logger = logging.getLogger(__name__)

# pool_size must exceed refresh_all's batch_size (scheduler/worker.py, currently 30): refresh_one
# holds its session — and thus a pooled connection — across the whole multi-second fetch chain, so a
# 30-wide gather needs 30 concurrent connections or the tail tasks time out waiting and fail silently.
engine: AsyncEngine = create_async_engine(DATABASE_URL, pool_size=32, max_overflow=8)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Portfolio was removed in favor of a lightweight "favorites" flag. One-time migration:
        # carry any prior holdings over as favorites (so those names aren't lost), then drop the
        # now-orphan portfolio tables. Guarded on table existence → no-op on fresh DBs and re-runs.
        await conn.exec_driver_sql(
            "DO $$ BEGIN "
            "IF to_regclass('portfolio_holdings') IS NOT NULL THEN "
            "INSERT INTO watchlist (ticker, list_type, added_at) "
            "SELECT ticker, 'favorite', added_at FROM portfolio_holdings "
            "ON CONFLICT (ticker) DO UPDATE SET list_type = 'favorite'; "
            "END IF; END $$;"
        )
        await conn.exec_driver_sql("DROP TABLE IF EXISTS portfolio_holdings")
        await conn.exec_driver_sql("DROP TABLE IF EXISTS portfolio_prices")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


# ── Fundamentals ──────────────────────────────────────────────────────────────


async def write_fundamentals(
    session: AsyncSession, ticker: str, period: str, data: dict, overwrite: bool = False
) -> None:
    stmt = pg_insert(FundamentalsHistory).values(
        ticker=ticker,
        period=period,
        data_json=json.dumps(data),
        created_at=utcnow_iso(),
    )
    # A period first fetched right after its report can be partial (cash-flow/balance-sheet
    # rows still null while the income statement is populated); on_conflict_do_nothing would
    # freeze those nulls forever. overwrite=True re-writes it so a later, complete fetch (or a
    # restatement) actually lands. Used only for the most-recent periods — older ones stay frozen.
    if overwrite:
        stmt = stmt.on_conflict_do_update(
            index_elements=["ticker", "period"],
            set_={"data_json": stmt.excluded.data_json},
        )
    else:
        stmt = stmt.on_conflict_do_nothing()
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


async def read_all_fundamentals_batch(
    session: AsyncSession, tickers: list[str]
) -> dict[str, list[dict]]:
    """Batched read_all_fundamentals — one query for many tickers instead of one query each."""
    if not tickers:
        return {}
    result = await session.execute(
        select(FundamentalsHistory)
        .where(FundamentalsHistory.ticker.in_(tickers))
        .order_by(FundamentalsHistory.ticker, FundamentalsHistory.period.desc())
    )
    out: dict[str, list[dict]] = {t: [] for t in tickers}
    for r in result.scalars().all():
        out[r.ticker].append({"period": r.period, **json.loads(r.data_json)})
    return out


# ── Market snapshot ───────────────────────────────────────────────────────────


async def write_snapshot(session: AsyncSession, ticker: str, data: dict) -> None:
    stmt = pg_insert(MarketSnapshot).values(
        ticker=ticker,
        data_json=json.dumps(data),
        refreshed_at=utcnow_iso(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker"],
        set_={"data_json": stmt.excluded.data_json, "refreshed_at": stmt.excluded.refreshed_at},
    )
    await session.execute(stmt)
    await session.commit()


async def read_snapshot(session: AsyncSession, ticker: str) -> dict | None:
    result = await session.execute(select(MarketSnapshot).where(MarketSnapshot.ticker == ticker))
    row = result.scalars().first()
    return json.loads(row.data_json) if row else None


# ── Score history (one snapshot per ticker per day, for "change since" comparisons) ──


async def write_score_history_if_missing(
    session: AsyncSession, ticker: str, date: str, scores: dict
) -> None:
    stmt = (
        pg_insert(ScoreHistory)
        .values(
            ticker=ticker,
            date=date,
            data_json=json.dumps(scores),
        )
        .on_conflict_do_nothing()
    )
    await session.execute(stmt)
    await session.commit()


async def read_score_history_reference(
    session: AsyncSession, ticker: str, since_date: str, today: str
) -> dict | None:
    """Oldest score snapshot within [since_date, today) — a rolling anchor for a trailing-window
    comparison (e.g. "change over the last 7 days"). Using the oldest sample *in* the window rather
    than requiring one exactly at its start means the comparison becomes visible after just one day
    of history and accumulates day over day, instead of staying empty until a full window has passed.
    """
    result = await session.execute(
        select(ScoreHistory.data_json)
        .where(
            ScoreHistory.ticker == ticker,
            ScoreHistory.date >= since_date,
            ScoreHistory.date < today,
        )
        .order_by(ScoreHistory.date.asc())
        .limit(1)
    )
    row = result.first()
    return json.loads(row[0]) if row else None


async def read_score_history_reference_batch(
    session: AsyncSession, tickers: list[str], since_date: str, today: str
) -> dict[str, dict]:
    """Batched read_score_history_reference — one oldest-in-window row per ticker, one query."""
    if not tickers:
        return {}
    ranked = (
        select(
            ScoreHistory.ticker,
            ScoreHistory.data_json,
            func.row_number()
            .over(partition_by=ScoreHistory.ticker, order_by=ScoreHistory.date.asc())
            .label("rn"),
        )
        .where(
            ScoreHistory.ticker.in_(tickers),
            ScoreHistory.date >= since_date,
            ScoreHistory.date < today,
        )
        .subquery()
    )
    result = await session.execute(
        select(ranked.c.ticker, ranked.c.data_json).where(ranked.c.rn == 1)
    )
    return {row.ticker: json.loads(row.data_json) for row in result}


# ── Fetch timestamps ──────────────────────────────────────────────────────────


async def get_last_fetch(session: AsyncSession, ticker: str, data_type: str) -> datetime | None:
    result = await session.execute(
        select(FetchTimestamp).where(
            FetchTimestamp.ticker == ticker,
            FetchTimestamp.data_type == data_type,
        )
    )
    row = result.scalars().first()
    return parse_iso_aware(row.fetched_at) if row else None


async def set_last_fetch(session: AsyncSession, ticker: str, data_type: str) -> None:
    stmt = pg_insert(FetchTimestamp).values(
        ticker=ticker,
        data_type=data_type,
        fetched_at=utcnow_iso(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["ticker", "data_type"],
        set_={"fetched_at": stmt.excluded.fetched_at},
    )
    await session.execute(stmt)
    await session.commit()


async def should_fetch(
    session: AsyncSession, ticker: str, data_type: str, max_age: timedelta, force: bool = False
) -> bool:
    if force:
        return True
    last = await get_last_fetch(session, ticker, data_type)
    if last is None:
        return True
    return datetime.now(UTC) - last > max_age
