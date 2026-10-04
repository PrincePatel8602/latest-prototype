"""RAW -> VALIDATION -> CLEANING -> TRANSFORMATION -> NORMALISATION (files only).

`process_snapshot` is a pure function of the raw file: delete data/processed and
data/normalized and re-run it and you get byte-identical output. PostgreSQL / Pinecone loading
happens afterwards in app.historical.ingest.
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from app.historical import settings
from app.historical.events import SourceProvenance, build_document, build_event
from app.historical.ibtracs.aggregate import StormSummary, summarize_all
from app.historical.ibtracs.clean import QualityReport, TrackPoint, clean_rows
from app.historical.ibtracs.download import RawSnapshot
from app.historical.ibtracs.parse import read_rows

POINT_FIELDS = ["storm_id", "timestamp", "lat", "lon", "wind_kt", "wind_source", "pressure_mb",
                "pressure_source", "original_category", "normalized_category", "category_source",
                "nature", "track_type", "iflag", "is_interpolated", "dist2land_km", "landfall_km",
                "quality_flags"]


@dataclass
class ProcessingResult:
    snapshot: RawSnapshot
    provenance: SourceProvenance
    points: list[TrackPoint]
    storms: list[StormSummary]
    events: list[dict]
    documents: dict[str, str]        # event_id -> search text
    report: QualityReport
    min_year: int | None
    subset_label: str


def subset_label(subset: str, min_year: int | None, basins: tuple[str, ...] | None = None) -> str:
    label = f"{subset}/min_year>={min_year}" if min_year else f"{subset}/all_years"
    return f"{label}/basins={'+'.join(basins)}" if basins else label


def process_snapshot(snapshot: RawSnapshot, *, min_year: int | None = 1980,
                     basins: tuple[str, ...] | None = None, now=None) -> ProcessingResult:
    label = subset_label(snapshot.subset, min_year, basins)
    report = QualityReport(source=snapshot.source, version=snapshot.version, subset=label)
    points, report = clean_rows(read_rows(snapshot.path), min_year=min_year, basins=basins, now=now, report=report)
    storms = summarize_all(points)
    prov = SourceProvenance(source=snapshot.source, source_version=snapshot.version, source_url=snapshot.url,
                            subset=label, downloaded_at=snapshot.downloaded_at, file_sha256=snapshot.sha256)
    events = [build_event(s, prov) for s in storms]
    docs = {e["event_id"]: build_document(s, prov) for e, s in zip(events, storms)}
    return ProcessingResult(snapshot, prov, points, storms, events, docs, report, min_year, label)


def write_outputs(res: ProcessingResult, processed_dir: Path = settings.PROCESSED_DIR,
                  normalized_dir: Path = settings.NORMALIZED_DIR) -> dict[str, Path]:
    """Write processed + normalised files. Raw is never touched."""
    tag = f"{res.snapshot.version}/{res.snapshot.subset}"
    pdir = processed_dir / tag
    pdir.mkdir(parents=True, exist_ok=True)
    normalized_dir.mkdir(parents=True, exist_ok=True)

    points_path = pdir / "track_points_clean.csv"
    with points_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(POINT_FIELDS)
        for p in res.points:
            w.writerow([p.storm_id, p.timestamp.isoformat(), p.lat, p.lon, p.wind_kt, p.wind_source,
                        p.pressure_mb, p.pressure_source, p.original_category, p.normalized_category,
                        p.category_source, p.nature, p.track_type, p.iflag, int(p.is_interpolated),
                        p.dist2land_km, p.landfall_km, ";".join(p.quality_flags)])

    rejects_path = pdir / "rejected_rows.csv"
    with rejects_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["line", "sid", "reason", "detail"])
        w.writeheader()
        w.writerows(res.report.reject_samples)

    report_path = pdir / "ingestion_report.json"
    report_path.write_text(json.dumps({
        "source": res.snapshot.source, "dataset_version": res.snapshot.version, "subset": res.subset_label,
        "source_url": res.snapshot.url, "downloaded_at": res.snapshot.downloaded_at,
        "raw_file": res.snapshot.path.name, "raw_sha256": res.snapshot.sha256,
        "quality": res.report.to_dict(), "storms": len(res.storms),
    }, indent=2, sort_keys=True), encoding="utf-8")

    events_path = normalized_dir / f"ibtracs_{res.snapshot.version}_{res.snapshot.subset}.jsonl"
    with events_path.open("w", encoding="utf-8") as fh:
        for e in res.events:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    return {"points": points_path, "rejects": rejects_path, "report": report_path, "events": events_path}


def format_report(res: ProcessingResult) -> str:
    r = res.report
    lines = [
        f"Source:                 {res.snapshot.source}",
        f"Dataset version:        {res.snapshot.version}",
        f"Subset:                 {res.subset_label}",
        f"Downloaded at:          {res.snapshot.downloaded_at}",
        f"Raw file sha256:        {res.snapshot.sha256[:16]}...",
        f"Raw rows read:          {r.raw_rows}",
        f"Filtered (min year):    {r.filtered_out_min_year}",
        f"Filtered (basin):       {r.filtered_out_basin}",
        f"Valid track points:     {r.valid_points}",
        f"Rejected rows:          {r.rejected_rows}",
        f"Duplicates removed:     {r.duplicates_removed} (conflicting: {r.duplicates_conflicting})",
        f"Missing wind:           {r.missing_wind}",
        f"Missing pressure:       {r.missing_pressure}",
        f"Missing names:          {r.missing_names}",
        f"Category disagreements: {r.category_disagreements} (derived vs source USA_SSHS)",
        f"Storms:                 {len(res.storms)}",
    ]
    if r.reject_reasons:
        lines.append("Reject reasons:         " + ", ".join(f"{k}={v}" for k, v in sorted(r.reject_reasons.items())))
    if r.flag_counts:
        lines.append("Quality flags:          " + ", ".join(f"{k}={v}" for k, v in sorted(r.flag_counts.items())))
    return "\n".join(lines)
