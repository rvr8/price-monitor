"""Vercel serverless function: update product settings (e.g. check frequency)."""

import json
import os
from base64 import b64decode, b64encode
from http.server import BaseHTTPRequestHandler

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "rvr8/price-monitor").strip()
DB_FILE_PATH = "docs/db.json"
VALID_FREQUENCIES = [6, 12, 24]


def _github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get_db_from_github():
    import httpx
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE_PATH}"
    resp = httpx.get(url, headers=_github_headers(), timeout=15)
    resp.raise_for_status()
    data = resp.json()
    content = b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]


def _put_db_to_github(db, sha, message):
    import httpx
    content = json.dumps(db, indent=2, ensure_ascii=False)
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DB_FILE_PATH}"
    resp = httpx.put(
        url,
        headers=_github_headers(),
        json={
            "message": message,
            "content": b64encode(content.encode("utf-8")).decode("ascii"),
            "sha": sha,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not GITHUB_TOKEN:
            self._json_response(500, {"error": "Server not configured: missing GITHUB_TOKEN"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_length)) if content_length else {}

            product_id = body.get("product_id", "").strip()
            frequency = body.get("check_frequency_hours")

            if not product_id:
                self._json_response(400, {"error": "product_id is required"})
                return
            if frequency not in VALID_FREQUENCIES:
                self._json_response(400, {"error": f"check_frequency_hours must be one of {VALID_FREQUENCIES}"})
                return

            db, sha = _get_db_from_github()

            product = next((p for p in db["products"] if p["id"] == product_id), None)
            if not product:
                self._json_response(404, {"error": f"Product '{product_id}' not found"})
                return

            product["check_frequency_hours"] = frequency

            _put_db_to_github(db, sha, f"settings: {product['name']} freq={frequency}h")

            self._json_response(200, {
                "status": "updated",
                "product_id": product_id,
                "check_frequency_hours": frequency,
            })

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
