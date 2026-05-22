import unittest

from pmc_agent.test_server import LLM_MODULES, SCENARIOS, TEST_TARGETS, get_model_options, run_chat, run_llm_module, run_scenario, run_test_target


class TestServerTests(unittest.TestCase):
    def test_test_targets_cover_current_modules(self):
        ids = {item["id"] for item in TEST_TARGETS}

        self.assertIn("all", ids)
        self.assertIn("planning", ids)
        self.assertIn("state", ids)
        self.assertIn("model_io", ids)
        self.assertIn("orchestrator", ids)

    def test_scenarios_cover_agent_task_types(self):
        ids = {item["id"] for item in SCENARIOS}

        self.assertIn("simple_chat", ids)
        self.assertIn("inventory_risk", ids)
        self.assertIn("shortage_trace", ids)
        self.assertIn("shipment_verification", ids)
        self.assertIn("purchase_verification", ids)
        self.assertIn("weekly_plan", ids)
        for item in SCENARIOS:
            self.assertTrue(item["expected_nodes"])

    def test_llm_modules_expose_standard_input(self):
        ids = {item["id"] for item in LLM_MODULES}

        self.assertIn("intent_recognition", ids)
        for item in LLM_MODULES:
            self.assertTrue(item["standard_input"]["text"])
            self.assertTrue(item["input_schema"])

    def test_model_options_have_default_model(self):
        result = get_model_options()

        self.assertTrue(result["default_model"])
        self.assertIn(result["default_model"], result["options"])

    def test_run_unknown_test_returns_error(self):
        result = run_test_target("missing")

        self.assertFalse(result["ok"])

    def test_run_unknown_llm_module_returns_error(self):
        result = run_llm_module("missing")

        self.assertFalse(result["ok"])

    def test_run_scenario_returns_state_history(self):
        result = run_scenario("inventory_risk")

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "fake_intent_model")
        self.assertTrue(result["state_check"]["ok"])
        self.assertTrue(result["result"]["state_history"])

    def test_run_scenario_fake_model_ignores_model_override(self):
        result = run_scenario("inventory_risk", model="custom-model")

        self.assertTrue(result["ok"])
        self.assertIsNone(result["model"])

    def test_run_chat_returns_reply(self):
        result = run_chat({"text": "检查 A100 是否有缺料风险"})

        self.assertTrue(result["ok"])
        self.assertIn("A100", result["reply"])
        self.assertEqual(result["mode"], "local_heuristic")

    def test_run_chat_greeting_does_not_run_agent(self):
        result = run_chat({"text": "你好"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "local_heuristic")
        self.assertEqual(result["result"]["plan"]["task_type"], "simple_chat")
        self.assertIn("你好", result["reply"])


if __name__ == "__main__":
    unittest.main()
