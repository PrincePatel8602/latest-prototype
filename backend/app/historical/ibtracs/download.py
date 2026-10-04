"""Reproducible download of an IBTrACS CSV with a provenance manifest.

Raw snapshots are immutable: each download goes to  raw/ibtracs/<version>/<subset>/<YYYYMMDD>/
together with a manifest.json (URL, version, download time, HTTP Last-Modified, size, sha256).
A later download never overwrites an earlier one.
"""
from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

from app.historical import settings


@dataclass
class RawSnapshot:
    path: Path
    manifest_path: Path
    source: str
    version: str
    subset: str
    url: str
    downloaded_at: str
    http_last_modified: str | None
    bytes: int
    sha256: str
    origin: str = "downloaded_by_aegis"   # or "user_supplied_file" (download time = file mtime)


def csv_url(subset: str, version: str = settings.SOURCE_VERSION) -> str:
    if subset not in settings.SUPPORTED_SUBSETS:
        raise ValueError(f"unsupported subset {subset!r}; choose from {settings.SUPPORTED_SUBSETS}")
    return settings.CSV_BASE_URL.format(version=version, subset=subset)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(subset: str = "NA", version: str = settings.SOURCE_VERSION,
             raw_dir: Path = settings.RAW_DIR, timeout: int = 120) -> RawSnapshot:
    url = csv_url(subset, version)
    stamp = datetime.now(timezone.utc)
    dest_dir = raw_dir / version / subset / stamp.strftime("%Y%m%d")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / Path(url).name
    if dest.exists():
        raise FileExistsError(f"{dest} already exists; raw snapshots are never overwritten")
    part = dest.with_suffix(dest.suffix + ".part")

    req = urllib.request.Request(url, headers={"User-Agent": "AEGIS-historical-ingest/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp, part.open("wb") as out:  # noqa: S310
        last_modified = resp.headers.get("Last-Modified")
        expected = resp.headers.get("Content-Length")
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    size = part.stat().st_size
    if expected and int(expected) != size:
        part.unlink(missing_ok=True)
        raise IOError(f"incomplete download: expected {expected} bytes, got {size}")
    part.rename(dest)

    snap = RawSnapshot(
        path=dest, manifest_path=dest_dir / "manifest.json", source=settings.SOURCE_NAME,
        version=version, subset=subset, url=url, downloaded_at=stamp.isoformat(),
        http_last_modified=last_modified, bytes=size, sha256=sha256_file(dest),
    )
    snap.manifest_path.write_text(json.dumps({**asdict(snap), "path": dest.name, "manifest_path": None},
                                             indent=2), encoding="utf-8")
    return snap


def load_snapshot(csv_path: Path) -> RawSnapshot:
    """Describe an already-downloaded file (uses manifest.json next to it when present)."""
    csv_path = Path(csv_path)
    manifest = csv_path.parent / "manifest.json"
    sha = sha256_file(csv_path)
    if manifest.exists():
        m = json.loads(manifest.read_text(encoding="utf-8"))
        if m.get("sha256") != sha:
            raise ValueError(f"{csv_path} does not match its manifest sha256 (file modified?)")
        return RawSnapshot(path=csv_path, manifest_path=manifest, source=m["source"], version=m["version"],
                           subset=m["subset"], url=m["url"], downloaded_at=m["downloaded_at"],
                           http_last_modified=m.get("http_last_modified"), bytes=m["bytes"], sha256=sha,
                           origin=m.get("origin", "downloaded_by_aegis"))
    # file placed manually: infer what we can, never invent a download time
    name = csv_path.name  # ibtracs.NA.list.v04r01.csv
    parts = name.split(".")
    subset = parts[1] if len(parts) >= 5 else "unknown"
    version = parts[3] if len(parts) >= 5 else settings.SOURCE_VERSION
    ts = datetime.fromtimestamp(csv_path.stat().st_mtime, tz=timezone.utc).isoformat()
    return RawSnapshot(path=csv_path, manifest_path=manifest, source=settings.SOURCE_NAME, version=version,
                       subset=subset, url=csv_url(subset, version) if subset in settings.SUPPORTED_SUBSETS else "",
                       downloaded_at=ts, http_last_modified=None, bytes=csv_path.stat().st_size, sha256=sha,
                       origin="user_supplied_file")


def latest_snapshot(subset: str = "NA", version: str = settings.SOURCE_VERSION,
                    raw_dir: Path = settings.RAW_DIR) -> RawSnapshot | None:
    base = raw_dir / version / subset
    if not base.exists():
        return None
    for d in sorted((p for p in base.iterdir() if p.is_dir()), reverse=True):
        for f in d.glob("ibtracs.*.csv"):
            return load_snapshot(f)
    return None


def adopt_into_raw_store(csv_path: Path, raw_dir: Path = settings.RAW_DIR) -> RawSnapshot:
    """Copy a manually downloaded IBTrACS CSV into the immutable raw store with a manifest.

    The original file is left where it is. Re-adopting the same bytes is a no-op (same sha256),
    so the call is idempotent. The recorded download time is the file's modification time
    (the real download time is unknown) and origin is "user_supplied_file".
    """
    import shutil
    snap = load_snapshot(csv_path)
    if snap.subset not in settings.SUPPORTED_SUBSETS:
        raise ValueError(f"cannot infer an IBTrACS subset from {csv_path.name!r}")
    try:                                                   # already inside the store
        csv_path.resolve().relative_to(raw_dir.resolve())
        return snap
    except ValueError:
        pass
    base = raw_dir / snap.version / snap.subset
    if base.exists():
        for m in base.glob("*/manifest.json"):
            if json.loads(m.read_text(encoding="utf-8")).get("sha256") == snap.sha256:
                return load_snapshot(next(m.parent.glob("ibtracs.*.csv")))
    stamp = datetime.fromisoformat(snap.downloaded_at).strftime("%Y%m%d")
    dest_dir = base / stamp
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / csv_path.name
    if dest.exists():
        raise FileExistsError(f"{dest} already exists with different content; raw snapshots are never overwritten")
    shutil.copy2(csv_path, dest)
    adopted = RawSnapshot(path=dest, manifest_path=dest_dir / "manifest.json", source=snap.source,
                          version=snap.version, subset=snap.subset, url=snap.url, downloaded_at=snap.downloaded_at,
                          http_last_modified=None, bytes=snap.bytes, sha256=snap.sha256, origin="user_supplied_file")
    adopted.manifest_path.write_text(json.dumps({**asdict(adopted), "path": dest.name, "manifest_path": None},
                                                indent=2), encoding="utf-8")
    return adopted
