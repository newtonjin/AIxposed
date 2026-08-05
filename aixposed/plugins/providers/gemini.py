import re

from aixposed.plugins.base import ProviderPlugin

PROVIDER = ProviderPlugin(
    key="gemini",
    name="Gemini",
    url_template="https://gemini.google.com/share/{id}",
    discovery_patterns=(
        "gemini.google.com/share/",
        "gemini.google.com/share/*",
        "g.co/gemini/share/",
    ),
    url_regex=re.compile(
        r"https?://(?:gemini\.google\.com/share/|g\.co/gemini/share/)"
        r"([A-Za-z0-9_-]+)",
        re.I,
    ),
    verify_hosts=("gemini.google.com", "g.co"),
)
