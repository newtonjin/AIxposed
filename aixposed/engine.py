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
    show_banner: bool = False
    rotate_ua: bool = True
    live_only: bool = False
    query: str | None = None
    after: str | None = None
    before: str | None = None


async def _pump_source(source, ctx: DiscoverContext, queue: asyncio.Queue) -> None:
    try:
        async for cand in source.discover(ctx):
            await queue.put(cand)
    except Exception as exc:
        await queue.put(("__error__", source.key, f"{type(exc).__name__}: {exc}"))
    finally:
        await queue.put(None)


async def _collect_candidates(cfg: DiscoverConfig, evasion: HostEvasion) -> list[dict[str, str]]:
    providers = resolve_providers(cfg.providers)
    sources = resolve_sources(cfg.sources)

    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    hard_cap = max(1, cfg.limit)

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
            query=cfg.query,
            after=cfg.after,
            before=cfg.before,
        )

        labels = ",".join(s.key for s in sources)
        queue: asyncio.Queue = asyncio.Queue()
        tasks = [
            asyncio.create_task(_pump_source(source, ctx, queue), name=source.key)
            for source in sources
        ]
        finished = 0

        qbit = f"  query=[yellow]{cfg.query}[/yellow]" if cfg.query else ""
        console.print(
            f"[dim]live hits[/dim]  target=[cyan]{hard_cap}[/cyan]  "
            f"sources=[magenta]{labels}[/magenta]{qbit}"
        )

        try:
            while finished < len(tasks) and len(rows) < hard_cap:
                item = await queue.get()
                if item is None:
                    finished += 1
                    continue
                if isinstance(item, tuple) and item and item[0] == "__error__":
                    _, src, msg = item
                    console.print(
                        f"[yellow]![/yellow] source [magenta]{src}[/magenta] failed: {msg}"
                    )
                    continue

                cand: Candidate = item
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
                        "created_at": "",
                    }
                )
                n = len(rows)
                title_bit = f"  [white]{cand.title}[/white]" if cand.title else ""
                prefix = f"  [green]{n:>4}[/green]/{hard_cap}  "
                console.print(
                    prefix
                    + f"[cyan]{cand.provider:<8}[/cyan] "
                    + f"[dim]{cand.source:<11}[/dim] "
                    + f"{cand.link}{title_bit}"
                )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    console.print(f"[dim]discovery done — {len(rows)} unique link(s)[/dim]")
    return interleave_by_key(rows, key_fn=lambda r: r.get("provider", ""))


async def _verify_rows(
    rows: list[dict[str, str]],
    cfg: DiscoverConfig,
    evasion: HostEvasion,
) -> list[dict[str, str]]:
    providers = {p.key: p for p in resolve_providers(cfg.providers)}
    filtering = bool(cfg.query or cfg.after or cfg.before)

    to_verify = [r for r in rows if r.get("source") not in cfg.skip_verify_sources]
    already_ok = [
        r for r in rows if r.get("source") in cfg.skip_verify_sources and r.get("title")
    ]
    for r in already_ok:
        r.setdefault("status", "live")
        r.setdefault("title", r.get("title") or "(untitled)")
        r.setdefault("created_at", "")

    if not cfg.verify:
        if filtering:
            console.print(
                "[yellow]Note:[/yellow] --query/--after/--before need live checks; "
                "ignoring --no-verify for filter pass."
            )
        else:
            for r in rows:
                if not r.get("title"):
                    r["title"] = "(unverified)"
                r["status"] = r.get("status") or "unverified"
                r.setdefault("created_at", "")
            return rows

    to_verify = interleave_by_key(to_verify, key_fn=lambda r: host_of(r.get("link", "")))

    sem = asyncio.Semaphore(cfg.concurrency)
    verified: list[dict[str, str]] = list(already_ok)
    live_n = len(already_ok)
    dead_n = 0
    miss_n = 0

    async with make_client() as client:

        async def one(row: dict[str, str]):
            nonlocal live_n, dead_n, miss_n
            provider = providers.get(row["provider"]) or load_providers().get(row["provider"])
            if not provider:
                return None
            async with sem:
                result = await probe_share(
                    client,
                    provider,
                    row["link"],
                    evasion=evasion,
                    query=cfg.query,
                    after=cfg.after,
                    before=cfg.before,
                )
            out = dict(row)
            if result.created_at:
                out["created_at"] = result.created_at
            if not result.alive:
                dead_n += 1
                out["status"] = "dead"
                out["title"] = out.get("title") or "(dead/revoked)"
                console.print(f"  [red]dead[/red]  {out['link']}")
                # Query mode: don't keep dead noise
                if filtering or cfg.live_only:
                    return None
                return out
            if result.matched_query is False:
                miss_n += 1
                console.print(
                    f"  [dim]miss[/dim]  {result.title or '(untitled)'}  {out['link']}"
                )
                # Search mode feeds ONLY matches
                return None
            live_n += 1
            out["status"] = "live"
            out["title"] = result.title or "(untitled)"
            date_bit = f"  [dim]{out['created_at']}[/dim]" if out.get("created_at") else ""
            console.print(
                f"  [green]live[/green]  [cyan]{out['provider']:<8}[/cyan] "
                f"[white]{out['title']}[/white]{date_bit}  [dim]{out['link']}[/dim]"
            )
            return out

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            label = "Filtering title/body/date..." if filtering else "Verifying..."
            task = progress.add_task(label, total=len(to_verify))
            window = max(cfg.concurrency * 3, 12)
            for i in range(0, len(to_verify), window):
                chunk = to_verify[i : i + window]
                futs = [asyncio.create_task(one(r)) for r in chunk]
                for fut in asyncio.as_completed(futs):
                    item = await fut
                    if item:
                        verified.append(item)
                    progress.advance(task)

    console.print(
        f"[dim]verify summary:[/dim] [green]{live_n} live[/green] / "
        f"[red]{dead_n} dead[/red] / [dim]{miss_n} miss[/dim] / "
        f"kept [cyan]{len(verified)}[/cyan]"
    )
    return verified


async def run_discover(cfg: DiscoverConfig) -> str:
    if cfg.show_banner:
        print_banner(console)

    # Filters require probing page content.
    if (cfg.query or cfg.after or cfg.before) and not cfg.verify:
        cfg.verify = True

    providers = resolve_providers(cfg.providers)
    sources = resolve_sources(cfg.sources)

    bits = [
        f"providers=[cyan]{','.join(p.key for p in providers)}[/cyan]",
        f"sources=[magenta]{','.join(s.key for s in sources)}[/magenta]",
        "mode=[yellow]parallel+interleaved[/yellow]",
        f"limit=[cyan]{cfg.limit}[/cyan]",
    ]
    if cfg.query:
        bits.append(f"query=[yellow]{cfg.query}[/yellow]")
    if cfg.after:
        bits.append(f"after=[yellow]{cfg.after}[/yellow]")
    if cfg.before:
        bits.append(f"before=[yellow]{cfg.before}[/yellow]")
    console.print("[bold white]AIxposed[/bold white]  " + "  ".join(bits))

    evasion = HostEvasion(
        base_delay=cfg.delay,
        min_host_gap=cfg.min_host_gap,
        rotate_ua=cfg.rotate_ua,
    )

    candidates = await _collect_candidates(cfg, evasion)
    console.print(f"Unique candidates: [cyan]{len(candidates)}[/cyan]")
    final_rows = await _verify_rows(candidates, cfg, evasion)

    path = write_csv(cfg.out, final_rows)
    console.print(
        f"[green]CSV ready:[/green] {path}  ([cyan]{len(final_rows)}[/cyan] row(s)"
    )
    return str(path)


_ = Candidate
