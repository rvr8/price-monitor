"""Generic scraper — works on any site with JSON-LD Product data or embedded price JSON.

Used for retailers we don't have a specific scraper for. Attempts multiple
extraction strategies: JSON-LD, meta tags, embedded JSON, HTML selectors."""

import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


class GenericScraper(BaseScraper):
    """Universal product page scraper. Works on most e-commerce sites."""

    RETAILER_NAME = "Generic"

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        return []  # Generic scraper doesn't support search

    def scrape(self, url: str) -> ScrapeResult:
        try:
            html = self.fetch(url)
        except Exception as e:
            return ScrapeResult(error=f"Fetch failed: {e}")

        result = ScrapeResult()
        soup = BeautifulSoup(html, "lxml")

        # Strategy 1: JSON-LD
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

        # Strategy 2: Embedded JSON with "price" field
        if not result.price:
            price_match = re.search(r'"price"\s*:\s*"?(\d[\d.]*)"?', html)
            if price_match:
                try:
                    result.price = float(price_match.group(1))
                except ValueError:
                    pass

        # Strategy 3: Meta tags
        if not result.product_name:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                result.product_name = og_title.get("content", "")
        if not result.product_name:
            title = soup.find("title")
            if title:
                result.product_name = title.get_text(strip=True).split("|")[0].split("-")[0].strip()

        if not result.image_url:
            og_img = soup.find("meta", property="og:image")
            if og_img:
                result.image_url = og_img.get("content", "")

        # Strategy 4: Common price selectors
        if not result.price:
            for selector in [
                ".product-price", ".price", ".current-price", ".special-price",
                "[itemprop='price']", ".woocommerce-Price-amount",
                ".product-new-price", ".our-price", ".pret",
            ]:
                el = soup.select_one(selector)
                if el:
                    # Check for content attribute first (microdata)
                    price_val = el.get("content") or el.get_text()
                    result.price = self.parse_romanian_price(price_val)
                    if result.price:
                        break

        # Original price
        if not result.original_price:
            for selector in [".old-price", ".was-price", ".list-price", "del", ".price-old", ".pret-vechi"]:
                el = soup.select_one(selector)
                if el:
                    result.original_price = self.parse_romanian_price(el.get_text())
                    if result.original_price:
                        break

        if result.original_price and result.price and abs(result.original_price - result.price) < 1:
            result.original_price = None

        # Stock fallback
        if not result.in_stock:
            body_text = soup.get_text().lower()
            if "adaugă în coș" in body_text or "adauga in cos" in body_text or "add to cart" in body_text:
                result.in_stock = True
            if "indisponibil" in body_text or "stoc epuizat" in body_text:
                result.in_stock = False

        if not result.price:
            result.error = "Could not extract price"

        return result

    def _extract_jsonld(self, soup) -> Optional[dict]:
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
