"""Builds a small IBTrACS-FORMAT csv for tests.

!! SYNTHETIC !! Storm ids/names/values here are invented test fixtures (names start with TEST,
years 2098/2099) and are never loaded by the application. Validation against REAL storms
(Katrina, Rita, Harvey, Ida) lives in test_real_dataset_validation.py and needs the real file.
"""
import csv
from pathlib import Path

COLUMNS = ["SID", "SEASON", "NUMBER", "BASIN", "SUBBASIN", "NAME", "ISO_TIME", "NATURE", "LAT", "LON",
           "WMO_WIND", "WMO_PRES", "TRACK_TYPE", "DIST2LAND", "LANDFALL", "IFLAG",
           "USA_WIND", "USA_PRES", "USA_SSHS", "USA_STATUS"]
UNITS = ["", "Year", "", "", "", "", "", "", "degrees_north", "degrees_east", "kts", "mb", "", "km", "km", "",
         "kts", "mb", "1", ""]


def row(sid, season, name, t, lat, lon, wind="", pres="", sshs="", iflag="O_____________", track="main",
        basin="NA", sub="GM", nature="TS", d2l="500", lf="500", wmo_wind=None, wmo_pres=None):
    return [sid, season, "1", basin, sub, name, t, nature, lat, lon,
            wind if wmo_wind is None else wmo_wind, pres if wmo_pres is None else wmo_pres,
            track, d2l, lf, iflag, wind, pres, sshs, "HU"]


def base_rows():
    A, B, C = "2099001N20280", "2099010N15300", "2098005N25270"
    rows = [
        # Gulf storm: TS -> Cat 4 -> weaker, with a landfall indicator, one interpolated row
        row(A, 2099, "TESTGULF", "2099-08-20 00:00:00", "24.0", "-85.0", "40", "1005", "0"),
        row(A, 2099, "TESTGULF", "2099-08-20 06:00:00", "25.0", "-86.0", "65", "990", "1"),
        row(A, 2099, "TESTGULF", "2099-08-20 09:00:00", "25.5", "-86.5", "75", "985", "1", iflag="I_____________"),
        row(A, 2099, "TESTGULF", "2099-08-20 12:00:00", "26.0", "-87.0", "100", "960", "3"),
        row(A, 2099, "TESTGULF", "2099-08-20 18:00:00", "27.0", "-88.0", "120", "940", "4"),
        row(A, 2099, "TESTGULF", "2099-08-21 00:00:00", "28.5", "-89.5", "95", "955", "2", lf="0", d2l="0"),
        row(A, 2099, "TESTGULF", "2099-08-21 06:00:00", "30.0", "-90.0", "50", "990", "0", lf="0", d2l="0"),
        # open-Atlantic storm, never in the Gulf, no pressure at all
        row(B, 2099, "TESTATL", "2099-09-01 00:00:00", "15.0", "-30.0", "35", "", "0", sub="MM"),
        row(B, 2099, "TESTATL", "2099-09-01 06:00:00", "16.0", "-32.0", "70", "", "1", sub="MM"),
        # unnamed, old season
        row(C, 2098, "UNNAMED", "2098-07-01 00:00:00", "25.0", "-90.0", "30", "1008", "-1"),
        row(C, 2098, "  ", "2098-07-01 06:00:00", "25.5", "-90.5", "", "", ""),
    ]
    return rows


def bad_rows():
    A = "2099001N20280"
    return [
        row(A, 2099, "TESTGULF", "2099-08-20 06:00:00", "25.0", "-86.0", "65", "990", "1"),   # exact duplicate
        row(A, 2099, "TESTGULF", "2099-08-20 12:00:00", "26.5", "-87.5", "100", "960", "3"),   # conflicting duplicate
        row("2099099N10100", 2099, "TESTBAD", "2099-08-22 00:00:00", "95.0", "-90.0", "50", "990", "0"),  # lat
        row("2099099N10100", 2099, "TESTBAD", "not-a-time", "20.0", "-90.0", "50", "990", "0"),            # time
        row("2099099N10100", 2099, "TESTBAD", "2099-08-23 00:00:00", "", "-90.0", "50", "990", "0"),       # coords
        row("2099099N10100", 2099, "TESTBAD", "2099-08-24 00:00:00", "20.0", "-90.0", "50", "990", "0", track="spur"),
        row("", 2099, "TESTBAD", "2099-08-25 00:00:00", "20.0", "-90.0", "50", "990", "0"),               # no SID
        row("2099098N10100", 2099, "TESTBAD2", "2099-08-26 00:00:00", "20.0", "-90.0", "999", "5", "0"),   # impossible wind/pres
        row("2099097N10100", 2099, "TESTWS", "2099-08-27 00:00:00", " 20.0 ", " -90.0 ", " 55 ", " 995 ", " 0 "),  # whitespace
    ]


def write_csv(path: Path, rows) -> Path:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLUMNS)
        w.writerow(UNITS)
        w.writerows(rows)
    return path
