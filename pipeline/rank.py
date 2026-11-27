"""Score new items: noise or not, topic, region, importance, why-it-matters, story grouping.

Uses Claude when ANTHROPIC_API_KEY (or another Anthropic credential) is available.
`offline_score` is a crude keyword fallback used for tests and dry runs.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .fetch import Item

PROFILE = (Path(__file__).parent / "profile.md").read_text(encoding="utf-8")

MODEL = os.environ.get("UUDISED_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("UUDISED_EFFORT", "low")
BATCH_SIZE = 40

TOPICS = ["ukraine-russia", "tech-ai", "estonia-politics", "economy", "security", "eu", "world", "science", "climate-energy", "culture", "other"]
REGIONS = ["estonia", "baltics-nordics", "europe", "world"]

SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "noise": {"type": "boolean"},
                    "topic": {"type": "string", "enum": TOPICS},
                    "region": {"type": "string", "enum": REGIONS},
                    "importance": {"type": "integer"},
                    "story": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["key", "noise", "topic", "region", "importance", "story", "why"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


def _feedback_block(skipped_titles: list[str], read_titles: list[str]) -> str:
    parts = []
    if skipped_titles:
        parts.append(
            "Karl recently marked these stories NOT INTERESTED. Treat similar items as lower importance or noise:\n"
            + "\n".join(f"- {t}" for t in skipped_titles[-40:])
        )
    if read_titles:
        parts.append(
            "Karl recently READ these stories (a mild signal of interest):\n"
            + "\n".join(f"- {t}" for t in read_titles[-40:])
        )
    return "\n\n".join(parts)


def llm_score(items: list[Item], existing: list[dict], skipped_titles: list[str], read_titles: list[str]) -> dict[str, dict]:
    import anthropic

    client = anthropic.Anthropic()
    feedback = _feedback_block(skipped_titles, read_titles)
    existing_txt = "\n".join(f"{s['id']}: {s['title']}" for s in existing) or "(none yet)"
    results: dict[str, dict] = {}

    for start in range(0, len(items), BATCH_SIZE):
        batch = items[start : start + BATCH_SIZE]
        payload = [
            {"key": it.key, "source": it.source, "lang": it.lang, "title": it.title, "excerpt": it.excerpt}
            for it in batch
        ]
        user = (
            (feedback + "\n\n" if feedback else "")
            + "Existing stories:\n"
            + existing_txt
            + "\n\nNew items (JSON):\n"
            + json.dumps(payload, ensure_ascii=False)
            + "\n\nReturn one entry per new item, same keys."
        )
        try:
            resp = client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                system=[{"type": "text", "text": PROFILE, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user}],
                output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            )
        except anthropic.RateLimitError as exc:
            print(f"  rate limited, skipping batch: {exc}", file=sys.stderr)
            continue
        except anthropic.APIStatusError as exc:
            print(f"  API error {exc.status_code}, skipping batch: {exc.message}", file=sys.stderr)
            continue
        except anthropic.APIConnectionError as exc:
            print(f"  connection error, skipping batch: {exc}", file=sys.stderr)
            continue

        if resp.stop_reason == "refusal":
            print("  batch refused, skipping", file=sys.stderr)
            continue
        text = next((b.text for b in resp.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            print(f"  bad JSON (stop_reason={resp.stop_reason}), skipping batch", file=sys.stderr)
            continue
        for row in data.get("items", []):
            row["importance"] = max(0, min(100, int(row.get("importance", 0))))
            results[row["key"]] = row
        u = resp.usage
        print(f"  scored {len(batch)} items (in={u.input_tokens}, cached={u.cache_read_input_tokens}, out={u.output_tokens})", file=sys.stderr)
    return results


# --- offline fallback -------------------------------------------------------

NOISE_WORDS = re.compile(
    r"\b(skandaal|kuritegu|politsei|avarii|õnnetus|kohus|tapmine|staar|kuulsus|horoskoop|retsept|küsitlus|reiting|otseblogi|"
    r"scandal|murder|police|crash|celebrity|horoscope|recipe|poll|live|as it happened|deal|sale|review|quiz)\b",
    re.I,
)
TOPIC_WORDS = {
    "ukraine-russia": r"ukrain|russia|venemaa|putin|zelensk|kremlin|kreml",
    "tech-ai": r"\bai\b|tehisintellekt|openai|anthropic|nvidia|chip|software|tarkvara|google|apple|microsoft",
    "estonia-politics": r"riigikogu|valitsus|minist|eelarve|koalitsioon|government|parliament|estonia",
    "economy": r"inflatsioon|majandus|intress|euribor|economy|inflation|interest rate|ecb|gdp|skp|börs|market",
}


def offline_score(items: list[Item], existing: list[dict], *_args) -> dict[str, dict]:
    results = {}
    for it in items:
        text = f"{it.title} {it.excerpt}"
        topic = next((t for t, rx in TOPIC_WORDS.items() if re.search(rx, text, re.I)), "other")
        noise = bool(NOISE_WORDS.search(text)) or topic == "other"
        region = "estonia" if it.lang == "et" or re.search(r"eesti|estonia", text, re.I) else "world"
        importance = {"ukraine-russia": 75, "tech-ai": 65, "estonia-politics": 60, "economy": 55}.get(topic, 30)
        if region == "estonia":
            importance += 5
        match = next(
            (s["id"] for s in existing if _overlap(s["title"], it.title) >= 0.5),
            f"new:{it.key}",
        )
        results[it.key] = {
            "key": it.key,
            "noise": noise,
            "topic": topic,
            "region": region,
            "importance": importance,
            "story": match,
            "why": f"(offline) {topic.replace('-', ' ')} story from {it.source}.",
        }
    return results


def _overlap(a: str, b: str) -> float:
    wa = {w for w in re.findall(r"\w{4,}", a.lower())}
    wb = {w for w in re.findall(r"\w{4,}", b.lower())}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))
