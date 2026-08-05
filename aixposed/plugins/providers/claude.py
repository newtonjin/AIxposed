import re

from aixposed.plugins.base import ProviderPlugin

PROVIDER = ProviderPlugin(
    key="claude",
    name="Claude",
    url_template="https://claude.ai/share/{id}",
    discovery_patterns=("claude.ai/share/", "claude.ai/share/*"),
    url_regex=re.compile(
        r"https?://(?:www\.)?claude\.ai/share/"
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        re.I,
    ),
    verify_hosts=("claude.ai",),
)
