import unittest

from pmc_agent.config import InventoryPolicy
from pmc_agent.domain import RiskLevel
from pmc_agent.tools.inventory import (
    ControlTowerTool,
    ExceptionCaseTool,
    InventoryRiskTool,
    InventorySnapshotTool,
    PurchaseVerificationTool,
    WeeklyShipmentPlanTool,
)


class EmptyConnector:
    def get_inventory_snapshot(self, material_code=None):
        raise LookupError("No inventory snapshot found in STI database for material_code=ZZ999.")


class InventoryToolTests(unittest.TestCase):
    def test_snapshot_tool_warns_for_missing_material(self):
        with self.assertLogs("pmc_agent.tools.inventory", level="WARNING") as logs:
            result = InventorySnapshotTool().run(material_code="ZZ999")

        self.assertEqual(result, [])
        self.assertEqual(logs.records[0].event, "inventory_snapshot_missing")

    def test_snapshot_tool_does_not_fallback_when_connector_fails(self):
        with self.assertRaisesRegex(LookupError, "No inventory snapshot found"):
            InventorySnapshotTool(connector=EmptyConnector()).run(material_code="ZZ999")

    def test_inventory_risk_tool_outputs_decision_and_warning(self):
        snapshots = InventorySnapshotTool().run(material_code="A100")

        with self.assertLogs("pmc_agent.tools.inventory", level="WARNING") as logs:
            decisions = InventoryRiskTool(policy=InventoryPolicy()).run(snapshots=snapshots)

        self.assertEqual(decisions[0].risk_level, RiskLevel.CRITICAL)
        self.assertTrue(decisions[0].recommended_actions)
        self.assertEqual(logs.records[0].event, "inventory_high_risk_detected")

    def test_control_tower_and_weekly_plan_emit_artifact_logs(self):
        signals = ControlTowerTool().run(InventorySnapshotTool().run())

        with self.assertLogs("pmc_agent.tools.inventory", level="WARNING") as logs:
            plan = WeeklyShipmentPlanTool().run(signals=signals)

        self.assertEqual(plan["status"], "draft")
        self.assertEqual(logs.records[0].event, "weekly_plan_manual_confirmation_required")

    def test_purchase_verification_requires_manual_confirmation(self):
        snapshots = InventorySnapshotTool().run(material_code="A100")

        with self.assertLogs("pmc_agent.tools.inventory", level="WARNING") as logs:
            decisions = PurchaseVerificationTool().run(snapshots=snapshots)

        self.assertEqual(decisions[0].category, "purchase_verification")
        self.assertEqual(logs.records[0].event, "purchase_manual_confirmation_required")

    def test_exception_case_tool_outputs_draft_cases(self):
        signals = ControlTowerTool().run(InventorySnapshotTool().run(material_code="A100"))
        cases = ExceptionCaseTool().run(signals=signals)

        self.assertEqual(cases[0].status, "draft")


if __name__ == "__main__":
    unittest.main()
