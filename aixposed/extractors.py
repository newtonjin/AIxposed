"""Fetch public share pages and extract conversation titles / metadata."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

from aixposed.evasion import HostEvasion
from aixposed.http_client import request_get
from aixposed.plugins.base import ProviderPlugin

TITLE_CLEAN_SUFFIXES = (
    " | Shared Grok Conversation",
    " | Claude",
    " | ChatGPT",
    " - ChatGPT",
    " | Grok",
    " | Gemini",
    " | DeepSeek",
    " - Claude",
    " · Claude",
)

TITLE_CLEAN_PREFIXES = (
    "ChatGPT - ",
    "ChatGPT — ",
    "Claude - ",
    "Grok - ",
)

GENERIC_TITLES = {
    "claude",
    "chatgpt",
    "grok",
    "gemini",
    "deepseek",
    "share",
    "shared conversation",
    "shared via chatgpt",
}


@dataclass
class ShareResult:
    url: str
    provider: str
    alive: bool
    title: str | None = None
    status_code: int | None = None
    note: str | None = None
    created_at: str | None = None  # ISO date YYYY-MM-DD when known
    text_blob: str = ""
    matched_query: bool | None = None


def _clean_title(title: str | None) -> str | None:
    if not title:
        return None
    title = re.sub(r"\s+", " ", title).strip()
    # Unescape common JSON fragments
    title = title.replace("\\n", " ").replace('\\"', '"')
    for prefix in TITLE_CLEAN_PREFIXES:
        if title.startswith(prefix):
            title = title[len(prefix) :].strip()
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
    if low in GENERIC_TITLES:
        return None
    return title or None


def _unix_to_date(value: float | int | str | None) -> str | None:
    if value is None:
        return None
    try:
        ts = float(value)
        if ts > 1e12:  # ms
            ts /= 1000.0
        if ts < 1e9:  # nonsense
            return None
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _title_from_react_router_stream(html: str) -> tuple[str | None, str | None, str]:
    """Parse ChatGPT's window.__reactRouterContext.streamController payload."""
    title = None
    created = None
    blob_parts: list[str] = []

    # Adjacent-string Flight encoding: "pageTitle","Actual Title"
    for key in ("pageTitle", "ogTitle"):
        m = re.search(rf'"{key}","([^"\\]{{2,300}})"', html)
        if m:
            t = _clean_title(m.group(1))
            if t:
                title = title or t
                blob_parts.append(t)

    # "title","..." near conversation meta (skip ultra-generic)
    for m in re.finditer(r'"title","([^"\\]{2,300})"', html):
        t = _clean_title(m.group(1))
        if t and t.lower() not in GENERIC_TITLES:
            title = title or t
            blob_parts.append(t)
            break

    m = re.search(r'"create_time",([0-9]+(?:\.[0-9]+)?)', html)
    if m:
        created = _unix_to_date(m.group(1))

    # Pull a sample of message parts for query matching
    for m in re.finditer(r'"parts",\[(\d+)\]', html):
        # indexed form is hard; also grab quoted user/assistant strings nearby
        pass
    for m in re.finditer(r'"parts",\["([^"\\]{8,400})"\]', html):
        blob_parts.append(m.group(1))
    # Plain quoted utterances often appear as standalone strings in the stream
    for m in re.finditer(r'",\"((?:[^"\\]|\\.){20,400})\"', html):
        chunk = m.group(1).replace("\\n", " ").replace('\\"', '"')
        if any(c.isalpha() for c in chunk):
            blob_parts.append(chunk)
        if len(blob_parts) > 40:
            break

    return title, created, "\n".join(blob_parts[:40])


def _title_from_html(html: str) -> tuple[str | None, str | None, str]:
    soup = BeautifulSoup(html, "lxml")
    title = None
    created = None
    blob_parts: list[str] = []

    # ChatGPT RSC / react-router stream first — richest signal
    if "__reactRouterContext" in html or "pageTitle" in html or "sharedConversationId" in html:
        t, c, blob = _title_from_react_router_stream(html)
        title = t or title
        created = c or created
        if blob:
            blob_parts.append(blob)

    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = _clean_title(og["content"])
        if t:
            title = title or t
            blob_parts.append(t)

    desc = soup.find("meta", property="og:description")
    if desc and desc.get("content"):
        blob_parts.append(desc["content"])

    tw = soup.find("meta", attrs={"name": "twitter:title"})
    if tw and tw.get("content"):
        t = _clean_title(tw["content"])
        if t:
            title = title or t

    if soup.title and soup.title.string:
        t = _clean_title(soup.title.string)
        if t:
            title = title or t

    for script in soup.find_all("script"):
        text = script.string or script.get_text() or ""
        if not text:
            continue
        if script.get("id") == "__NEXT_DATA__":
            try:
                data = json.loads(text)
                found = _walk_for_title(data)
                if found:
                    title = title or found
                c = _walk_for_time(data)
                if c:
                    created = created or c
            except json.JSONDecodeError:
                pass
        for pattern in (
            r'"pageTitle"\s*,\s*"([^"\\]{2,300})"',
            r'"ogTitle"\s*,\s*"([^"\\]{2,300})"',
            r'"conversation_title"\s*:\s*"([^"\\]{2,300})"',
            r'"title"\s*:\s*"([^"\\]{2,300})"',
        ):
            m = re.search(pattern, text)
            if m:
                t = _clean_title(m.group(1))
                if t and t.lower() not in GENERIC_TITLES:
                    title = title or t

    # Visible text fallback for query matching (keep it small)
    visible = soup.get_text(" ", strip=True)
    if visible:
        blob_parts.append(visible[:4000])

    return title, created, "\n".join(blob_parts)


def _walk_for_title(obj, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    if isinstance(obj, dict):
        for key in ("pageTitle", "ogTitle", "title", "name", "conversation_title", "chat_title"):
            val = obj.get(key)
            if isinstance(val, str):
                t = _clean_title(val)
                if t and t.lower() not in GENERIC_TITLES:
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


def _walk_for_time(obj, depth: int = 0) -> str | None:
    if depth > 8:
        return None
    if isinstance(obj, dict):
        for key in ("create_time", "created_at", "createdAt", "timestamp"):
            raw = obj.get(key)
            if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw[:1].isdigit()):
                d = _unix_to_date(raw)
                if d:
                    return d
            if isinstance(raw, str) and re.match(r"\d{4}-\d{2}-\d{2}", raw):
                return raw[:10]
        for val in obj.values():
            found = _walk_for_time(val, depth + 1)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj[:50]:
            found = _walk_for_time(item, depth + 1)
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


def matches_query(title: str | None, text_blob: str, query: str | None) -> bool:
    if not query:
        return True
    hay = f"{title or ''}\n{text_blob}".lower()
    # AND semantics for space-separated tokens; quoted phrases supported lightly
    tokens = re.findall(r'"([^"]+)"|(\S+)', query.strip())
    parts = [a or b for a, b in tokens if (a or b)]
    if not parts:
        return True
    return all(p.lower() in hay for p in parts)


def in_date_range(created_at: str | None, after: str | None, before: str | None) -> bool:
    if not after and not before:
        return True
    if not created_at:
        # Unknown date: keep unless user demanded a bound strictly — keep for recall
        return True
    if after and created_at < after:
        return False
    if before and created_at > before:
        return False
    return True


async def probe_share(
    client: httpx.AsyncClient,
    provider: ProviderPlugin,
    url: str,
    *,
    evasion: HostEvasion | None = None,
    query: str | None = None,
    after: str | None = None,
    before: str | None = None,
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

    title, created_at, text_blob = _title_from_html(html)
    if resp.status_code == 200 and (title or "share" in html.lower()):
        if title is None and ("can't load" in html.lower() or "not found" in html.lower()):
            return ShareResult(
                url=url,
                provider=provider.key,
                alive=False,
                status_code=resp.status_code,
                note="dead_soft",
            )
        ok_query = matches_query(title, text_blob, query)
        ok_date = in_date_range(created_at, after, before)
        matched = ok_query and ok_date
        note = None
        if not ok_query:
            note = "query_miss"
        elif not ok_date:
            note = "date_miss"
        return ShareResult(
            url=url,
            provider=provider.key,
            alive=True,
            title=title or "(untitled)",
            status_code=resp.status_code,
            created_at=created_at,
            text_blob=text_blob,
            matched_query=matched,
            note=note,
        )

    return ShareResult(
        url=url,
        provider=provider.key,
        alive=False,
        status_code=resp.status_code,
        note="http_error",
    )
