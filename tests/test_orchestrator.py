import unittest
import os

from pmc_agent import PmcAgent
from pmc_agent.config import AgentConfig
from pmc_agent.domain import TaskType
from pmc_agent.model import FailureHandlingDecision, IntentAssessment
from pmc_agent.state import RunStatus
from pmc_agent.tools import InventoryRiskTool, ToolRegistry


class FakeIntentModel:
    def __init__(self, task_type):
        self.task_type = task_type

    def assess_intent(self, request, recent_context=None):
        return IntentAssessment(
            task_type=self.task_type,
            confidence=0.9,
            user_expectation="test intent",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=False,
            risk_level="medium",
            reasoning_summary="semantic test fixture",
        )


class FakeFailureModel:
    def handle_failure(self, request, plan_task_type, failed_step, failed_tool, error, context=None):
        return FailureHandlingDecision(
            failure_type=type(error).__name__,
            user_message="没有查到这个物料，请补充真实 msku、sku 或 fnsku。",
            next_action="ask_user_for_input",
            needs_user_input=True,
            retryable=True,
            suggested_inputs=["msku", "sku", "fnsku"],
            reasoning_summary="test failure handling",
        )


class FailingSnapshotTool:
    name = "inventory_snapshot"
    description = "always fail"

    def run(self, **kwargs):
        raise LookupError("No inventory snapshot found in STI database for material_code=A100.")


class PmcAgentTests(unittest.TestCase):
    def setUp(self):
        self._old_db_enabled = os.environ.get("STI_DB_ENABLED")
        os.environ["STI_DB_ENABLED"] = "false"

    def tearDown(self):
        if self._old_db_enabled is None:
            os.environ.pop("STI_DB_ENABLED", None)
        else:
            os.environ["STI_DB_ENABLED"] = self._old_db_enabled

    def test_inventory_risk_request_produces_decision(self):
        result = PmcAgent.create_default(FakeIntentModel(TaskType.INVENTORY_RISK)).run("检查 A100 是否有缺料风险")

        self.assertEqual(result.plan.task_type, TaskType.INVENTORY_RISK)
        self.assertEqual(result.decisions[0].material_code, "A100")
        self.assertTrue(result.decisions[0].recommended_actions)
        self.assertTrue(result.verification)
        self.assertEqual(result.state_history[-1].to_status, RunStatus.COMPLETED)
        self.assertRegex(result.request.metadata["request_id"], r"^\d{8}_\d{6}_\d{6}$")

    def test_portfolio_request_handles_missing_material_code(self):
        result = PmcAgent.create_default(FakeIntentModel(TaskType.INVENTORY_RISK)).run("检查库存风险")

        self.assertEqual(result.plan.task_type, TaskType.INVENTORY_RISK)
        self.assertGreaterEqual(len(result.decisions), 2)
        self.assertTrue(result.plan.assumptions)

    def test_weekly_shipment_plan_returns_artifact(self):
        result = PmcAgent.create_default(FakeIntentModel(TaskType.WEEKLY_SHIPMENT_PLAN)).run("生成周度发货计划草稿")

        self.assertEqual(result.plan.task_type, TaskType.WEEKLY_SHIPMENT_PLAN)
        self.assertIn("weekly_shipment_plan", result.artifacts)

    def test_tool_failure_is_handled_by_failure_model(self):
        agent = PmcAgent(
            config=AgentConfig(),
            tools=ToolRegistry(
                {
                    "inventory_snapshot": FailingSnapshotTool(),
                    "inventory_risk": InventoryRiskTool(policy=AgentConfig().inventory_policy),
                }
            ),
            intent_model=FakeIntentModel(TaskType.INVENTORY_RISK),
            failure_model=FakeFailureModel(),
        )

        result = agent.run("检查 A100 是否有缺料风险")

        self.assertIn("failure_decision", result.artifacts)
        self.assertEqual(result.artifacts["failure_decision"].next_action, "ask_user_for_input")
        self.assertEqual(result.state_history[-1].to_status, RunStatus.COMPLETED)


if __name__ == "__main__":
    unittest.main()
