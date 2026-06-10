import unittest

from pmc_agent.agentic_loop import AgenticAction, AgenticDecision, AgenticRunResult, AgenticStep
from pmc_agent.config import InventoryPolicy
from pmc_agent.domain import AgentRunResult, ExecutionPlan, PlanStep, TaskRequest, TaskType
from pmc_agent.response_formatter import build_agent_result_ui, build_agentic_result_ui, format_agent_reply, strip_markdown_tables
from pmc_agent.tools.inventory import InventoryRiskTool, InventorySnapshotTool
from tests.fake_control_tower import FakeMainRuleConnector


class ResponseFormatterTests(unittest.TestCase):
    def test_reply_contains_meaning_headers_and_calculation_logic(self):
        connector = FakeMainRuleConnector()
        snapshots = InventorySnapshotTool(connector=connector).run(material_code="A100")
        decisions = InventoryRiskTool(policy=InventoryPolicy(), connector=connector).run(snapshots=snapshots)
        result = AgentRunResult(
            request=TaskRequest(text="检查 A100 是否有缺料风险", material_code="A100"),
            plan=ExecutionPlan(
                task_type=TaskType.INVENTORY_RISK,
                confidence=0.9,
                steps=[PlanStep("collect_inventory", "Collect inventory.", "inventory_snapshot")],
            ),
            decisions=decisions,
            verification=[],
        )

        reply = format_agent_reply(result)

        self.assertIn("当前总库存（FBA、海外仓、本地仓等库存合计）", reply)
        self.assertIn("预计 7 天后库存 = 可用库存 - 未来/近 7 天需求", reply)
        self.assertIn("**建议动作**", reply)

    def test_structured_ui_contains_fixed_tables(self):
        connector = FakeMainRuleConnector()
        snapshots = InventorySnapshotTool(connector=connector).run(material_code="A100")
        decisions = InventoryRiskTool(policy=InventoryPolicy(), connector=connector).run(snapshots=snapshots)
        result = AgentRunResult(
            request=TaskRequest(text="检查 A100 是否有缺料风险", material_code="A100"),
            plan=ExecutionPlan(task_type=TaskType.INVENTORY_RISK, confidence=0.9, steps=[]),
            decisions=decisions,
            verification=[],
        )

        ui = build_agent_result_ui(result)

        self.assertEqual(ui["tables"][0]["id"], "query_result")
        self.assertEqual(ui["tables"][0]["columns"][0]["label"], "物料编码")
        self.assertEqual(ui["tables"][0]["columns"][2]["meaning"], "FBA、海外仓、本地仓等库存合计")
        self.assertTrue(ui["calculations"])

    def test_agentic_ui_extracts_markdown_table(self):
        class Result:
            reply = "说明\n\n| 字段名称 | 字段说明 |\n|---|---|\n| msku | 物料编码 |\n\n计算逻辑\n1. 可用库存 = 总库存 - 占用"

        ui = build_agentic_result_ui(Result())

        self.assertEqual(ui["tables"][0]["columns"][0]["label"], "字段名称")
        self.assertEqual(ui["tables"][0]["rows"][0]["字段说明"], "物料编码")
        self.assertEqual(ui["calculations"], ["可用库存 = 总库存 - 占用"])
        self.assertNotIn("|---|", strip_markdown_tables(Result.reply))

    def test_agentic_ui_can_use_tool_observation_without_markdown_table(self):
        result = AgenticRunResult(
            ok=True,
            reply="已查询到库存结果。",
            model="test-model",
            steps=[
                AgenticStep(
                    iteration=1,
                    decision=AgenticDecision(action=AgenticAction.QUERY_INVENTORY_SNAPSHOT),
                    observation={"snapshots": [{"material_code": "A100", "warehouse": "IC-CA", "on_hand": 25}]},
                )
            ],
        )

        ui = build_agentic_result_ui(result)

        self.assertEqual(ui["tables"][0]["id"], "agentic_observation_result")
        self.assertEqual(ui["tables"][0]["rows"][0]["material_code"], "A100")

    def test_agentic_ui_prefers_observation_table_over_markdown_table(self):
        result = AgenticRunResult(
            ok=True,
            reply="说明\n\n| 物料编码 | 当前总库存 |\n|---|---|\n| A100 | 25 |\n\n计算逻辑\n1. 可用库存 = 总库存 - 占用",
            model="test-model",
            steps=[
                AgenticStep(
                    iteration=1,
                    decision=AgenticDecision(action=AgenticAction.QUERY_INVENTORY_SNAPSHOT),
                    observation={"snapshots": [{"material_code": "A100", "warehouse": "IC-CA", "on_hand": 25}]},
                )
            ],
        )

        ui = build_agentic_result_ui(result)

        self.assertEqual(len(ui["tables"]), 1)
        self.assertEqual(ui["tables"][0]["id"], "agentic_observation_result")
        self.assertEqual(ui["calculations"], ["可用库存 = 总库存 - 占用"])


if __name__ == "__main__":
    unittest.main()
