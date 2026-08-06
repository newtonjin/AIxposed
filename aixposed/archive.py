"""Wayback Machine helpers — pull titles when live shares lack metadata."""

from __future__ import annotations

import httpx

from aixposed.evasion import HostEvasion
from aixposed.extractors import _title_from_html
from aixposed.http_client import request_get

CDX_URL = "https://web.archive.org/cdx/search/cdx"


def is_weak_title(title: str | None) -> bool:
    if not title:
        return True
    weak = {
        "",
        "(untitled)",
        "(unverified)",
        "(dead/revoked)",
        "chatgpt",
        "claude",
        "grok",
        "gemini",
        "deepseek",
    }
    return title.strip().lower() in weak


def _archive_url_candidates(url: str) -> list[str]:
    urls = [url]
    if "chatgpt.com/share/" in url:
        urls.append(url.replace("chatgpt.com/share/", "chat.openai.com/share/", 1))
    elif "chat.openai.com/share/" in url:
        urls.append(url.replace("chat.openai.com/share/", "chatgpt.com/share/", 1))
    return urls


async def title_from_wayback(
    client: httpx.AsyncClient,
    url: str,
    *,
    evasion: HostEvasion | None = None,
    hint_ts: str | None = None,
) -> tuple[str | None, str | None]:
    """Best-effort archive title. Needs a timestamp hint (from CDX) — no slow lookups."""
    if not hint_ts or not str(hint_ts).isdigit():
        return None, None
    ts = str(hint_ts)
    for candidate in _archive_url_candidates(url):
        for archive_url in (
            f"https://web.archive.org/web/{ts}id_/{candidate}",
            f"https://web.archive.org/web/{ts}/{candidate}",
        ):
            try:
                resp = await request_get(client, archive_url, evasion=evasion)
            except Exception:
                continue
            if resp.status_code != 200 or not resp.text or len(resp.text) < 200:
                continue
            title, created, _ = _title_from_html(resp.text)
            if not created and len(ts) >= 8:
                created = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
            if title and not is_weak_title(title):
                return title, created
            if title:
                return title, created
    return None, None
