"""Pattern/seed probe — interleaved across providers to avoid single-domain bursts."""

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


def _normalize_seed(value: str) -> str:
    value = value.strip()
    if UUID_RE.fullmatch(value):
        return value.lower()
    return value


def generate_candidates(
    pattern: str, attempts: int, seed_ids: Iterable[str] | None = None
) -> list[str]:
    out: list[str] = []
    if seed_ids:
        out.extend(dict.fromkeys(_normalize_seed(s) for s in seed_ids if s and s.strip()))
    need = max(0, attempts - len(out))
    factory = generate_uuid8 if pattern == "uuid8" else (lambda: str(uuid.uuid4()))
    out.extend(factory() for _ in range(need))
    random.shuffle(out)
    return out[:attempts] if attempts else out


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

        candidates = generate_candidates(ctx.brute_pattern, ctx.brute_attempts, seeds)
        targets = [p for p in ctx.providers if p.supports_uuid8_brute or seeds]
        if not targets:
            targets = [p for p in ctx.providers if p.key == "chatgpt"]

        # Build (provider, id) jobs and interleave by provider key.
        jobs: list[tuple[ProviderPlugin, str]] = [
            (provider, share_id) for share_id in candidates for provider in targets
        ]
        jobs = interleave_by_key(jobs, key_fn=lambda j: j[0].key)

        sem = asyncio.Semaphore(max(1, ctx.concurrency // 2 or 1))

        async def check_one(provider: ProviderPlugin, share_id: str):
            url = provider.normalize_url(share_id)
            async with sem:
                result = await probe_share(
                    ctx.client, provider, url, evasion=ctx.evasion
                )
            return provider, share_id, url, result

        # Process in rolling windows so we don't spawn tens of thousands of tasks,
        # while still keeping provider interleaving inside each window.
        window = max(16, ctx.concurrency * 4)
        for i in range(0, len(jobs), window):
            chunk = jobs[i : i + window]
            tasks = [asyncio.create_task(check_one(p, sid)) for p, sid in chunk]
            for fut in asyncio.as_completed(tasks):
                provider, share_id, url, result = await fut
                if result and result.alive:
                    yield Candidate(
                        provider=provider.key,
                        share_id=share_id,
                        link=url,
                        source=self.key,
                        title=result.title or "(untitled)",
                    )


SOURCE = BruteSource()
