import unittest
import time
import os
import zipfile
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from pmc_agent.agentic_loop import AgenticAction, AgenticDecision, AgenticRunResult, AgenticStep
from pmc_agent.config import AgentConfig, InventoryPolicy
from pmc_agent.orchestrator import PmcAgent
from pmc_agent.test_server import LLM_MODULES, SCENARIOS, TEST_TARGETS, _agentic_attachments, _append_attachment_links, _to_jsonable, get_model_options, get_monitored_chat_run, run_chat, run_llm_module, run_scenario, run_test_target, start_monitored_chat
from pmc_agent.tools import ToolRegistry
from pmc_agent.tools.inventory import (
    ControlTowerTool,
    ExceptionCaseTool,
    InventoryRiskTool,
    InventorySnapshotTool,
    KnowledgeLookupTool,
    PurchaseVerificationTool,
    ShipmentVerificationTool,
    ShortageTraceTool,
    SimpleChatTool,
    WeeklyShipmentPlanTool,
)
from tests.fake_control_tower import FakeMainRuleConnector


class TestServerTests(unittest.TestCase):
    def setUp(self):
        self._old_db_enabled = os.environ.get("STI_DB_ENABLED")
        os.environ["STI_DB_ENABLED"] = "false"
        self._create_default_patch = patch(
            "pmc_agent.test_server.PmcAgent.create_default",
            side_effect=lambda intent_model=None: _fake_agent(intent_model),
        )
        self._create_default_patch.start()

    def tearDown(self):
        self._create_default_patch.stop()
        if self._old_db_enabled is None:
            os.environ.pop("STI_DB_ENABLED", None)
        else:
            os.environ["STI_DB_ENABLED"] = self._old_db_enabled

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

    def test_to_jsonable_handles_database_decimal_and_date_values(self):
        result = _to_jsonable({"qty": Decimal("12.50"), "day": date(2026, 5, 22)})

        self.assertEqual(result, {"qty": 12.5, "day": "2026-05-22"})

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
        self.assertIn("| 物料编码", result["reply"])
        self.assertIn("**计算逻辑**", result["reply"])
        self.assertEqual(result["ui"]["tables"][0]["id"], "query_result")
        self.assertEqual(result["mode"], "local_heuristic")

    def test_run_chat_creates_excel_attachment_only_when_requested(self):
        normal = run_chat({"text": "检查 A100 是否有缺料风险"})
        with_attachment = run_chat({"text": "检查 A100 是否有缺料风险，并导出 Excel 附件"})

        self.assertNotIn("attachments", normal["result"]["artifacts"])
        attachments = with_attachment["result"]["artifacts"]["attachments"]
        self.assertTrue(attachments)
        self.assertIn("附件", with_attachment["reply"])
        path = attachments[0]["path"]
        self.assertTrue(zipfile.is_zipfile(path))

    def test_agentic_result_creates_excel_attachment_link_when_requested(self):
        result = AgenticRunResult(
            ok=True,
            reply="已查询到库存明细。",
            model="test-model",
            steps=[
                AgenticStep(
                    iteration=1,
                    decision=AgenticDecision(action=AgenticAction.QUERY_INVENTORY_SNAPSHOT),
                    observation={
                        "snapshots": [
                            {
                                "material_code": "A100",
                                "warehouse": "IC-CA",
                                "country": "加拿大",
                                "on_hand": Decimal("25"),
                                "sales_7d": Decimal("0.86"),
                            }
                        ],
                    },
                )
            ],
        )

        attachments = _agentic_attachments(result, "请导出 xlsx 下载", "unit_test_agentic_attachment")
        reply = _append_attachment_links(result.reply, attachments)

        self.assertTrue(attachments)
        self.assertIn("附件下载", reply)
        self.assertIn(attachments[0]["url"], reply)
        self.assertTrue(zipfile.is_zipfile(attachments[0]["path"]))

    def test_agentic_result_can_export_markdown_table_reply(self):
        result = AgenticRunResult(
            ok=True,
            reply="| 店铺 | 国家 | 可用库存 |\n|---|---|---|\n| IC-CA | 加拿大 | 25 |",
            model="test-model",
            steps=[
                AgenticStep(
                    iteration=1,
                    decision=AgenticDecision(action=AgenticAction.FINAL_ANSWER),
                    observation={"ok": True, "message": "final"},
                )
            ],
        )

        attachments = _agentic_attachments(result, "xlsx 下载", "unit_test_agentic_markdown_attachment")

        self.assertTrue(attachments)
        self.assertTrue(zipfile.is_zipfile(attachments[0]["path"]))

    def test_run_chat_greeting_does_not_run_agent(self):
        result = run_chat({"text": "你好"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["mode"], "local_heuristic")
        self.assertEqual(result["result"]["plan"]["task_type"], "simple_chat")
        self.assertIn("你好", result["reply"])

    def test_monitored_chat_exposes_runtime_events(self):
        started = start_monitored_chat({"text": "检查 A100 是否有缺料风险"})

        self.assertTrue(started["ok"])
        run_id = started["run_id"]
        status = get_monitored_chat_run(run_id)
        for _ in range(20):
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
            status = get_monitored_chat_run(run_id)

        self.assertEqual(status["status"], "completed")
        self.assertTrue(status["events"])
        event_names = [item["event"] for item in status["events"]]
        self.assertIn("route_started", event_names)
        self.assertIn("route_node_completed", event_names)
        self.assertIn("final_returned", event_names)
        self.assertIn("A100", status["result"]["reply"])


def _fake_agent(intent_model):
    connector = FakeMainRuleConnector()
    return PmcAgent(
        config=AgentConfig(),
        tools=ToolRegistry(
            {
                "inventory_snapshot": InventorySnapshotTool(connector=connector),
                "simple_chat": SimpleChatTool(),
                "inventory_risk": InventoryRiskTool(policy=InventoryPolicy(), connector=connector),
                "control_tower": ControlTowerTool(connector=connector),
                "shortage_trace": ShortageTraceTool(connector=connector),
                "shipment_verification": ShipmentVerificationTool(),
                "purchase_verification": PurchaseVerificationTool(),
                "weekly_shipment_plan": WeeklyShipmentPlanTool(),
                "exception_case": ExceptionCaseTool(),
                "knowledge_lookup": KnowledgeLookupTool(),
            }
        ),
        intent_model=intent_model,
    )


if __name__ == "__main__":
    unittest.main()
