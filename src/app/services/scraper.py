from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup
from bs4.element import Tag
from loguru import logger

from ..core.config import get_settings
from ..exceptions import KleinanzeigenBannedError
from ..models.listings import (
    DetailedListingItem,
    ListingDetail,
    ListingSummary,
    PaginationMetadata,
)
from ..models.metrics import PageMetric, PerformanceMetrics
from .http_client import fetch_json
from .parsers.detail_parser import (
    parse_categories,
    parse_details,
    parse_extra_info,
    parse_images,
    parse_location,
    parse_price,
    parse_seller,
)

_UMLAUT = str.maketrans(
    {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"}
)

# Two distinct German strings that both appear on every Kleinanzeigen IP-ban page.
# Checking both avoids false positives from pages that mention one word in passing.
_BAN_MARKER_1 = "IP-Bereich"
_BAN_MARKER_2 = "gesperrt"


def _is_ip_ban_page(html: str) -> bool:
    """Return True if *html* is Kleinanzeigen's IP-range block page.

    The block page is returned with either HTTP 200 or HTTP 403 depending on
    the client and request path.  Checking the body is more reliable than
    relying on the status code alone.
    """
    return _BAN_MARKER_1 in html and _BAN_MARKER_2 in html


class KleinanzeigenScraperService:
    """Scrape Kleinanzeigen listings and details via HTTP + BeautifulSoup."""

    BASE_URL = "https://www.kleinanzeigen.de"
    LISTING_DETAILS_URL = "https://www.kleinanzeigen.de/s-anzeige/{listing_id}"
    LISTING_VIEWS_URL = "https://www.kleinanzeigen.de/s-vac-inc-get.json"

    def __init__(self, *, client: httpx.AsyncClient) -> None:
        self._settings = get_settings()
        self._client = client

    async def fetch_listing_views(self, listing_id: str) -> int | None:
        """Fetch the view count for a listing from the Kleinanzeigen API."""
        normalized_id = self._normalize_listing_id(listing_id)
        try:
            data = await fetch_json(
                self._client, self.LISTING_VIEWS_URL, params={"adId": normalized_id}
            )
        except httpx.HTTPError:
            return None

        visits = data.get("numVisits")
        if isinstance(visits, int):
            return visits
        visits_str = data.get("numVisitsStr")
        if isinstance(visits_str, str):
            cleaned = visits_str.strip()
            if cleaned.isdigit():
                stripped = cleaned.lstrip("0")
                return int(stripped) if stripped else 0
        return None

    @staticmethod
    def _normalize_listing_id(listing_id: str) -> str:
        return listing_id.split("-", 1)[0]

    async def fetch_listing_detail(self, listing_id: str) -> ListingDetail:
        """Fetch and parse the full detail page for a single listing."""
        url = self.LISTING_DETAILS_URL.format(listing_id=listing_id)
        logger.debug("Fetching listing detail from {}", url)

        response = await self._client.get(url)
        if _is_ip_ban_page(response.text):
            raise KleinanzeigenBannedError(
                "IP range temporarily blocked by Kleinanzeigen"
            )
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        raw_price = soup.find(id="viewad-price")
        price_data = parse_price(raw_price.get_text() if raw_price else None)

        title_element = soup.find(id="viewad-title")
        title = title_element.get_text(strip=True) if title_element else ""

        views = await self.fetch_listing_views(listing_id)

        return ListingDetail.model_validate(
            {
                "id": listing_id,
                "categories": parse_categories(soup),
                "title": title,
                "status": "active",
                "price": price_data,
                "delivery": self._parse_delivery_method(soup),
                "delivery_cost": self._parse_delivery_cost(soup),
                "location": parse_location(soup),
                "views": views,
                "description": self._extract_description(soup),
                "images": parse_images(soup),
                "details": parse_details(soup),
                "features": self._extract_features(soup),
                "seller": parse_seller(soup),
                "extra_info": parse_extra_info(soup),
            }
        )

    async def fetch_listings(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        radius: int | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        sort_by: str | None = None,
        page_count: int = 1,
        start_page: int = 1,
    ) -> tuple[list[ListingSummary], PerformanceMetrics, PaginationMetadata]:
        """Fetch one or more listing pages concurrently.

        Pages are fetched in parallel up to *page_fetch_concurrency* at a time.
        Results are merged in page order with duplicate ad IDs removed.
        Pagination stops early if a redirect (exhausted pages) is detected.
        """
        page_numbers = list(range(start_page, start_page + page_count))

        async def _fetch(
            page_number: int,
        ) -> tuple[PageMetric, list[ListingSummary], bool, int | None]:
            return await self._fetch_listings_page(
                page_number=page_number,
                query=query,
                location=location,
                radius=radius,
                min_price=min_price,
                max_price=max_price,
                sort_by=sort_by,
            )

        raw_results = await self._fetch_pages_until_redirect(page_numbers, _fetch)

        page_metrics: list[PageMetric] = []
        summaries: list[ListingSummary] = []
        seen_ad_ids: set[str] = set()
        duplicates_removed = 0
        total_available_results: int | None = None
        highest_processed_page: int | None = None

        for page_number in page_numbers:
            if page_number not in raw_results:
                continue

            result = raw_results[page_number]
            if isinstance(result, Exception):
                logger.warning(
                    "Page {} fetch raised unexpected exception: {}",
                    page_number,
                    result,
                )
                page_metrics.append(
                    PageMetric(
                        page_number=page_number,
                        time_taken=0.0,
                        success=False,
                        retry_count=0,
                        results_count=0,
                        error=str(result),
                        error_category="exception",
                    )
                )
                highest_processed_page = page_number
                continue

            metric, page_summaries, is_redirect, page_total = result
            page_metrics.append(metric)
            highest_processed_page = page_number

            if is_redirect:
                logger.info(
                    "Page {} returned redirect — pagination exhausted, stopping",
                    page_number,
                )
                break

            if total_available_results is None and page_total is not None:
                total_available_results = page_total

            for summary in page_summaries:
                if summary.ad_id in seen_ad_ids:
                    duplicates_removed += 1
                else:
                    seen_ad_ids.add(summary.ad_id)
                    summaries.append(summary)

        # If every attempted page returned a ban response and we have no results,
        # surface it as a hard error rather than silently returning empty results.
        if (
            not summaries
            and page_metrics
            and all(
                m.error_category == "ip_banned" for m in page_metrics if not m.success
            )
            and not any(m.success for m in page_metrics)
        ):
            raise KleinanzeigenBannedError(
                "IP range temporarily blocked by Kleinanzeigen. "
                "All page fetches returned a block response. "
                "The restriction is temporary — try again in a few hours."
            )

        successful = [m for m in page_metrics if m.success]
        times = [m.time_taken for m in successful]

        metrics = PerformanceMetrics(
            pages_requested=page_count,
            pages_successful=len(successful),
            pages_failed=len(page_metrics) - len(successful),
            concurrency=self._settings.page_fetch_concurrency,
            success_rate=(len(successful) / page_count * 100) if page_count else 100.0,
            average_page_time=sum(times) / len(times) if times else 0.0,
            fastest_page_time=min(times, default=0.0),
            slowest_page_time=max(times, default=0.0),
            page_details=page_metrics,
        )

        pagination_metadata = PaginationMetadata(
            pages_requested=page_count,
            pages_fetched=len(page_metrics),
            start_page=start_page,
            end_page=highest_processed_page or start_page,
            total_available_results=total_available_results,
            results_per_page=25,
            duplicates_removed=duplicates_removed,
        )

        return summaries, metrics, pagination_metadata

    async def _fetch_pages_until_redirect(
        self,
        page_numbers: list[int],
        fetch_page,
    ) -> dict[
        int, tuple[PageMetric, list[ListingSummary], bool, int | None] | Exception
    ]:
        """Fetch pages with bounded concurrency and stop scheduling after redirect."""

        raw_results: dict[
            int, tuple[PageMetric, list[ListingSummary], bool, int | None] | Exception
        ] = {}
        in_flight: dict[asyncio.Task, int] = {}
        next_index = 0
        concurrency = self._settings.page_fetch_concurrency
        redirect_page: int | None = None

        def _schedule(page_number: int) -> None:
            task = asyncio.create_task(fetch_page(page_number))
            in_flight[task] = page_number

        while next_index < len(page_numbers) and len(in_flight) < concurrency:
            _schedule(page_numbers[next_index])
            next_index += 1

        while in_flight:
            done, _ = await asyncio.wait(
                in_flight.keys(), return_when=asyncio.FIRST_COMPLETED
            )

            for task in done:
                page_number = in_flight.pop(task)
                try:
                    result = task.result()
                except asyncio.CancelledError:
                    continue
                except Exception as exc:
                    raw_results[page_number] = exc
                else:
                    raw_results[page_number] = result
                    if result[2] and (
                        redirect_page is None or page_number < redirect_page
                    ):
                        redirect_page = page_number

            if redirect_page is not None:
                for task, page_number in list(in_flight.items()):
                    if page_number > redirect_page:
                        task.cancel()
                        in_flight.pop(task)
                continue

            while next_index < len(page_numbers) and len(in_flight) < concurrency:
                _schedule(page_numbers[next_index])
                next_index += 1

        return raw_results

    async def fetch_listings_with_details(
        self,
        *,
        query: str | None = None,
        location: str | None = None,
        radius: int | None = None,
        min_price: int | None = None,
        max_price: int | None = None,
        sort_by: str | None = None,
        page_count: int = 1,
        start_page: int = 1,
        max_concurrent_details: int = 10,
    ) -> list[DetailedListingItem]:
        """Fetch listing summaries then enrich each with its detail page."""
        listings, _, _ = await self.fetch_listings(
            query=query,
            location=location,
            radius=radius,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
            page_count=page_count,
            start_page=start_page,
        )

        semaphore = asyncio.Semaphore(max_concurrent_details)

        async def fetch_detail(summary: ListingSummary) -> DetailedListingItem | None:
            async with semaphore:
                try:
                    detail = await self.fetch_listing_detail(summary.ad_id)
                except httpx.HTTPError as exc:
                    logger.warning(
                        "Failed to fetch detail for {}: {}", summary.ad_id, exc
                    )
                    return None
                return DetailedListingItem(summary=summary, detail=detail)

        results = await asyncio.gather(
            *[fetch_detail(s) for s in listings], return_exceptions=True
        )

        combined: list[DetailedListingItem] = []
        for result in results:
            if isinstance(result, DetailedListingItem):
                combined.append(result)
            elif isinstance(result, Exception):
                logger.warning("Detail fetch task failed: {}", result)
        return combined

    async def _fetch_listings_page(
        self,
        *,
        page_number: int,
        query: str | None,
        location: str | None,
        radius: int | None,
        min_price: int | None,
        max_price: int | None,
        sort_by: str | None,
    ) -> tuple[PageMetric, list[ListingSummary], bool, int | None]:
        """Fetch and parse a single search result page.

        Returns:
            (metric, summaries, is_redirect, total_available_results)
        """
        start = time.perf_counter()
        url = self._build_search_url(
            page_number=page_number,
            query=query,
            location=location,
            radius=radius,
            min_price=min_price,
            max_price=max_price,
            sort_by=sort_by,
        )
        logger.debug("Fetching listing page {} via {}", page_number, url)

        try:
            response = await self._client.get(url)

            if response.is_redirect:
                duration = time.perf_counter() - start
                logger.debug(
                    "Page {} returned {} redirect — no more pages",
                    page_number,
                    response.status_code,
                )
                metric = PageMetric(
                    page_number=page_number,
                    time_taken=duration,
                    success=False,
                    retry_count=0,
                    results_count=0,
                    error=f"Redirect {response.status_code}",
                    error_category="redirect",
                )
                return metric, [], True, None

            # Detect IP ban before raise_for_status — the ban page can arrive as
            # HTTP 200, 403, or other status codes depending on the request path.
            if _is_ip_ban_page(response.text):
                duration = time.perf_counter() - start
                logger.error(
                    "IP range temporarily blocked by Kleinanzeigen (page {}, HTTP {})",
                    page_number,
                    response.status_code,
                )
                metric = PageMetric(
                    page_number=page_number,
                    time_taken=duration,
                    success=False,
                    retry_count=0,
                    results_count=0,
                    error="IP range temporarily blocked by Kleinanzeigen",
                    error_category="ip_banned",
                )
                return metric, [], False, None

            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")
            total_results = self._extract_total_results(soup)

            page_summaries: list[ListingSummary] = []
            for article in soup.find_all(
                "article", class_="aditem", attrs={"data-adid": True}
            ):
                if summary := self._parse_listing_summary(article):
                    page_summaries.append(summary)

            duration = time.perf_counter() - start
            metric = PageMetric(
                page_number=page_number,
                time_taken=duration,
                success=True,
                retry_count=0,
                results_count=len(page_summaries),
            )
            return metric, page_summaries, False, total_results

        except httpx.HTTPStatusError as exc:
            duration = time.perf_counter() - start
            logger.warning(
                "HTTP {} on page {}: {}",
                exc.response.status_code,
                page_number,
                exc,
            )
            metric = PageMetric(
                page_number=page_number,
                time_taken=duration,
                success=False,
                retry_count=0,
                results_count=0,
                error=str(exc),
                error_category="http_error",
            )
            return metric, [], False, None

        except httpx.HTTPError as exc:
            duration = time.perf_counter() - start
            logger.warning("Network error on page {}: {}", page_number, exc)
            metric = PageMetric(
                page_number=page_number,
                time_taken=duration,
                success=False,
                retry_count=0,
                results_count=0,
                error=str(exc),
                error_category="network_error",
            )
            return metric, [], False, None

    def _build_search_url(
        self,
        *,
        page_number: int,
        query: str | None,
        location: str | None,
        radius: int | None,
        min_price: int | None,
        max_price: int | None,
        sort_by: str | None = None,
    ) -> str:
        params: dict[str, Any] = {}
        if location:
            params["locationStr"] = location
        if radius:
            params["radius"] = radius

        first_modifier: str | None = None
        path_segments: list[str] = []

        if sort_by:
            if sort_by.lower() in {"price", "lowest", "preis"}:
                first_modifier = "sortierung:preis"
            elif sort_by.lower() in {"highest", "teuerste"}:
                first_modifier = "sortierung:teuerste"

        if not first_modifier and (min_price is not None or max_price is not None):
            min_seg = str(min_price) if min_price is not None else ""
            max_seg = str(max_price) if max_price is not None else ""
            first_modifier = f"preis:{min_seg}:{max_seg}"

        slugified_query = self._slugify(query) if query else None

        if first_modifier:
            base_path = f"s-{first_modifier}"
        elif slugified_query:
            base_path = f"s-{slugified_query}"
            slugified_query = None
        else:
            base_path = "s"

        if sort_by and (min_price is not None or max_price is not None):
            min_seg = str(min_price) if min_price is not None else ""
            max_seg = str(max_price) if max_price is not None else ""
            path_segments.append(f"preis:{min_seg}:{max_seg}")

        if page_number > 1:
            path_segments.append(f"seite:{page_number}")

        if slugified_query:
            path_segments.append(slugified_query)

        path_segments.append("k0")

        full_path = f"{base_path}/{'/'.join(path_segments)}"
        base_url = f"{self.BASE_URL}/{full_path}"
        query_string = urlencode(params)
        return f"{base_url}?{query_string}" if query_string else base_url

    @staticmethod
    def _slugify(value: str) -> str:
        """Convert a search term to a Kleinanzeigen-compatible URL slug.

        Handles German umlauts (ä→ae, ö→oe, ü→ue, ß→ss) before ASCII-folding
        so that queries like "möbel" produce "moebel" rather than "mbel".
        """
        value = value.strip().lower().translate(_UMLAUT)
        value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
        value = re.sub(r"\s+", "-", value)
        value = re.sub(r"[^a-z0-9-]", "", value)
        return value or "k0"

    @staticmethod
    def _extract_total_results(soup: BeautifulSoup) -> int | None:
        """Parse the total result count from the breadcrumb summary span.

        Example text: "1 - 25 von 3.006 Ergebnissen für „mini pc" in Deutschland"
        Returns 3006.
        """
        breadcrumb = soup.find(class_="breadcrump-summary")
        if not breadcrumb:
            return None
        text = breadcrumb.get_text(strip=True)
        match = re.search(r"von\s+([\d.]+)\s+Ergebnis", text)
        if not match:
            return None
        total_str = match[1].replace(".", "")
        try:
            return int(total_str)
        except ValueError:
            logger.warning("Failed to parse total results from: {}", text)
            return None

    def _parse_listing_summary(self, article: Tag) -> ListingSummary | None:
        ad_id = article.get("data-adid")
        href = article.get("data-href")
        if not ad_id or not href:
            return None

        title_element = article.find("a", class_="ellipsis")
        price_element = article.find(
            "p", class_="aditem-main--middle--price-shipping--price"
        )
        description_element = article.find(
            "p", class_="aditem-main--middle--description"
        )

        price = parse_price(price_element.get_text() if price_element else None)

        summary_data: dict[str, Any] = {
            "adid": ad_id,
            "url": f"{self.BASE_URL}{href}",
            "title": title_element.get_text(strip=True) if title_element else "",
            "price": price["amount"],
            "currency": price["currency"],
            "negotiable": price["negotiable"],
            "description": (
                description_element.get_text(strip=True)
                if description_element
                else None
            ),
        }
        return ListingSummary.model_validate(summary_data)

    def _parse_delivery_method(self, soup: BeautifulSoup) -> str | None:
        shipping_text = soup.find(class_="boxedarticle--details--shipping")
        if shipping_text is None:
            return None
        text = shipping_text.get_text(strip=True)
        if "Nur Abholung" in text:
            return "pickup"
        return "shipping" if "Versand" in text else None

    def _parse_delivery_cost(self, soup: BeautifulSoup) -> str | None:
        shipping_text = soup.find(class_="boxedarticle--details--shipping")
        if shipping_text is None:
            return None
        text = shipping_text.get_text(" ", strip=True)
        match = re.search(r"([0-9.,]+)\s*€", text)
        return f"{match[1]} €" if match else None

    def _extract_description(self, soup: BeautifulSoup) -> str | None:
        description = soup.find(id="viewad-description-text")
        if not description:
            return None
        cleaned = description.get_text("\n", strip=True)
        return re.sub(r"\n{2,}", "\n", cleaned)

    def _extract_features(self, soup: BeautifulSoup) -> list[str]:
        container = soup.find(id="viewad-configuration")
        if container is None:
            return []
        return [
            tag.get_text(strip=True)
            for tag in container.find_all(class_="checktag")
            if tag.get_text(strip=True)
        ]
