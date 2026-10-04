"""Common normalised historical-event representation + the Pinecone search document.

This is NOT a market-impact representation. It only describes what physically happened, with
provenance, in a dataset-agnostic shape so future datasets can be aligned by event/time/region.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.historical.categories import category_label, event_type_from_category, kt_to_mph
from app.historical.ibtracs.aggregate import StormSummary


@dataclass(frozen=True)
class SourceProvenance:
    source: str
    source_version: str
    source_url: str
    subset: str
    downloaded_at: str | None = None
    file_sha256: str | None = None


def event_id_for(storm_id: str) -> str:
    return f"ibtracs:{storm_id}"       # stable; used as the Pinecone record id


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def build_event(s: StormSummary, prov: SourceProvenance) -> dict:
    cat = s.max_category_normalized
    return {
        "event_id": event_id_for(s.storm_id),
        "event_type": event_type_from_category(cat),
        "name": s.name,
        "year": s.year,
        "basin": s.basin,
        "region": s.region,
        "start_time": _iso(s.start_datetime),
        "end_time": _iso(s.end_datetime),
        "hazard_features": {
            "max_wind_kt": s.max_wind_kt,
            "max_wind_mph": kt_to_mph(s.max_wind_kt),
            "min_pressure_mb": s.min_pressure_mb,
            "max_category": cat,
            "max_category_original": s.max_category_original,
            "duration_hours": s.duration_hours,
            "track_length_km": s.track_length_km,
            "n_observations": s.n_observations,
            "gulf_of_mexico_entered": s.gulf_of_mexico_entered,
            "max_category_in_gulf": s.max_category_in_gulf,
            "landfall_indicator_observations": s.landfall_indicator_observations,
        },
        "data_quality_status": s.data_quality_status,
        "source_metadata": {
            "source": prov.source, "source_version": prov.source_version,
            "source_url": prov.source_url, "subset": prov.subset,
            "downloaded_at": prov.downloaded_at, "file_sha256": prov.file_sha256,
            "source_record_id": s.storm_id,
        },
    }


def _fmt(v, unit: str = "", nd: int | None = None) -> str:
    if v is None:
        return "not reported"
    if nd is not None:
        v = int(round(v)) if nd == 0 else round(v, nd)
    return f"{v}{unit}"


def build_document(s: StormSummary, prov: SourceProvenance) -> str:
    """One concise, deterministic, factual document per storm (the Pinecone searchable text)."""
    cat = s.max_category_normalized
    name = "unnamed storm" if s.name == "UNNAMED" else s.name.title()
    kind = event_type_from_category(cat).replace("_", " ")
    parts = [
        f"Historical {kind} {name}, {s.year}, {s.region}.",
        f"Maximum intensity: {category_label(cat)}"
        f" (max sustained wind {_fmt(s.max_wind_kt, ' kt')}"
        f" / {_fmt(kt_to_mph(s.max_wind_kt), ' mph')}; minimum central pressure {_fmt(s.min_pressure_mb, ' mb')}).",
        f"Lifetime {s.start_datetime:%Y-%m-%d} to {s.end_datetime:%Y-%m-%d}"
        f" ({_fmt(s.duration_hours, ' hours')}), {s.n_observations} track observations,"
        f" track length about {_fmt(s.track_length_km, ' km', 0)}.",
    ]
    if s.gulf_of_mexico_entered:
        parts.append(
            f"Entered the Gulf of Mexico region; peak category while in the Gulf: "
            f"{category_label(s.max_category_in_gulf)}."
        )
    else:
        parts.append("Did not enter the Gulf of Mexico region.")
    if s.landfall_indicator_observations:
        parts.append(
            f"Track data flags {s.landfall_indicator_observations} observation(s) with an "
            f"imminent-landfall indicator."
        )
    parts.append(f"Source: {prov.source} {prov.source_version}, storm id {s.storm_id}.")
    return " ".join(parts)
