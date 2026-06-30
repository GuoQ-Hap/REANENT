from __future__ import annotations

from datetime import date
import unittest

from pmc_agent.query_cache import DailyQueryCache, bottom_table_force_refresh


class DailyQueryCacheTests(unittest.TestCase):
    def test_reuses_value_until_forced_refresh(self):
        current_day = date(2026, 6, 25)
        cache = DailyQueryCache(today_fn=lambda: current_day)
        calls = 0

        def loader():
            nonlocal calls
            calls += 1
            return [{"value": calls}]

        self.assertEqual([{"value": 1}], cache.get_or_load("inventory", {"sku": "A100"}, loader))
        self.assertEqual([{"value": 1}], cache.get_or_load("inventory", {"sku": "A100"}, loader))
        with bottom_table_force_refresh(True):
            self.assertEqual([{"value": 2}], cache.get_or_load("inventory", {"sku": "A100"}, loader))
        self.assertEqual(2, calls)

    def test_expires_when_day_changes(self):
        current_day = [date(2026, 6, 25)]
        cache = DailyQueryCache(today_fn=lambda: current_day[0])
        calls = 0

        def loader():
            nonlocal calls
            calls += 1
            return [{"value": calls}]

        cache.get_or_load("sales", {"date": "2026-06-23"}, loader)
        current_day[0] = date(2026, 6, 26)

        self.assertEqual([{"value": 2}], cache.get_or_load("sales", {"date": "2026-06-23"}, loader))
        self.assertEqual(2, calls)

    def test_cache_hit_returns_copy(self):
        cache = DailyQueryCache(today_fn=lambda: date(2026, 6, 25))

        first = cache.get_or_load("pici", {"store": "US"}, lambda: [{"fnsku": "X001", "gap": -3}])
        first[0]["gap"] = 999

        self.assertEqual(
            [{"fnsku": "X001", "gap": -3}],
            cache.get_or_load("pici", {"store": "US"}, lambda: [{"fnsku": "X001", "gap": -4}]),
        )

    def test_snapshot_counts_hit_miss_refresh_and_stale_prune(self):
        current_day = [date(2026, 6, 25)]
        cache = DailyQueryCache(today_fn=lambda: current_day[0])
        calls = 0

        def loader():
            nonlocal calls
            calls += 1
            return [{"value": calls}]

        cache.get_or_load("inventory", {"sku": "A100"}, loader)
        cache.get_or_load("inventory", {"sku": "A100"}, loader)
        with bottom_table_force_refresh(True):
            cache.get_or_load("inventory", {"sku": "A100"}, loader)
        current_day[0] = date(2026, 6, 26)
        cache.get_or_load("sales", {"date": "2026-06-23"}, loader)

        snapshot = cache.snapshot()
        by_namespace = {row["namespace"]: row for row in snapshot["namespaces"]}

        self.assertEqual(1, by_namespace["inventory"]["hits"])
        self.assertEqual(1, by_namespace["inventory"]["misses"])
        self.assertEqual(1, by_namespace["inventory"]["refreshes"])
        self.assertEqual(2, by_namespace["inventory"]["writes"])
        self.assertEqual(1, by_namespace["inventory"]["stale_pruned"])
        self.assertEqual(1, by_namespace["sales"]["misses"])
        self.assertEqual(1, snapshot["entry_count"])

    def test_clear_and_reset_stats(self):
        cache = DailyQueryCache(today_fn=lambda: date(2026, 6, 25))
        cache.get_or_load("inventory", {"sku": "A100"}, lambda: [{"value": 1}])

        cache.clear()
        self.assertEqual(0, cache.snapshot()["entry_count"])
        self.assertEqual(1, cache.snapshot()["namespaces"][0]["misses"])

        cache.reset_stats()
        self.assertEqual([], cache.snapshot()["namespaces"])


if __name__ == "__main__":
    unittest.main()
