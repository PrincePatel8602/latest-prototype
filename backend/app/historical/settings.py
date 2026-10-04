"""Paths, provenance constants and environment configuration (no secrets in code)."""
from __future__ import annotations

import os
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

try:   # make DATABASE_URL / PINECONE_* from the project .env visible to os.getenv (real env vars win)
    from dotenv import load_dotenv
    for _env in (BACKEND_ROOT / ".env", BACKEND_ROOT.parent / ".env"):
        load_dotenv(_env, override=False)
except ImportError:
    pass
DATA_ROOT = Path(os.getenv("HISTORICAL_DATA_DIR", BACKEND_ROOT / "data"))

RAW_DIR = DATA_ROOT / "raw" / "ibtracs"
PROCESSED_DIR = DATA_ROOT / "processed" / "ibtracs"
NORMALIZED_DIR = DATA_ROOT / "normalized" / "historical_events"

SOURCE_NAME = "NOAA IBTrACS"
SOURCE_VERSION = "v04r01"
SOURCE_LANDING_URL = "https://www.ncei.noaa.gov/products/international-best-track-archive"
CSV_BASE_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
    "{version}/access/csv/ibtracs.{subset}.list.{version}.csv"
)
COLUMN_DOC_URL = (
    "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-stewardship-ibtracs/"
    "v04r01/doc/IBTrACS_v04r01_column_documentation.pdf"
)
SUPPORTED_SUBSETS = ("NA", "since1980")  # NA = North Atlantic basin file (default)

PG_TABLE_STORMS = "historical_storms"

# Pinecone (all overridable by env; reuse your existing project values if you have them)
DEFAULT_NAMESPACE = "aegis-historical-events"
DEFAULT_INDEX_NAME = "aegis-historical"
DEFAULT_EMBED_MODEL = "llama-text-embed-v2"


def database_url() -> str | None:
    url = os.getenv("DATABASE_URL") or None
    if url and url.startswith(("postgresql://", "postgres://")):      # use the psycopg 3 driver we ship
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    return url


def pinecone_config() -> dict:
    return {
        "api_key": os.getenv("PINECONE_API_KEY") or None,
        "index_name": os.getenv("PINECONE_INDEX_NAME") or DEFAULT_INDEX_NAME,
        "namespace": os.getenv("PINECONE_NAMESPACE") or DEFAULT_NAMESPACE,
        "cloud": os.getenv("PINECONE_CLOUD", "aws"),
        "region": os.getenv("PINECONE_REGION", "us-east-1"),
        "embed_model": os.getenv("PINECONE_EMBED_MODEL", DEFAULT_EMBED_MODEL),
    }
