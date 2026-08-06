"""Wayback CDX source — interleaved across providers/patterns."""

from __future__ import annotations

from collections.abc import AsyncIterator

from aixposed.evasion import round_robin_jobs
from aixposed.http_client import request_get
from aixposed.plugins.base import UUID_RE, Candidate, DiscoverContext, ProviderPlugin

CDX_URL = "https://web.archive.org/cdx/search/cdx"


class CdxSource:
    key = "cdx"
    name = "Wayback CDX"

    async def discover(self, ctx: DiscoverContext) -> AsyncIterator[Candidate]:
        seen: set[tuple[str, str]] = set()
        jobs: list[tuple[ProviderPlugin, str]] = []
        for provider in ctx.providers:
            for pattern in provider.discovery_patterns:
                jobs.append((provider, pattern))
        jobs = round_robin_jobs(jobs, key_fn=lambda j: j[0].key)

        per_job = max(20, ctx.limit // max(1, len(jobs)))
        yielded = 0

        for provider, pattern in jobs:
            if yielded >= ctx.limit:
                break
            params = {
                "url": pattern if pattern.endswith("*") else f"{pattern}*",
                "output": "json",
                "fl": "original,timestamp,statuscode",
                "filter": "statuscode:200",
                "collapse": "urlkey",
                "limit": str(min(per_job, ctx.limit - yielded)),
            }
            rows = None
            try:
                resp = await request_get(
                    ctx.client, CDX_URL, evasion=ctx.evasion, params=params
                )
                if resp.status_code == 200 and resp.text.strip():
                    ctx.evasion.reward(CDX_URL)
                    rows = resp.json()
                else:
                    # Retry simpler field list (some IA edges dislike fl combos)
                    params["fl"] = "original,statuscode"
                    resp = await request_get(
                        ctx.client, CDX_URL, evasion=ctx.evasion, params=params
                    )
                    if resp.status_code != 200 or not resp.text.strip():
                        ctx.evasion.penalize(CDX_URL, resp.status_code)
                        continue
                    ctx.evasion.reward(CDX_URL)
                    rows = resp.json()
            except Exception:
                ctx.evasion.penalize(CDX_URL, 503)
                continue

            if not rows or not isinstance(rows, list):
                continue
            # header may be original[,timestamp],statuscode
            start = 1 if rows and rows[0] and rows[0][0] == "original" else 0
            has_ts = bool(rows) and len(rows[0]) >= 3 and (
                rows[0][1] == "timestamp" or (start == 0 and len(rows[0]) >= 3)
            )
            batch = 0
            for row in rows[start:]:
                if not row or yielded >= ctx.limit or batch >= per_job:
                    break
                original = row[0]
                timestamp = ""
                if has_ts and len(row) >= 2 and str(row[1]).isdigit():
                    timestamp = str(row[1])
                elif len(row) >= 3 and str(row[1]).isdigit():
                    timestamp = str(row[1])
                ids = provider.extract_ids(original)
                if not ids:
                    tail = original.rstrip("/").split("/")[-1]
                    if UUID_RE.fullmatch(tail):
                        ids = {tail.lower()}
                for share_id in ids:
                    key = (provider.key, share_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    yield Candidate(
                        provider=provider.key,
                        share_id=share_id,
                        link=provider.normalize_url(share_id),
                        source=self.key,
                        archive_ts=str(timestamp or ""),
                    )
                    yielded += 1
                    batch += 1
                    if yielded >= ctx.limit or batch >= per_job:
                        break


SOURCE = CdxSource()
