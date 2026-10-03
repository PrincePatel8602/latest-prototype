import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("path", ["/api/market", "/api/weather", "/api/news", "/api/portfolio"])
def test_endpoints_label_their_source(path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.json()["meta"]["source"] in {"demo", "live", "user"}


def test_demo_portfolio_math():
    body = client.get("/api/portfolio").json()
    assert body["energy_exposure_pct"] == 65  # 30 + 20 + 15
    assert sum(h["value_usd"] for h in body["holdings"]) == pytest.approx(body["total_value"])


def test_news_aggregate_is_mean_of_items():
    body = client.get("/api/news").json()
    mean = sum(i["sentiment_score"] for i in body["items"]) / len(body["items"])
    assert body["aggregate_score"] == pytest.approx(mean, abs=1e-3)


def test_post_portfolio_roundtrip():
    new = {"name": "Mine", "total_value": 100000,
           "holdings": [{"symbol": "aapl", "name": "Apple", "sector": "Technology", "weight_pct": 100}]}
    assert client.post("/api/portfolio", json=new).status_code == 200
    got = client.get("/api/portfolio").json()
    assert got["meta"]["source"] == "user" and got["holdings"][0]["symbol"] == "AAPL"


@pytest.mark.parametrize("bad", [
    {"name": "x", "total_value": 1000, "holdings": [{"symbol": "A", "name": "A", "sector": "Energy", "weight_pct": 50}]},  # sums to 50
    {"name": "x", "total_value": 1000, "holdings": [{"symbol": "A B", "name": "A", "sector": "Energy", "weight_pct": 100}]},  # bad symbol
    {"name": "x", "total_value": 1000, "holdings": [{"symbol": "A", "name": "<b>", "sector": "Energy", "weight_pct": 100}]},  # html chars
    {"name": "x", "total_value": -5, "holdings": []},
])
def test_post_portfolio_rejects_bad_input(bad):
    assert client.post("/api/portfolio", json=bad).status_code == 422
