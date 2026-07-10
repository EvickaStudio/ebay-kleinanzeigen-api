from __future__ import annotations

from typing import Any

import httpx
from loguru import logger

from ..core.config import get_settings


def create_shared_client() -> httpx.AsyncClient:
    """Create the application-scoped HTTPX async client.

    Uses connection pooling, explicit redirect handling (disabled so 302s
    are detected as pagination end), and reads all tuning from Settings.
    """
    settings = get_settings()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(settings.http_timeout),
        transport=httpx.AsyncHTTPTransport(retries=settings.http_max_retries),
        follow_redirects=False,
        limits=httpx.Limits(
            max_connections=settings.http_max_connections,
            max_keepalive_connections=settings.http_max_keepalive_connections,
            keepalive_expiry=30.0,
        ),
        # Keep pooling stateless: experiment cookies change the scrapeable markup.
        headers={"User-Agent": settings.http_user_agent, "Cookie": ""},
    )


async def fetch_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """GET JSON from *url*, raising on HTTP or network errors."""
    try:
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "HTTP error {} for {}", exc.response.status_code, exc.request.url
        )
        raise
    except httpx.HTTPError as exc:
        logger.error("HTTP client error for {}: {}", url, exc)
        raise
