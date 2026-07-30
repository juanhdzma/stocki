from __future__ import annotations

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class FundamentalsHistory(Base):
    __tablename__ = "fundamentals_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20))
    period: Mapped[str] = mapped_column(String(20))
    data_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(32))
    __table_args__ = (UniqueConstraint("ticker", "period"),)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshot"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    data_json: Mapped[str] = mapped_column(Text)
    refreshed_at: Mapped[str] = mapped_column(String(32))


class Watchlist(Base):
    __tablename__ = "watchlist"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    # "watchlist" | "favorite" — favorites surface in a separate top section (a starred subset)
    list_type: Mapped[str] = mapped_column(String(20), server_default="watchlist")
    added_at: Mapped[str] = mapped_column(String(32), server_default="1970-01-01T00:00:00+00:00")


class FetchTimestamp(Base):
    __tablename__ = "fetch_timestamps"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    data_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    fetched_at: Mapped[str] = mapped_column(String(32))


class ScoreHistory(Base):
    __tablename__ = "score_history"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    date: Mapped[str] = mapped_column(
        String(10), primary_key=True
    )  # YYYY-MM-DD, one row per ticker per day
    data_json: Mapped[str] = mapped_column(Text)  # compute_all() output
