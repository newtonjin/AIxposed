"""HTTP helpers wired to HostEvasion."""

from __future__ import annotations

from typing import Any

import httpx

from aixposed.evasion import HostEvasion

DEFAULT_TIMEOUT = httpx.Timeout(30.0)


def make_client(timeout: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=httpx.Timeout(timeout),
        http2=False,
        headers={
            "Accept": "text/html,application/json,*/*;q=0.8",
        },
    )


async def request_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    evasion: HostEvasion | None = None,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    hdrs = {}
    if evasion:
        await evasion.wait(url)
        hdrs.update(evasion.next_headers())
    if headers:
        hdrs.update(headers)
    resp = await client.get(url, params=params, headers=hdrs or None)
    if evasion:
        if resp.status_code in (403, 429, 503):
            evasion.penalize(url, resp.status_code)
        elif resp.status_code < 400:
            evasion.reward(url)
    return resp
