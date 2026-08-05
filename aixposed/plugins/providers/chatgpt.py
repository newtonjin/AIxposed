import re

from aixposed.plugins.base import ProviderPlugin

PROVIDER = ProviderPlugin(
    key="chatgpt",
    name="ChatGPT",
    url_template="https://chatgpt.com/share/{id}",
    discovery_patterns=(
        "chatgpt.com/share/",
        "chatgpt.com/share/*",
        "chat.openai.com/share/",
        "chat.openai.com/share/*",
    ),
    url_regex=re.compile(
        r"https?://(?:www\.)?(?:chatgpt\.com|chat\.openai\.com)/share/"
        r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
        re.I,
    ),
    supports_uuid8_brute=True,
    verify_hosts=("chatgpt.com", "chat.openai.com"),
)
