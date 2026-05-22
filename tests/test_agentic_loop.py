import json
import unittest

from pmc_agent.agentic_loop import AgenticAction, AgenticDecision, AgenticPmcLoop
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

    def get_inventory_snapshot(self, material_code=None):
        self.material_codes.append(material_code)
        return [
            InventorySnapshot(
                material_code=material_code or "UNKNOWN",
                on_hand=10,
                allocated=2,
                inbound=0,
                demand_next_7d=12,
                demand_next_30d=30,
            )
        ]


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


if __name__ == "__main__":
    unittest.main()
