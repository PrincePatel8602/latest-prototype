"""Stored event-study results (one row per storm x asset). Derived data: always regenerable from
historical_storms/storm_track_points + market_observations by `scripts/run_event_study.py`."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.historical.models import PK, HistoricalBase, JSONType


class EventStudyResult(HistoricalBase):
    __tablename__ = "event_study_results"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    storm_id: Mapped[str] = mapped_column(String(32), ForeignKey("historical_storms.storm_id", ondelete="CASCADE"), nullable=False)
    series_key: Mapped[str] = mapped_column(String(64), ForeignKey("market_series.series_key", ondelete="CASCADE"), nullable=False)
    anchor: Mapped[str] = mapped_column(String(24), nullable=False)             # "gulf_entry"
    anchor_date: Mapped[date] = mapped_column(Date, nullable=False)
    t0_date: Mapped[date | None] = mapped_column(Date)                          # first trading day on/after the anchor
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str | None] = mapped_column(String(200))
    n_estimation: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alpha: Mapped[float | None] = mapped_column(Float)
    beta: Mapped[float | None] = mapped_column(Float)
    resid_std: Mapped[float | None] = mapped_column(Float)
    vol_ratio: Mapped[float | None] = mapped_column(Float)
    max_drawdown: Mapped[float | None] = mapped_column(Float)
    overlap: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    overlapping_storms: Mapped[list | None] = mapped_column(JSONType)
    windows: Mapped[dict | None] = mapped_column(JSONType)                      # "0,5" -> {car, raw_return, t_stat, n_days}
    method: Mapped[dict | None] = mapped_column(JSONType)
    provenance: Mapped[dict | None] = mapped_column(JSONType)                   # benchmark + raw hashes + storm dataset version
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("storm_id", "series_key", name="uq_event_study_storm_series"),
                      Index("ix_event_study_series", "series_key"), Index("ix_event_study_storm", "storm_id"))
