"""CSV export helpers."""

from __future__ import annotations

import csv
from pathlib import Path

FIELDNAMES = ("title", "link", "provider", "source", "share_id")


def write_csv(path: str | Path, rows: list[dict[str, str]]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    deduped: dict[str, dict[str, str]] = {}
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
            }
        elif (prev.get("title") in ("", "(untitled)", "(unverified)")) and row.get(
            "title"
        ):
            prev["title"] = row["title"]

    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in sorted(deduped.values(), key=lambda r: (r["provider"], r["title"])):
            writer.writerow(row)
    return out
