"""Dataset-specific parsing for BSEE (Bureau of Safety and Environmental Enforcement) storm activity statistics.

BSEE publishes no structured file: each storm has daily press-release pages with sentences such as
  "Approximately 24.49 percent of the current oil production of 1,750,000 barrels of oil per day in the Gulf of
   Mexico was shut-in, which equates to 428,568 barrels of oil per day."
Parsing is deliberately strict: a number is only recorded when the sentence pattern matches; otherwise the field is
left empty and the report is flagged (never guessed).
"""
from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass, field
from datetime import date, datetime

MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_RE = re.compile(rf"\b({MONTHS}|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.?\s+(\d{{1,2}}),?\s+(\d{{4}})")


@dataclass
class IndexEntry:
    year: int
    storm_label: str          # accordion heading, e.g. "Hurricane Helene"
    url: str                  # absolute
    link_text: str
    listed_date: date | None  # date shown next to the link in the index (None when absent)


def to_date(month: str, day: str, year: str) -> date | None:
    month = month.rstrip(".")
    for fmt in ("%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(f"{month[:3] if fmt == '%b %d %Y' else month} {day} {year}", fmt).date()
        except ValueError:
            continue
    if month.lower().startswith("sept"):
        return datetime.strptime(f"Sep {day} {year}", "%b %d %Y").date()
    return None


def find_date(text: str) -> date | None:
    m = DATE_RE.search(text)
    return to_date(*m.groups()) if m else None


def plain_text(raw_html: str) -> str:
    t = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw_html)
    t = re.sub(r"(?s)<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", htmllib.unescape(t)).strip()


# ------------------------------------------------------------------ index page
def _is_release_url(url: str) -> bool:
    host = re.match(r"^https?://([^/]+)", url)
    return bool(host and host.group(1).lower().endswith("bsee.gov")
                and re.search(r"press-releases|hurricane", url, re.I))


def _absolute(href: str, base: str) -> str:
    m = re.match(r"^https?://([^/]+)(/.*)?$", href)
    if m and "." not in m.group(1):                       # malformed link such as http://newsroom/latest-news/...
        return base + "/" + m.group(1) + (m.group(2) or "")
    if m:
        return href
    return base + (href if href.startswith("/") else "/" + href)


_TOKEN = re.compile(
    r'<button[^>]*usa-accordion__button[^>]*>\s*(?P<btn>[^<]+?)\s*</button>'
    r'|<li>(?P<li>.*?)</li>', re.S)
_YEAR_BTN = re.compile(r"^(\d{4})\s*\(\d+\)$")
_A = re.compile(r'<a\s+[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<text>.*?)</a>', re.S)


def parse_index(raw_html: str, base: str = "https://www.bsee.gov") -> list[IndexEntry]:
    out: list[IndexEntry] = []
    year, storm = None, None
    for m in _TOKEN.finditer(raw_html):
        if m.group("btn"):
            label = htmllib.unescape(m.group("btn")).strip()
            ym = _YEAR_BTN.match(label)
            if ym:
                year, storm = int(ym.group(1)), None
            else:
                storm = label                       # storm heading (h2 or h4 depending on the year)
        elif m.group("li") and year and storm:
            a = _A.search(m.group("li"))
            if not a:
                continue
            href = htmllib.unescape(a.group("href"))
            if "mailto:" in href or href.startswith("#"):
                continue
            url = _absolute(href, base)
            if not _is_release_url(url):
                continue                              # page footer / navigation links are not storm reports
            li_text = plain_text(m.group("li"))
            out.append(IndexEntry(year, storm, url, plain_text(a.group("text")), find_date(li_text)))
    return out


# ------------------------------------------------------------------ release page
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_CUR = r"(?:current\s+)?(?:daily\s+)?(?:Gulf\s+of\s+\w+\s+)?"
_PCT_OIL = re.compile(rf"{_NUM}\s*(?:percent|%)\s+of\s+the\s+{_CUR}oil\s+production", re.I)
_PCT_GAS = re.compile(rf"{_NUM}\s*(?:percent|%)\s+of\s+the\s+{_CUR}(?:natural\s+)?gas\s+production", re.I)
_BOPD = re.compile(rf"equates\s+to\s+{_NUM}\s+barrels\s+of\s+oil\s+per\s+day", re.I)
_MCFD = re.compile(rf"(?:equates\s+to|or)\s+{_NUM}\s+(?:million\s+cubic\s+feet|MMcf)", re.I)
_PLATFORMS = re.compile(rf"{_NUM}\s+(?:production\s+)?platforms?\s+(?:have\s+been\s+|were\s+|are\s+)?(?:evacuated|shut)", re.I)
_PLAT_ALT = re.compile(rf"(?:personnel\s+)?(?:have\s+been\s+)?evacuated\s+from\s+(?:a\s+total\s+of\s+)?{_NUM}\s+(?:production\s+)?platforms?", re.I)
_RIGS = re.compile(rf"{_NUM}\s+rigs?\s+(?:have\s+been\s+|were\s+|are\s+)?(?:moved|evacuated|secured)", re.I)


def _f(s: str) -> float:
    return float(s.replace(",", ""))


_TYPE_WORDS = re.compile(r"\b(?:post-tropical cyclone|tropical depression|tropical storm|hurricane|major hurricane|subtropical storm)\b", re.I)


ARCHIVE_NOTICE = re.compile(r"You are viewing ARCHIVED content.*?rescinded\.", re.S | re.I)


def head_for_date(full: str) -> str:
    """Page text with the archive notice (it contains a 2025 date) removed."""
    return ARCHIVE_NOTICE.sub(" ", full)


def body_text(raw_html: str) -> str:
    """Article text without the site navigation that wraps every BSEE page."""
    t = plain_text(raw_html)
    i = t.find("rescinded.")
    return t[i + len("rescinded."):].strip() if i != -1 else t


def storm_name_from_label(label: str) -> str:
    return _TYPE_WORDS.sub("", label).strip(" -").strip()


@dataclass
class ReleaseFacts:
    report_date: date | None = None
    oil_shut_in_pct: float | None = None
    gas_shut_in_pct: float | None = None
    oil_shut_in_bopd: float | None = None
    gas_shut_in_mmcfd: float | None = None
    platforms_evacuated: float | None = None
    rigs_moved_off: float | None = None
    flags: list[str] = field(default_factory=list)
    shutin_sentence: str | None = None
    accepted: bool = True            # False when the page cannot be trusted to describe the labelled storm


def parse_release(raw_html: str, *, storm_label: str = "", entry_year: int | None = None,
                  listed_date: date | None = None) -> ReleaseFacts:
    full = plain_text(raw_html)
    text = body_text(raw_html)
    f = ReleaseFacts()
    page_date = find_date(text[:600]) or find_date(head_for_date(full)[:3000])
    f.report_date = listed_date or page_date
    if f.report_date is None:
        f.flags.append("no_report_date")
    # BSEE re-used some page addresses for later storms: verify the page really is about the labelled storm/year
    name = storm_name_from_label(storm_label)
    if name and not name.isdigit() and name.lower() not in full.lower():
        f.accepted = False
        f.flags.append("storm_name_not_on_page")
    if entry_year and page_date and abs(page_date.year - entry_year) > 0 and f.accepted:
        f.accepted = False
        f.flags.append(f"page_year_{page_date.year}_differs_from_{entry_year}")
    if listed_date and page_date and abs((page_date - listed_date).days) > 1:
        f.flags.append("listed_date_differs_from_page_date")
    sent = re.search(r"[^.]*?\bshut[- ]in\b[^.]*\.", text, re.I)
    f.shutin_sentence = sent.group(0).strip()[:400] if sent else None
    for attr, rx in (("oil_shut_in_pct", _PCT_OIL), ("gas_shut_in_pct", _PCT_GAS)):
        m = rx.search(text)
        if m:
            v = _f(m.group(1))
            if 0 <= v <= 100:
                setattr(f, attr, v)
            else:
                f.flags.append(f"{attr}_out_of_range")
    for attr, rx in (("oil_shut_in_bopd", _BOPD), ("gas_shut_in_mmcfd", _MCFD), ("rigs_moved_off", _RIGS)):
        m = rx.search(text)
        if m:
            setattr(f, attr, _f(m.group(1)))
    m = _PLATFORMS.search(text) or _PLAT_ALT.search(text)
    if m:
        f.platforms_evacuated = _f(m.group(1))
    if f.oil_shut_in_pct is None and f.gas_shut_in_pct is None:
        f.flags.append("no_shutin_percentages")
    return f
