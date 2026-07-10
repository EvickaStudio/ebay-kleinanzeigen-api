"""Integration tests for FastAPI routes — outbound httpx calls are mocked."""

from __future__ import annotations

import uuid

import httpx
import pytest

from src.app.middleware.request_id import resolve_x_request_id
from tests.html_fixtures import (
    DETAIL_PAGE_HTML,
    EMPTY_LISTING_PAGE_HTML,
    IP_BAN_HTML,
    LISTING_PAGE_HTML,
)

_SEARCH_RE = r"https://www\.kleinanzeigen\.de/s[^-].*|https://www\.kleinanzeigen\.de/s-(?!anzeige|vac).*"
_DETAIL_RE = r"https://www\.kleinanzeigen\.de/s-anzeige/.*"
_VIEWS_URL = "https://www.kleinanzeigen.de/s-vac-inc-get.json"
_VIEWS_JSON = {"numVisits": 412}


class TestHealth:
    def test_returns_ok(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_status_200(self, client):
        assert client.get("/health").status_code == 200

    def test_not_in_openapi_schema(self, client):
        paths = client.get("/openapi.json").json()["paths"]
        assert "/health" not in paths

    def test_echoes_request_id_header(self, client):
        response = client.get("/health", headers={"X-Request-ID": "test-abc"})
        assert response.headers.get("x-request-id") == "test-abc"

    def test_generates_request_id_when_absent(self, client):
        response = client.get("/health")
        assert "x-request-id" in response.headers
        assert len(response.headers["x-request-id"]) > 0

    def test_strips_whitespace_on_request_id(self, client):
        response = client.get("/health", headers={"X-Request-ID": "  my-id  "})
        assert response.headers.get("x-request-id") == "my-id"

    def test_oversized_request_id_replaced(self, client):
        long_id = "a" * 200
        response = client.get("/health", headers={"X-Request-ID": long_id})
        rid = response.headers.get("x-request-id")
        assert rid is not None
        assert len(rid) == 36
        uuid.UUID(rid)

    def test_control_char_in_request_id_replaced(self, client):
        response = client.get("/health", headers={"X-Request-ID": "bad\nid"})
        rid = response.headers.get("x-request-id")
        assert rid != "bad\nid"
        uuid.UUID(rid)


class TestResolveXRequestId:
    def test_none_generates_uuid(self):
        rid = resolve_x_request_id(None)
        assert len(rid) == 36
        uuid.UUID(rid)

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("simple", "simple"),
            ("  padded  ", "padded"),
            ("a-z_0.9:", "a-z_0.9:"),
        ],
    )
    def test_valid_values(self, raw: str, expected: str):
        assert resolve_x_request_id(raw) == expected

    def test_empty_after_strip_generates_uuid(self):
        rid = resolve_x_request_id("   ")
        uuid.UUID(rid)


class TestListingsValidation:
    def test_invalid_sort_by_returns_422(self, client):
        assert client.get("/v1/listings?sort_by=invalid").status_code == 422

    def test_radius_zero_returns_422(self, client):
        assert client.get("/v1/listings?radius=0").status_code == 422

    def test_radius_over_100_returns_422(self, client):
        assert client.get("/v1/listings?radius=101").status_code == 422

    def test_page_count_zero_returns_422(self, client):
        assert client.get("/v1/listings?page_count=0").status_code == 422

    def test_page_count_over_10_returns_422(self, client):
        assert client.get("/v1/listings?page_count=11").status_code == 422

    def test_start_page_over_200_returns_422(self, client):
        assert client.get("/v1/listings?start_page=201").status_code == 422

    def test_negative_min_price_returns_422(self, client):
        assert client.get("/v1/listings?min_price=-1").status_code == 422

    def test_valid_sort_aliases_accepted(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=EMPTY_LISTING_PAGE_HTML)
        )
        for alias in ("price", "lowest", "preis", "highest", "teuerste"):
            assert client.get(f"/v1/listings?sort_by={alias}").status_code == 200


class TestListingsSuccess:
    def test_identical_request_hits_cache(self, client, mock_http):
        route = mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        headers = {"Cache-Control": ""}
        first = client.get("/v1/listings?query=cache-test", headers=headers)
        second = client.get("/v1/listings?query=cache-test", headers=headers)
        assert first.headers["x-fastapi-cache"] == "MISS"
        assert second.headers["x-fastapi-cache"] == "HIT"
        assert route.call_count == 1

    def test_returns_200_with_results(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        response = client.get("/v1/listings?query=test")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert data["total_results"] == 2
        assert len(data["results"]) == 2

    def test_response_envelope_shape(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        body = client.get("/v1/listings").json()
        assert "success" in body
        assert "data" in body
        assert "time_taken" in body

    def test_listing_summary_fields(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        result = client.get("/v1/listings?query=test").json()["data"]["results"][0]
        for field in (
            "adid",
            "title",
            "price",
            "currency",
            "negotiable",
            "url",
            "description",
        ):
            assert field in result
        assert result["adid"] == "12345678"
        assert result["price"] == 149.99
        assert result["negotiable"] is False

    def test_pagination_metadata(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        pagination = client.get("/v1/listings?page_count=1&start_page=1").json()[
            "data"
        ]["pagination"]
        assert pagination["pages_requested"] == 1
        assert pagination["pages_fetched"] == 1
        assert pagination["start_page"] == 1
        assert pagination["end_page"] == 1
        assert pagination["total_available_results"] == 3006
        assert pagination["results_per_page"] == 25

    def test_metrics_included(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        metrics = client.get("/v1/listings?query=test").json()["data"]["metrics"]
        assert metrics["pages_requested"] == 1
        assert metrics["pages_successful"] == 1
        assert metrics["success_rate"] == 100.0

    def test_empty_results(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=EMPTY_LISTING_PAGE_HTML)
        )
        data = client.get("/v1/listings?query=xyznotfound").json()["data"]
        assert data["total_results"] == 0
        assert data["results"] == []

    def test_multipage_deduplication(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        data = client.get("/v1/listings?query=test&page_count=3").json()["data"]
        assert data["total_results"] == 2
        assert data["pagination"]["duplicates_removed"] == 4

    def test_redirect_stops_pagination_early(self, client, mock_http):
        def side_effect(request):
            if "seite:2" in str(request.url):
                return httpx.Response(
                    302, headers={"Location": "https://www.kleinanzeigen.de/"}
                )
            return httpx.Response(200, text=LISTING_PAGE_HTML)

        mock_http.get(url__regex=_SEARCH_RE).mock(side_effect=side_effect)
        response = client.get("/v1/listings?query=test&page_count=3")
        assert response.status_code == 200
        assert response.json()["data"]["total_results"] == 2


class TestListingsErrors:
    def test_ip_ban_returns_503(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=IP_BAN_HTML)
        )
        response = client.get("/v1/listings?query=test")
        assert response.status_code == 503
        body = response.json()
        assert body["success"] is False
        assert body["error"]
        assert body["error_category"] == "ip_banned"

    def test_upstream_http_error_returns_empty_not_502(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(500, text="error")
        )
        response = client.get("/v1/listings?query=test")
        assert response.status_code == 200
        assert response.json()["data"]["total_results"] == 0

    def test_error_response_shape(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=IP_BAN_HTML)
        )
        body = client.get("/v1/listings?query=test").json()
        assert body["success"] is False
        assert "error" in body


class TestListingDetailValidation:
    def test_too_short_id_returns_400(self, client):
        response = client.get("/v1/listings/123")
        assert response.status_code == 400
        assert response.json()["success"] is False

    def test_non_numeric_id_returns_400(self, client):
        assert client.get("/v1/listings/not-valid-id!").status_code == 400

    def test_id_with_valid_slug_accepted(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=DETAIL_PAGE_HTML)
        )
        mock_http.get(_VIEWS_URL).mock(
            return_value=httpx.Response(200, json=_VIEWS_JSON)
        )
        assert client.get("/v1/listings/12345678-test-laptop").status_code == 200

    def test_numeric_only_id_accepted(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=DETAIL_PAGE_HTML)
        )
        mock_http.get(_VIEWS_URL).mock(
            return_value=httpx.Response(200, json=_VIEWS_JSON)
        )
        assert client.get("/v1/listings/12345678").status_code == 200


class TestListingDetailSuccess:
    def _get_detail(self, client, mock_http, listing_id: str = "12345678") -> dict:
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=DETAIL_PAGE_HTML)
        )
        mock_http.get(_VIEWS_URL).mock(
            return_value=httpx.Response(200, json=_VIEWS_JSON)
        )
        return client.get(f"/v1/listings/{listing_id}").json()

    def test_status_200(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=DETAIL_PAGE_HTML)
        )
        mock_http.get(_VIEWS_URL).mock(
            return_value=httpx.Response(200, json=_VIEWS_JSON)
        )
        assert client.get("/v1/listings/12345678").status_code == 200

    def test_detail_fields(self, client, mock_http):
        body = self._get_detail(client, mock_http)
        assert body["success"] is True
        detail = body["data"]
        assert detail["id"] == "12345678"
        assert detail["title"] == "Test Laptop"
        assert detail["price"]["amount"] == 299.0
        assert detail["price"]["negotiable"] is True
        assert detail["price"]["currency"] == "EUR"

    def test_location_parsed(self, client, mock_http):
        detail = self._get_detail(client, mock_http)["data"]
        assert detail["location"]["zip"] == "10115"
        assert detail["location"]["state"] == "Berlin"
        assert detail["location"]["city"] == "Mitte"

    def test_views_from_api(self, client, mock_http):
        assert self._get_detail(client, mock_http)["data"]["views"] == 412

    def test_categories(self, client, mock_http):
        detail = self._get_detail(client, mock_http)["data"]
        assert "Elektronik" in detail["categories"]
        assert "Laptops" in detail["categories"]

    def test_images(self, client, mock_http):
        assert len(self._get_detail(client, mock_http)["data"]["images"]) == 2

    def test_seller(self, client, mock_http):
        detail = self._get_detail(client, mock_http)["data"]
        assert detail["seller"]["name"] == "max_user"
        assert detail["seller"]["type"] == "private"
        assert detail["seller"]["since"] == "2020"

    def test_delivery(self, client, mock_http):
        detail = self._get_detail(client, mock_http)["data"]
        assert detail["delivery"] == "shipping"
        assert detail["delivery_cost"] == "4,99 €"

    def test_details_dict(self, client, mock_http):
        detail = self._get_detail(client, mock_http)["data"]
        assert detail["details"]["Zustand"] == "Gebraucht"
        assert detail["details"]["Marke"] == "Dell"

    def test_features_list(self, client, mock_http):
        detail = self._get_detail(client, mock_http)["data"]
        assert "Feature 1" in detail["features"]
        assert "Feature 2" in detail["features"]


class TestListingDetailErrors:
    def test_expired_listing_returns_404(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(
                302, headers={"Location": "https://www.kleinanzeigen.de/"}
            )
        )
        response = client.get("/v1/listings/12345678")
        assert response.status_code == 404
        assert response.json()["success"] is False

    def test_upstream_500_returns_502(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(500, text="server error")
        )
        assert client.get("/v1/listings/12345678").status_code == 502

    def test_ip_ban_returns_503(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=IP_BAN_HTML)
        )
        response = client.get("/v1/listings/12345678")
        assert response.status_code == 503
        assert response.json()["error_category"] == "ip_banned"

    def test_views_failure_is_graceful(self, client, mock_http):
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=DETAIL_PAGE_HTML)
        )
        mock_http.get(_VIEWS_URL).mock(return_value=httpx.Response(500, text="error"))
        response = client.get("/v1/listings/12345678")
        assert response.status_code == 200
        assert response.json()["data"]["views"] is None


class TestListingsDetailedValidation:
    def test_page_count_max_is_5(self, client):
        assert client.get("/v1/listings-detailed?page_count=6").status_code == 422

    def test_max_concurrent_over_20_returns_422(self, client):
        assert (
            client.get("/v1/listings-detailed?max_concurrent_details=21").status_code
            == 422
        )

    def test_max_concurrent_zero_returns_422(self, client):
        assert (
            client.get("/v1/listings-detailed?max_concurrent_details=0").status_code
            == 422
        )


class TestListingsDetailedSuccess:
    def test_returns_list_of_summary_detail_pairs(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        mock_http.get(url__regex=_DETAIL_RE).mock(
            return_value=httpx.Response(200, text=DETAIL_PAGE_HTML)
        )
        mock_http.get(_VIEWS_URL).mock(
            return_value=httpx.Response(200, json=_VIEWS_JSON)
        )
        response = client.get("/v1/listings-detailed?query=test")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        data = body["data"]
        assert isinstance(data, list)
        assert len(data) == 2
        item = data[0]
        assert "summary" in item and "detail" in item
        assert item["summary"]["adid"] in ("12345678", "87654321")

    def test_failed_detail_fetch_excluded_silently(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=LISTING_PAGE_HTML)
        )
        call_count = 0

        def detail_side_effect(request):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(200, text=DETAIL_PAGE_HTML)
            return httpx.Response(500, text="error")

        mock_http.get(url__regex=_DETAIL_RE).mock(side_effect=detail_side_effect)
        mock_http.get(_VIEWS_URL).mock(
            return_value=httpx.Response(200, json=_VIEWS_JSON)
        )
        response = client.get("/v1/listings-detailed?query=test")
        assert response.status_code == 200
        assert len(response.json()["data"]) >= 1


class TestErrorEnvelope:
    def test_400_has_success_false_and_error(self, client):
        body = client.get("/v1/listings/bad!").json()
        assert body["success"] is False
        assert isinstance(body["error"], str) and body["error"]

    def test_404_for_unknown_route(self, client):
        assert client.get("/v1/nonexistent-endpoint").status_code == 404

    def test_503_has_ip_banned_category(self, client, mock_http):
        mock_http.get(url__regex=_SEARCH_RE).mock(
            return_value=httpx.Response(200, text=IP_BAN_HTML)
        )
        body = client.get("/v1/listings?query=test").json()
        assert body["success"] is False
        assert body["error_category"] == "ip_banned"
