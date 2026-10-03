"""Category normalisation.

The SOURCE category (IBTrACS ``USA_SSHS``) is stored untouched as ``original_category``.
``normalized_category`` is derived deterministically from sustained wind so every dataset
we add later can be mapped onto one scale.

Convention (documented, not assumed):
  * Wind is the 1-minute sustained maximum wind in KNOTS (IBTrACS ``USA_WIND``; the
    WMO_WIND column is only used as an explicitly-labelled fallback).
  * Saffir-Simpson thresholds in knots (NHC): TD < 34, TS 34-63, Cat1 64-82, Cat2 83-95,
    Cat3 96-112, Cat4 113-136, Cat5 >= 137.
  * Integer scale: -1 = tropical depression, 0 = tropical storm, 1..5 = hurricane category.
    (IBTrACS uses more negative codes for sub/extra-tropical systems; those are kept only
    in ``original_category``.)
"""
from __future__ import annotations

KT_TO_MPH = 1.150779
KT_TO_KMH = 1.852

CATEGORY_SOURCE_USA_WIND = "derived:saffir_simpson_kt:usa_wind"
CATEGORY_SOURCE_WMO_WIND = "derived:saffir_simpson_kt:wmo_wind_fallback"

_THRESHOLDS = ((137, 5), (113, 4), (96, 3), (83, 2), (64, 1), (34, 0))


def category_from_wind_kt(wind_kt: float | None) -> int | None:
    """Return the normalised category for a wind in knots, or None if wind is unknown."""
    if wind_kt is None:
        return None
    for lower, cat in _THRESHOLDS:
        if wind_kt >= lower:
            return cat
    return -1


def category_label(cat: int | None) -> str:
    if cat is None:
        return "unknown"
    if cat >= 1:
        return f"Category {cat} hurricane"
    return {0: "tropical storm", -1: "tropical depression"}.get(cat, "unknown")


def event_type_from_category(cat: int | None) -> str:
    if cat is None:
        return "tropical_cyclone"
    if cat >= 1:
        return "hurricane"
    return "tropical_storm" if cat == 0 else "tropical_depression"


def kt_to_mph(kt: float | None) -> float | None:
    return None if kt is None else round(kt * KT_TO_MPH, 1)
