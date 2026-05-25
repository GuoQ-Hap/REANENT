import unittest
from datetime import datetime, time

from pmc_agent.memory.scheduler import _next_run_at, _parse_run_time


class MemorySchedulerTests(unittest.TestCase):
    def test_parse_run_time(self):
        self.assertEqual(_parse_run_time("18:30"), time(18, 30))

    def test_next_run_uses_today_when_future(self):
        now = datetime(2026, 5, 22, 17, 0)
        self.assertEqual(_next_run_at(now, time(18, 0)), datetime(2026, 5, 22, 18, 0))

    def test_next_run_moves_to_tomorrow_when_past(self):
        now = datetime(2026, 5, 22, 19, 0)
        self.assertEqual(_next_run_at(now, time(18, 0)), datetime(2026, 5, 23, 18, 0))


if __name__ == "__main__":
    unittest.main()
