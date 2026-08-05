import re

from aixposed.plugins.base import ProviderPlugin

PROVIDER = ProviderPlugin(
    key="grok",
    name="Grok",
    url_template="https://grok.com/share/{id}",
    discovery_patterns=("grok.com/share/", "grok.com/share/*", "x.com/i/grok/share/"),
    url_regex=re.compile(
        r"https?://(?:www\.)?(?:grok\.com/share/|x\.com/i/grok/share/)"
        r"([A-Za-z0-9_-]+)",
        re.I,
    ),
    verify_hosts=("grok.com", "x.com"),
)
