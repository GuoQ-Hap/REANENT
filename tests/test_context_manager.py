import unittest

from pmc_agent.context_manager import ContextDecision, ContextManager, HeuristicContextDecisionClient, normalize_recent_context


class RecordingContextClient:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def decide_context(self, user_text, recent_context, metadata=None):
        self.calls.append((user_text, recent_context, metadata))
        return self.decision


class ContextManagerTests(unittest.TestCase):
    def test_normalize_recent_context_limits_and_sanitizes(self):
        raw = [{"role": "user", "content": str(i)} for i in range(10)]

        result = normalize_recent_context(raw)

        self.assertEqual(len(result), 8)
        self.assertEqual(result[0]["content"], "2")

    def test_manager_hides_context_when_none_available(self):
        client = RecordingContextClient(ContextDecision(use_context=True, selected_context=[{"role": "user", "content": "x"}]))
        manager = ContextManager(client)

        result = manager.select_context("你好", [])

        self.assertFalse(result.use_context)
        self.assertEqual(client.calls, [])

    def test_heuristic_context_client_detects_follow_up(self):
        manager = ContextManager(HeuristicContextDecisionClient())

        result = manager.select_context("这个风险呢", [{"role": "user", "content": "B0BXD4MCCK库存"}])

        self.assertTrue(result.use_context)
        self.assertIn("B0BXD4MCCK", result.selected_context[0]["content"])

    def test_heuristic_context_client_hides_context_for_explicit_code(self):
        manager = ContextManager(HeuristicContextDecisionClient())

        result = manager.select_context("B0BXD4MCCK这个有多少库存", [{"role": "user", "content": "A100库存"}])

        self.assertFalse(result.use_context)


if __name__ == "__main__":
    unittest.main()
