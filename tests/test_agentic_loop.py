import json
import unittest
from datetime import date
from decimal import Decimal

from pmc_agent.agentic_loop import AgenticAction, AgenticDecision, AgenticPmcLoop, _parse_agentic_decision_response
from pmc_agent.domain import InventorySnapshot


class FakePlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.QUERY_INVENTORY_SNAPSHOT,
                arguments={"material_code": "B0BXD4MCCK"},
                reasoning_summary="Need inventory snapshot first.",
            )
        if self.calls == 2:
            return AgenticDecision(
                action=AgenticAction.EVALUATE_INVENTORY_RISK,
                reasoning_summary="Snapshot is available; calculate risk.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="B0BXD4MCCK 当前库存风险已完成判断。",
            reasoning_summary="Enough evidence to answer.",
        )


class FakeDbConnector:
    def __init__(self):
        self.material_codes = []
        self.query_specs = []

    def get_inventory_snapshot(self, material_code=None, field_pack=None, query_spec=None):
        self.material_codes.append(material_code)
        self.query_specs.append(query_spec)
        return [
            InventorySnapshot(
                material_code=material_code or "UNKNOWN",
                on_hand=10,
                allocated=2,
                inbound=0,
                demand_next_7d=12,
                demand_next_30d=30,
                metadata={"decimal_value": Decimal("12.50"), "snapshot_date": date(2026, 5, 22)},
            )
        ]


class AgenticFunctionCallParsingTests(unittest.TestCase):
    def test_parse_business_function_call_as_decision(self):
        response = {
            "output": [
                {
                    "type": "function_call",
                    "name": "query_inventory_snapshot",
                    "arguments": json.dumps(
                        {
                            "material_code": "B0BXD4MCCK",
                            "field_pack": "inventory_snapshot",
                            "reasoning_summary": "Need the snapshot first.",
                        }
                    ),
                }
            ]
        }

        decision = _parse_agentic_decision_response(response)

        self.assertEqual(decision.action, AgenticAction.QUERY_INVENTORY_SNAPSHOT)
        self.assertEqual(decision.arguments["material_code"], "B0BXD4MCCK")
        self.assertEqual(decision.reasoning_summary, "Need the snapshot first.")
        self.assertNotIn("reasoning_summary", decision.arguments)

    def test_quota_marker_only_is_clear_error(self):
        response = {
            "output": [
                {
                    "type": "function_call",
                    "name": "quota_soft_limit_marker",
                    "arguments": "{}",
                }
            ]
        }

        with self.assertRaisesRegex(ValueError, "quota_soft_limit_marker"):
            _parse_agentic_decision_response(response)


class LoopingPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if metadata and metadata.get("forced_summary"):
            return AgenticDecision(
                action=AgenticAction.FINAL_ANSWER,
                final_text="已根据前面步骤做最终总结。",
                reasoning_summary="Summarized after loop limit.",
            )
        return AgenticDecision(
            action=AgenticAction.EVALUATE_INVENTORY_RISK,
            reasoning_summary="Keep trying without final answer.",
        )


class MissingMaterialThenCorrectPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.QUERY_INVENTORY_SNAPSHOT,
                arguments={},
                reasoning_summary="Incorrectly omitted material code.",
            )
        if self.calls == 2:
            return AgenticDecision(
                action=AgenticAction.QUERY_INVENTORY_SNAPSHOT,
                arguments={"material_code": "B0BXD4MCCK"},
                reasoning_summary="Use the material code from the user request.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="B0BXD4MCCK 已按模型返回的编码查询。",
            reasoning_summary="Enough evidence to answer.",
        )


class ContextCheckingPlanner:
    def __init__(self):
        self.last_messages = []
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        self.last_messages = messages
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.DECIDE_CONTEXT,
                arguments={"use_context": True, "context_limit": 8},
                reasoning_summary="Follow-up needs hidden context.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="已基于上一轮物料继续处理。",
            reasoning_summary="Recent context is available.",
        )


class EmptyAskUserPlanner:
    def decide_next(self, messages, metadata=None):
        return AgenticDecision(
            action=AgenticAction.ASK_USER,
            final_text="",
            reasoning_summary="需要确认是查询 B0BXD4MCCK 的全链路还是整体组合。",
        )


class SerialSpacePlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.RUN_SERIAL_SPACE,
                arguments={
                    "tasks": [
                        {
                            "kind": "tool",
                            "action": AgenticAction.QUERY_INVENTORY_SNAPSHOT.value,
                            "arguments": {"material_code": "B0BXD4MCCK"},
                        },
                        {
                            "kind": "tool",
                            "action": AgenticAction.EVALUATE_INVENTORY_RISK.value,
                            "arguments": {},
                        },
                    ]
                },
                reasoning_summary="Run inventory lookup and risk evaluation in one controlled serial space.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="串行空间已完成库存查询和风险判断。",
            reasoning_summary="Enough evidence to answer.",
        )


class ParallelSubBehaviorPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.RUN_SERIAL_SPACE,
                arguments={
                    "tasks": [
                        {
                            "kind": "parallel",
                            "tasks": [
                                {"kind": "model_behavior", "behavior": "summary", "prompt": "总结库存观察"},
                                {"kind": "model_behavior", "behavior": "business_explanation", "prompt": "解释业务影响"},
                            ],
                        }
                    ]
                },
                reasoning_summary="Ask two sub models to work independently.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="子模型并行处理完成。",
            reasoning_summary="Enough evidence to answer.",
        )


class SerialSpaceWithEmptyParallelFieldsPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.RUN_SERIAL_SPACE,
                arguments={
                    "tasks": [
                        {
                            "kind": "tool",
                            "action": AgenticAction.QUERY_INVENTORY_SNAPSHOT.value,
                            "arguments": {"material_code": "B0BXD4MCCK"},
                            "parallel": [],
                            "tasks": [],
                            "subtasks": [],
                        },
                        {
                            "kind": "tool",
                            "action": AgenticAction.EVALUATE_INVENTORY_RISK.value,
                            "arguments": {},
                            "parallel": [],
                            "tasks": [],
                            "subtasks": [],
                        },
                    ]
                },
                reasoning_summary="Schema may include empty list fields; they must not turn tools into parallel groups.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="空 parallel 字段未影响串行工具执行。",
            reasoning_summary="Enough evidence to answer.",
        )


class PortfolioHotRiskPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.QUERY_INVENTORY_SNAPSHOT,
                arguments={
                    "material_code": "",
                    "scope": "portfolio",
                    "field_pack": "inventory_risk",
                    "filters": {
                        "sales_property": "爆",
                        "risk_only": True,
                        "positive_demand": True,
                        "order_by": "risk_then_demand",
                    },
                },
                reasoning_summary="Query hot items with shortage risk.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="已查询爆款断货风险。",
            reasoning_summary="Enough evidence to answer.",
        )


class FakeSubBehaviorClient:
    def __init__(self):
        self.calls = []

    def run_behavior(self, behavior, prompt, context, model=None, metadata=None):
        self.calls.append((behavior, prompt, model))
        return {"ok": True, "behavior": behavior, "model": model or f"{behavior}-model", "output": f"{behavior}:{prompt}"}


class FakeKnowledgeTool:
    def __init__(self):
        self.queries = []

    def run(self, query="", **kwargs):
        self.queries.append(query)
        return [{"title": "采购校验规则", "content": "按 MOQ、箱规和需求规则复核。"}]


class FakeGraphMetadataTool:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "mode": kwargs["query_type"],
            "table_name": kwargs.get("table_name", ""),
            "fields": [
                {
                    "table": kwargs.get("table_name", ""),
                    "field": "fnsku",
                    "comment": "FNSKU",
                    "concepts": ["FNSKU"],
                }
            ],
            "row_count": 1,
        }


class FakeMemoryLookupTool:
    def __init__(self):
        self.calls = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "mode": "memory_lookup",
            "query": kwargs.get("query", ""),
            "memories": [{"summary": "采购建议需要展示 MOQ 和人工确认边界。"}],
            "memory_count": 1,
        }


class KnowledgeLookupPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.KNOWLEDGE_LOOKUP,
                arguments={"query": "采购校验规则"},
                reasoning_summary="Need SOP knowledge before answering.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="已检索采购校验规则并完成回答。",
            reasoning_summary="Knowledge snippets are enough.",
        )


class MemoryLookupPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.MEMORY_LOOKUP,
                arguments={"query": "采购建议偏好 MOQ 人工确认", "limit": 5},
                reasoning_summary="Need durable preferences before answering.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="已按长期记忆补充 MOQ 和人工确认边界。",
            reasoning_summary="Memory is enough.",
        )


class GraphMetadataPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.GRAPH_METADATA_LOOKUP,
                arguments={
                    "query_type": "describe_table",
                    "table_name": "dwd_lingxing_fba_warehouse_detail",
                    "limit": 20,
                },
                reasoning_summary="Need table fields from Neo4j metadata graph.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="已查询 FBA 库存明细表字段。",
            reasoning_summary="Graph metadata is enough.",
        )


class SelfReviewRetryPlanner:
    def __init__(self):
        self.calls = 0
        self.trace_payload = None

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if self.calls == 1:
            return AgenticDecision(
                action=AgenticAction.QUERY_INVENTORY_SNAPSHOT,
                arguments={"material_code": "B0BXD4MCCK"},
                reasoning_summary="Need data first.",
            )
        if self.calls == 2:
            return AgenticDecision(
                action=AgenticAction.FINAL_ANSWER,
                arguments={"self_review_passed": False, "review_notes": "缺少风险判断步骤。"},
                final_text="草稿：库存没问题。",
                reasoning_summary="Self review rejected the draft.",
            )
        if self.calls == 3:
            return AgenticDecision(
                action=AgenticAction.INSPECT_RUN_TRACE,
                arguments={"include_prompts": True, "include_observations": True, "review_notes": "查看失败草稿和路径。"},
                reasoning_summary="Inspect path before retry.",
            )
        if self.calls == 4:
            self.trace_payload = json.loads(messages[-1]["content"])
            return AgenticDecision(
                action=AgenticAction.EVALUATE_INVENTORY_RISK,
                reasoning_summary="Retry with the missing risk calculation.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text="已重新尝试并补充风险判断。",
            reasoning_summary="Self review passed after retry.",
        )


class AlwaysFailingSelfReviewPlanner:
    def __init__(self):
        self.calls = 0

    def decide_next(self, messages, metadata=None):
        self.calls += 1
        if metadata and metadata.get("forced_summary"):
            return AgenticDecision(
                action=AgenticAction.FINAL_ANSWER,
                final_text="达到轮次上限，基于失败草稿做保守总结。",
                reasoning_summary="Forced summary.",
            )
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            arguments={"self_review_passed": False, "review_notes": "仍不满足证据要求。"},
            final_text="失败草稿",
            reasoning_summary="Self review failed.",
        )


class AgenticLoopTests(unittest.TestCase):
    def test_model_decides_actions_before_tools_run(self):
        planner = FakePlanner()
        db = FakeDbConnector()
        loop = AgenticPmcLoop(planner=planner, model="test-model", db_connector=db)

        result = loop.run("B0BXD4MCCK 这个库存还有多少")

        self.assertTrue(result.ok)
        self.assertEqual(db.material_codes, ["B0BXD4MCCK"])
        self.assertEqual([step.decision.action for step in result.steps], [
            AgenticAction.QUERY_INVENTORY_SNAPSHOT,
            AgenticAction.EVALUATE_INVENTORY_RISK,
            AgenticAction.FINAL_ANSWER,
        ])
        self.assertIn("B0BXD4MCCK", result.reply)

    def test_loop_limit_asks_model_for_final_summary(self):
        planner = LoopingPlanner()
        loop = AgenticPmcLoop(planner=planner, model="test-model", max_iterations=2)

        result = loop.run("总结当前库存风险")

        self.assertTrue(result.ok)
        self.assertEqual(result.error, "max_iterations_reached")
        self.assertEqual(planner.calls, 3)
        self.assertEqual(result.steps[-1].decision.action, AgenticAction.FINAL_ANSWER)
        self.assertIn("最终总结", result.reply)

    def test_missing_model_material_argument_does_not_query_portfolio(self):
        planner = MissingMaterialThenCorrectPlanner()
        db = FakeDbConnector()
        loop = AgenticPmcLoop(planner=planner, model="test-model", db_connector=db)

        result = loop.run("B0BXD4MCCK这个库存有风险吗")

        self.assertTrue(result.ok)
        self.assertEqual(db.material_codes, ["B0BXD4MCCK"])
        self.assertFalse(result.steps[0].observation["ok"])
        self.assertEqual(result.steps[0].observation["error_type"], "MissingModelArgument")
        self.assertIn("B0BXD4MCCK", result.reply)

    def test_recent_context_is_sent_to_model(self):
        planner = ContextCheckingPlanner()
        loop = AgenticPmcLoop(planner=planner, model="test-model")

        result = loop.run("你能查一整个链路吗", recent_context=[{"role": "user", "content": "B0BXD4MCCK这个有多少库存"}])

        self.assertTrue(result.ok)
        first_user_payload = json.loads(planner.last_messages[1]["content"])
        self.assertTrue(first_user_payload["hidden_context_available"])
        self.assertNotIn("B0BXD4MCCK", planner.last_messages[1]["content"])
        self.assertIn("B0BXD4MCCK", planner.last_messages[-1]["content"])
        self.assertEqual(result.steps[0].decision.action, AgenticAction.DECIDE_CONTEXT)
        self.assertTrue(result.steps[0].observation["context_loaded"])

    def test_empty_ask_user_does_not_return_blank_reply(self):
        loop = AgenticPmcLoop(planner=EmptyAskUserPlanner(), model="test-model")

        result = loop.run("你能查一整个链路吗")

        self.assertTrue(result.ok)
        self.assertIn("需要确认", result.reply)

    def test_serial_space_runs_multiple_tool_subtasks_under_main_model_control(self):
        planner = SerialSpacePlanner()
        db = FakeDbConnector()
        loop = AgenticPmcLoop(planner=planner, model="test-model", db_connector=db)

        result = loop.run("B0BXD4MCCK 库存风险快速判断")

        self.assertTrue(result.ok)
        self.assertEqual(db.material_codes, ["B0BXD4MCCK"])
        self.assertEqual(result.steps[0].decision.action, AgenticAction.RUN_SERIAL_SPACE)
        self.assertEqual(result.steps[0].observation["mode"], "serial_space")
        self.assertEqual(result.steps[0].observation["subtask_count"], 2)
        self.assertEqual(result.steps[0].observation["decision_count"], 1)
        self.assertIn("串行空间", result.reply)

    def test_serial_space_ignores_empty_parallel_fields_on_tool_subtasks(self):
        planner = SerialSpaceWithEmptyParallelFieldsPlanner()
        db = FakeDbConnector()
        loop = AgenticPmcLoop(planner=planner, model="test-model", db_connector=db)

        result = loop.run("B0BXD4MCCK 库存风险快速判断")

        self.assertTrue(result.ok)
        self.assertEqual(db.material_codes, ["B0BXD4MCCK"])
        subtasks = result.steps[0].observation["subtasks"]
        self.assertEqual([item["kind"] for item in subtasks], ["tool", "tool"])
        self.assertNotIn("InvalidParallelGroup", json.dumps(subtasks))

    def test_portfolio_query_passes_controlled_filters_to_connector(self):
        db = FakeDbConnector()
        loop = AgenticPmcLoop(planner=PortfolioHotRiskPlanner(), model="test-model", db_connector=db)

        result = loop.run("现在哪些爆款可能断货")

        self.assertTrue(result.ok)
        self.assertEqual(db.material_codes, [None])
        self.assertEqual(db.query_specs[0].scope, "portfolio")
        self.assertEqual(db.query_specs[0].filters["sales_property"], "爆")
        self.assertTrue(db.query_specs[0].filters["risk_only"])
        self.assertEqual(result.steps[0].observation["filters"]["order_by"], "risk_then_demand")

    def test_serial_space_can_run_parallel_model_sub_behaviors(self):
        sub_behavior = FakeSubBehaviorClient()
        loop = AgenticPmcLoop(
            planner=ParallelSubBehaviorPlanner(),
            model="test-model",
            sub_behavior_client=sub_behavior,
        )

        result = loop.run("请快速拆分总结和业务解释")

        self.assertTrue(result.ok)
        self.assertEqual([call[0] for call in sub_behavior.calls], ["summary", "business_explanation"])
        group = result.steps[0].observation["subtasks"][0]
        self.assertEqual(group["kind"], "parallel_model_group")
        self.assertEqual(group["subtask_count"], 2)
        self.assertTrue(all(item["ok"] for item in group["subtasks"]))

    def test_knowledge_lookup_action_is_available_to_agentic_loop(self):
        knowledge_tool = FakeKnowledgeTool()
        loop = AgenticPmcLoop(
            planner=KnowledgeLookupPlanner(),
            model="test-model",
            knowledge_tool=knowledge_tool,
        )

        result = loop.run("采购校验规则是什么")

        self.assertTrue(result.ok)
        self.assertEqual(knowledge_tool.queries, ["采购校验规则"])
        self.assertEqual(result.steps[0].decision.action, AgenticAction.KNOWLEDGE_LOOKUP)
        self.assertEqual(result.steps[0].observation["snippet_count"], 1)

    def test_memory_lookup_action_is_available_to_agentic_loop(self):
        memory_tool = FakeMemoryLookupTool()
        loop = AgenticPmcLoop(
            planner=MemoryLookupPlanner(),
            model="test-model",
            memory_lookup_tool=memory_tool,
        )

        result = loop.run("采购建议按我之前的偏好来")

        self.assertTrue(result.ok)
        self.assertEqual(result.steps[0].decision.action, AgenticAction.MEMORY_LOOKUP)
        self.assertEqual(memory_tool.calls[0]["query"], "采购建议偏好 MOQ 人工确认")
        self.assertEqual(result.steps[0].observation["memory_count"], 1)

    def test_graph_metadata_lookup_action_is_available_to_agentic_loop(self):
        graph_tool = FakeGraphMetadataTool()
        loop = AgenticPmcLoop(
            planner=GraphMetadataPlanner(),
            model="test-model",
            graph_metadata_tool=graph_tool,
        )

        result = loop.run("dwd_lingxing_fba_warehouse_detail 这张表有哪些字段")

        self.assertTrue(result.ok)
        self.assertEqual(result.steps[0].decision.action, AgenticAction.GRAPH_METADATA_LOOKUP)
        self.assertEqual(graph_tool.calls[0]["query_type"], "describe_table")
        self.assertEqual(graph_tool.calls[0]["table_name"], "dwd_lingxing_fba_warehouse_detail")
        self.assertEqual(result.steps[0].observation["row_count"], 1)

    def test_graph_metadata_tool_normalizes_missing_concept_from_keyword(self):
        from pmc_agent.tools.graph_metadata import GraphMetadataTool

        class NormalizingGraphTool(GraphMetadataTool):
            def _execute(self, cypher, parameters):
                return [{"table": "demo", "matched_fields": ["fnsku"], "concept": parameters["concept"]}]

        result = NormalizingGraphTool().run(query_type="find_tables_by_concept", keyword="哪些表有FNSKU字段")

        self.assertEqual(result["concept"], "FNSKU")
        self.assertEqual(result["row_count"], 1)

    def test_self_review_failure_can_inspect_trace_and_retry_within_budget(self):
        planner = SelfReviewRetryPlanner()
        loop = AgenticPmcLoop(planner=planner, model="test-model", db_connector=FakeDbConnector(), max_iterations=6)

        result = loop.run("B0BXD4MCCK 库存风险")

        self.assertTrue(result.ok)
        self.assertEqual([step.decision.action for step in result.steps], [
            AgenticAction.QUERY_INVENTORY_SNAPSHOT,
            AgenticAction.FINAL_ANSWER,
            AgenticAction.INSPECT_RUN_TRACE,
            AgenticAction.EVALUATE_INVENTORY_RISK,
            AgenticAction.FINAL_ANSWER,
        ])
        self.assertTrue(result.steps[1].observation["self_review_failed"])
        self.assertEqual(result.steps[2].observation["mode"], "run_trace")
        self.assertEqual(result.steps[2].observation["remaining_iterations_after_this"], 3)
        self.assertIn("prompts", result.steps[2].observation)
        self.assertIn("failed_drafts", result.steps[2].observation)
        self.assertEqual(planner.trace_payload["observation"]["mode"], "run_trace")
        self.assertIn("重新尝试", result.reply)

    def test_repeated_self_review_failures_stay_inside_iteration_limit(self):
        planner = AlwaysFailingSelfReviewPlanner()
        loop = AgenticPmcLoop(planner=planner, model="test-model", max_iterations=2)

        result = loop.run("生成库存答复")

        self.assertTrue(result.ok)
        self.assertEqual(result.error, "max_iterations_reached")
        self.assertEqual(planner.calls, 3)
        self.assertEqual(len(result.steps), 3)
        self.assertTrue(result.steps[0].observation["self_review_failed"])
        self.assertTrue(result.steps[1].observation["self_review_failed"])


if __name__ == "__main__":
    unittest.main()
