import re
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult


class EmagScraper(BaseScraper):
    """
    eMAG.ro scraper.
    eMAG is a React SPA — product data is embedded in JavaScript variables, not in clean HTML.
    Strategy: extract from JS vars (EM.productFullPrice, EM.offer.price.current) via regex.
    Fallback: JSON-LD script tags, meta tags.
    """

    def scrape(self, url: str) -> ScrapeResult:
        try:
            html = self.fetch(url)
        except Exception as e:
            return ScrapeResult(error=f"Fetch failed: {e}")

        result = ScrapeResult()
        soup = BeautifulSoup(html, "lxml")

        # Product name
        result.product_name = self._extract_name(soup, html)
        result.image_url = self._extract_image(soup)

        # Price from JS variables
        result.price = self._extract_js_price(html, r'EM\.offer\.price\.current\s*=\s*["\']?([\d.]+)')
        if not result.price:
            result.price = self._extract_js_price(html, r'"sale_price"\s*:\s*"?([\d.]+)')

        # Original price
        result.original_price = self._extract_js_price(html, r'EM\.productFullPrice\s*=\s*["\']?([\d.]+)')
        if not result.original_price:
            result.original_price = self._extract_js_price(html, r'"list_price"\s*:\s*"?([\d.]+)')

        # Fallback: meta tag
        if not result.price:
            meta = soup.find("meta", {"name": "product:price:amount"})
            if meta:
                result.price = self.parse_romanian_price(meta.get("content", ""))

        # Stock
        result.in_stock = self._check_stock(html, soup)

        if not result.price:
            result.error = "Could not extract price"

        return result

    def _extract_name(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        # Try page title
        h1 = soup.find("h1", class_="page-title")
        if h1:
            return h1.get_text(strip=True)
        title = soup.find("title")
        if title:
            text = title.get_text(strip=True)
            # Remove " - eMAG.ro" suffix
            return re.sub(r'\s*[-|]\s*eMAG\.ro$', '', text)
        return None

    def _extract_image(self, soup: BeautifulSoup) -> Optional[str]:
        meta = soup.find("meta", property="og:image")
        if meta:
            return meta.get("content")
        return None

    def _extract_js_price(self, html: str, pattern: str) -> Optional[float]:
        match = re.search(pattern, html)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _check_stock(self, html: str, soup: BeautifulSoup) -> bool:
        # JS variable
        match = re.search(r'"availability"\s*:\s*\{\s*"code"\s*:\s*"(\w+)"', html)
        if match:
            return match.group(1).lower() in ("in_stock", "instock", "available")
        # Schema.org
        match = re.search(r'"availability"\s*:\s*"[^"]*InStock"', html)
        if match:
            return True
        # Button check
        btn = soup.find("button", class_="yeahIWantIt")
        if btn:
            return True
        return False
