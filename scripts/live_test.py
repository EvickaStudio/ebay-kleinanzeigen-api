from __future__ import annotations

import argparse

import httpx


def get_data(
    client: httpx.Client, path: str, params: dict[str, object] | None = None
) -> object:
    response = client.get(path, params=params)
    response.raise_for_status()
    body = response.json()
    assert body.get("success") is True, body
    return body["data"]


def check_results(
    results: list[dict], query: str, min_price: int, max_price: int
) -> None:
    assert results, "search returned no listings"
    assert all(
        item["price"] is None or min_price <= item["price"] <= max_price
        for item in results
    ), "a listing is outside the requested price range"
    terms = query.casefold().split()
    assert any(
        all(
            term in f"{item['title']} {item.get('description') or ''}".casefold()
            for term in terms
        )
        for item in results
    ), "no listing matches the search query"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check all API endpoints against a running live server"
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--query", default="Mini PC")
    parser.add_argument("--min-price", type=int, default=50)
    parser.add_argument("--max-price", type=int, default=500)
    args = parser.parse_args()

    params = {
        "query": args.query,
        "min_price": args.min_price,
        "max_price": args.max_price,
        "page_count": 1,
        "start_page": 1,
    }

    with httpx.Client(base_url=args.base_url, timeout=60) as client:
        health = client.get("/health")
        health.raise_for_status()
        assert health.json() == {"status": "ok"}
        print("PASS /health")

        listings = get_data(client, "/v1/listings", params)
        check_results(listings["results"], args.query, args.min_price, args.max_price)
        assert listings["total_results"] == len(listings["results"])
        assert listings["pagination"]["pages_requested"] == 1
        assert listings["pagination"]["start_page"] == 1
        print(f"PASS /v1/listings ({listings['total_results']} results)")

        summary = listings["results"][0]
        detail = get_data(client, f"/v1/listings/{summary['adid']}")
        assert detail["id"] == summary["adid"]
        assert detail["title"]
        print(f"PASS /v1/listings/{{id}} ({summary['adid']})")

        detailed_params = {**params, "max_concurrent_details": 10}
        detailed = get_data(client, "/v1/listings-detailed", detailed_params)
        check_results(
            [item["summary"] for item in detailed],
            args.query,
            args.min_price,
            args.max_price,
        )
        assert all(item["summary"]["adid"] == item["detail"]["id"] for item in detailed)
        print(f"PASS /v1/listings-detailed ({len(detailed)} results)")


if __name__ == "__main__":
    main()
