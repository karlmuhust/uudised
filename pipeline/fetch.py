"""Fetch candidate items from RSS feeds and the Guardian API."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

import feedparser

from .sources import EXCERPT_CHARS, SOURCES, USER_AGENT, Source

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclass
class Item:
    key: str
    source: str
    lang: str
    title: str
    url: str
    excerpt: str
    published: str  # ISO 8601 UTC, may be ""

    def to_dict(self) -> dict:
        return asdict(self)


def clean(text: str) -> str:
    return WS_RE.sub(" ", html.unescape(TAG_RE.sub(" ", text or ""))).strip()


def shorten(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = clean(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def canonical_url(url: str) -> str:
    parts = urllib.parse.urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in urllib.parse.parse_qsl(parts.query)
        if not k.lower().startswith(("utm_", "at_", "cmp", "ref"))
    ]
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc.lower(), parts.path, urllib.parse.urlencode(query), "")
    )


def item_key(url: str) -> str:
    return hashlib.sha1(canonical_url(url).encode()).hexdigest()[:16]


def _iso(struct_time) -> str:
    if not struct_time:
        return ""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", struct_time)


def _http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def parse_rss(source: Source, raw: bytes) -> list[Item]:
    feed = feedparser.parse(raw)
    items = []
    for e in feed.entries:
        link = e.get("link")
        title = clean(e.get("title", ""))
        if not link or not title:
            continue
        excerpt = shorten(e.get("summary", "")) if source.excerpt else ""
        items.append(
            Item(
                key=item_key(link),
                source=source.name,
                lang=source.lang,
                title=title,
                url=link,
                excerpt=excerpt,
                published=_iso(e.get("published_parsed") or e.get("updated_parsed")),
            )
        )
    return items


def parse_guardian(source: Source, raw: bytes) -> list[Item]:
    data = json.loads(raw)
    items = []
    for r in data.get("response", {}).get("results", []):
        url = r.get("webUrl")
        if not url:
            continue
        items.append(
            Item(
                key=item_key(url),
                source=source.name,
                lang=source.lang,
                title=clean(r.get("webTitle", "")),
                url=url,
                excerpt=shorten(r.get("fields", {}).get("trailText", "")),
                published=r.get("webPublicationDate", ""),
            )
        )
    return items


def guardian_url(source: Source, api_key: str) -> str:
    q = {
        "section": "world|technology|business|environment|science",
        "show-fields": "trailText",
        "page-size": "40",
        "order-by": "newest",
        "api-key": api_key,
    }
    return source.url + "?" + urllib.parse.urlencode(q)


def fetch_all(fixtures: Path | None = None) -> list[Item]:
    """Fetch every source. With `fixtures`, read <fixtures>/<slug>.xml|json instead of the network."""
    all_items: list[Item] = []
    for source in SOURCES:
        slug = re.sub(r"[^a-z0-9]+", "-", source.name.lower()).strip("-")
        try:
            if fixtures is not None:
                path = fixtures / (slug + (".json" if source.kind == "guardian" else ".xml"))
                if not path.exists():
                    continue
                raw = path.read_bytes()
            elif source.kind == "guardian":
                key = os.environ.get("GUARDIAN_API_KEY")
                if not key:
                    continue
                raw = _http_get(guardian_url(source, key))
            else:
                raw = _http_get(source.url)
            parser = parse_guardian if source.kind == "guardian" else parse_rss
            got = parser(source, raw)
            print(f"  {source.name}: {len(got)} items", file=sys.stderr)
            all_items.extend(got)
        except Exception as exc:  # one broken feed must not stop the run
            print(f"  {source.name}: FAILED ({exc})", file=sys.stderr)
    # de-duplicate by canonical URL
    seen: dict[str, Item] = {}
    for it in all_items:
        seen.setdefault(it.key, it)
    return list(seen.values())
