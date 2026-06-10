import unittest

from pmc_agent import PmcAgent
from pmc_agent.config import AgentConfig, InventoryPolicy
from pmc_agent.domain import GoalLoopStatus, TaskType
from pmc_agent.model import IntentAssessment
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


class FakeIntentModel:
    def __init__(self, task_type):
        self.task_type = task_type

    def assess_intent(self, request, recent_context=None):
        return IntentAssessment(
            task_type=self.task_type,
            confidence=0.9,
            user_expectation="test goal loop intent",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=False,
            risk_level="medium",
            reasoning_summary="semantic test fixture",
        )


class GoalLoopTests(unittest.TestCase):
    def test_goal_loop_completes_single_iteration_without_feedback(self):
        agent = _fake_agent(FakeIntentModel(TaskType.INVENTORY_RISK))

        result = agent.run_goal("检查 A100 是否有缺料风险")

        self.assertEqual(result.status, GoalLoopStatus.COMPLETED)
        self.assertEqual(len(result.iterations), 1)
        self.assertIn("task_type=inventory_risk", result.final_answer)
        self.assertIsNone(result.iterations[0].applied_feedback)

    def test_goal_loop_applies_feedback_to_next_iteration(self):
        agent = _fake_agent(FakeIntentModel(TaskType.PURCHASE_VERIFICATION))

        result = agent.run_goal("验证 A100 采购建议", feedback=["请按 MOQ 和人工确认边界重新检查"])

        self.assertEqual(result.status, GoalLoopStatus.COMPLETED)
        self.assertEqual(len(result.iterations), 2)
        self.assertEqual(result.iterations[1].applied_feedback, "请按 MOQ 和人工确认边界重新检查")
        self.assertIn("用户反馈", result.iterations[1].request_text)
        self.assertIn("上一轮观察", result.iterations[1].request_text)

    def test_goal_loop_stops_at_max_iterations(self):
        agent = _fake_agent(FakeIntentModel(TaskType.INVENTORY_RISK))

        result = agent.run_goal("检查 A100 是否有缺料风险", feedback=["补充条件一", "补充条件二", "补充条件三"], max_iterations=2)

        self.assertEqual(result.status, GoalLoopStatus.MAX_ITERATIONS_REACHED)
        self.assertEqual(len(result.iterations), 2)


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
