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


class ScoresCache(Base):
    __tablename__ = "scores_cache"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    scores_json: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[str] = mapped_column(String(32))


class Watchlist(Base):
    __tablename__ = "watchlist"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    list_type: Mapped[str] = mapped_column(String(20), server_default="watchlist")
    added_at: Mapped[str] = mapped_column(String(32), server_default="")


class FetchTimestamp(Base):
    __tablename__ = "fetch_timestamps"
    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    data_type: Mapped[str] = mapped_column(String(30), primary_key=True)
    fetched_at: Mapped[str] = mapped_column(String(32))
