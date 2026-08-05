"""N3 Sec ASCII banner for AIxposed."""

from __future__ import annotations

from rich.console import Console
from rich.text import Text

N3SEC_ASCII_LOGO = [
    r"$$\   $$\  $$$$$$\   $$$$$$\ ",
    r"$$$\  $$ |$$ ___$$\ $$  __$$\ ",
    r"$$$$\ $$ |\_/   $$ |$$ /  \__| $$$$$$\   $$$$$$$\ ",
    r"$$ $$\$$ |  $$$$$ / \$$$$$$\  $$  __$$\ $$  _____|",
    r"$$ \$$$$ |  \___$$\  \____$$\ $$$$$$$$ |$$ /",
    r"$$ |\$$$ |$$\   $$ |$$\   $$ |$$   ____|$$ |",
    r"$$ | \$$ |\$$$$$$  |\$$$$$$  |\$$$$$$$\ \$$$$$$$\ ",
    r"\__|  \__| \______/  \______/  \_______|\_______|",
]

# Mirrors $Script:N3SecGradient (PowerShell -> Rich)
N3SEC_GRADIENT = [
    "dark_cyan",
    "cyan",
    "blue",
    "dark_blue",
    "magenta",
    "dark_magenta",
    "cyan",
    "white",
]


def _paint_gradient(lines: list[str]) -> Text:
    """Color each character cycling through the N3 Sec gradient."""
    out = Text()
    color_i = 0
    for line_i, line in enumerate(lines):
        for ch in line:
            out.append(ch, style=N3SEC_GRADIENT[color_i % len(N3SEC_GRADIENT)])
            if not ch.isspace():
                color_i += 1
        if line_i < len(lines) - 1:
            out.append("\n")
    return out


def print_banner(console: Console | None = None) -> None:
    console = console or Console()
    console.print()
    console.print(_paint_gradient(N3SEC_ASCII_LOGO))
    console.print()
