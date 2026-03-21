"""GoMag platform scraper — works for ErFi.ro, CaruselulCuVise.ro, and other GoMag stores.

GoMag embeds product JSON in the page HTML. Search results use Releva (JS-only),
so search() is not supported — only scrape() for individual product pages."""

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


class GoMagScraper(BaseScraper):
    """Base scraper for GoMag-powered stores. Subclass to set RETAILER_NAME."""

    RETAILER_NAME = "GoMag"

    # Pattern to find start of GoMag product JSON objects
    _PRODUCT_START_RE = re.compile(r'\{"id":["\d]')

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """GoMag stores use Releva for search (JS-rendered). Not supported via HTML scraping."""
        return []

    def scrape(self, url: str) -> ScrapeResult:
        """Scrape a GoMag product page by extracting the embedded JSON."""
        try:
            html = self.fetch(url)
        except Exception as e:
            return ScrapeResult(error=f"Fetch failed: {e}")

        result = ScrapeResult()

        # Strategy 1: Extract GoMag embedded product JSON
        product_data = self._extract_gomag_json(html, url)
        if product_data:
            result.product_name = product_data.get("name", "").replace("\\/", "/")
            try:
                result.price = float(product_data.get("price", 0)) or None
            except (ValueError, TypeError):
                result.price = None

            try:
                base = float(product_data.get("basePrice", 0))
                if base and result.price and base > result.price:
                    result.original_price = base
            except (ValueError, TypeError):
                pass

            result.currency = "RON"
            stock_status = product_data.get("stockStatus", "")
            result.in_stock = stock_status in ("instock", "order")

            img = product_data.get("image", "")
            if img:
                result.image_url = img.replace("\\/", "/")

        # Strategy 2: Fallback to HTML/meta tags
        if not result.price:
            soup = BeautifulSoup(html, "lxml")
            result = self._fallback_html(soup, result)

        if not result.price:
            result.error = "Could not extract price"

        return result

    def _extract_gomag_json(self, html: str, page_url: str) -> Optional[dict]:
        """Find the GoMag product JSON that matches the current page URL.
        Uses brace-balancing to extract complete JSON objects (they contain nested dicts)."""
        page_slug = page_url.rstrip("/").split("/")[-1].replace(".html", "").lower()

        candidates = []
        for m in self._PRODUCT_START_RE.finditer(html):
            obj = self._extract_balanced_json(html, m.start())
            if obj and obj.get("name") and obj.get("price") and obj.get("stockStatus"):
                candidates.append(obj)

        if not candidates:
            return None

        # Try to find the one matching the page URL slug
        for c in candidates:
            product_url = c.get("url", "").lower()
            if page_slug in product_url:
                return c

        # Fallback: return the first valid product
        return candidates[0]

    @staticmethod
    def _extract_balanced_json(html: str, start: int) -> Optional[dict]:
        """Extract a JSON object starting at 'start' by balancing braces."""
        depth = 0
        in_string = False
        escape = False
        for i in range(start, min(len(html), start + 15000)):
            c = html[i]
            if escape:
                escape = False
                continue
            if c == '\\' and in_string:
                escape = True
                continue
            if c == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(html[start:i + 1])
                    except json.JSONDecodeError:
                        return None
        return None

    def _fallback_html(self, soup: BeautifulSoup, result: ScrapeResult) -> ScrapeResult:
        """Fallback: extract from HTML meta tags and elements."""
        if not result.product_name:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                result.product_name = og_title.get("content", "")
            else:
                h1 = soup.find("h1")
                if h1:
                    result.product_name = h1.get_text(strip=True)

        if not result.image_url:
            og_img = soup.find("meta", property="og:image")
            if og_img:
                result.image_url = og_img.get("content", "")

        # Price from HTML
        if not result.price:
            for selector in [".product-price", ".price", ".special-price"]:
                el = soup.select_one(selector)
                if el:
                    result.price = self.parse_romanian_price(el.get_text())
                    if result.price:
                        break

        return result


class ErFiScraper(GoMagScraper):
    RETAILER_NAME = "ErFi"


class CaruselulCuViseScraper(GoMagScraper):
    RETAILER_NAME = "CaruselulCuVise"
