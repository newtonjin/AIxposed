"""Plug-and-play registry: drop files into providers/ or sources/ to extend AIxposed."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from aixposed.plugins.base import ProviderPlugin, SourcePlugin

if TYPE_CHECKING:
    pass

_PROVIDERS: dict[str, ProviderPlugin] | None = None
_SOURCES: dict[str, SourcePlugin] | None = None


def _load_package_plugins(package_name: str, attr: str) -> dict:
    package = importlib.import_module(package_name)
    found: dict = {}
    for modinfo in pkgutil.iter_modules(package.__path__, package.__name__ + "."):
        if modinfo.name.rsplit(".", 1)[-1].startswith("_"):
            continue
        module = importlib.import_module(modinfo.name)
        plugin = getattr(module, attr, None)
        if plugin is None:
            continue
        key = getattr(plugin, "key", None)
        if not key:
            continue
        found[str(key).lower()] = plugin
    return found


def load_providers(force: bool = False) -> dict[str, ProviderPlugin]:
    global _PROVIDERS
    if _PROVIDERS is None or force:
        _PROVIDERS = _load_package_plugins("aixposed.plugins.providers", "PROVIDER")
    return _PROVIDERS


def load_sources(force: bool = False) -> dict[str, SourcePlugin]:
    global _SOURCES
    if _SOURCES is None or force:
        _SOURCES = _load_package_plugins("aixposed.plugins.sources", "SOURCE")
    return _SOURCES


def resolve_providers(keys: list[str] | None) -> list[ProviderPlugin]:
    registry = load_providers()
    if not keys or keys == ["all"]:
        return list(registry.values())
    out: list[ProviderPlugin] = []
    for key in keys:
        key = key.strip().lower()
        if key == "all":
            return list(registry.values())
        if key not in registry:
            raise ValueError(
                f"Unknown provider '{key}'. Available: {', '.join(registry)} or all. "
                "Add a plugin under aixposed/plugins/providers/"
            )
        out.append(registry[key])
    return out


def resolve_sources(keys: list[str] | None) -> list[SourcePlugin]:
    registry = load_sources()
    if not keys:
        keys = ["search", "cdx"]
    out: list[SourcePlugin] = []
    for key in keys:
        key = key.strip().lower()
        if key == "cc":
            key = "commoncrawl"
        if key not in registry:
            raise ValueError(
                f"Unknown source '{key}'. Available: {', '.join(registry)}. "
                "Add a plugin under aixposed/plugins/sources/"
            )
        out.append(registry[key])
    return out
