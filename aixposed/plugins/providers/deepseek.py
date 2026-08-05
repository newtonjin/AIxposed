import re

from aixposed.plugins.base import ProviderPlugin

PROVIDER = ProviderPlugin(
    key="deepseek",
    name="DeepSeek",
    url_template="https://chat.deepseek.com/share/{id}",
    discovery_patterns=("chat.deepseek.com/share/", "chat.deepseek.com/share/*"),
    url_regex=re.compile(
        r"https?://(?:www\.)?chat\.deepseek\.com/share/"
        r"([A-Za-z0-9_-]+)",
        re.I,
    ),
    verify_hosts=("chat.deepseek.com",),
)
