# API Usage Guide

## Base URL

```
http://localhost:8000
```

All scraping endpoints are under the `/v1` prefix.  
Interactive docs: `http://localhost:8000/docs` · ReDoc: `http://localhost:8000/redoc`

---

## Endpoints

### `GET /v1/listings`

Retrieve listing summaries with filtering, sorting, and multi-page support.

**Query parameters**

| Parameter | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `raw_url` | string | — | — | Raw URL to scrape (overrides all other filters) |
| `query` | string | — | — | Search term |
| `location` | string | — | — | City or location name |
| `radius` | integer | — | 1–100 | Search radius in km |
| `min_price` | integer | — | ≥ 0 | Minimum price in EUR |
| `max_price` | integer | — | ≥ 0 | Maximum price in EUR |
| `sort_by` | enum | — | see below | Sort order |
| `page_count` | integer | 1 | 1–10 | Pages to fetch (fetched in parallel) |
| `start_page` | integer | 1 | 1–200 | Starting page number |

`sort_by` accepted values:

| Value | Effect |
|---|---|
| `lowest` / `price` / `preis` | Cheapest first |
| `highest` / `teuerste` | Most expensive first |
| *(omit)* | Newest first (Kleinanzeigen default) |

**Example requests**

```bash
# Basic search
curl "http://localhost:8000/v1/listings?query=mini%20pc"

# Price-filtered, sorted, multi-page
curl "http://localhost:8000/v1/listings?query=pc&min_price=10&max_price=350&sort_by=price&page_count=3"

# Continue from a later page
curl "http://localhost:8000/v1/listings?query=pc&start_page=6&page_count=5"

# Location-based
curl "http://localhost:8000/v1/listings?query=fahrrad&location=Berlin&radius=20"

# Using a raw URL (must be URL-encoded)
curl "http://localhost:8000/v1/listings?raw_url=https%3A%2F%2Fwww.kleinanzeigen.de%2Fs-berlin%2Ffahrrad%2Fk0l3331"
```

**Response**

```json
{
  "success": true,
  "time_taken": 0.31,
  "data": {
    "success": true,
    "results": [
      {
        "adid": "1641118170",
        "url": "https://www.kleinanzeigen.de/s-anzeige/...",
        "title": "Mini PC Intel i5",
        "price": 149.0,
        "currency": "EUR",
        "negotiable": false,
        "is_top": false,
        "description": "Guter Zustand, voll funktionsfähig..."
      }
    ],
    "total_results": 25,
    "pagination": {
      "pages_requested": 1,
      "pages_fetched": 1,
      "start_page": 1,
      "end_page": 1,
      "total_available_results": 3006,
      "results_per_page": 25,
      "duplicates_removed": 0
    },
    "metrics": {
      "pages_requested": 1,
      "pages_successful": 1,
      "pages_failed": 0,
      "concurrency": 3,
      "success_rate": 100.0,
      "average_page_time": 0.28,
      "fastest_page_time": 0.28,
      "slowest_page_time": 0.28,
      "page_details": [
        {
          "page_number": 1,
          "time_taken": 0.28,
          "success": true,
          "retry_count": 0,
          "results_count": 25,
          "duplicates_found": 0
        }
      ]
    },
    "time_taken": 0.31
  }
}
```

**`pagination` fields**

| Field | Description |
|---|---|
| `pages_requested` | Number of pages requested |
| `pages_fetched` | Pages actually processed before completion or early termination |
| `start_page` / `end_page` | Processed page range |
| `total_available_results` | Total results on Kleinanzeigen (from breadcrumb, if detected) |
| `results_per_page` | Always 25 |
| `duplicates_removed` | Listings removed because the same `adid` appeared on multiple pages |

---

### `GET /v1/listings/{listing_id}`

Retrieve full detail for a single listing.

**Path parameters**

| Parameter | Format |
|---|---|
| `listing_id` | Numeric ID, optionally followed by a slug: `1641118170` or `1641118170-mini-pc` |

**Example**

```bash
curl "http://localhost:8000/v1/listings/1641118170"
```

**Response**

```json
{
  "success": true,
  "time_taken": 0.34,
  "data": {
    "id": "1641118170",
    "title": "Mini PC Intel i5",
    "status": "active",
    "categories": ["Computer", "Mini-PCs"],
    "price": {
      "amount": 149.0,
      "currency": "EUR",
      "negotiable": false
    },
    "location": {
      "zip": "10115",
      "city": "Berlin",
      "state": null
    },
    "delivery": "shipping",
    "delivery_cost": "4,99 €",
    "views": 412,
    "description": "Guter Zustand...",
    "images": [
      "https://img.kleinanzeigen.de/api/v1/prod-ads/images/..."
    ],
    "details": {
      "Zustand": "Gebraucht"
    },
    "features": [],
    "seller": {
      "name": "max_m",
      "since": "2020",
      "type": "private",
      "badges": []
    },
    "extra_info": {
      "created_at": "Gestern, 14:32"
    }
  }
}
```

Returns HTTP `404` if the listing has expired or been removed.

---

### `GET /v1/listings-detailed`

Fetch listing summaries and their full detail pages in a single request. Internally calls `/v1/listings` then fetches each detail page concurrently.

**Query parameters**

Same as `/v1/listings`, plus:

| Parameter | Type | Default | Constraints | Description |
|---|---|---|---|---|
| `max_concurrent_details` | integer | 10 | 1–20 | Detail pages fetched in parallel |
| `page_count` | integer | 1 | 1–5 | Pages to fetch (lower max than `/v1/listings`) |

**Example**

```bash
# Basic search
curl "http://localhost:8000/v1/listings-detailed?query=laptop&page_count=2&max_concurrent_details=10"

# Using a raw URL
curl "http://localhost:8000/v1/listings-detailed?raw_url=https%3A%2F%2Fwww.kleinanzeigen.de%2Fs-berlin%2Flaptop%2Fk0l3331&page_count=2"
```

**Response** — `data` is a list of `{ "summary": {...}, "detail": {...} }` objects:

```json
{
  "success": true,
  "time_taken": 5.21,
  "data": [
    {
      "summary": {
        "adid": "1641118170",
        "url": "https://www.kleinanzeigen.de/...",
        "title": "Mini PC Intel i5",
        "price": 149.0,
        "currency": "EUR",
        "negotiable": false,
        "is_top": true,
        "description": "..."
      },
      "detail": {
        "id": "1641118170",
        "title": "Mini PC Intel i5",
        "price": { "amount": 149.0, "currency": "EUR", "negotiable": false },
        "location": { "zip": "10115", "city": "Berlin", "state": null },
        "views": 412,
        "seller": { "name": "max_m", "type": "private", "since": "2020", "badges": [] }
      }
    }
  ]
}
```

---

### `GET /health`

Health check endpoint. Returns `{"status": "ok"}` when the server is running. Not included in the OpenAPI schema.

Used by Docker `HEALTHCHECK`, Kubernetes liveness probes, and reverse-proxy health monitors.

---

## Error Responses

Application-generated errors use this shape:

```json
{
  "success": false,
  "error": "Listing not found",
  "error_category": null
}
```

FastAPI validation failures (`422`) do not use `ApiErrorResponse`; they keep the default framework payload:

```json
{
  "detail": [
    {
      "type": "greater_than_equal",
      "loc": ["query", "radius"],
      "msg": "Input should be greater than or equal to 1",
      "input": 0,
      "ctx": { "ge": 1 }
    }
  ]
}
```

| HTTP status | Meaning |
|---|---|
| `400` | Invalid parameter handled by the application (e.g. bad `listing_id` format) |
| `404` | Listing has expired or been removed |
| `422` | FastAPI validation error (query param out of range, wrong type) with default `detail` array |
| `429` | Rate limit exceeded (when `APP_RATE_LIMIT_ENABLED=true`) |
| `500` | Unhandled server error |
| `502` | Downstream Kleinanzeigen request failed |
| `503` | Kleinanzeigen has temporarily blocked the host IP range (`error_category: "ip_banned"`) |

### IP block (503)

When the server's IP is temporarily blocked by Kleinanzeigen, every request returns:

```json
{
  "success": false,
  "error": "IP range temporarily blocked by Kleinanzeigen. All page fetches returned a block response. The restriction is temporary — try again in a few hours.",
  "error_category": "ip_banned"
}
```

Detection is based on the HTML response body (Kleinanzeigen sometimes returns the block page with HTTP 200 *and* with HTTP 403, so checking the status code alone is not reliable). The API checks both — it will never silently return empty results when a block is active.

The block is usually lifted within a few hours. See [Kleinanzeigen's own explanation](https://themen.kleinanzeigen.de/ip-eingeschraenkt/) for more detail.

---

## Configuration

All settings use the `APP_` environment variable prefix and can also be placed in a `.env` file in the project root.

| Variable | Default | Description |
|---|---|---|
| `APP_HTTP_TIMEOUT` | `15.0` | Per-request timeout in seconds |
| `APP_HTTP_MAX_RETRIES` | `3` | Retry count for transient network failures |
| `APP_HTTP_MAX_CONNECTIONS` | `50` | Total connection pool size |
| `APP_HTTP_MAX_KEEPALIVE_CONNECTIONS` | `20` | Keep-alive connections retained |
| `APP_PAGE_FETCH_CONCURRENCY` | `3` | Max pages fetched in parallel for a single request |
| `APP_RATE_LIMIT_ENABLED` | `false` | Enable per-IP rate limiting |
| `APP_RATE_LIMIT_REQUESTS` | `60` | Requests allowed per window |
| `APP_RATE_LIMIT_WINDOW_SECONDS` | `60` | Rate limit window size in seconds |
| `APP_CORS_ALLOW_ORIGINS` | `["*"]` | Allowed CORS origins (JSON array) |
| `APP_CACHE_TTL_SECONDS` | `60` | In-memory cache TTL for listing searches |
| `APP_CACHE_TTL_DETAIL_SECONDS` | `300` | In-memory cache TTL for single listing detail |
| `APP_LOGGING_CONSOLE_LEVEL` | `INFO` | Console log level |
| `APP_LOGGING_FILE_LEVEL` | `DEBUG` | File log level (rotates at 100 MB, kept 10 days) |
| `APP_LOGGING_APP_NAME` | `kleinanzeigen-api` | Log file name prefix |
| `APP_DOCS_URL` | `/docs` | Swagger UI path (set to empty string to disable) |
| `APP_REDOC_URL` | `/redoc` | ReDoc path |

---

## Caching

The API uses an in-memory cache (process-local, not shared across workers). A response is cached per unique URL + query string combination.

- `/v1/listings` and `/v1/listings-detailed`: cached for `APP_CACHE_TTL_SECONDS` (default 60 s)
- `/v1/listings/{id}`: cached for `APP_CACHE_TTL_DETAIL_SECONDS` (default 300 s)

The cache is populated on first request and served instantly for subsequent identical requests within the TTL window. This significantly reduces load on Kleinanzeigen for repeated queries (e.g. polling or re-running the same search).

**Note on benchmarks:** The benchmark script runs 3 iterations per case. The first iteration is a cold network fetch; iterations 2 and 3 will hit the cache if they fall within the TTL window. The `min` column in the benchmark table typically represents a cache hit; `max` is the closest figure to a realistic cold-start time.

---

## Production Deployment

### Multiple Workers (Gunicorn)

```sh
gunicorn src.app.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 4 \
  --bind 0.0.0.0:8000 \
  --timeout 120
```

A good starting point is `(2 × CPU cores) + 1` workers. Note that the in-memory cache is **not shared** between workers — each worker maintains its own cache.

### Rate Limiting

Enable per-IP rate limiting to prevent a single client from exhausting your Kleinanzeigen request budget:

```env
APP_RATE_LIMIT_ENABLED=true
APP_RATE_LIMIT_REQUESTS=30
APP_RATE_LIMIT_WINDOW_SECONDS=60
```

### Disable Public Docs

```env
APP_DOCS_URL=
APP_REDOC_URL=
```

---

## Python Examples

### Basic search

```python
import requests

resp = requests.get(
    "http://localhost:8000/v1/listings",
    params={
        "query": "mini pc",
        "min_price": 10,
        "max_price": 350,
        "sort_by": "price",
        "page_count": 3,
    },
)
data = resp.json()
print(f"Found {data['data']['total_results']} listings")
print(f"Total available on site: {data['data']['pagination']['total_available_results']}")

for listing in data["data"]["results"]:
    print(f"{listing['title']}: {listing['price']} EUR")
```

### Paginated batch fetching

```python
import requests

def fetch_all_pages(query: str, batch_size: int = 5):
    all_listings = []
    page = 1

    while True:
        resp = requests.get(
            "http://localhost:8000/v1/listings",
            params={"query": query, "start_page": page, "page_count": batch_size},
        )
        data = resp.json()
        batch = data["data"]["results"]
        if not batch:
            break
        all_listings.extend(batch)
        page += batch_size

    return all_listings
```

### Fetch listing with full details

```python
import requests

resp = requests.get("http://localhost:8000/v1/listings/1641118170")
if resp.status_code == 404:
    print("Listing has expired")
else:
    detail = resp.json()["data"]
    print(f"{detail['title']} — {detail['price']['amount']} EUR")
    print(f"Views: {detail['views']}, Seller: {detail['seller']['name']}")
```

---

## Tips

- Use `raw_url` when you want to perform a search with specific categories or filters not directly exposed by the API (e.g., "Nur Abholung"). Simply configure your search in a web browser and copy-paste the resulting URL into the `raw_url` parameter.
- Use `start_page` with consistent `page_count` to paginate through large result sets without overlap.
- Check `pagination.duplicates_removed` — a non-zero value means the same listing appeared on multiple pages (common near the end of results).
- Use `pagination.total_available_results` to estimate how many pages exist: `ceil(total / 25)`.
- The API stops early if Kleinanzeigen redirects to the homepage (no more pages), so requesting `page_count=10` for a query with only 2 pages is safe.
- Lower `max_concurrent_details` if you receive connection errors from `/v1/listings-detailed`.
- Logs are written to `logs/kleinanzeigen-api_YYYYMMDD.log` and rotate at 100 MB.
