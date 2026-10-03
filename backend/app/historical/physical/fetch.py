"""Polite fetching + immutable raw storage for BSEE pages.

raw/bsee/<YYYYMMDD>/index.html            the Hurricane History index at fetch time
raw/bsee/pages/<sha1(url)>/<sha256>.html  one directory per page URL; a changed page becomes a NEW file (never overwritten)
raw/bsee/pages/<sha1(url)>/manifest.json  url, fetched_at, sha256 history
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.historical import settings

INDEX_URL = "https://www.bsee.gov/resources-tools/planning-preparedness/hurricane/Hurricane%20History"
RAW_DIR = settings.DATA_ROOT / "raw" / "bsee"
HEADERS = {"User-Agent": "AEGIS-historical-research/1.0 (academic hackathon project)"}
DELAY_S = 0.4


@dataclass
class StoredPage:
    url: str
    path: Path
    sha256: str
    fetched_at: str
    status: str            # downloaded | unchanged | cached


def _get(client: httpx.Client, url: str, tries: int = 3) -> str:
    last: Exception | None = None
    for i in range(tries):
        try:
            r = client.get(url, headers=HEADERS, timeout=40, follow_redirects=True)
            if r.status_code == 404:
                raise FileNotFoundError(url)
            r.raise_for_status()
            return r.text
        except FileNotFoundError:
            raise
        except httpx.HTTPError as e:
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"fetch failed ({type(last).__name__})")


def store_index(client: httpx.Client, raw_dir: Path = RAW_DIR) -> tuple[str, Path]:
    html = _get(client, INDEX_URL)
    d = raw_dir / datetime.now(timezone.utc).strftime("%Y%m%d")
    d.mkdir(parents=True, exist_ok=True)
    p = d / "index.html"
    p.write_text(html, encoding="utf-8")
    return html, p


def _page_dir(url: str, raw_dir: Path) -> Path:
    return raw_dir / "pages" / hashlib.sha1(url.encode()).hexdigest()


def cached_page(url: str, raw_dir: Path = RAW_DIR) -> StoredPage | None:
    man = _page_dir(url, raw_dir) / "manifest.json"
    if not man.exists():
        return None
    m = json.loads(man.read_text(encoding="utf-8"))
    last = m["history"][-1]
    return StoredPage(url, _page_dir(url, raw_dir) / f"{last['sha256']}.html", last["sha256"], last["fetched_at"], "cached")


def fetch_page(client: httpx.Client, url: str, raw_dir: Path = RAW_DIR, refresh: bool = False) -> StoredPage:
    """Fetch (or reuse) one page. Same bytes -> no new file; changed bytes -> a new immutable file."""
    prev = cached_page(url, raw_dir)
    if prev and not refresh:
        return prev
    html = _get(client, url)
    time.sleep(DELAY_S)
    data = html.encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    d = _page_dir(url, raw_dir)
    d.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    man_path = d / "manifest.json"
    man = json.loads(man_path.read_text(encoding="utf-8")) if man_path.exists() else {"url": url, "history": []}
    status = "downloaded"
    if man["history"] and man["history"][-1]["sha256"] == sha:
        status = "unchanged"
    else:
        (d / f"{sha}.html").write_bytes(data)
        man["history"].append({"sha256": sha, "fetched_at": now, "bytes": len(data)})
    if status == "unchanged":
        man["history"][-1]["last_checked"] = now
    man_path.write_text(json.dumps(man, indent=2), encoding="utf-8")
    return StoredPage(url, d / f"{man['history'][-1]['sha256']}.html", man["history"][-1]["sha256"],
                      man["history"][-1]["fetched_at"], status)
