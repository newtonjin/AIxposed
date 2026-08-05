"""Common Crawl Index — interleaved across providers."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from aixposed.evasion import round_robin_jobs
from aixposed.http_client import request_get
from aixposed.plugins.base import UUID_RE, Candidate, DiscoverContext, ProviderPlugin

CC_INDEXES = (
    "https://index.commoncrawl.org/CC-MAIN-2025-33-index",
    "https://index.commoncrawl.org/CC-MAIN-2025-21-index",
    "https://index.commoncrawl.org/CC-MAIN-2025-08-index",
    "https://index.commoncrawl.org/CC-MAIN-2024-51-index",
)


class CommonCrawlSource:
    key = "commoncrawl"
    name = "Common Crawl"

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
            query = pattern.rstrip("*")
            if not query.endswith("/"):
                query += "/"
            got_any = False
            for index_url in CC_INDEXES:
                if yielded >= ctx.limit:
                    break
                params = {
                    "url": f"{query}*",
                    "output": "json",
                    "fl": "url,status",
                    "filter": "status:200",
                    "limit": str(min(per_job, 1000, ctx.limit - yielded)),
                }
                try:
                    resp = await request_get(
                        ctx.client, index_url, evasion=ctx.evasion, params=params
                    )
                    if resp.status_code != 200 or not resp.text.strip():
                        ctx.evasion.penalize(index_url, resp.status_code)
                        continue
                    ctx.evasion.reward(index_url)
                except Exception:
                    ctx.evasion.penalize(index_url, 503)
                    continue

                batch = 0
                for line in resp.text.splitlines():
                    if yielded >= ctx.limit or batch >= per_job:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    url = row.get("url") or ""
                    ids = provider.extract_ids(url)
                    if not ids:
                        tail = url.rstrip("/").split("/")[-1]
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
                        )
                        yielded += 1
                        batch += 1
                        got_any = True
                if got_any:
                    break


SOURCE = CommonCrawlSource()
