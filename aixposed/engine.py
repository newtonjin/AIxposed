"""AIxposed orchestration — interleaved discovery + verify across domains."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from aixposed.archive import is_weak_title, title_from_wayback
from aixposed.banner import print_banner
from aixposed.csv_export import write_csv
from aixposed.evasion import HostEvasion, host_of, interleave_by_key
from aixposed.extractors import matches_query, probe_share
from aixposed.http_client import make_client
from aixposed.plugins import load_providers, resolve_providers, resolve_sources
from aixposed.plugins.base import Candidate, DiscoverContext

# legacy_windows=False avoids cp1252 crashes on spinner glyphs
console = Console(legacy_windows=False)


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
                        "archive_ts": getattr(cand, "archive_ts", "") or "",
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


async def _enrich_rows(
    rows: list[dict[str, str]],
    cfg: DiscoverConfig,
    evasion: HostEvasion,
) -> list[dict[str, str]]:
    """Always fetch titles from live pages; optionally keep dead rows / filter by query."""
    providers = {p.key: p for p in resolve_providers(cfg.providers)}
    filtering = bool(cfg.query or cfg.after or cfg.before)

    # Brute already probed and usually has titles.
    already_ok = [
        r
        for r in rows
        if r.get("source") in cfg.skip_verify_sources and not is_weak_title(r.get("title"))
    ]
    for r in already_ok:
        r.setdefault("status", "live")
        r.setdefault("created_at", "")

    already_ids = {id(r) for r in already_ok}
    pending = [r for r in rows if id(r) not in already_ids]
    pending = interleave_by_key(pending, key_fn=lambda r: host_of(r.get("link", "")))

    sem = asyncio.Semaphore(cfg.concurrency)
    out_rows: list[dict[str, str]] = list(already_ok)
    live_n = len(already_ok)
    dead_n = 0
    miss_n = 0

    if not pending:
        return out_rows

    async with make_client() as client:

        async def one(row: dict[str, str]):
            nonlocal live_n, dead_n, miss_n
            provider = providers.get(row["provider"]) or load_providers().get(row["provider"])
            if not provider:
                return None
            out = dict(row)

            async with sem:
                # ALWAYS hit the share page for title — even with --no-verify.
                result = await probe_share(
                    client,
                    provider,
                    row["link"],
                    evasion=evasion,
                    query=cfg.query if cfg.verify or filtering else None,
                    after=cfg.after if cfg.verify or filtering else None,
                    before=cfg.before if cfg.verify or filtering else None,
                )

                if result.created_at:
                    out["created_at"] = result.created_at

                if result.alive:
                    if result.matched_query is False:
                        miss_n += 1
                        console.print(
                            f"  [dim]miss[/dim]  {result.title or '(untitled)'}  {out['link']}"
                        )
                        return None
                    live_n += 1
                    out["status"] = "live"
                    if not is_weak_title(result.title):
                        out["title"] = result.title  # type: ignore[assignment]
                    console.print(
                        f"  [green]live[/green]  [cyan]{out['provider']:<8}[/cyan] "
                        f"[white]{out.get('title') or result.title or '(…)'}[/white]  "
                        f"[dim]{out['link']}[/dim]"
                    )
                else:
                    dead_n += 1
                    out["status"] = "dead"
                    if cfg.live_only or filtering:
                        console.print(f"  [red]dead[/red]  {out['link']}")
                        return None
                    console.print(f"  [red]dead[/red]  {out['link']}")

                # Archive fallback only when we have a CDX timestamp hint (fast path).
                if is_weak_title(out.get("title")) and out.get("archive_ts"):
                    title, created = await title_from_wayback(
                        client,
                        out["link"],
                        evasion=evasion,
                        hint_ts=out.get("archive_ts"),
                    )
                    if title and not is_weak_title(title):
                        out["title"] = title
                        console.print(
                            f"  [magenta]arch[/magenta] [white]{title}[/white]  "
                            f"[dim]{out['link']}[/dim]"
                        )
                    if created and not out.get("created_at"):
                        out["created_at"] = created

                if is_weak_title(out.get("title")):
                    # Last resort: use whatever probe returned
                    if result.title and not is_weak_title(result.title):
                        out["title"] = result.title
                    else:
                        out["title"] = (
                            "(dead/revoked)"
                            if out.get("status") == "dead"
                            else "(untitled)"
                        )

                if filtering and cfg.query and not matches_query(out.get("title"), "", cfg.query):
                    miss_n += 1
                    return None
                return out

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching titles...", total=len(pending))
            window = max(cfg.concurrency * 3, 12)
            for i in range(0, len(pending), window):
                chunk = pending[i : i + window]
                futs = [asyncio.create_task(one(r)) for r in chunk]
                for fut in asyncio.as_completed(futs):
                    item = await fut
                    if item:
                        out_rows.append(item)
                    progress.advance(task)

    console.print(
        f"[dim]enrich summary:[/dim] [green]{live_n} live[/green] / "
        f"[red]{dead_n} dead[/red] / [dim]{miss_n} miss[/dim] / "
        f"kept [cyan]{len(out_rows)}[/cyan]"
    )
    return out_rows


async def run_discover(cfg: DiscoverConfig) -> str:
    if cfg.show_banner:
        print_banner(console)

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
    final_rows = await _enrich_rows(candidates, cfg, evasion)

    for r in final_rows:
        r.pop("archive_ts", None)

    path = write_csv(cfg.out, final_rows)
    titled = sum(1 for r in final_rows if not is_weak_title(r.get("title")))
    console.print(
        f"[green]CSV ready:[/green] {path}  "
        f"([cyan]{len(final_rows)}[/cyan] row(s), [cyan]{titled}[/cyan] with titles)"
    )
    return str(path)


_ = Candidate
