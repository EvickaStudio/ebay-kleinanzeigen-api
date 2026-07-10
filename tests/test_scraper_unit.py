"""Unit tests for scraper helpers — no real HTTP calls."""

from __future__ import annotations

import anyio
import httpx
import pytest
from bs4 import BeautifulSoup

from src.app.models.metrics import PageMetric
from src.app.services.scraper import KleinanzeigenScraperService, _is_ip_ban_page
from tests.html_fixtures import IP_BAN_HTML, LISTING_PAGE_HTML


@pytest.fixture
def scraper(request: pytest.FixtureRequest) -> KleinanzeigenScraperService:
    client = httpx.AsyncClient()

    def _close() -> None:
        async def _aclose() -> None:
            await client.aclose()

        anyio.run(_aclose)

    request.addfinalizer(_close)
    return KleinanzeigenScraperService(client=client)


class TestIsBanPage:
    def test_detects_ban(self):
        assert _is_ip_ban_page(IP_BAN_HTML) is True

    def test_normal_page_not_banned(self):
        assert _is_ip_ban_page(LISTING_PAGE_HTML) is False

    def test_requires_both_markers(self):
        assert _is_ip_ban_page("IP-Bereich ohne anderes wort") is False
        assert _is_ip_ban_page("gesperrt ohne den anderen marker") is False


class TestSlugify:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("mini pc", "mini-pc"),
            ("Mini PC", "mini-pc"),
            ("möbel", "moebel"),
            ("büro", "buero"),
            ("straße", "strasse"),
            ("Äpfel", "aepfel"),
            ("hello world!", "hello-world"),
            ("  spaces  ", "spaces"),
            ("", "k0"),
            ("123", "123"),
        ],
    )
    def test_slugify(self, value: str, expected: str):
        assert KleinanzeigenScraperService._slugify(value) == expected


class TestNormalizeListingId:
    @pytest.mark.parametrize(
        ("input_id", "expected"),
        [
            ("12345678", "12345678"),
            ("12345678-test-laptop", "12345678"),
            ("12345678-laptop-2024", "12345678"),
            ("12345", "12345"),
            ("123-abc", "123"),
        ],
    )
    def test_normalize(self, input_id: str, expected: str):
        assert KleinanzeigenScraperService._normalize_listing_id(input_id) == expected


class TestExtractTotalResults:
    def _breadcrumb(self, text: str) -> BeautifulSoup:
        return BeautifulSoup(
            f'<span class="breadcrump-summary">{text}</span>', "html.parser"
        )

    def test_standard_german_format(self, scraper):
        soup = self._breadcrumb('1 - 25 von 3.006 Ergebnissen für „mini pc"')
        assert scraper._extract_total_results(soup) == 3006

    def test_small_result_count(self, scraper):
        assert (
            scraper._extract_total_results(self._breadcrumb("1 - 5 von 5 Ergebnissen"))
            == 5
        )

    def test_large_number_with_multiple_dots(self, scraper):
        soup = self._breadcrumb("1 - 25 von 1.234.567 Ergebnissen")
        assert scraper._extract_total_results(soup) == 1234567

    def test_returns_none_when_no_breadcrumb(self, scraper):
        assert (
            scraper._extract_total_results(BeautifulSoup("<html/>", "html.parser"))
            is None
        )

    def test_returns_none_when_pattern_absent(self, scraper):
        assert (
            scraper._extract_total_results(self._breadcrumb("Keine Ergebnisse")) is None
        )


class TestBuildSearchUrl:
    base = "https://www.kleinanzeigen.de"

    def _url(self, scraper, **kwargs) -> str:
        defaults = {
            "page_number": 1,
            "query": None,
            "location": None,
            "radius": None,
            "min_price": None,
            "max_price": None,
            "sort_by": None,
        }
        defaults |= kwargs
        return scraper._build_search_url(**defaults)

    def test_no_params(self, scraper):
        assert self._url(scraper) == f"{self.base}/s/k0"

    def test_query_only(self, scraper):
        assert self._url(scraper, query="mini pc") == f"{self.base}/s-mini-pc/k0"

    def test_query_with_umlaut(self, scraper):
        assert self._url(scraper, query="möbel") == f"{self.base}/s-moebel/k0"

    def test_query_page_2(self, scraper):
        assert self._url(scraper, query="mini pc", page_number=2) == (
            f"{self.base}/s-mini-pc/seite:2/k0"
        )

    def test_sort_price_ascending(self, scraper):
        assert self._url(scraper, query="pc", sort_by="price") == (
            f"{self.base}/s-sortierung:preis/pc/k0"
        )

    def test_sort_aliases_map_to_same_segment(self, scraper):
        for alias in ("price", "lowest", "preis"):
            assert "sortierung:preis" in self._url(scraper, sort_by=alias)

    def test_sort_price_descending(self, scraper):
        assert "sortierung:teuerste" in self._url(scraper, sort_by="highest")

    def test_price_range_only(self, scraper):
        assert self._url(scraper, min_price=10, max_price=350) == (
            f"{self.base}/s-preis:10:350/k0"
        )

    def test_price_range_min_only(self, scraper):
        assert "preis:50:" in self._url(scraper, min_price=50)

    def test_sort_and_price_and_query(self, scraper):
        assert (
            self._url(scraper, query="pc", sort_by="price", min_price=10, max_price=350)
            == f"{self.base}/s-sortierung:preis/preis:10:350/pc/k0"
        )

    def test_location_as_query_param(self, scraper):
        assert "locationStr=Berlin" in self._url(scraper, location="Berlin")

    def test_radius_as_query_param(self, scraper):
        url = self._url(scraper, location="Berlin", radius=20)
        assert "radius=20" in url
        assert "locationStr=Berlin" in url

    def test_page_number_in_path_not_params(self, scraper):
        url = self._url(scraper, query="laptop", page_number=3)
        assert "seite:3" in url
        assert "page" not in url.split("?")[0]


class TestParseListingSummary:
    def test_parses_first_article(self, scraper):
        soup = BeautifulSoup(LISTING_PAGE_HTML, "html.parser")
        article = soup.select("article.aditem[data-adid]")[0]
        summary = scraper._parse_listing_summary(article)
        assert summary is not None
        assert summary.ad_id == "12345678"
        assert summary.price == 149.99
        assert summary.currency == "EUR"
        assert summary.negotiable is False
        assert summary.title == "Test Item"
        assert "12345678" in summary.url

    def test_parses_negotiable_listing(self, scraper):
        soup = BeautifulSoup(LISTING_PAGE_HTML, "html.parser")
        article = soup.select("article.aditem[data-adid]")[1]
        summary = scraper._parse_listing_summary(article)
        assert summary is not None
        assert summary.negotiable is True
        assert summary.price == 50.0

    def test_returns_none_for_missing_adid(self, scraper):
        html = '<article class="aditem" data-href="/test"></article>'
        article = BeautifulSoup(html, "html.parser").select_one("article")
        assert article is not None
        assert scraper._parse_listing_summary(article) is None

    def test_returns_none_for_missing_href(self, scraper):
        html = '<article class="aditem" data-adid="99999"></article>'
        article = BeautifulSoup(html, "html.parser").select_one("article")
        assert article is not None
        assert scraper._parse_listing_summary(article) is None


class TestListingViews:
    @pytest.mark.anyio
    async def test_num_visits_str_all_zeros_returns_zero(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"numVisitsStr": "000"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            scraper = KleinanzeigenScraperService(client=client)
            assert await scraper.fetch_listing_views("12345678") == 0

    @pytest.mark.anyio
    async def test_num_visits_int_returns_value(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"numVisits": 123})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            scraper = KleinanzeigenScraperService(client=client)
            assert await scraper.fetch_listing_views("12345678") == 123

    @pytest.mark.anyio
    async def test_num_visits_str_with_leading_zeros_returns_parsed_int(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"numVisitsStr": "00123"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            scraper = KleinanzeigenScraperService(client=client)
            assert await scraper.fetch_listing_views("12345678") == 123

    @pytest.mark.anyio
    async def test_num_visits_str_with_non_digits_returns_none(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"numVisitsStr": "123 views"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            scraper = KleinanzeigenScraperService(client=client)
            assert await scraper.fetch_listing_views("12345678") is None

    @pytest.mark.anyio
    async def test_http_error_returns_none(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "internal error"})

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            scraper = KleinanzeigenScraperService(client=client)
            assert await scraper.fetch_listing_views("12345678") is None


class TestFetchListingsPagination:
    @pytest.mark.anyio
    async def test_redirect_stops_scheduling_and_updates_metadata(
        self, scraper, monkeypatch
    ):
        called_pages: list[int] = []
        monkeypatch.setattr(scraper._settings, "page_fetch_concurrency", 1)

        async def fake_fetch_listings_page(
            *,
            page_number: int,
            query: str | None,
            location: str | None,
            radius: int | None,
            min_price: int | None,
            max_price: int | None,
            sort_by: str | None,
        ):
            called_pages.append(page_number)
            if page_number == 1:
                return (
                    PageMetric(
                        page_number=1,
                        time_taken=0.01,
                        success=True,
                        retry_count=0,
                        results_count=0,
                    ),
                    [],
                    False,
                    3006,
                )
            return (
                PageMetric(
                    page_number=page_number,
                    time_taken=0.01,
                    success=False,
                    retry_count=0,
                    results_count=0,
                    error="Redirect 302",
                    error_category="redirect",
                ),
                [],
                True,
                None,
            )

        monkeypatch.setattr(scraper, "_fetch_listings_page", fake_fetch_listings_page)

        _, metrics, pagination = await scraper.fetch_listings(
            query="test", page_count=3
        )

        assert called_pages == [1, 2]
        assert metrics.pages_requested == 3
        assert metrics.pages_failed == 1
        assert pagination.pages_fetched == 2
        assert pagination.end_page == 2
