"""Pinecone semantic layer (integrated embedding, current SDK API).

PostgreSQL stays the source of truth: Pinecone holds ONE searchable document per storm plus the
metadata needed to link back (event_id / storm_id / postgres_id) and to pre-filter. No numeric
track data lives here and no result is ever returned to a caller without being re-read from
PostgreSQL.

API used (Pinecone Python SDK, integrated inference):
    pc.create_index_for_model(name, cloud, region, embed={"model", "field_map": {"text": "chunk_text"}})
    index.upsert_records(namespace, [{"_id": ..., "chunk_text": ..., **metadata}])
    index.search(namespace=..., query={"top_k": n, "inputs": {"text": ...}, "filter": {...}})
Pin `pinecone` to a major version you have tested (see requirements_historical.txt).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Sequence

from app.historical import settings

log = logging.getLogger("aegis.historical.vector")
TEXT_FIELD = "chunk_text"
UPSERT_BATCH = 90          # hosted-embedding upserts are limited to 96 records per request


@dataclass(frozen=True)
class SemanticHit:
    event_id: str
    score: float
    metadata: dict


def build_metadata(storm: dict) -> dict:
    """Flat, Pinecone-legal metadata (str/number/bool only; None dropped)."""
    prov = storm["provenance"]
    md = {
        "event_id": storm["event_id"], "postgres_id": storm["postgres_id"], "storm_id": storm["storm_id"],
        "name": storm["name"], "year": storm["year"], "basin": storm["basin"], "region": storm["region"],
        "event_type": storm["event_type"], "max_category": storm["max_category_normalized"],
        "max_category_in_gulf": storm["max_category_in_gulf"],
        "gulf_of_mexico_entered": bool(storm["gulf_of_mexico_entered"]),
        "max_wind_kt": storm["max_wind_kt"], "source": prov["source"], "source_version": prov["dataset_version"],
        "content_hash": storm.get("content_hash"),
    }
    return {k: v for k, v in md.items() if v is not None}


def build_record(storm: dict, document: str) -> dict:
    return {"_id": storm["event_id"], TEXT_FIELD: document, **build_metadata(storm)}


def to_pinecone_filter(f) -> dict | None:
    """Translate a StormFilter into a Pinecone metadata filter (pre-filter only; PostgreSQL re-verifies)."""
    clauses: list[dict] = []
    if f.basin:
        clauses.append({"basin": {"$eq": f.basin.upper()}})
    if f.name:
        clauses.append({"name": {"$eq": f.name.upper()}})
    if f.year is not None:
        clauses.append({"year": {"$eq": f.year}})
    if f.year_from is not None:
        clauses.append({"year": {"$gte": f.year_from}})
    if f.year_to is not None:
        clauses.append({"year": {"$lte": f.year_to}})
    if f.event_type:
        clauses.append({"event_type": {"$eq": f.event_type}})
    if f.gulf_only:
        clauses.append({"gulf_of_mexico_entered": {"$eq": True}})
    field = "max_category_in_gulf" if f.category_scope == "gulf" else "max_category"
    if f.min_category is not None:
        clauses.append({field: {"$gte": f.min_category}})
    if f.max_category is not None:
        clauses.append({field: {"$lte": f.max_category}})
    if f.min_wind_kt is not None:
        clauses.append({"max_wind_kt": {"$gte": f.min_wind_kt}})
    if not clauses:
        return None
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def _get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class HistoricalVectorStore:
    def __init__(self, index: Any, namespace: str):
        self.index, self.namespace = index, namespace

    def upsert(self, records: Sequence[dict], batch_size: int = UPSERT_BATCH) -> int:
        n = 0
        for i in range(0, len(records), batch_size):
            batch = list(records[i:i + batch_size])
            self.index.upsert_records(namespace=self.namespace, records=batch)       # idempotent: same _id overwrites
            n += len(batch)
        return n

    def search(self, text: str, top_k: int = 10, filter: dict | None = None) -> list[SemanticHit]:
        kwargs: dict = {"namespace": self.namespace, "top_k": top_k, "inputs": {"text": text}}
        if filter:
            kwargs["filter"] = filter
        fn = getattr(self.index, "search", None) or getattr(self.index, "search_records")
        res = fn(**kwargs)
        hits = _get(_get(res, "result", {}), "hits", []) or []
        out = []
        for h in hits:
            fields = _get(h, "fields", {}) or {}
            out.append(SemanticHit(event_id=_get(h, "id") or _get(h, "_id"),      # SDK 9: Hit.id / Hit.score; REST: _id / _score
                               score=float(_get(h, "score", None) if _get(h, "score", None) is not None else _get(h, "_score", 0.0)),
                               metadata=dict(fields)))
        return out

    def count(self) -> int | None:
        try:
            st = self.index.describe_index_stats()
            ns = _get(_get(st, "namespaces", {}) or {}, self.namespace, None)
            return None if ns is None else int(_get(ns, "vector_count", 0))
        except Exception:                                           # noqa: BLE001
            return None


def _wait_ready(pc: Any, name: str, timeout: int = 180) -> Any:
    deadline = time.time() + timeout
    while True:
        desc = pc.describe_index(name)
        status = _get(desc, "status", {}) or {}
        if _get(status, "ready", False):
            return desc
        if time.time() > deadline:
            raise TimeoutError(f"Pinecone index {name!r} not ready after {timeout}s")
        time.sleep(3)


def connect(cfg: dict | None = None, *, create: bool = True) -> HistoricalVectorStore | None:
    """Return a store, or None when PINECONE_API_KEY is not configured (callers report that explicitly)."""
    cfg = cfg or settings.pinecone_config()
    if not cfg["api_key"]:
        return None
    from pinecone import Pinecone  # imported lazily so the rest of the app never needs the SDK

    pc = Pinecone(api_key=cfg["api_key"])
    name = cfg["index_name"]
    if not pc.has_index(name):
        if not create:
            raise RuntimeError(f"Pinecone index {name!r} does not exist")
        log.info("creating Pinecone index %s (%s, model %s)", name, cfg["cloud"], cfg["embed_model"])
        pc.create_index_for_model(name=name, cloud=cfg["cloud"], region=cfg["region"],
                                  embed={"model": cfg["embed_model"], "field_map": {"text": TEXT_FIELD}})
    desc = _wait_ready(pc, name)
    return HistoricalVectorStore(pc.Index(host=_get(desc, "host")), cfg["namespace"])
