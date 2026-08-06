"""Pattern/seed probe — finds shares that were never indexed."""

from __future__ import annotations

import asyncio
import random
import secrets
import uuid
from collections.abc import AsyncIterator, Iterable

from aixposed.evasion import interleave_by_key
from aixposed.extractors import probe_share
from aixposed.plugins.base import UUID_RE, Candidate, DiscoverContext, ProviderPlugin


def generate_uuid8() -> str:
    hex_chars = "0123456789abcdef"
    s1 = "".join(secrets.choice(hex_chars) for _ in range(8))
    s2 = "".join(secrets.choice(hex_chars) for _ in range(4))
    s3 = "8" + "".join(secrets.choice(hex_chars) for _ in range(3))
    s4 = secrets.choice("89ab") + "".join(secrets.choice(hex_chars) for _ in range(3))
    s5 = "".join(secrets.choice(hex_chars) for _ in range(12))
    return f"{s1}-{s2}-{s3}-{s4}-{s5}"


def generate_uuid4() -> str:
    return str(uuid.uuid4())


def _normalize_seed(value: str) -> str:
    value = value.strip()
    # Accept full URLs in seed files
    for marker in ("/share/", "/public/artifacts/"):
        if marker in value:
            value = value.rstrip("/").split(marker)[-1]
            break
    if UUID_RE.fullmatch(value):
        return value.lower()
    return value


def _neighbors(seed: str, radius: int = 8) -> list[str]:
    """Flip last hex nibbles — catches sequential-ish allocations near known hits."""
    if not UUID_RE.fullmatch(seed):
        return []
    raw = seed.replace("-", "")
    out: list[str] = []
    try:
        n = int(raw, 16)
    except ValueError:
        return []
    for delta in range(-radius, radius + 1):
        if delta == 0:
            continue
        m = n + delta
        if m < 0:
            continue
        h = f"{m:032x}"
        out.append(f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}")
    return out


def generate_candidates(
    pattern: str,
    attempts: int,
    seed_ids: Iterable[str] | None = None,
    *,
    with_neighbors: bool = True,
) -> list[str]:
    out: list[str] = []
    seeds: list[str] = []
    if seed_ids:
        seeds = list(dict.fromkeys(_normalize_seed(s) for s in seed_ids if s and s.strip()))
        out.extend(seeds)
        if with_neighbors:
            for s in seeds:
                out.extend(_neighbors(s))
            out = list(dict.fromkeys(out))

    factory = generate_uuid8 if pattern == "uuid8" else generate_uuid4
    need = max(0, attempts - len(out))
    out.extend(factory() for _ in range(need))
    random.shuffle(out)
    return out[:attempts] if attempts else out


def _pattern_for(provider: ProviderPlugin, default_pattern: str) -> str:
    if provider.supports_uuid8_brute:
        return "uuid8"
    # Claude / others → random uuid4 space (still better than nothing)
    if default_pattern == "uuid8" and not provider.supports_uuid8_brute:
        return "uuid4"
    return default_pattern


class BruteSource:
    key = "brute"
    name = "Brute / Probe"

    async def discover(self, ctx: DiscoverContext) -> AsyncIterator[Candidate]:
        seeds: list[str] = []
        if ctx.seed_file:
            with open(ctx.seed_file, encoding="utf-8") as fh:
                seeds = [
                    line.strip()
                    for line in fh
                    if line.strip() and not line.startswith("#")
                ]

        # Probe every selected provider — not just ChatGPT.
        targets = list(ctx.providers) or [
            p for p in ctx.providers if p.key == "chatgpt"
        ]
        if not targets:
            return

        # Split attempts across providers so Claude/GPT both get love.
        per = max(20, ctx.brute_attempts // max(1, len(targets)))
        jobs: list[tuple[ProviderPlugin, str]] = []
        for provider in targets:
            pattern = _pattern_for(provider, ctx.brute_pattern)
            ids = generate_candidates(pattern, per, seeds, with_neighbors=bool(seeds))
            jobs.extend((provider, sid) for sid in ids)

        jobs = interleave_by_key(jobs, key_fn=lambda j: j[0].key)
        sem = asyncio.Semaphore(max(1, ctx.concurrency // 2 or 1))

        async def check_one(provider: ProviderPlugin, share_id: str):
            url = provider.normalize_url(share_id)
            async with sem:
                result = await probe_share(
                    ctx.client,
                    provider,
                    url,
                    evasion=ctx.evasion,
                    query=ctx.query,
                    after=ctx.after,
                    before=ctx.before,
                )
            return provider, share_id, url, result

        window = max(16, ctx.concurrency * 4)
        for i in range(0, len(jobs), window):
            chunk = jobs[i : i + window]
            tasks = [asyncio.create_task(check_one(p, sid)) for p, sid in chunk]
            for fut in asyncio.as_completed(tasks):
                provider, share_id, url, result = await fut
                if not result or not result.alive:
                    continue
                if result.matched_query is False:
                    continue
                yield Candidate(
                    provider=provider.key,
                    share_id=share_id,
                    link=url,
                    source=self.key,
                    title=result.title or "(untitled)",
                )


SOURCE = BruteSource()
