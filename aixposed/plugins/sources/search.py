"""DuckDuckGo / ddgs dork search — interleaved across providers/hosts."""

from __future__ import annotations

from collections.abc import AsyncIterator

from aixposed.evasion import round_robin_jobs
from aixposed.plugins.base import Candidate, DiscoverContext, ProviderPlugin

DORK_TEMPLATES = (
    "site:{host} inurl:/share/",
    'inurl:"{host}/share/"',
)

# Extra Claude-oriented dorks (shares were briefly SEO-indexed hard)
CLAUDE_EXTRA = (
    'site:claude.ai/share',
    'site:claude.ai inurl:/share/',
    '"claude.ai/share/"',
)


def _open_ddgs():
    try:
        from ddgs import DDGS

        return DDGS()
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS

        return DDGS()
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pip install ddgs  (or duckduckgo-search)") from exc


class SearchSource:
    key = "search"
    name = "Web Search"

    async def discover(self, ctx: DiscoverContext) -> AsyncIterator[Candidate]:
        query = (ctx.query or "").strip()
        jobs: list[tuple[ProviderPlugin, str, str]] = []
        for provider in ctx.providers:
            hosts = provider.hosts()[:2] if provider.key == "claude" else provider.hosts()[:1]
            for host in hosts:
                for template in DORK_TEMPLATES:
                    q = template.format(host=host)
                    if query:
                        q = f"{q} {query}"
                    jobs.append((provider, host, q))
            if provider.key == "claude":
                for extra in CLAUDE_EXTRA:
                    q = f"{extra} {query}".strip() if query else extra
                    jobs.append((provider, "claude.ai", q))
            # When user supplies a topical query, also try bare site+query
            if query:
                for host in hosts:
                    jobs.append((provider, host, f'site:{host}/share {query}'))
                    jobs.append((provider, host, f'"{query}" site:{host} inurl:share'))

        jobs = round_robin_jobs(jobs, key_fn=lambda j: j[0].key)

        seen: set[tuple[str, str]] = set()
        yielded = 0

        with _open_ddgs() as ddgs:
            for provider, _host, dork in jobs:
                if yielded >= ctx.limit:
                    break
                remaining = ctx.limit - yielded
                max_results = min(25, max(5, remaining))
                await ctx.evasion.wait("duckduckgo.com")
                try:
                    results = list(ddgs.text(dork, max_results=max_results))
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
                    # Prefer IDs from the matching provider; also try all providers on the blob
                    # so a Claude URL in a mixed SERP still lands.
                    providers_try = [provider] + [p for p in ctx.providers if p.key != provider.key]
                    for prov in providers_try:
                        for share_id in prov.extract_ids(blob):
                            key = (prov.key, share_id)
                            if key in seen:
                                continue
                            seen.add(key)
                            yield Candidate(
                                provider=prov.key,
                                share_id=share_id,
                                link=prov.normalize_url(share_id),
                                source=self.key,
                            )
                            yielded += 1
                            if yielded >= ctx.limit:
                                break
                        if yielded >= ctx.limit:
                            break


SOURCE = SearchSource()
