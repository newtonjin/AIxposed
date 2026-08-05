"""DuckDuckGo dork search — interleaved across providers/hosts."""

from __future__ import annotations

from collections.abc import AsyncIterator

from aixposed.evasion import round_robin_jobs
from aixposed.plugins.base import Candidate, DiscoverContext, ProviderPlugin

DORK_TEMPLATES = (
    "site:{host} inurl:/share/",
    "site:{host}/share",
    '"{host}/share/"',
    'inurl:"{host}/share/"',
)


class SearchSource:
    key = "search"
    name = "Web Search"

    async def discover(self, ctx: DiscoverContext) -> AsyncIterator[Candidate]:
        try:
            from duckduckgo_search import DDGS
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("pip install duckduckgo-search") from exc

        jobs: list[tuple[ProviderPlugin, str, str]] = []
        for provider in ctx.providers:
            for host in provider.hosts():
                for template in DORK_TEMPLATES:
                    jobs.append((provider, host, template.format(host=host)))
        jobs = round_robin_jobs(jobs, key_fn=lambda j: j[0].key)

        seen: set[tuple[str, str]] = set()
        yielded = 0
        max_results = 30

        with DDGS() as ddgs:
            for provider, _host, query in jobs:
                if yielded >= ctx.limit:
                    break
                # Pace search engine too.
                await ctx.evasion.wait("duckduckgo.com")
                try:
                    results = list(ddgs.text(query, max_results=max_results))
                    ctx.evasion.reward("duckduckgo.com")
                except Exception:
                    ctx.evasion.penalize("duckduckgo.com", 429)
                    continue

                for item in results:
                    if yielded >= ctx.limit:
                        break
                    blob = " ".join(
                        str(item.get(k, "")) for k in ("href", "link", "url", "title", "body")
                    )
                    for share_id in provider.extract_ids(blob):
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


SOURCE = SearchSource()
