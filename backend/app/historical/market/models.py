"""PostgreSQL tables for historical market/macro series (shares the HistoricalBase metadata).

market_series        one row per series (metadata + provenance of the latest load)
market_observations  one row per (series, date); unique so re-ingestion never duplicates
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.historical.models import PK, HistoricalBase, JSONType


class MarketSeries(HistoricalBase):
    __tablename__ = "market_series"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    series_key: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    source_series_id: Mapped[str] = mapped_column(String(48), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str] = mapped_column(String(24), nullable=False)
    frequency: Mapped[str] = mapped_column(String(12), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_note: Mapped[str | None] = mapped_column(String(160))
    raw_file_sha256: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_date: Mapped[date | None] = mapped_column(Date)
    last_date: Mapped[date | None] = mapped_column(Date)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    quality_report: Mapped[dict | None] = mapped_column(JSONType)

    __table_args__ = (UniqueConstraint("series_key", name="uq_market_series_key"),
                      Index("ix_market_series_category", "category"))


class MarketObservation(HistoricalBase):
    __tablename__ = "market_observations"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    series_key: Mapped[str] = mapped_column(
        String(64), ForeignKey("market_series.series_key", ondelete="CASCADE"), nullable=False)
    obs_date: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    open: Mapped[float | None] = mapped_column(Float)
    high: Mapped[float | None] = mapped_column(Float)
    low: Mapped[float | None] = mapped_column(Float)
    adj_close: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (UniqueConstraint("series_key", "obs_date", name="uq_market_obs_series_date"),
                      Index("ix_market_obs_series_date", "series_key", "obs_date"),
                      Index("ix_market_obs_date", "obs_date"))
