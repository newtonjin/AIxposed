"""Fetch public share pages and extract conversation titles."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from aixposed.evasion import HostEvasion
from aixposed.http_client import request_get
from aixposed.plugins.base import ProviderPlugin

TITLE_CLEAN_SUFFIXES = (
    " | Claude",
    " | ChatGPT",
    " - ChatGPT",
    " | Grok",
    " | Gemini",
    " | DeepSeek",
    " - Claude",
    " · Claude",
)


@dataclass
class ShareResult:
    url: str
    provider: str
    alive: bool
    title: str | None = None
    status_code: int | None = None
    note: str | None = None


def _clean_title(title: str | None) -> str | None:
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    for suffix in TITLE_CLEAN_SUFFIXES:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
    dead_markers = (
        "can't load",
        "page not found",
        "not found",
        "conversation not found",
        "this shared link",
        "share not found",
        "something went wrong",
    )
    low = title.lower()
    if any(m in low for m in dead_markers) and len(title) < 80:
        return None
    return title or None


def _title_from_html(html: str) -> str | None:
    soup = BeautifulSoup(html, "lxml")

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = _clean_title(og["content"])
        if t:
            return t

    tw = soup.find("meta", attrs={"name": "twitter:title"})
    if tw and tw.get("content"):
        t = _clean_title(tw["content"])
        if t:
            return t

    if soup.title and soup.title.string:
        t = _clean_title(soup.title.string)
        if t:
            return t

    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if not text or "title" not in text:
            continue
        if script.get("id") == "__NEXT_DATA__":
            try:
                data = json.loads(text)
                found = _walk_for_title(data)
                if found:
                    return found
            except json.JSONDecodeError:
                pass
        for pattern in (
            r'"title"\s*:\s*"([^"\\]{3,200})"',
            r'"name"\s*:\s*"([^"\\]{3,200})"',
            r'"conversation_title"\s*:\s*"([^"\\]{3,200})"',
        ):
            m = re.search(pattern, text)
            if m:
                t = _clean_title(m.group(1))
                if t and t.lower() not in {"claude", "chatgpt", "grok", "gemini"}:
                    return t
    return None


def _walk_for_title(obj, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    if isinstance(obj, dict):
        for key in ("title", "name", "conversation_title", "chat_title"):
            val = obj.get(key)
            if isinstance(val, str):
                t = _clean_title(val)
                if t and t.lower() not in {"claude", "chatgpt", "share"}:
                    return t
        for val in obj.values():
            found = _walk_for_title(val, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj[:50]:
            found = _walk_for_title(item, depth + 1)
            if found:
                return found
    return None


def _looks_dead(html: str, status_code: int) -> bool:
    if status_code in (404, 410, 451):
        return True
    low = html.lower()
    markers = (
        "can't load shared conversation",
        "unable to load shared conversation",
        "this shared chat is no longer available",
        "conversation not found",
        "share not found",
        "page not found",
    )
    return any(m in low for m in markers)


async def probe_share(
    client: httpx.AsyncClient,
    provider: ProviderPlugin,
    url: str,
    *,
    evasion: HostEvasion | None = None,
) -> ShareResult:
    try:
        resp = await request_get(client, url, evasion=evasion)
    except Exception as exc:
        return ShareResult(
            url=url,
            provider=provider.key,
            alive=False,
            note=f"request_error:{type(exc).__name__}",
        )

    html = resp.text or ""
    if _looks_dead(html, resp.status_code):
        return ShareResult(
            url=url,
            provider=provider.key,
            alive=False,
            status_code=resp.status_code,
            note="dead_or_revoked",
        )

    title = _title_from_html(html)
    if resp.status_code == 200 and (title or "share" in html.lower()):
        if title is None and ("can't load" in html.lower() or "not found" in html.lower()):
            return ShareResult(
                url=url,
                provider=provider.key,
                alive=False,
                status_code=resp.status_code,
                note="dead_soft",
            )
        return ShareResult(
            url=url,
            provider=provider.key,
            alive=True,
            title=title or "(untitled)",
            status_code=resp.status_code,
        )

    return ShareResult(
        url=url,
        provider=provider.key,
        alive=False,
        status_code=resp.status_code,
        note="http_error",
    )
