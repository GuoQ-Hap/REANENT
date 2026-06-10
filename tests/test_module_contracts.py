import unittest
import os

from pmc_agent.config import AgentConfig, InventoryPolicy
from pmc_agent.domain import TaskRequest, TaskType
from pmc_agent.model import IntentAssessment
from pmc_agent.orchestrator import PmcAgent
from pmc_agent.planning import build_plan, classify_task
from pmc_agent.test_server import FakeIntentModel, MODULE_CONTRACTS, SCENARIOS, check_expected_nodes
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


class FakeModel:
    def assess_intent(self, request, recent_context=None):
        return IntentAssessment(
            task_type=TaskType.PURCHASE_VERIFICATION,
            confidence=0.88,
            user_expectation="验证采购建议",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=True,
            risk_level="medium",
            reasoning_summary="测试语义输出",
        )


class ModuleContractTests(unittest.TestCase):
    def setUp(self):
        self._old_db_enabled = os.environ.get("STI_DB_ENABLED")
        os.environ["STI_DB_ENABLED"] = "false"

    def tearDown(self):
        if self._old_db_enabled is None:
            os.environ.pop("STI_DB_ENABLED", None)
        else:
            os.environ["STI_DB_ENABLED"] = self._old_db_enabled

    def test_contracts_declare_input_output_and_nodes(self):
        for contract in MODULE_CONTRACTS:
            self.assertTrue(contract["input"])
            self.assertTrue(contract["expected_output"])
            self.assertTrue(contract["expected_nodes"])

    def test_planning_input_output_contract(self):
        request = TaskRequest(text="帮我验证采购建议", material_code="A100")
        intent = classify_task(request, FakeModel())
        plan = build_plan(request, intent.task_type, intent.confidence)

        self.assertEqual(intent.task_type, TaskType.PURCHASE_VERIFICATION)
        self.assertEqual(plan.task_type, TaskType.PURCHASE_VERIFICATION)
        self.assertEqual(plan.steps[0].tool, "inventory_snapshot")
        self.assertEqual(plan.steps[1].tool, "purchase_verification")

    def test_inventory_tool_input_output_contract(self):
        connector = FakeMainRuleConnector()
        snapshots = InventorySnapshotTool(connector=connector).run(material_code="A100")
        decisions = InventoryRiskTool(policy=InventoryPolicy(), connector=connector).run(snapshots=snapshots)

        self.assertEqual(snapshots[0].material_code, "A100")
        self.assertTrue(decisions[0].recommended_actions)
        self.assertIn("on_hand", decisions[0].evidence)

    def test_purchase_tool_input_output_contract(self):
        snapshots = InventorySnapshotTool(connector=FakeMainRuleConnector()).run(material_code="A100")
        decisions = PurchaseVerificationTool().run(snapshots=snapshots)

        self.assertEqual(decisions[0].category, "purchase_verification")
        self.assertIn("suggested_purchase_qty", decisions[0].evidence)

    def test_all_scenarios_match_expected_state_nodes(self):
        for scenario in SCENARIOS:
            agent = _fake_agent(FakeIntentModel(scenario["task_type"]))
            result = agent.run(scenario["text"])
            check = check_expected_nodes(result.state_history, scenario["expected_nodes"])

            self.assertTrue(check["ok"], f"{scenario['id']} missing nodes: {check['missing']}")

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
