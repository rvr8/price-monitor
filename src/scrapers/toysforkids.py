import json
import re
from typing import Optional

from bs4 import BeautifulSoup

from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult


class ToysForKidsScraper(BaseScraper):
    """
    ToysForKids.ro scraper.
    Uses JSON-LD structured data (schema.org Product) — most reliable source.
    Fallback: span.ty-price elements in HTML.
    Search: CS-Cart dispatch URL with .ut2-gl__item cards.
    """

    RETAILER_NAME = "ToysForKids"
    SEARCH_URL = "https://www.toysforkids.ro/index.php?dispatch=products.search&search_performed=Y&q={query}"

    def search(self, query: str, max_results: int = 10) -> list[SearchResult]:
        """Search ToysForKids.ro for products matching query."""
        url = self.SEARCH_URL.format(query=query.replace(" ", "+"))
        try:
            html = self.fetch(url)
        except Exception:
            return []

        soup = BeautifulSoup(html, "lxml")
        results = []

        items = soup.select(".ut2-gl__item")
        for item in items[:max_results]:
            # Name + URL
            name_el = item.select_one("a.product-title")
            if not name_el:
                continue
            name = name_el.get_text(strip=True)
            product_url = name_el.get("href", "")
            if not name or not product_url:
                continue

            # Price
            price = None
            price_el = item.select_one(".ty-price-num, .ty-price")
            if price_el:
                price = self.parse_romanian_price(price_el.get_text())

            # Image
            img_el = item.select_one("img")
            image_url = None
            if img_el:
                image_url = img_el.get("data-src") or img_el.get("src")

            # Stock — assume in stock unless marked otherwise
            in_stock = True
            stock_el = item.select_one(".ty-qty-out-of-stock, .out-of-stock")
            if stock_el:
                in_stock = False

            results.append(SearchResult(
                name=name,
                url=product_url,
                retailer=self.RETAILER_NAME,
                price=price,
                in_stock=in_stock,
                image_url=image_url,
            ))

        return results

    def scrape(self, url: str) -> ScrapeResult:
        try:
            html = self.fetch(url)
        except Exception as e:
            return ScrapeResult(error=f"Fetch failed: {e}")

        result = ScrapeResult()
        soup = BeautifulSoup(html, "lxml")

        # Try JSON-LD first (most reliable)
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

        # Fallback: HTML elements
        if not result.price:
            result.price = self._extract_html_price(soup)

        if not result.product_name:
            result.product_name = self._extract_name(soup)

        if not result.image_url:
            result.image_url = self._extract_image(soup)

        # Original price (crossed-out / list price)
        result.original_price = self._extract_original_price(soup)

        # Stock fallback: check HTML if JSON-LD didn't have availability
        if not result.in_stock:
            # Add-to-cart button present = in stock
            cart_btn = soup.select_one('.ty-btn__add-to-cart, button[name*="checkout.add"]')
            if cart_btn:
                result.in_stock = True
            # "in stoc" text
            stock_el = soup.select_one('.ty-qty-in-stock, .ty-product-block__field-group')
            if stock_el and 'stoc' in stock_el.get_text(strip=True).lower():
                result.in_stock = True
            # Explicit out-of-stock marker overrides
            oos = soup.select_one('.ty-qty-out-of-stock, .ty-product-block__out-of-stock')
            if oos:
                result.in_stock = False

        # If original equals current, clear it
        if result.original_price and result.price and abs(result.original_price - result.price) < 0.01:
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

    def _extract_html_price(self, soup: BeautifulSoup) -> Optional[float]:
        # Current/sale price
        for selector in ["span.ty-price-num", "span.ty-price", ".ty-price-update"]:
            el = soup.select_one(selector)
            if el:
                price = self.parse_romanian_price(el.get_text())
                if price:
                    return price
        return None

    def _extract_original_price(self, soup: BeautifulSoup) -> Optional[float]:
        # Look for crossed-out / list price
        for selector in [".ty-list-price .ty-price-num", ".ty-list-price .ty-price",
                         ".ty-price-old .ty-price-num", "span.ty-strike"]:
            el = soup.select_one(selector)
            if el:
                price = self.parse_romanian_price(el.get_text())
                if price:
                    return price
        return None

    def _extract_name(self, soup: BeautifulSoup) -> Optional[str]:
        h1 = soup.find("h1", class_="ty-product-block-title")
        if h1:
            return h1.get_text(strip=True)
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return None

    def _extract_image(self, soup: BeautifulSoup) -> Optional[str]:
        meta = soup.find("meta", property="og:image")
        if meta:
            return meta.get("content")
        return None
