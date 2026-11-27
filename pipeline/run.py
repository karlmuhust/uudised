"""One Uudised update run.

1. Fetch candidate items from all sources.
2. Skip items already seen in earlier runs.
3. Score the new ones (Claude, or the offline heuristic).
4. Merge them into the story pool: same event -> same story card with several links.
5. Write site/data/stories.json, which the site reads.

The site shows the 20 highest-ranked stories Karl hasn't marked read or
"not interested". Unread stories never fade with age; they stay until read.

Usage:
    python -m pipeline.run                    # live fetch, Claude scoring
    python -m pipeline.run --offline          # live fetch, keyword scoring
    python -m pipeline.run --fixtures tests/fixtures --offline
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .fetch import Item, fetch_all
from .rank import llm_score, offline_score

ROOT = Path(__file__).resolve().parent.parent
STORIES_PATH = ROOT / "site" / "data" / "stories.json"
SEEN_PATH = ROOT / "data" / "seen.json"
STATE_PATH = ROOT / "data" / "state.json"  # written by pipeline/serve.py

MIN_IMPORTANCE = 35  # below this a story is not kept
FOLLOW_UP_MIN = 60  # a follow-up to an already-read story gets its own card only if this important
MAX_POOL = 600  # hard cap on stored stories (lowest-ranked read/dismissed go first)
READ_RETENTION_DAYS = 120  # read/dismissed stories are dropped from the pool after this
SEEN_RETENTION_DAYS = 30
GROUPING_WINDOW_DAYS = 21  # only stories updated this recently are offered for grouping
MAX_LINKS = 8


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def fetch_state() -> dict:
    """Karl's read / not-interested clicks, kept by the local server in data/state.json."""
    data = load_json(STATE_PATH, {})
    return {"read": data.get("read", {}), "dismissed": data.get("dismissed", {})}


def link_of(it: Item) -> dict:
    return {"source": it.source, "url": it.url, "title": it.title, "lang": it.lang, "published": it.published}


def merge(pool: dict[str, dict], items: list[Item], scores: dict[str, dict], state: dict, t: datetime) -> dict:
    stats = {"new_stories": 0, "updated": 0, "noise": 0, "low": 0}
    done = set(state["read"]) | set(state["dismissed"])
    new_groups: dict[str, str] = {}  # "new:label" -> story id created this run

    # most important first, so the strongest item becomes a new card's headline
    ordered = sorted(items, key=lambda it: -scores.get(it.key, {}).get("importance", 0))
    for it in ordered:
        s = scores.get(it.key)
        if s is None:
            continue
        if s["noise"]:
            stats["noise"] += 1
            continue
        if s["importance"] < MIN_IMPORTANCE:
            stats["low"] += 1
            continue

        target = s["story"]
        if target.startswith("new:") and target in new_groups:
            target = new_groups[target]
        story = pool.get(target)

        if story is not None and story["id"] in state["read"] and s["importance"] >= FOLLOW_UP_MIN and s["importance"] >= story["importance"] - 10:
            # an important development on a story Karl already read: give it its own card
            story_followed = story
            story = None
            follow_up_of = story_followed["id"]
        else:
            follow_up_of = None

        if story is not None:
            if all(l["url"] != it.url for l in story["links"]) and len(story["links"]) < MAX_LINKS:
                story["links"].append(link_of(it))
            story["importance"] = max(story["importance"], s["importance"])
            story["updated_at"] = iso(t)
            if story["id"] not in done:
                story["has_update"] = True
            stats["updated"] += 1
            continue

        sid = it.key
        pool[sid] = {
            "id": sid,
            "title": it.title,
            "excerpt": it.excerpt,
            "why": s["why"].strip(),
            "topic": s["topic"],
            "region": s["region"],
            "importance": s["importance"],
            "lang": it.lang,
            "first_seen": iso(t),
            "updated_at": iso(t),
            "has_update": False,
            "follow_up_of": follow_up_of,
            "links": [link_of(it)],
        }
        if s["story"].startswith("new:"):
            new_groups[s["story"]] = sid
        stats["new_stories"] += 1
    return stats


def prune(pool: dict[str, dict], state: dict, t: datetime) -> None:
    done_at = {**state["dismissed"], **state["read"]}
    cutoff = t - timedelta(days=READ_RETENTION_DAYS)
    for sid in list(pool):
        ts = done_at.get(sid)
        if ts and parse_iso(ts) < cutoff:
            del pool[sid]
    if len(pool) > MAX_POOL:
        # drop the least important finished stories first, then the least important unread ones
        ranked = sorted(pool.values(), key=lambda s: (s["id"] not in done_at, s["importance"], s["updated_at"]))
        for s in ranked[: len(pool) - MAX_POOL]:
            del pool[s["id"]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", type=Path, help="read feeds from this folder instead of the network")
    ap.add_argument("--offline", action="store_true", help="keyword scoring instead of Claude")
    ap.add_argument("--limit", type=int, default=300, help="max new items to score per run")
    args = ap.parse_args(argv)

    t = now()
    data = load_json(STORIES_PATH, {"stories": []})
    pool = {s["id"]: s for s in data.get("stories", [])}
    seen: dict[str, str] = load_json(SEEN_PATH, {})
    state = fetch_state()

    print("Fetching sources…", file=sys.stderr)
    items = fetch_all(args.fixtures)
    fresh = [it for it in items if it.key not in seen and it.key not in pool][: args.limit]
    print(f"{len(items)} items fetched, {len(fresh)} new", file=sys.stderr)

    if fresh:
        cutoff = iso(t - timedelta(days=GROUPING_WINDOW_DAYS))
        existing = sorted(
            (s for s in pool.values() if s["updated_at"] >= cutoff),
            key=lambda s: -s["importance"],
        )[:200]
        existing = [{"id": s["id"], "title": s["title"]} for s in existing]
        skipped = [pool[i]["title"] for i in sorted(state["dismissed"], key=state["dismissed"].get) if i in pool]
        read = [pool[i]["title"] for i in sorted(state["read"], key=state["read"].get) if i in pool]

        use_llm = not args.offline and (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
        scorer = llm_score if use_llm else offline_score
        print(f"Scoring with {'Claude' if use_llm else 'offline heuristic'}…", file=sys.stderr)
        scores = scorer(fresh, existing, skipped, read)

        stats = merge(pool, fresh, scores, state, t)
        print(f"Result: {stats}", file=sys.stderr)
        for it in fresh:
            if it.key in scores:  # unscored items (failed batch) get another chance next run
                seen[it.key] = iso(t)

    prune(pool, state, t)
    seen_cutoff = iso(t - timedelta(days=SEEN_RETENTION_DAYS))
    seen = {k: v for k, v in seen.items() if v >= seen_cutoff}

    stories = sorted(pool.values(), key=lambda s: (-s["importance"], s["first_seen"]))
    save_json(STORIES_PATH, {"generated_at": iso(t), "stories": stories})
    save_json(SEEN_PATH, seen)
    print(f"Wrote {len(stories)} stories to {STORIES_PATH.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
