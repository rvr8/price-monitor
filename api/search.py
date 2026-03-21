"""Vercel serverless function: search all retailers for products."""

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

# Add project root to path so scrapers can be imported
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scrapers import search_all


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            query = body.get("query", "").strip()
            if not query or len(query) < 2:
                self._json_response(400, {"error": "Query must be at least 2 characters"})
                return

            groups = search_all(query)

            result = []
            for g in groups:
                result.append({
                    "normalized_name": g.normalized_name,
                    "best_price": g.best_price,
                    "max_price": g.max_price,
                    "count": g.count,
                    "in_stock_count": g.in_stock_count,
                    "retailers": g.retailers,
                    "best_image": g.best_image,
                    "items": [
                        {
                            "name": item.name,
                            "url": item.url,
                            "retailer": item.retailer,
                            "price": item.price,
                            "original_price": item.original_price,
                            "in_stock": item.in_stock,
                            "image_url": item.image_url,
                        }
                        for item in g.items
                    ],
                })

            self._json_response(200, {"groups": result})

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
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
