"""Parsing + cleaning of raw market payloads into a common daily observation shape.

Nothing is dropped silently: every rejected row is counted by reason in the report.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from app.historical.market.config import SeriesSpec

MISSING = {"", ".", "na", "nan", "null", "none", "-"}


@dataclass(slots=True)
class Observation:
    obs_date: date
    value: float                   # close / spot / index level
    open: float | None = None
    high: float | None = None
    low: float | None = None
    adj_close: float | None = None
    volume: float | None = None


@dataclass
class MarketReport:
    series_key: str = ""
    raw_rows: int = 0
    valid: int = 0
    rejected: int = 0
    duplicates_removed: int = 0
    reject_reasons: Counter = field(default_factory=Counter)
    first_date: str | None = None
    last_date: str | None = None

    def reject(self, reason: str) -> None:
        self.rejected += 1
        self.reject_reasons[reason] += 1

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "reject_reasons"}
        d["reject_reasons"] = dict(self.reject_reasons)
        return d


def _num(v) -> float | None:
    """None for a recognised missing token; ValueError/TypeError for garbage."""
    if v is None or (isinstance(v, str) and v.strip().lower() in MISSING):
        return None
    x = float(v)
    return x if math.isfinite(x) else None


def _date(v) -> date:
    return datetime.strptime(str(v).strip()[:10], "%Y-%m-%d").date()


# ------------------------------------------------------------------ source-specific parsers -> (date, fields)
def parse_fred(payload: dict):
    for o in payload.get("observations", []):
        yield o.get("date"), {"value": o.get("value")}


def parse_eia(pages: list[dict]):
    for page in pages:
        for o in page.get("response", {}).get("data", []):
            yield o.get("period"), {"value": o.get("value")}


def parse_yahoo(payload: dict):
    res = (payload.get("chart", {}).get("result") or [None])[0]
    if not res:
        return
    off = res.get("meta", {}).get("gmtoffset", 0) or 0
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    for i, ts in enumerate(res.get("timestamp") or []):
        d = datetime.fromtimestamp(ts + off, tz=timezone.utc).date().isoformat()
        yield d, {"value": q["close"][i], "open": q["open"][i], "high": q["high"][i], "low": q["low"][i],
                  "volume": q["volume"][i], "adj_close": adj[i] if adj else None}


PARSERS = {"fred": parse_fred, "eia": parse_eia, "yahoo": parse_yahoo}


def clean(spec: SeriesSpec, payload) -> tuple[list[Observation], MarketReport]:
    rep = MarketReport(series_key=spec.key)
    kept: dict[date, Observation] = {}
    today = datetime.now(timezone.utc).date()
    for raw_date, f in PARSERS[spec.source](payload):
        rep.raw_rows += 1
        try:
            d = _date(raw_date)
        except (ValueError, TypeError):
            rep.reject("invalid_date"); continue
        if d > today:
            rep.reject("future_date"); continue
        try:
            value = _num(f.get("value"))
            extras = {k: _num(f.get(k)) for k in ("open", "high", "low", "adj_close", "volume")}
        except (TypeError, ValueError):
            rep.reject("non_numeric"); continue
        if value is None:
            rep.reject("missing_value"); continue
        if value < 0 and not spec.allow_negative:
            rep.reject("negative_value"); continue
        if spec.category in ("equity", "etf") and value == 0:
            rep.reject("zero_price"); continue
        if d in kept:
            rep.duplicates_removed += 1
        kept[d] = Observation(d, value, **extras)      # a later duplicate row replaces an earlier one
    out = [kept[d] for d in sorted(kept)]
    rep.valid = len(out)
    if out:
        rep.first_date, rep.last_date = out[0].obs_date.isoformat(), out[-1].obs_date.isoformat()
    return out, rep
