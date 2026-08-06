"""CSV export helpers."""

from __future__ import annotations

import csv
from pathlib import Path

FIELDNAMES = ("title", "link", "provider", "source", "share_id", "status", "created_at")


def write_csv(path: str | Path, rows: list[dict[str, str]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    deduped: dict[str, dict[str, str]] = {}
    weak_titles = {"", "(untitled)", "(unverified)", "(dead/revoked)"}
    for row in rows:
        link = row.get("link", "").strip()
        if not link:
            continue
        prev = deduped.get(link)
        if not prev:
            deduped[link] = {
                "title": row.get("title") or "(untitled)",
                "link": link,
                "provider": row.get("provider", ""),
                "source": row.get("source", ""),
                "share_id": row.get("share_id", ""),
                "status": row.get("status") or "unverified",
                "created_at": row.get("created_at") or "",
            }
        else:
            if prev.get("title") in weak_titles and row.get("title"):
                prev["title"] = row["title"]
            if not prev.get("created_at") and row.get("created_at"):
                prev["created_at"] = row["created_at"]
            rank = {"live": 3, "unverified": 2, "dead": 1, "miss": 0}
            if rank.get(row.get("status", ""), 0) > rank.get(prev.get("status", ""), 0):
                prev["status"] = row["status"]
                if row.get("title"):
                    prev["title"] = row["title"]

    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in sorted(
            deduped.values(),
            key=lambda r: (r.get("status", ""), r["provider"], r["title"]),
        ):
            writer.writerow(row)
    return out
