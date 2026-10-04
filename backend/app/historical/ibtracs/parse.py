"""Dataset-specific parsing of the IBTrACS CSV (raw -> dict rows). No cleaning happens here.

File layout (v04r01): row 1 = column names, row 2 = units (skipped), then one row per
6-hourly / 3-hourly track point. Missing values are an empty string or a single space.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterator

# Only the columns the foundation layer needs. Everything else stays in the raw file.
USED_COLUMNS = (
    "SID", "SEASON", "NUMBER", "BASIN", "SUBBASIN", "NAME", "ISO_TIME", "NATURE", "LAT", "LON",
    "WMO_WIND", "WMO_PRES", "TRACK_TYPE", "DIST2LAND", "LANDFALL", "IFLAG",
    "USA_WIND", "USA_PRES", "USA_SSHS", "USA_STATUS",
)
REQUIRED_COLUMNS = ("SID", "SEASON", "ISO_TIME", "LAT", "LON", "NAME", "BASIN")


class IBTrACSFormatError(ValueError):
    pass


def _looks_like_units_row(row: list[str], idx: dict[str, int]) -> bool:
    sid = row[idx["SID"]].strip() if idx["SID"] < len(row) else ""
    season = row[idx["SEASON"]].strip() if idx["SEASON"] < len(row) else ""
    return sid == "" or season.lower() == "year"


def read_rows(path: str | Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Yield (physical_line_number, {column: raw_string}) for every data row."""
    path = Path(path)
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration as e:  # empty file
            raise IBTrACSFormatError(f"{path} is empty") from e
        idx = {name: i for i, name in enumerate(header)}
        missing = [c for c in REQUIRED_COLUMNS if c not in idx]
        if missing:
            raise IBTrACSFormatError(f"{path} is missing required IBTrACS columns: {missing}")
        present = [c for c in USED_COLUMNS if c in idx]

        first_data = True
        for line_no, row in enumerate(reader, start=2):
            if first_data:
                first_data = False
                if _looks_like_units_row(row, idx):
                    continue  # the units row
            if not row:
                continue
            yield line_no, {c: (row[idx[c]] if idx[c] < len(row) else "") for c in present}
