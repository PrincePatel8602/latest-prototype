"""PostgreSQL tables for BSEE storm shut-in statistics (shares the HistoricalBase metadata).

bsee_reports          one row per BSEE press release page (accepted AND rejected, so nothing is hidden)
bsee_storm_shutins    one row per storm: maxima over the ACCEPTED reports, coverage, and the link to IBTrACS
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.historical.models import PK, HistoricalBase, JSONType


class BseeReport(HistoricalBase):
    __tablename__ = "bsee_reports"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(400), nullable=False)
    storm_label: Mapped[str] = mapped_column(String(80), nullable=False)       # accordion heading on the BSEE index
    storm_name: Mapped[str] = mapped_column(String(64), nullable=False)        # upper-case name without storm-type words
    index_year: Mapped[int] = mapped_column(Integer, nullable=False)
    report_date: Mapped[date | None] = mapped_column(Date)
    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)           # page verified to describe this storm/year
    status: Mapped[str] = mapped_column(String(24), nullable=False)           # ok | no_percentages | rejected | fetch_error
    oil_shut_in_pct: Mapped[float | None] = mapped_column(Float)
    gas_shut_in_pct: Mapped[float | None] = mapped_column(Float)
    oil_shut_in_bopd: Mapped[float | None] = mapped_column(Float)
    gas_shut_in_mmcfd: Mapped[float | None] = mapped_column(Float)
    platforms_evacuated: Mapped[float | None] = mapped_column(Float)
    rigs_moved_off: Mapped[float | None] = mapped_column(Float)
    flags: Mapped[list | None] = mapped_column(JSONType)
    shutin_sentence: Mapped[str | None] = mapped_column(Text)
    raw_sha256: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="BSEE storm activity statistics")
    ingestion_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("url", name="uq_bsee_reports_url"),
                      Index("ix_bsee_reports_storm", "index_year", "storm_name"),
                      Index("ix_bsee_reports_date", "report_date"))


class BseeStormShutin(HistoricalBase):
    __tablename__ = "bsee_storm_shutins"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    storm_key: Mapped[str] = mapped_column(String(100), nullable=False)       # "<year>:<storm_label>"
    storm_label: Mapped[str] = mapped_column(String(80), nullable=False)
    storm_name: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    storm_id: Mapped[str | None] = mapped_column(String(32))                  # IBTrACS id when matched
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)     # name_year | unmatched | ambiguous
    n_reports_listed: Mapped[int] = mapped_column(Integer, nullable=False)
    n_reports_used: Mapped[int] = mapped_column(Integer, nullable=False)
    max_oil_shut_in_pct: Mapped[float | None] = mapped_column(Float)
    max_gas_shut_in_pct: Mapped[float | None] = mapped_column(Float)
    max_platforms_evacuated: Mapped[float | None] = mapped_column(Float)
    peak_oil_date: Mapped[date | None] = mapped_column(Date)
    first_report_date: Mapped[date | None] = mapped_column(Date)
    last_report_date: Mapped[date | None] = mapped_column(Date)
    source_urls: Mapped[list | None] = mapped_column(JSONType)               # accepted report URLs
    note: Mapped[str] = mapped_column(String(300), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("storm_key", name="uq_bsee_storm_key"),
                      Index("ix_bsee_storm_id", "storm_id"))
