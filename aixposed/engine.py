"""AIxposed orchestration — interleaved discovery + verify across domains."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from aixposed.banner import print_banner
from aixposed.csv_export import write_csv
from aixposed.evasion import HostEvasion, host_of, interleave_by_key
from aixposed.extractors import probe_share
from aixposed.http_client import make_client
from aixposed.plugins import load_providers, resolve_providers, resolve_sources
from aixposed.plugins.base import Candidate, DiscoverContext

console = Console()


@dataclass
class DiscoverConfig:
    # Default: all plugged-in providers, interleaved.
    providers: list[str] = field(default_factory=lambda: ["all"])
    sources: list[str] = field(default_factory=lambda: ["search", "cdx"])
    out: str = "aixposed.csv"
    limit: int = 2000
    delay: float = 0.7
    min_host_gap: float = 1.1
    verify: bool = True
    concurrency: int = 6
    brute_attempts: int = 200
    brute_pattern: str = "uuid8"
    seed_file: str | None = None
    skip_verify_sources: tuple[str, ...] = ("brute",)
    show_banner: bool = True
    rotate_ua: bool = True


async def _merge_sources_round_robin(generators: list):
    """Pull one candidate at a time from each source so domains/sources alternate."""
    active = list(generators)
    while active:
        next_round = []
        for gen in active:
            try:
                item = await gen.__anext__()
            except StopAsyncIteration:
                continue
            yield item
            next_round.append(gen)
        active = next_round


async def _collect_candidates(cfg: DiscoverConfig, evasion: HostEvasion) -> list[dict[str, str]]:
    providers = resolve_providers(cfg.providers)
    sources = resolve_sources(cfg.sources)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    soft_cap = cfg.limit * max(1, len(sources))

    async with make_client() as client:
        ctx = DiscoverContext(
            client=client,
            providers=providers,
            evasion=evasion,
            limit=cfg.limit,
            brute_attempts=cfg.brute_attempts,
            brute_pattern=cfg.brute_pattern,
            seed_file=cfg.seed_file,
            concurrency=cfg.concurrency,
        )

        labels = ",".join(s.key for s in sources)
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task(
                f"Interleaved discovery [{labels}] × providers...",
                total=None,
            )
            # Each source already round-robins providers; here we also
            # round-robin *across* sources so we never drain one stack alone.
            gens = [source.discover(ctx) for source in sources]
            async for cand in _merge_sources_round_robin(gens):
                if cand.link in seen:
                    continue
                seen.add(cand.link)
                rows.append(
                    {
                        "provider": cand.provider,
                        "share_id": cand.share_id,
                        "link": cand.link,
                        "source": cand.source,
                        "title": cand.title or "",
                    }
                )
                if len(rows) >= soft_cap:
                    break
            progress.remove_task(task)

    # Final interleave by provider host for verify cadence.
    return interleave_by_key(rows, key_fn=lambda r: r.get("provider", ""))


async def _verify_rows(
    rows: list[dict[str, str]],
    cfg: DiscoverConfig,
    evasion: HostEvasion,
) -> list[dict[str, str]]:
    providers = {p.key: p for p in resolve_providers(cfg.providers)}

    to_verify = [r for r in rows if r.get("source") not in cfg.skip_verify_sources]
    already_ok = [
        r for r in rows if r.get("source") in cfg.skip_verify_sources and r.get("title")
    ]

    if not cfg.verify:
        for r in rows:
            if not r.get("title"):
                r["title"] = "(unverified)"
        return rows

    # Interleave verification by target host (claude.ai / chatgpt.com / …).
    to_verify = interleave_by_key(to_verify, key_fn=lambda r: host_of(r.get("link", "")))

    sem = asyncio.Semaphore(cfg.concurrency)
    verified: list[dict[str, str]] = list(already_ok)

    async with make_client() as client:

        async def one(row: dict[str, str]):
            provider = providers.get(row["provider"])
            if not provider:
                # Provider may still be in registry even if filtered — reload all.
                provider = load_providers().get(row["provider"])
            if not provider:
                return None
            async with sem:
                result = await probe_share(
                    client, provider, row["link"], evasion=evasion
                )
            if not result.alive:
                return None
            out = dict(row)
            out["title"] = result.title or "(untitled)"
            return out

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Verifying (hosts interleaved)...", total=len(to_verify)
            )
            # Process in interleaved windows to keep host rotation under concurrency.
            window = max(cfg.concurrency * 3, 12)
            for i in range(0, len(to_verify), window):
                chunk = to_verify[i : i + window]
                futs = [asyncio.create_task(one(r)) for r in chunk]
                for fut in asyncio.as_completed(futs):
                    item = await fut
                    if item:
                        verified.append(item)
                    progress.advance(task)

    return verified


async def run_discover(cfg: DiscoverConfig) -> str:
    if cfg.show_banner:
        print_banner(console)

    providers = resolve_providers(cfg.providers)
    sources = resolve_sources(cfg.sources)

    console.print(
        f"[bold white]AIxposed[/bold white]  providers=[cyan]"
        f"{','.join(p.key for p in providers)}[/cyan]  "
        f"sources=[magenta]{','.join(s.key for s in sources)}[/magenta]  "
        f"mode=[yellow]interleaved[/yellow]"
    )

    evasion = HostEvasion(
        base_delay=cfg.delay,
        min_host_gap=cfg.min_host_gap,
        rotate_ua=cfg.rotate_ua,
    )

    candidates = await _collect_candidates(cfg, evasion)
    console.print(f"Unique candidates: [cyan]{len(candidates)}[/cyan] (already interleaved)")
    final_rows = await _verify_rows(candidates, cfg, evasion)

    path = write_csv(cfg.out, final_rows)
    label = "shares" if not cfg.verify else "live shares"
    console.print(
        f"[green]CSV ready:[/green] {path}  ([cyan]{len(final_rows)}[/cyan] {label})"
    )
    return str(path)


# Silence unused import warning in type checkers for Candidate re-export convenience.
_ = Candidate
