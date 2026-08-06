"""AIxposed CLI — N3 Sec."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from typing import Any, TypeVar

import click
from rich.console import Console

from aixposed import __version__
from aixposed.banner import print_banner
from aixposed.engine import DiscoverConfig, run_discover
from aixposed.plugins import load_providers, load_sources

console = Console()

F = TypeVar("F", bound=Callable[..., Any])


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def discover_options(fn: F) -> F:
    """Shared flags for root `aixposed` and subcommands."""
    options = [
        click.option(
            "--providers",
            default="all",
            show_default=True,
            help="Comma-separated providers, or 'all' (plug-and-play).",
        ),
        click.option(
            "--sources",
            default="search,cdx",
            show_default=True,
            help="Sources: search,cdx,commoncrawl,brute",
        ),
        click.option("--out", "out_path", default="aixposed.csv", show_default=True),
        click.option(
            "--limit",
            default=2000,
            show_default=True,
            help="Max unique share links to collect (total, across all sources).",
        ),
        click.option(
            "--query",
            "-q",
            default=None,
            help="Only keep shares whose title/body match (AND tokens). Also biases web dorks.",
        ),
        click.option(
            "--after",
            default=None,
            help="Only keep shares with create date on/after YYYY-MM-DD (when known).",
        ),
        click.option(
            "--before",
            default=None,
            help="Only keep shares with create date on/before YYYY-MM-DD (when known).",
        ),
        click.option(
            "--delay", default=0.7, show_default=True, help="Base global delay (evasion)"
        ),
        click.option(
            "--host-gap",
            default=1.1,
            show_default=True,
            help="Minimum gap between requests to the same host",
        ),
        click.option("--concurrency", default=6, show_default=True),
        click.option("--brute-attempts", default=500, show_default=True),
        click.option(
            "--brute-pattern",
            type=click.Choice(["uuid8", "uuid4"], case_sensitive=False),
            default="uuid8",
            show_default=True,
            help="uuid8=ChatGPT-shaped; uuid4 used automatically for Claude/etc.",
        ),
        click.option(
            "--seed-file",
            type=click.Path(exists=True, dir_okay=False),
            default=None,
            help="IDs/URLs to probe (+ nearby UUID neighbors)",
        ),
        click.option(
            "--no-verify",
            is_flag=True,
            help="Still fetch titles, but keep dead/revoked rows (don't require live-only)",
        ),
        click.option(
            "--live-only",
            is_flag=True,
            help="Drop dead/revoked shares from CSV (default keeps them with status=dead)",
        ),
        click.option("--banner", is_flag=True, help="Show N3 Sec ASCII art (off by default)"),
        click.option("--no-rotate-ua", is_flag=True, help="Disable User-Agent rotation"),
    ]
    for option in reversed(options):
        fn = option(fn)
    return fn


def _run_discover(
    providers: str,
    sources: str,
    out_path: str,
    limit: int,
    query: str | None,
    after: str | None,
    before: str | None,
    delay: float,
    host_gap: float,
    concurrency: int,
    brute_attempts: int,
    brute_pattern: str,
    seed_file: str | None,
    no_verify: bool,
    live_only: bool,
    banner: bool,
    no_rotate_ua: bool,
) -> None:
    cfg = DiscoverConfig(
        providers=_split_csv(providers) or ["all"],
        sources=_split_csv(sources),
        out=out_path,
        limit=limit,
        delay=delay,
        min_host_gap=host_gap,
        verify=not no_verify,
        concurrency=concurrency,
        brute_attempts=brute_attempts,
        brute_pattern=brute_pattern.lower(),
        seed_file=seed_file,
        show_banner=banner,
        rotate_ua=not no_rotate_ua,
        live_only=live_only,
        query=query,
        after=after,
        before=before,
    )
    try:
        asyncio.run(run_discover(cfg))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(130) from None


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="AIxposed")
@discover_options
@click.pass_context
def main(
    ctx: click.Context,
    providers: str,
    sources: str,
    out_path: str,
    limit: int,
    query: str | None,
    after: str | None,
    before: str | None,
    delay: float,
    host_gap: float,
    concurrency: int,
    brute_attempts: int,
    brute_pattern: str,
    seed_file: str | None,
    no_verify: bool,
    live_only: bool,
    banner: bool,
    no_rotate_ua: bool,
) -> None:
    """AIxposed — interleaved discovery of public AI chat shares (N3 Sec).

    Examples:
      python -m aixposed --limit 60 --out test.csv
      python -m aixposed -q "stanford" --providers claude,chatgpt --out hits.csv
      python -m aixposed search -q "ransomware" --after 2024-01-01
    """
    if ctx.invoked_subcommand is None:
        _run_discover(
            providers=providers,
            sources=sources,
            out_path=out_path,
            limit=limit,
            query=query,
            after=after,
            before=before,
            delay=delay,
            host_gap=host_gap,
            concurrency=concurrency,
            brute_attempts=brute_attempts,
            brute_pattern=brute_pattern,
            seed_file=seed_file,
            no_verify=no_verify,
            live_only=live_only,
            banner=banner,
            no_rotate_ua=no_rotate_ua,
        )


@main.command("discover")
@discover_options
def discover(
    providers: str,
    sources: str,
    out_path: str,
    limit: int,
    query: str | None,
    after: str | None,
    before: str | None,
    delay: float,
    host_gap: float,
    concurrency: int,
    brute_attempts: int,
    brute_pattern: str,
    seed_file: str | None,
    no_verify: bool,
    live_only: bool,
    banner: bool,
    no_rotate_ua: bool,
) -> None:
    """Interleaved discovery across providers/domains + CSV."""
    _run_discover(
        providers=providers,
        sources=sources,
        out_path=out_path,
        limit=limit,
        query=query,
        after=after,
        before=before,
        delay=delay,
        host_gap=host_gap,
        concurrency=concurrency,
        brute_attempts=brute_attempts,
        brute_pattern=brute_pattern,
        seed_file=seed_file,
        no_verify=no_verify,
        live_only=live_only,
        banner=banner,
        no_rotate_ua=no_rotate_ua,
    )


@main.command("search")
@discover_options
def search_cmd(
    providers: str,
    sources: str,
    out_path: str,
    limit: int,
    query: str | None,
    after: str | None,
    before: str | None,
    delay: float,
    host_gap: float,
    concurrency: int,
    brute_attempts: int,
    brute_pattern: str,
    seed_file: str | None,
    no_verify: bool,
    live_only: bool,
    banner: bool,
    no_rotate_ua: bool,
) -> None:
    """Topic search: dork the web + filter title/body. Adds brute by default."""
    if not query and not after and not before:
        raise click.UsageError("search needs --query/-q and/or --after/--before")
    # Default sources for search mode if user left the generic default.
    src = sources
    if src == "search,cdx":
        src = "search,cdx,brute"
    _run_discover(
        providers=providers,
        sources=src,
        out_path=out_path,
        limit=limit,
        query=query,
        after=after,
        before=before,
        delay=delay,
        host_gap=host_gap,
        concurrency=concurrency,
        brute_attempts=brute_attempts,
        brute_pattern=brute_pattern,
        seed_file=seed_file,
        no_verify=False,  # must probe content
        live_only=True if live_only or query else live_only,
        banner=banner,
        no_rotate_ua=no_rotate_ua,
    )


@main.command("plugins")
def plugins() -> None:
    """List loaded plug-and-play providers and sources."""
    console.print("[bold]Providers[/bold]  (aixposed/plugins/providers/*.py)")
    for key, p in load_providers().items():
        brute = "uuid8" if p.supports_uuid8_brute else "uuid4"
        console.print(
            f"  [cyan]{key:10}[/cyan] {p.name:12} {p.url_template}  brute={brute}"
        )
    console.print()
    console.print("[bold]Sources[/bold]  (aixposed/plugins/sources/*.py)")
    for key, s in load_sources().items():
        console.print(f"  [magenta]{key:12}[/magenta] {s.name}")
    console.print()
    console.print(
        "[dim]Plug-and-play: drop a new .py in those folders exporting "
        "PROVIDER=... or SOURCE=...[/dim]"
    )


@main.command("banner")
def banner_cmd() -> None:
    """Show the N3 Sec ASCII art."""
    print_banner(console)


if __name__ == "__main__":
    sys.exit(main())
