from src.scrapers.base import BaseScraper, ScrapeResult, SearchResult, SearchResultGroup, normalize_product_name
from src.scrapers.emag import EmagScraper
from src.scrapers.babyneeds import BabyNeedsScraper
from src.scrapers.toysforkids import ToysForKidsScraper
from src.scrapers.babymatters import BabyMattersScraper
from src.scrapers.gomag import ErFiScraper, CaruselulCuViseScraper

SCRAPERS = {
    "emag.ro": EmagScraper,
    "www.emag.ro": EmagScraper,
    "babyneeds.ro": BabyNeedsScraper,
    "www.babyneeds.ro": BabyNeedsScraper,
    "toysforkids.ro": ToysForKidsScraper,
    "www.toysforkids.ro": ToysForKidsScraper,
    "babymatters.ro": BabyMattersScraper,
    "www.babymatters.ro": BabyMattersScraper,
    "erfi.ro": ErFiScraper,
    "www.erfi.ro": ErFiScraper,
    "caruselulcuvise.ro": CaruselulCuViseScraper,
    "www.caruselulcuvise.ro": CaruselulCuViseScraper,
}

# Scrapers that support search (eMAG blocked, so excluded)
SEARCHABLE_SCRAPERS = [
    BabyNeedsScraper,
    ToysForKidsScraper,
    BabyMattersScraper,
]


def get_scraper(url: str) -> BaseScraper:
    """Auto-detect retailer from URL and return the right scraper."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower()
    scraper_class = SCRAPERS.get(domain)
    if not scraper_class:
        raise ValueError(f"No scraper for domain: {domain}. Supported: emag.ro, babyneeds.ro, toysforkids.ro")
    return scraper_class()


def detect_retailer(url: str) -> str:
    """Return retailer name from URL."""
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower().replace("www.", "")
    names = {
        "emag.ro": "eMAG", "babyneeds.ro": "BabyNeeds", "toysforkids.ro": "ToysForKids",
        "babymatters.ro": "BabyMatters", "erfi.ro": "ErFi", "caruselulcuvise.ro": "CaruselulCuVise",
    }
    return names.get(domain, domain)


def search_all(query: str, max_results_per_retailer: int = 10) -> list[SearchResultGroup]:
    """Search all retailers for products matching query. Returns grouped results.
    Groups by normalized product name (color-agnostic)."""
    query_words = [w.lower() for w in query.split() if len(w) > 2]
    min_matches = max(2, len(query_words) // 2) if len(query_words) >= 2 else 1

    all_results = []
    for scraper_class in SEARCHABLE_SCRAPERS:
        scraper = scraper_class()
        try:
            results = scraper.search(query, max_results=max_results_per_retailer)
            for r in results:
                name_lower = r.name.lower()
                matches = sum(1 for w in query_words if w in name_lower)
                if matches >= min_matches:
                    all_results.append(r)
        except Exception:
            continue

    # Group by normalized name
    groups: dict[str, SearchResultGroup] = {}
    for r in all_results:
        key = r.normalized_name.lower()
        if key not in groups:
            groups[key] = SearchResultGroup(normalized_name=r.normalized_name)
        groups[key].items.append(r)

    # Sort each group's items by price
    for g in groups.values():
        g.items.sort(key=lambda r: r.price if r.price else float('inf'))

    # Sort groups by best price
    result = sorted(groups.values(), key=lambda g: g.best_price if g.best_price else float('inf'))
    return result
