"""AIxposed CLI — N3 Sec."""

from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console

from aixposed import __version__
from aixposed.banner import print_banner
from aixposed.engine import DiscoverConfig, run_discover
from aixposed.plugins import load_providers, load_sources

console = Console()


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="AIxposed")
@click.pass_context
def main(ctx: click.Context) -> None:
    """AIxposed — interleaved discovery of public AI chat shares (N3 Sec).

    Run with no subcommand to start plug-and-play discovery across all providers.
    """
    if ctx.invoked_subcommand is None:
        # Plug-and-play default: all providers, search+cdx, interleaved.
        ctx.invoke(discover)


@main.command("discover")
@click.option(
    "--providers",
    default="all",
    show_default=True,
    help="Comma-separated providers, or 'all' (plug-and-play).",
)
@click.option(
    "--sources",
    default="search,cdx",
    show_default=True,
    help="Sources: search,cdx,commoncrawl,brute",
)
@click.option("--out", "out_path", default="aixposed.csv", show_default=True)
@click.option("--limit", default=2000, show_default=True)
@click.option("--delay", default=0.7, show_default=True, help="Base global delay (evasion)")
@click.option(
    "--host-gap",
    default=1.1,
    show_default=True,
    help="Minimum gap between requests to the same host",
)
@click.option("--concurrency", default=6, show_default=True)
@click.option("--brute-attempts", default=200, show_default=True)
@click.option(
    "--brute-pattern",
    type=click.Choice(["uuid8", "uuid4"], case_sensitive=False),
    default="uuid8",
    show_default=True,
)
@click.option("--seed-file", type=click.Path(exists=True, dir_okay=False), default=None)
@click.option("--no-verify", is_flag=True, help="Skip page visits / no real titles")
@click.option("--no-banner", is_flag=True, help="Hide N3 Sec ASCII art")
@click.option("--no-rotate-ua", is_flag=True, help="Disable User-Agent rotation")
def discover(
    providers: str,
    sources: str,
    out_path: str,
    limit: int,
    delay: float,
    host_gap: float,
    concurrency: int,
    brute_attempts: int,
    brute_pattern: str,
    seed_file: str | None,
    no_verify: bool,
    no_banner: bool,
    no_rotate_ua: bool,
) -> None:
    """Interleaved discovery across providers/domains + CSV (title, link)."""
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
        show_banner=not no_banner,
        rotate_ua=not no_rotate_ua,
    )
    try:
        asyncio.run(run_discover(cfg))
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(130) from None


@main.command("plugins")
def plugins() -> None:
    """List loaded plug-and-play providers and sources."""
    print_banner(console)
    console.print("[bold]Providers[/bold]  (aixposed/plugins/providers/*.py)")
    for key, p in load_providers().items():
        brute = "uuid8" if p.supports_uuid8_brute else "-"
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
    # Allow `python -m aixposed.cli`
    sys.exit(main())
