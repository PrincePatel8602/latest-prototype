#!/usr/bin/env python
"""Smoke-check the live historical stack (DATABASE_URL + Pinecone) through the real API.

  python scripts/verify_historical.py
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
logging.disable(logging.INFO)

from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

settings.llm_api_key = ""        # this check must not spend LLM quota; the rule-based parser is enough

EXPECTED = {("KATRINA", 2005): (150, 5), ("RITA", 2005): (155, 5), ("HARVEY", 2017): (115, 4), ("IDA", 2021): (130, 4)}


def main() -> int:
    c, bad = TestClient(app), 0
    print("status:", c.get("/api/historical/status").json())
    for (name, year), (wind, cat) in EXPECTED.items():
        hits = c.post("/api/historical/search", json={"name": name, "year": year}).json().get("hits", [])
        if not hits:
            print(f"MISSING {name} {year}"); bad += 1; continue
        s = hits[0]["storm"]
        ok = abs(s["max_wind_kt"] - wind) <= 5 and s["max_category_normalized"] == cat
        bad += not ok
        print(f"{'OK  ' if ok else 'FAIL'} {name} {year}: {s['max_wind_kt']} kt, {s['min_pressure_mb']} mb, Cat {s['max_category_normalized']}, "
              f"pg={s['provenance']['postgres']['id']}, pinecone_in_sync={(s['provenance']['pinecone'] or {}).get('in_sync')}")
    r = c.post("/api/historical/search", json={"gulf_of_mexico": True, "category_scope": "gulf", "event_type": "hurricane",
                                               "category_target": 4, "query": "Category 4 Gulf hurricane", "top_k": 5}).json()
    print("hybrid:", r["retrieval_method"], r["semantic_status"],
          [(h["storm"]["name"], h["storm"]["year"], h["similarity_score"] and round(h["similarity_score"], 3)) for h in r["hits"]])
    q = c.post("/api/query", json={"query": "How would a Category 4 hurricane in the Gulf of Mexico affect my energy holdings?"}).json()
    print("pipeline historical:", q["historical"]["status"], q["historical"]["retrieval_method"], len(q["historical"]["matches"]))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
