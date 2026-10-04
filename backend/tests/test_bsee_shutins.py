"""BSEE shut-in layer tests on SYNTHETIC pages that copy the real wording/layouts (storm TESTANA etc. are invented)."""
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.analytics.models  # noqa: F401  (register tables)
import app.historical.market.models  # noqa: F401
import app.historical.physical.models  # noqa: F401
from app.api import historical as historical_api
from app.historical import runtime
from app.historical.models import HistoricalBase, HistoricalStorm
from app.historical.physical import fetch, parse
from app.historical.physical.models import BseeReport, BseeStormShutin
from app.historical.physical.pipeline import run_bsee_ingest
from app.main import app
from app.services import historical_service

NOTICE = ("You are viewing ARCHIVED content published online before Jan. 20, 2025. Please note that this content is NOT "
          "UPDATED , and links may not work. any previously issued guidance on this webpage should be considered rescinded.")


def page(title, body):
    return f"<html><body><nav>Home Hurricane Season Information</nav><h1>{title}</h1><p>{NOTICE}</p><p>{body}</p></body></html>"


NEW_STYLE = ("NEW ORLEANS - Approximately 24.49 percent of the current oil production of 1,750,000 barrels of oil per day in the "
             "Gulf of Mexico was shut-in, which equates to 428,568 barrels of oil per day. Approximately 25.94 percent of the "
             "natural gas production of 3,220 million cubic feet per day, or 835 million cubic feet per day in the Gulf was shut-in. "
             "Personnel have been evacuated from 112 production platforms.")
OLD_STYLE = ("it is estimated that approximately 93.53 percent of the current daily oil production in the Gulf of Mexico has been "
             "shut-in. It is also estimated that approximately 65.26 percent of the current daily natural gas production in the "
             "Gulf of Mexico has been shut-in. personnel have been evacuated from a total of 219 production platforms, equivalent "
             "to 36.75 percent of the 596 manned platforms.")


def index_html(items):
    """items: list of (year, storm_label, [(date_prefix_or_None, href, text)])"""
    out = ""
    years = sorted({i[0] for i in items}, reverse=True)
    for y in years:
        out += f'<h2 class="usa-accordion__heading"><button class="usa-accordion__button">{y} (9)</button></h2>'
        for yy, label, lis in items:
            if yy != y:
                continue
            out += f'<h4 class="usa-accordion__heading"><button class="usa-accordion__button">{label}</button></h4><ul>'
            for d, href, text in lis:
                out += f"<li>{d + ' -&nbsp;' if d else ''}<a href=\"{href}\">{text}</a></li>"
            out += "</ul>"
    out += '<ul><li><a href="https://www.usa.gov">USA.gov</a></li></ul>'          # footer link that must be ignored
    return out


# ------------------------------------------------------------------ parsing
def test_new_and_old_wording_both_parse():
    a = parse.parse_release(page("BSEE Hurricane Testana Activity Statistics: August 26, 2017", NEW_STYLE),
                            storm_label="Hurricane Testana", entry_year=2017)
    assert (a.oil_shut_in_pct, a.gas_shut_in_pct, a.oil_shut_in_bopd) == (24.49, 25.94, 428568.0)
    assert a.platforms_evacuated == 112 and a.report_date == date(2017, 8, 26) and a.accepted and not a.flags
    b = parse.parse_release(page("BSEE Tropical Storm Testana Activity Statistics: September 1, 2012", OLD_STYLE),
                            storm_label="Tropical Storm Testana", entry_year=2012)
    assert (b.oil_shut_in_pct, b.gas_shut_in_pct, b.platforms_evacuated) == (93.53, 65.26, 219) and b.accepted


def test_archive_notice_date_is_not_mistaken_for_the_report_date():
    f = parse.parse_release(page("BSEE Monitors Gulf Activities in Response to Hurricane Testana", NEW_STYLE),
                            storm_label="Hurricane Testana", entry_year=2020, listed_date=None)
    assert f.report_date is None and "no_report_date" in f.flags and f.accepted     # no 2025 date invented from the notice


def test_page_about_another_storm_or_year_is_rejected_and_numbers_are_not_used():
    other = parse.parse_release(page("BSEE Monitors ... Post-Tropical Cyclone Rafael Monday, November 11, 2024", NEW_STYLE),
                                storm_label="Hurricane Testana", entry_year=2021, listed_date=date(2021, 8, 28))
    assert not other.accepted and "storm_name_not_on_page" in other.flags
    wrong_year = parse.parse_release(page("Hurricane Testana Update Monday, November 11, 2024", NEW_STYLE),
                                     storm_label="Hurricane Testana", entry_year=2021)
    assert not wrong_year.accepted and any(f.startswith("page_year_2024") for f in wrong_year.flags)


def test_missing_and_out_of_range_percentages_are_flagged_not_guessed():
    f = parse.parse_release(page("Hurricane Testana", "Operators are monitoring. 140 percent of the current oil production shut-in."),
                            storm_label="Hurricane Testana", entry_year=2020)
    assert f.oil_shut_in_pct is None and "oil_shut_in_pct_out_of_range" in f.flags and "no_shutin_percentages" in f.flags


def test_index_parsing_handles_layouts_footers_and_malformed_links():
    html = index_html([
        (2024, "Hurricane Testana", [("September 24, 2024", "/newsroom/press-releases/a-1", "Update 1"), (None, "/BSEE-Newsroom/Press-Releases/2024/b/", "Update 2")]),
        (2021, "Tropical Storm Testbee", [("August 27, 2021", "http://newsroom/latest-news/statements-and-releases/press-releases/c", "Bad host")])])
    es = parse.parse_index(html)
    assert [(e.year, e.storm_label) for e in es] == [(2024, "Hurricane Testana")] * 2 + [(2021, "Tropical Storm Testbee")]
    assert es[0].url == "https://www.bsee.gov/newsroom/press-releases/a-1" and es[0].listed_date == date(2024, 9, 24)
    assert es[1].listed_date is None
    assert es[2].url == "https://www.bsee.gov/newsroom/latest-news/statements-and-releases/press-releases/c"
    assert not any("usa.gov" in e.url for e in es)


def test_storm_name_from_label():
    assert parse.storm_name_from_label("Post-Tropical Cyclone Rafael") == "Rafael"
    assert parse.storm_name_from_label("Hurricane michael") == "michael"
    assert parse.storm_name_from_label("Tropical Depression 13") == "13"


# ------------------------------------------------------------------ pipeline (fake network, real raw store)
class FakeClient:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **kw):
        self.calls.append(url)
        if url not in self.pages:
            return FakeResp(404, "")
        return FakeResp(200, self.pages[url])

    def close(self):
        pass


class FakeResp:
    def __init__(self, code, text):
        self.status_code, self.text = code, text

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError("x", request=None, response=self)


B = "https://www.bsee.gov"


def world():
    items = [
        (2017, "Hurricane Testana", [("August 25, 2017", "/newsroom/press-releases/ok1", "u1"), ("August 26, 2017", "/newsroom/press-releases/ok2", "u2"),
                                     ("August 27, 2017", "/newsroom/press-releases/reused", "u3"), ("August 28, 2017", "/newsroom/press-releases/gone", "u4")]),
        (2017, "Tropical Storm Testbee", [("August 26, 2017", "/newsroom/press-releases/ok2", "same page listed under two storms")]),
        (2018, "Tropical Storm Testcee", [("June 1, 2018", "/newsroom/press-releases/cee", "u5")]),
    ]
    pages = {
        B + "/newsroom/press-releases/ok1": page("Hurricane Testana Activity Statistics: August 25, 2017",
                           "Approximately 10.5 percent of the current oil production in the Gulf of Mexico was shut-in. "
                           "Approximately 5.0 percent of the natural gas production in the Gulf was shut-in."),
        B + "/newsroom/press-releases/ok2": page("Hurricane Testana Activity Statistics: August 26, 2017", NEW_STYLE),
        B + "/newsroom/press-releases/cee": page("Tropical Storm Testcee Activity Statistics: June 1, 2018",
                                                 "Approximately 3.0 percent of the current oil production in the Gulf was shut-in."),
        B + "/newsroom/press-releases/reused": page("Post-Tropical Cyclone Rafael Monday, November 11, 2024", NEW_STYLE),
        fetch.INDEX_URL: index_html(items),
    }
    return pages


@pytest.fixture
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    HistoricalBase.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def add_storm(factory, name="TESTANA", year=2017, sid="2017228N14314"):
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with factory() as s:
        s.add(HistoricalStorm(storm_id=sid, name=name, year=year, basin="NA", region="x", event_type="hurricane", start_datetime=now,
                              end_datetime=now, n_observations=1, n_original_observations=1, gulf_of_mexico_entered=True, min_lat=0,
                              max_lat=1, min_lon=0, max_lon=1, source="NOAA IBTrACS", source_version="v04r01", source_url="u",
                              source_subset="s", ingestion_timestamp=now, data_quality_status="ok", content_hash="h",
                              max_category_normalized=4, max_category_in_gulf=4, max_wind_kt=115))
        s.commit()


def test_ingest_verifies_dedupes_aggregates_links_and_is_idempotent(db, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "DELAY_S", 0)
    add_storm(db)
    client = FakeClient(world())
    with db() as s:
        out = run_bsee_ingest(s, client=client, raw_dir=tmp_path)
    assert out.entries == 6 and out.duplicate_listings == 1
    assert (out.accepted, out.rejected, out.fetch_errors) == (3, 1, 1)         # reused address rejected, dead link counted
    with db() as s:
        statuses = {r.url.rsplit("/", 1)[-1]: (r.status, r.accepted) for r in s.scalars(select(BseeReport))}
        assert statuses == {"ok1": ("ok", True), "ok2": ("ok", True), "reused": ("rejected", False), "gone": ("fetch_error", False), "cee": ("ok", True)}
        rej = s.scalar(select(BseeReport).where(BseeReport.status == "rejected"))
        assert rej.oil_shut_in_pct is None                                       # numbers from a mismatched page are never stored
        agg = s.scalar(select(BseeStormShutin).where(BseeStormShutin.storm_label == "Hurricane Testana"))
        assert (agg.max_oil_shut_in_pct, agg.max_gas_shut_in_pct, agg.n_reports_used, agg.n_reports_listed) == (24.49, 25.94, 2, 4)
        assert agg.storm_id == "2017228N14314" and agg.match_method == "name_year" and agg.peak_oil_date == date(2017, 8, 26)
        assert "lower bound" in agg.note
        assert s.scalar(select(BseeStormShutin).where(BseeStormShutin.storm_label == "Tropical Storm Testbee")) is None
        other = s.scalar(select(BseeStormShutin).where(BseeStormShutin.storm_label == "Tropical Storm Testcee"))
        assert other.match_method == "unmatched" and other.storm_id is None and other.max_oil_shut_in_pct == 3.0

    n_calls = len(client.calls)
    with db() as s:                                                              # second run: nothing changes, raw is reused
        again = run_bsee_ingest(s, client=client, raw_dir=tmp_path, from_raw=True)
        assert (again.reports_inserted, again.reports_updated, again.reports_unchanged) == (0, 0, 5)
        assert s.scalar(select(func.count()).select_from(BseeReport)) == 5
    assert len(client.calls) == n_calls                                          # --from-raw made no network calls
    assert len(list((tmp_path / "pages").rglob("*.html"))) == 4                  # one immutable raw file per fetched page


def test_changed_page_becomes_a_new_immutable_raw_file(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "DELAY_S", 0)
    url = B + "/newsroom/press-releases/x"
    c1 = FakeClient({url: "<html>v1</html>"})
    a = fetch.fetch_page(c1, url, tmp_path)
    c2 = FakeClient({url: "<html>v2</html>"})
    assert fetch.fetch_page(c2, url, tmp_path).sha256 == a.sha256 and not c2.calls    # cached: no refetch
    b = fetch.fetch_page(c2, url, tmp_path, refresh=True)
    assert b.status == "downloaded" and b.sha256 != a.sha256 and a.path.exists() and b.path.exists()
    assert fetch.fetch_page(c2, url, tmp_path, refresh=True).status == "unchanged"


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "DELAY_S", 0)
    out = run_bsee_ingest(None, dry_run=True, client=FakeClient(world()), raw_dir=tmp_path)
    assert out.dry_run and out.accepted == 3 and out.storms == 0


# ------------------------------------------------------------------ exposure through service + API
@pytest.fixture
def seeded(db, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "DELAY_S", 0)
    add_storm(db)
    with db() as s:
        run_bsee_ingest(s, client=FakeClient(world()), raw_dir=tmp_path)
    monkeypatch.setattr(historical_service, "get_sessionmaker", lambda: db)
    monkeypatch.setattr(runtime, "database_enabled", lambda: True)
    monkeypatch.setattr(runtime, "vector_store", lambda: None)

    def override():
        s = db()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[historical_api.get_session] = override
    yield db
    app.dependency_overrides.clear()


def test_agent_attaches_physical_impact_with_provenance(seeded):
    r = historical_service.search(event_type="hurricane", region="Gulf of Mexico", category=4)
    p = r.matches[0].physical_impact
    assert p.max_oil_shut_in_pct == 24.49 and p.max_gas_shut_in_pct == 25.94 and p.n_reports_used == 2 and p.n_reports_listed == 4
    assert p.source == "BSEE storm activity statistics" and p.source_urls and "lower bound" in p.note


def test_api_shut_in_endpoints(seeded):
    c = TestClient(app)
    d = c.get("/api/historical/shut-ins/2017228N14314").json()
    assert d["available"] and d["summary"]["max_oil_shut_in_pct"] == 24.49
    assert [r["date"] for r in d["reports"]] == ["2017-08-25", "2017-08-26"] and all(r["raw_sha256"] for r in d["reports"])
    assert c.get("/api/historical/shut-ins/NOPE").status_code == 404
    add_storm(seeded, name="OTHER", year=2001, sid="2001001N10100")
    assert c.get("/api/historical/shut-ins/2001001N10100").json()["available"] is False
    assert c.get("/api/historical/shutin-response").json()["series"] == {}              # no event-study rows yet: empty, not invented


def test_spearman_and_split_logic():
    from app.analytics.shutin_link import spearman
    assert spearman([1, 2, 3, 4, 5], [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4, 5], [5, 4, 3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 1, 1], [1, 2, 3]) is None and spearman([1, 2], [1, 2]) is None
