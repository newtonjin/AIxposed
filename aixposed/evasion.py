"""Rate-limit evasion: per-host pacing, UA rotation, interleaved hosts, backoff."""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import TypeVar
from urllib.parse import urlparse

T = TypeVar("T")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_6_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
    "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:126.0) Gecko/20100101 Firefox/126.0",
]

ACCEPT_LANGUAGES = [
    "en-US,en;q=0.9",
    "en-GB,en;q=0.9",
    "en-US,en;q=0.8,pt-BR;q=0.6",
    "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,es;q=0.5",
]


def host_of(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def interleave_by_key(items: list[T], key_fn) -> list[T]:
    """Round-robin items across keys so domains/providers alternate."""
    buckets: dict[object, deque[T]] = defaultdict(deque)
    order: list[object] = []
    for item in items:
        key = key_fn(item)
        if key not in buckets:
            order.append(key)
        buckets[key].append(item)

    # Shuffle bucket order once so default runs don't always start on the same host.
    random.shuffle(order)
    out: list[T] = []
    while any(buckets[k] for k in order):
        for key in order:
            if buckets[key]:
                out.append(buckets[key].popleft())
    return out


def round_robin_jobs(jobs: list[T], key_fn) -> list[T]:
    """Alias kept for readability at call sites."""
    return interleave_by_key(jobs, key_fn)


@dataclass
class HostEvasion:
    """Per-host rate limiter with jitter, UA rotation and 429 backoff."""

    base_delay: float = 0.7
    jitter: float = 0.45
    min_host_gap: float = 1.1
    max_backoff: float = 60.0
    rotate_ua: bool = True

    _locks: dict[str, asyncio.Lock] = field(default_factory=lambda: defaultdict(asyncio.Lock))
    _global_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last_host: dict[str, float] = field(default_factory=dict)
    _last_global: float = 0.0
    _host_backoff_until: dict[str, float] = field(default_factory=dict)
    _host_strikes: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _ua_index: int = 0
    _last_host_used: str | None = None

    def next_headers(self) -> dict[str, str]:
        if self.rotate_ua:
            self._ua_index = (self._ua_index + 1) % len(USER_AGENTS)
            ua = USER_AGENTS[self._ua_index]
        else:
            ua = USER_AGENTS[0]
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": random.choice(ACCEPT_LANGUAGES),
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "DNT": "1",
            "Upgrade-Insecure-Requests": "1",
        }

    async def wait(self, url_or_host: str) -> None:
        host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
        host = host or "global"
        lock = self._locks[host]
        async with lock:
            now = time.monotonic()

            # Honor active backoff window for this host.
            until = self._host_backoff_until.get(host, 0.0)
            if until > now:
                await asyncio.sleep(until - now)
                now = time.monotonic()

            # Prefer switching hosts: if same host as last global request, add extra gap.
            same_as_last = self._last_host_used == host
            host_gap = self.min_host_gap * (1.35 if same_as_last else 1.0)
            last_h = self._last_host.get(host, 0.0)
            wait_host = max(0.0, (last_h + host_gap) - now)

            async with self._global_lock:
                now = time.monotonic()
                global_gap = self.base_delay + random.uniform(0, self.jitter)
                # Extra pause when hammering the same host consecutively.
                if same_as_last:
                    global_gap += random.uniform(0.2, 0.8)
                wait_global = max(0.0, (self._last_global + global_gap) - now)
                sleep_for = max(wait_host, wait_global)
                if sleep_for > 0:
                    await asyncio.sleep(sleep_for)
                self._last_global = time.monotonic()
                self._last_host_used = host

            self._last_host[host] = time.monotonic()

    def penalize(self, url_or_host: str, status_code: int | None = None) -> None:
        """Increase backoff after 429/503/403 bursts."""
        host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
        host = host or "global"
        if status_code not in (403, 429, 503):
            # Gradual recovery.
            self._host_strikes[host] = max(0, self._host_strikes[host] - 1)
            return
        self._host_strikes[host] += 1
        strike = self._host_strikes[host]
        backoff = min(self.max_backoff, (2 ** min(strike, 5)) + random.uniform(0.5, 2.0))
        self._host_backoff_until[host] = time.monotonic() + backoff

    def reward(self, url_or_host: str) -> None:
        host = host_of(url_or_host) if "://" in url_or_host else url_or_host.lower()
        if host:
            self._host_strikes[host] = max(0, self._host_strikes[host] - 1)
