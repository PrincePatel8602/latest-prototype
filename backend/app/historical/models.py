"""PostgreSQL schema for the historical foundation.

historical_storms          one row per storm/event (source of truth for event-level facts)
storm_track_points         one row per observation, FK -> historical_storms.storm_id
historical_ingestion_runs  audit trail of every ingestion run

Source/provenance columns are on every table so a row can always be traced to the dataset,
version and raw file it came from.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")
PK = BigInteger().with_variant(Integer(), "sqlite")   # SQLite only autoincrements INTEGER primary keys


class HistoricalBase(DeclarativeBase):
    pass


class HistoricalStorm(HistoricalBase):
    __tablename__ = "historical_storms"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    storm_id: Mapped[str] = mapped_column(String(32), nullable=False)       # IBTrACS SID (stable source id)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    number: Mapped[int | None] = mapped_column(Integer)
    basin: Mapped[str] = mapped_column(String(4), nullable=False)
    subbasin: Mapped[str | None] = mapped_column(String(4))
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)

    start_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_hours: Mapped[float | None] = mapped_column(Float)

    max_wind_kt: Mapped[float | None] = mapped_column(Float)                # 1-min sustained, knots
    min_pressure_mb: Mapped[float | None] = mapped_column(Float)
    max_category_normalized: Mapped[int | None] = mapped_column(Integer)    # -1 TD, 0 TS, 1..5
    max_category_original: Mapped[int | None] = mapped_column(Integer)      # USA_SSHS as published
    category_source: Mapped[str | None] = mapped_column(String(64))

    track_length_km: Mapped[float | None] = mapped_column(Float)
    n_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    n_original_observations: Mapped[int] = mapped_column(Integer, nullable=False)
    gulf_of_mexico_entered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    gulf_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_category_in_gulf: Mapped[int | None] = mapped_column(Integer)
    max_wind_in_gulf_kt: Mapped[float | None] = mapped_column(Float)
    landfall_indicator_observations: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    min_dist2land_km: Mapped[float | None] = mapped_column(Float)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)

    # provenance
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(16), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_subset: Mapped[str] = mapped_column(String(48), nullable=False)
    source_downloaded_at: Mapped[str | None] = mapped_column(String(40))
    source_file_sha256: Mapped[str | None] = mapped_column(String(64))
    ingestion_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    data_quality_status: Mapped[str] = mapped_column(String(16), nullable=False)
    quality_flags: Mapped[dict | None] = mapped_column(JSONType)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)    # change detection

    # vector-index sync state (Pinecone is NOT the source of truth)
    pinecone_record_id: Mapped[str | None] = mapped_column(String(64))
    pinecone_namespace: Mapped[str | None] = mapped_column(String(64))
    pinecone_synced_hash: Mapped[str | None] = mapped_column(String(64))
    pinecone_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    points: Mapped[list["StormTrackPoint"]] = relationship(
        back_populates="storm", cascade="all, delete-orphan", passive_deletes=True,
        order_by="StormTrackPoint.timestamp")

    __table_args__ = (
        UniqueConstraint("storm_id", name="uq_historical_storms_storm_id"),
        Index("ix_historical_storms_year", "year"),
        Index("ix_historical_storms_basin", "basin"),
        Index("ix_historical_storms_name", "name"),
        Index("ix_historical_storms_max_category", "max_category_normalized"),
        Index("ix_historical_storms_gulf", "gulf_of_mexico_entered", "max_category_in_gulf"),
        Index("ix_historical_storms_start", "start_datetime"),
        Index("ix_historical_storms_bbox", "min_lat", "max_lat", "min_lon", "max_lon"),
    )


class StormTrackPoint(HistoricalBase):
    __tablename__ = "storm_track_points"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    storm_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("historical_storms.storm_id", ondelete="CASCADE"), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    wind_kt: Mapped[float | None] = mapped_column(Float)
    wind_source: Mapped[str | None] = mapped_column(String(16))
    pressure_mb: Mapped[float | None] = mapped_column(Float)
    pressure_source: Mapped[str | None] = mapped_column(String(16))
    original_category: Mapped[int | None] = mapped_column(Integer)           # USA_SSHS untouched
    normalized_category: Mapped[int | None] = mapped_column(Integer)
    category_source: Mapped[str | None] = mapped_column(String(64))
    nature: Mapped[str | None] = mapped_column(String(4))
    track_type: Mapped[str] = mapped_column(String(16), nullable=False)
    iflag: Mapped[str | None] = mapped_column(String(24))
    is_interpolated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dist2land_km: Mapped[float | None] = mapped_column(Float)
    landfall_km: Mapped[float | None] = mapped_column(Float)
    quality_flags: Mapped[str | None] = mapped_column(Text)                  # ';'-joined flags
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(16), nullable=False)

    storm: Mapped[HistoricalStorm] = relationship(back_populates="points")

    __table_args__ = (
        UniqueConstraint("storm_id", "timestamp", name="uq_track_points_storm_time"),
        Index("ix_track_points_storm_id", "storm_id"),
        Index("ix_track_points_timestamp", "timestamp"),
        Index("ix_track_points_category", "normalized_category"),
        Index("ix_track_points_lat_lon", "latitude", "longitude"),
    )


class IngestionRun(HistoricalBase):
    __tablename__ = "historical_ingestion_runs"

    id: Mapped[int] = mapped_column(PK, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    source_version: Mapped[str] = mapped_column(String(16), nullable=False)
    subset: Mapped[str] = mapped_column(String(48), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_file_sha256: Mapped[str | None] = mapped_column(String(64))
    report: Mapped[dict | None] = mapped_column(JSONType)

    __table_args__ = (Index("ix_ingestion_runs_started", "started_at"),)
