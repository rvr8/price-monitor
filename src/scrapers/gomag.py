"""GoMag platform scraper — works for ErFi.ro, CaruselulCuVise.ro, and other GoMag stores.

GoMag embeds product JSON in page HTML. Search results pages also contain product
URLs and embedded JSON, even though visible content is JS-rendered via Releva."""

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


class GoMagScraper(BaseScraper):
    """Base scraper for GoMag-powered stores. Subclass to set RETAILER_NAME."""

    RETAILER_NAME = "GoMag"
    SEARCH_URL = ""  # Override in subclass: e.g. "https://www.erfi.ro/catalogsearch/result?q={query}"

    # Pattern to find start of GoMag product JSON objects
    _PRODUCT_START_RE = re.compile(r'\{"id":["\d]')

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search GoMag store: fetch search page, extract product URLs,
        filter by query words in URL slug, scrape matching pages for data."""
        if not self.SEARCH_URL:
            return []

        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = self.fetch(url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "lxml")

        # Extract product URLs from the page
        base_domain = self.SEARCH_URL.split("/catalogsearch")[0]
        seen = set()
        product_urls = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if (href.startswith(base_domain) and href.endswith(".html")
                    and "catalogsearch" not in href and "customer" not in href
                    and "checkout" not in href and href not in seen):
                seen.add(href)
                product_urls.append(href)

        # Filter URLs by query words in the slug
        query_words = [w.lower() for w in query.split() if len(w) > 2]
        matching_urls = []
        for purl in product_urls:
            slug = purl.split("/")[-1].lower()
            matches = sum(1 for w in query_words if w in slug)
            if matches >= max(2, len(query_words) // 2):
                matching_urls.append(purl)

        # Scrape only matching URLs (max 5 to stay within timeout)
        results = []
        for product_url in matching_urls[:min(max_results, 5)]:
            try:
                page_html = self.fetch(product_url)
                product_data = self._extract_gomag_json(page_html, product_url)
                if not product_data or not product_data.get("name") or not product_data.get("price"):
                    continue

                price = float(product_data["price"])
                original_price = None
                try:
                    base = float(product_data.get("basePrice", 0))
                    if base > price:
                        original_price = base
                except (ValueError, TypeError):
                    pass

                image = product_data.get("image", "").replace("\\/", "/")
                in_stock = product_data.get("stockStatus", "") in ("instock", "order")

                results.append(SearchResult(
                    name=product_data["name"].replace("\\/", "/"),
                    url=product_data.get("url", product_url).replace("\\/", "/"),
                    retailer=self.RETAILER_NAME,
                    price=price,
                    original_price=original_price,
                    in_stock=in_stock,
                    image_url=image if image else None,
                ))
            except Exception:
                continue

        return results

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
    SEARCH_URL = "https://www.erfi.ro/catalogsearch/result?q={query}"


class CaruselulCuViseScraper(GoMagScraper):
    RETAILER_NAME = "CaruselulCuVise"
    SEARCH_URL = "https://www.caruselulcuvise.ro/catalogsearch/result?q={query}"
