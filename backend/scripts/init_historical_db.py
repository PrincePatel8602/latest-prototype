#!/usr/bin/env python
"""Create the historical tables (idempotent). Uses DATABASE_URL."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.historical.database import init_schema  # noqa: E402

init_schema()
print("historical_storms, storm_track_points, historical_ingestion_runs ready")
