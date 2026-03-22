"""Vercel serverless function: list retailers with status and metadata."""

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Retailer metadata — static info about each supported retailer
RETAILERS = [
    {
        "id": "toysforkids",
        "name": "ToysForKids",
        "url": "https://www.toysforkids.ro",
        "mechanism": "HTML scraping (CS-Cart search + JSON-LD product pages)",
        "supports_search": True,
        "color": "#3b82f6",
    },
    {
        "id": "babyneeds",
        "name": "BabyNeeds",
        "url": "https://www.babyneeds.ro",
        "mechanism": "HTML scraping (custom search endpoint + JSON-LD/regex product pages)",
        "supports_search": True,
        "color": "#10b981",
    },
    {
        "id": "babymatters",
        "name": "BabyMatters",
        "url": "https://babymatters.ro",
        "mechanism": "Algolia instant search API + JSON-LD product pages",
        "supports_search": True,
        "color": "#f43f5e",
    },
    {
        "id": "erfi",
        "name": "ErFi",
        "url": "https://www.erfi.ro",
        "mechanism": "GoMag embedded JSON (search page URLs + product page data)",
        "supports_search": True,
        "color": "#8b5cf6",
    },
    {
        "id": "caruselulcuvise",
        "name": "CaruselulCuVise",
        "url": "https://www.caruselulcuvise.ro",
        "mechanism": "GoMag embedded JSON (search page URLs + product page data)",
        "supports_search": True,
        "color": "#f59e0b",
    },
    {
        "id": "emag",
        "name": "eMAG",
        "url": "https://www.emag.ro",
        "mechanism": "Playwright headless Chromium (price checking in GitHub Actions only)",
        "supports_search": False,
        "color": "#f59e0b",
    },
]


def _check_retailer_status(retailer_id: str) -> dict:
    """Real scrape test — search for a known product and verify we get results with prices."""
    from src.scrapers import SEARCHABLE_SCRAPERS, SCRAPERS

    retailer = next((r for r in RETAILERS if r["id"] == retailer_id), None)
    if not retailer:
        return {"status": "unknown", "error": "Not found"}

    # Find the scraper class for this retailer
    scraper_class = None
    for sc in SEARCHABLE_SCRAPERS:
        if sc.RETAILER_NAME == retailer["name"]:
            scraper_class = sc
            break

    if not scraper_class:
        # Scrape-only retailer (eMAG) — just check if site is reachable
        import httpx
        try:
            resp = httpx.head(retailer["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=10, follow_redirects=True)
            return {"status": "reachable", "detail": "Scrape-only (no search test)"}
        except Exception as e:
            return {"status": "error", "error": str(e)[:80]}

    # Test search with a known product
    try:
        scraper = scraper_class()
        results = scraper.search("Cybex Balios", max_results=3)
        if results:
            prices = [r.price for r in results if r.price]
            return {
                "status": "ok",
                "detail": f"{len(results)} products found, prices: {', '.join(str(int(p)) for p in prices[:3])} Lei",
            }
        else:
            return {"status": "warning", "detail": "Search returned 0 results"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:80]}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Return list of retailers with metadata. Add ?check=true for live status."""
        try:
            from urllib.parse import parse_qs, urlparse
            query = parse_qs(urlparse(self.path).query)
            do_check = "true" in query.get("check", [])

            result = []
            for r in RETAILERS:
                entry = {**r}
                if do_check:
                    entry["health"] = _check_retailer_status(r["id"])
                result.append(entry)

            self._json_response(200, {"retailers": result})
        except Exception as e:
            self._json_response(500, {"error": str(e)})

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
