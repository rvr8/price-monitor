"""BabyMatters.ro scraper — uses Algolia search API for search, JSON-LD for scraping."""

import json
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


class BabyMattersScraper(BaseScraper):
    """
    BabyMatters.ro scraper.
    Search: Algolia instant search API (public keys embedded in site).
    Scrape: JSON-LD structured data on product pages.
    """

    RETAILER_NAME = "BabyMatters"

    # Algolia credentials (public, embedded in babymatters.ro frontend)
    ALGOLIA_APP_ID = "VA5GVTEU38"
    ALGOLIA_API_KEY = "20eb4aba2767aff32880a15747f206fe"
    ALGOLIA_INDEX = "bbm_ro_live"
    ALGOLIA_URL = "https://{app_id}-dsn.algolia.net/1/indexes/{index}"

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search BabyMatters via Algolia API."""
        import httpx

        url = self.ALGOLIA_URL.format(app_id=self.ALGOLIA_APP_ID, index=self.ALGOLIA_INDEX)
        try:
            resp = httpx.get(
                url,
                params={"query": query, "hitsPerPage": max_results},
                headers={
                    "X-Algolia-Application-Id": self.ALGOLIA_APP_ID,
                    "X-Algolia-API-Key": self.ALGOLIA_API_KEY,
                },
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []

        results = []
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            product_url = hit.get("url", "")
            if not title or not product_url:
                continue

            # price_value is integer (e.g., 4684 = 4684 lei)
            price = None
            price_val = hit.get("price_value")
            if price_val:
                try:
                    price = float(price_val)
                except (ValueError, TypeError):
                    pass

            # rrp_price is string with dots (e.g., "5.389")
            original_price = None
            rrp = hit.get("rrp_price")
            if rrp:
                try:
                    original_price = float(str(rrp).replace(".", "").replace(",", "."))
                except (ValueError, TypeError):
                    pass

            # If original_price equals price, clear it
            if original_price and price and abs(original_price - price) < 1:
                original_price = None

            in_stock = hit.get("stock", 0) > 0
            image_url = hit.get("image")

            results.append(SearchResult(
                name=title,
                url=product_url,
                retailer=self.RETAILER_NAME,
                price=price,
                original_price=original_price,
                in_stock=in_stock,
                image_url=image_url,
            ))

        return results

    def scrape(self, url: str) -> ScrapeResult:
        """Scrape a BabyMatters product page for current price."""
        try:
            html = self.fetch(url)
        except Exception as e:
            return ScrapeResult(error=f"Fetch failed: {e}")

        result = ScrapeResult()
        soup = BeautifulSoup(html, "lxml")

        # Try JSON-LD first
        jsonld = self._extract_jsonld(soup)
        if jsonld:
            result.product_name = jsonld.get("name")
            result.image_url = jsonld.get("image")
            if isinstance(result.image_url, list):
                result.image_url = result.image_url[0] if result.image_url else None

            offers = jsonld.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}

            try:
                result.price = float(offers.get("price", 0)) or None
            except (ValueError, TypeError):
                result.price = None

            result.currency = offers.get("priceCurrency", "RON")

            avail = offers.get("availability", "")
            if avail:
                result.in_stock = "InStock" in avail

        # Fallback: HTML price elements
        if not result.price:
            price_el = soup.select_one(".product-price, .price, .current-price")
            if price_el:
                result.price = self.parse_romanian_price(price_el.get_text())

        if not result.product_name:
            h1 = soup.find("h1")
            if h1:
                result.product_name = h1.get_text(strip=True)

        # Original price
        if not result.original_price:
            old_price_el = soup.select_one(".old-price, .was-price, .rrp-price, del")
            if old_price_el:
                result.original_price = self.parse_romanian_price(old_price_el.get_text())

        if result.original_price and result.price and abs(result.original_price - result.price) < 1:
            result.original_price = None

        if not result.price:
            result.error = "Could not extract price"

        return result

    def _extract_jsonld(self, soup: BeautifulSoup) -> Optional[dict]:
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            return item
                elif data.get("@type") == "Product":
                    return data
            except json.JSONDecodeError:
                continue
        return None
