"""News sources Uudised reads.

Rules (see README): we only keep headline, link and a short excerpt.
Never store or show full article text.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    lang: str  # "et" or "en"
    excerpt: bool = True  # False = title + link only (e.g. Levila)
    kind: str = "rss"  # "rss" or "guardian"


SOURCES: list[Source] = [
    # Estonia
    Source("ERR", "https://www.err.ee/rss", "et"),
    Source("ERR News", "https://news.err.ee/rss", "en"),
    Source("Postimees", "https://www.postimees.ee/rss", "et"),  # robots: Crawl-delay 60; we fetch once per run
    Source("Äripäev", "https://www.aripaev.ee/rss", "et"),
    Source("Õhtuleht", "https://www.ohtuleht.ee/rss", "et"),
    Source("Levila", "https://admin.levila.ee/feed/", "et", excerpt=False),
    # International
    Source("BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml", "en"),
    Source("BBC Europe", "https://feeds.bbci.co.uk/news/world/europe/rss.xml", "en"),
    Source("BBC Business", "https://feeds.bbci.co.uk/news/business/rss.xml", "en"),
    Source("BBC Technology", "https://feeds.bbci.co.uk/news/technology/rss.xml", "en"),
    Source("The Guardian", "https://content.guardianapis.com/search", "en", kind="guardian"),
    # Tech
    Source("The Verge", "https://www.theverge.com/rss/index.xml", "en"),
    Source("Ars Technica", "https://feeds.arstechnica.com/arstechnica/index", "en"),
    Source("TechCrunch", "https://techcrunch.com/feed/", "en"),
]

USER_AGENT = "Uudised/0.1 (personal news reader; headlines and links only)"
EXCERPT_CHARS = 280
