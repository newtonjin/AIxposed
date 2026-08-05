"""Base contracts for AIxposed plug-and-play providers and sources."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import httpx

from aixposed.evasion import HostEvasion

UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@dataclass(frozen=True)
class ProviderPlugin:
    """Drop a module exporting PROVIDER = ProviderPlugin(...) to register."""

    key: str
    name: str
    url_template: str
    discovery_patterns: tuple[str, ...]
    url_regex: re.Pattern[str]
    supports_uuid8_brute: bool = False
    verify_hosts: tuple[str, ...] = ()

    def normalize_url(self, share_id: str) -> str:
        return self.url_template.format(id=share_id.strip())

    def extract_ids(self, text: str) -> set[str]:
        found: set[str] = set()
        for m in self.url_regex.finditer(text or ""):
            token = m.group(1)
            found.add(token.lower() if UUID_RE.fullmatch(token or "") else token)
        return found

    def hosts(self) -> list[str]:
        hosts: list[str] = []
        for pattern in self.discovery_patterns:
            host = pattern.split("/")[0]
            if host and host not in hosts:
                hosts.append(host)
        for host in self.verify_hosts:
            if host and host not in hosts:
                hosts.append(host)
        return hosts


@dataclass
class Candidate:
    provider: str
    share_id: str
    link: str
    source: str
    title: str = ""


@dataclass
class DiscoverContext:
    client: httpx.AsyncClient
    providers: list[ProviderPlugin]
    evasion: HostEvasion
    limit: int = 2000
    brute_attempts: int = 200
    brute_pattern: str = "uuid8"
    seed_file: str | None = None
    concurrency: int = 6
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SourcePlugin(Protocol):
    """Drop a module exporting SOURCE = YourSource() implementing this protocol."""

    key: str
    name: str

    def discover(self, ctx: DiscoverContext) -> AsyncIterator[Candidate]:
        ...
