"""Structured filter definition + a pure-Python predicate (no SQLAlchemy dependency)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StormFilter:
    storm_id: str | None = None
    name: str | None = None
    basin: str | None = None
    year: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    event_type: str | None = None
    min_category: int | None = None
    max_category: int | None = None
    category_scope: str = "overall"        # "overall" = peak anywhere, "gulf" = peak while in the Gulf
    gulf_only: bool = False
    min_wind_kt: float | None = None

    def is_active(self) -> bool:
        # NB: 0 is a real filter value (tropical-storm category), so test identity, not equality
        return any(v is not None and v is not False for k, v in self.__dict__.items() if k != "category_scope")


def storm_matches(d: dict, f: StormFilter) -> bool:
    """Python mirror of apply_filter, used to re-verify semantic candidates deterministically."""
    cat = d.get("max_category_in_gulf") if f.category_scope == "gulf" else d.get("max_category_normalized")
    checks = [
        f.storm_id is None or d["storm_id"] == f.storm_id.strip(),
        f.name is None or d["name"] == f.name.strip().upper(),
        f.basin is None or d["basin"] == f.basin.strip().upper(),
        f.year is None or d["year"] == f.year,
        f.year_from is None or d["year"] >= f.year_from,
        f.year_to is None or d["year"] <= f.year_to,
        f.event_type is None or d["event_type"] == f.event_type,
        not f.gulf_only or bool(d["gulf_of_mexico_entered"]),
        f.min_category is None or (cat is not None and cat >= f.min_category),
        f.max_category is None or (cat is not None and cat <= f.max_category),
        f.min_wind_kt is None or (d.get("max_wind_kt") is not None and d["max_wind_kt"] >= f.min_wind_kt),
    ]
    return all(checks)
