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
        "mechanism": "GoMag embedded JSON (product pages only, no search)",
        "supports_search": False,
        "color": "#8b5cf6",
    },
    {
        "id": "caruselulcuvise",
        "name": "CaruselulCuVise",
        "url": "https://www.caruselulcuvise.ro",
        "mechanism": "GoMag embedded JSON (product pages only, no search)",
        "supports_search": False,
        "color": "#f59e0b",
    },
    {
        "id": "emag",
        "name": "eMAG",
        "url": "https://www.emag.ro",
        "mechanism": "Blocked — eMAG blocks automated scraping (403/captcha)",
        "supports_search": False,
        "color": "#6b7280",
    },
]


def _check_retailer_status(retailer_id: str) -> dict:
    """Quick health check — try to fetch the retailer's homepage."""
    import httpx

    retailer = next((r for r in RETAILERS if r["id"] == retailer_id), None)
    if not retailer:
        return {"status": "unknown", "error": "Not found"}

    try:
        resp = httpx.head(
            retailer["url"],
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=10,
            follow_redirects=True,
        )
        if resp.status_code < 400:
            return {"status": "ok", "response_ms": int(resp.elapsed.total_seconds() * 1000)}
        else:
            return {"status": "error", "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


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
