import unittest

from pmc_agent.agentic_loop import AgenticAction, AgenticDecision, AgenticRunResult, AgenticStep
from pmc_agent.config import InventoryPolicy
from pmc_agent.domain import AgentRunResult, ExecutionPlan, PlanStep, TaskRequest, TaskType
from pmc_agent.response_formatter import _format_sku_diagnosis, build_agent_result_ui, build_agentic_result_ui, format_agent_reply, strip_markdown_tables
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

    def test_sku_diagnosis_formatter_includes_ai_capability_sections(self):
        reply = _format_sku_diagnosis(
            {
                "material_code": "SKU-1",
                "overall_status": "断货风险",
                "risk_level": "high",
                "suggested_action": "断货：核查在途；冗余：冻结SKU。",
                "inventory": {"findings": ["FBA可售 10。"]},
                "sales": {"findings": ["日均需求 4。"]},
                "stockout": {"findings": ["第 7 天断货。"]},
                "overstock": {"findings": []},
                "attribution": ["FBA前端短缺。"],
                "handling_logic": ["先保供。"],
                "logistics_plan": [],
                "replenishment_countdowns": [
                    {
                        "name": "补货倒计时1",
                        "action": "催FBA在途",
                        "formula": "可售天数1-FBA安全天数-FBA交付天数",
                        "countdown_days": -11.5,
                        "status": "已到动作点",
                    }
                ],
                "replenishment_recommendation": {
                    "sales_control": "控销方面：需要轻控销。",
                    "summary": "补货方面：加急空运 40件。",
                    "purchase": {"summary": "采购逻辑：下采购单草稿。", "suggested_purchase_quantity": 40},
                },
                "replenishment_cost_comparison": {
                    "rows": [{"channel": "urgent_air", "channel_label": "加急空运", "suggested_quantity": 40, "unit_shipping_cost_cny": 42.5, "estimated_cost_cny": 1700, "arrival_day": 10}],
                    "recommendation": "快船总成本最低。",
                },
                "root_cause_analysis": [{"cause": "物流/在途转化不及时", "evidence": "在途晚于缺口。", "recommendation": "催上架。"}],
                "sales_recommendation": {"sales_control": "控销方面：需要轻控销。", "stockout_projection": "预计第 7 天断货。", "ad_and_price_review": "缺少价格曲线。"},
                "potential_analysis": {"score": 58, "label": "中等潜力，稳态补货", "best_for_sales": "控缺口优先。"},
                "direction_recommendations": {
                    "sales": {
                        "summary": "销售方向：中等潜力，稳态补货。",
                        "sales_potential": {"score": 58, "label": "中等潜力，稳态补货", "weekly_sales_ad_ratio": 0.5, "sales_curve": "周度销量曲线上升。"},
                        "sales_performance": {
                            "actual_sales": 130,
                            "review_start_date": "2026-06-01",
                            "review_end_date": "2026-06-30",
                            "sales_curve": "周度销量连续上升。",
                            "sales_anomalies": [{"label": "销量持续增加", "reason": "最近 3 周销量连续上升。"}],
                        },
                        "stockout_and_sales_control": {"stockout_window": "预计第 7 天开始断货。", "control_quantity": 25, "control_days": 3, "recommendation": "控销方面：控 25 件。"},
                        "forecast_accuracy": {
                            "forecast_quantity": 100,
                            "actual_sales": 130,
                            "variance_percent": 30,
                            "recommendation": "销售预测：建议提高预测。",
                            "forecast_anomalies": [{"label": "预估异常", "reason": "前月对当前月预估偏差 30.0%。"}],
                        },
                        "skill_placeholders": [{"name": "sales_control_placeholder"}],
                    },
                    "logistics": {
                        "summary": "物流方向：检测到在途异常。",
                        "detected_anomalies": [{"cause": "物流/在途转化不及时", "evidence": "在途晚于缺口。", "recommendation": "催上架。"}],
                        "checks": ["检查 FBA 接收。"],
                    },
                    "plan": {
                        "summary": "计划方向：补货。",
                        "inventory_replenishment": {
                            "total_replenishment_quantity": 40,
                            "purchase": {"summary": "采购逻辑：下采购单草稿。", "suggested_purchase_quantity": 40},
                            "methods": [{"channel_label": "加急空运", "suggested_quantity": 40, "arrival_day": 10}],
                        },
                        "cost_comparison": {"recommendation": "快船总成本最低。"},
                        "skill_placeholders": [{"name": "purchase_order_placeholder"}],
                    },
                },
                "external_action_skills": [{"name": "purchase_order_placeholder", "owner": "采购", "implemented": False, "description": "记录采购建议草稿。"}],
                "remedies": [],
            }
        )

        self.assertIn("**销售方向**", reply)
        self.assertIn("**物流方向**", reply)
        self.assertIn("**计划方向**", reply)
        self.assertIn("**归因**", reply)
        self.assertIn("物流/在途转化不及时", reply)
        self.assertIn("控销 25 件 / 3 天", reply)
        self.assertIn("销售预测：建议提高预测", reply)
        self.assertIn("销量持续增加", reply)
        self.assertIn("前月对当前月预估偏差 30.0%", reply)
        self.assertIn("purchase_order_placeholder", reply)
        self.assertNotIn("**当前SKU建议**", reply)
        self.assertNotIn("**补货倒计时与采购逻辑**", reply)
        self.assertNotIn("**SKU潜力分析**", reply)


if __name__ == "__main__":
    unittest.main()
