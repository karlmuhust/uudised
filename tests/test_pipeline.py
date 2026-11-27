import unittest
from datetime import datetime, timezone

from pipeline.fetch import Item, canonical_url, shorten
from pipeline.run import merge, prune

T = datetime(2026, 11, 27, 12, tzinfo=timezone.utc)


def item(key, title="t", url=None):
    return Item(key=key, source="ERR", lang="et", title=title, url=url or f"https://x.test/{key}", excerpt="", published="")


def score(key, story, importance=70, noise=False):
    return {"key": key, "noise": noise, "topic": "economy", "region": "estonia", "importance": importance, "story": story, "why": "w"}


EMPTY = {"read": {}, "dismissed": {}}


class MergeTests(unittest.TestCase):
    def test_noise_and_low_importance_are_dropped(self):
        pool = {}
        stats = merge(pool, [item("a1"), item("b2")], {"a1": score("a1", "new:a", noise=True), "b2": score("b2", "new:b", 20)}, EMPTY, T)
        self.assertEqual(pool, {})
        self.assertEqual((stats["noise"], stats["low"]), (1, 1))

    def test_same_new_event_becomes_one_card_with_two_links(self):
        pool = {}
        merge(pool, [item("a1"), item("a2")], {"a1": score("a1", "new:x", 80), "a2": score("a2", "new:x", 60)}, EMPTY, T)
        self.assertEqual(list(pool), ["a1"])  # strongest item is the headline
        self.assertEqual(len(pool["a1"]["links"]), 2)

    def test_follow_up_joins_unread_story_and_flags_it(self):
        pool = {}
        merge(pool, [item("a1")], {"a1": score("a1", "new:x", 60)}, EMPTY, T)
        merge(pool, [item("a2")], {"a2": score("a2", "a1", 85)}, EMPTY, T)
        self.assertEqual(len(pool), 1)
        self.assertTrue(pool["a1"]["has_update"])
        self.assertEqual(pool["a1"]["importance"], 85)

    def test_important_follow_up_to_read_story_gets_own_card(self):
        pool = {}
        merge(pool, [item("a1")], {"a1": score("a1", "new:x", 70)}, EMPTY, T)
        state = {"read": {"a1": "2026-11-27T10:00:00Z"}, "dismissed": {}}
        merge(pool, [item("a2")], {"a2": score("a2", "a1", 75)}, state, T)
        self.assertIn("a2", pool)
        self.assertEqual(pool["a2"]["follow_up_of"], "a1")

    def test_minor_follow_up_to_dismissed_story_stays_hidden(self):
        pool = {}
        merge(pool, [item("a1")], {"a1": score("a1", "new:x", 70)}, EMPTY, T)
        state = {"read": {}, "dismissed": {"a1": "2026-11-27T10:00:00Z"}}
        merge(pool, [item("a2")], {"a2": score("a2", "a1", 75)}, state, T)
        self.assertEqual(list(pool), ["a1"])
        self.assertFalse(pool["a1"]["has_update"])

    def test_unread_stories_never_expire(self):
        pool = {"old": {"id": "old", "importance": 90, "updated_at": "2026-01-01T00:00:00Z"}}
        prune(pool, EMPTY, T)
        self.assertIn("old", pool)

    def test_long_read_stories_are_pruned(self):
        pool = {"old": {"id": "old", "importance": 90, "updated_at": "2026-01-01T00:00:00Z"}}
        prune(pool, {"read": {"old": "2026-01-02T00:00:00Z"}, "dismissed": {}}, T)
        self.assertNotIn("old", pool)


class FetchTests(unittest.TestCase):
    def test_tracking_params_removed(self):
        self.assertEqual(canonical_url("https://A.test/x?utm_source=rss&id=3"), "https://a.test/x?id=3")

    def test_excerpt_is_short_and_clean(self):
        out = shorten("<p>" + "sõna " * 200 + "</p>")
        self.assertLessEqual(len(out), 281)
        self.assertTrue(out.endswith("…"))


if __name__ == "__main__":
    unittest.main()
