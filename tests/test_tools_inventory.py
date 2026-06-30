import unittest

from pmc_agent.config import InventoryPolicy
from pmc_agent.domain import InventorySnapshot, RiskLevel
from pmc_agent.tools.inventory import (
    ControlTowerTool,
    ExceptionCaseTool,
    InventoryRiskTool,
    InventorySnapshotTool,
    KnowledgeLookupTool,
    PurchaseVerificationTool,
    WeeklyShipmentPlanTool,
)
from tests.fake_control_tower import FakeMainRuleConnector


class EmptyConnector:
    def get_inventory_snapshot(self, material_code=None):
        raise LookupError("No inventory snapshot found in STI database for material_code=ZZ999.")


class FieldPackConnector:
    def __init__(self):
        self.field_pack = None

    def get_inventory_snapshot(self, material_code=None, field_pack=None):
        self.field_pack = field_pack
        return [InventorySnapshot(material_code="A100", on_hand=1, allocated=0, inbound=0, demand_next_7d=1, demand_next_30d=1)]


class FakeKnowledgeConnector:
    def __init__(self, snippets):
        self.snippets = snippets
        self.calls = []

    def search(self, query, query_vector=None, limit=5):
        self.calls.append({"query": query, "query_vector": query_vector, "limit": limit})
        return self.snippets


class InventoryToolTests(unittest.TestCase):
    def test_snapshot_tool_warns_for_missing_material(self):
        with self.assertRaisesRegex(RuntimeError, "数据获取失败"):
            InventorySnapshotTool().run(material_code="ZZ999")

    def test_snapshot_tool_does_not_fallback_when_connector_fails(self):
        with self.assertRaisesRegex(LookupError, "No inventory snapshot found"):
            InventorySnapshotTool(connector=EmptyConnector()).run(material_code="ZZ999")

    def test_snapshot_tool_passes_field_pack_to_connector(self):
        connector = FieldPackConnector()

        InventorySnapshotTool(connector=connector).run(material_code="A100", field_pack="purchase_verification")

        self.assertEqual(connector.field_pack, "purchase_verification")

    def test_inventory_risk_tool_outputs_medium_decision(self):
        connector = FakeMainRuleConnector()
        snapshots = InventorySnapshotTool(connector=connector).run(material_code="A100")

        with self.assertNoLogs("pmc_agent.tools.inventory", level="WARNING"):
            decisions = InventoryRiskTool(policy=InventoryPolicy(), connector=connector).run(snapshots=snapshots)

        self.assertEqual(decisions[0].risk_level, RiskLevel.MEDIUM)
        self.assertTrue(decisions[0].recommended_actions)

    def test_control_tower_and_weekly_plan_emit_artifact_logs(self):
        signals = ControlTowerTool(connector=FakeMainRuleConnector()).run()

        with self.assertLogs("pmc_agent.tools.inventory", level="WARNING") as logs:
            plan = WeeklyShipmentPlanTool().run(signals=signals)

        self.assertEqual(plan["status"], "draft")
        self.assertEqual(logs.records[0].event, "weekly_plan_manual_confirmation_required")

    def test_purchase_verification_requires_manual_confirmation(self):
        snapshots = InventorySnapshotTool(connector=FakeMainRuleConnector()).run(material_code="A100")

        with self.assertLogs("pmc_agent.tools.inventory", level="WARNING") as logs:
            decisions = PurchaseVerificationTool().run(snapshots=snapshots)

        self.assertEqual(decisions[0].category, "purchase_verification")
        self.assertEqual(logs.records[0].event, "purchase_manual_confirmation_required")

    def test_exception_case_tool_outputs_draft_cases(self):
        signals = ControlTowerTool(connector=FakeMainRuleConnector()).run(material_code="A100")
        cases = ExceptionCaseTool().run(signals=signals)

        self.assertEqual(cases[0].status, "draft")

    def test_knowledge_lookup_uses_connector_when_available(self):
        connector = FakeKnowledgeConnector([{"title": "SOP", "content": "vector result"}])

        snippets = KnowledgeLookupTool(connector=connector).run(query="采购校验规则", query_vector=[0.1], limit=3)

        self.assertEqual(snippets, [{"title": "SOP", "content": "vector result"}])
        self.assertEqual(connector.calls, [{"query": "采购校验规则", "query_vector": [0.1], "limit": 3}])

    def test_knowledge_lookup_falls_back_when_connector_has_no_result(self):
        connector = FakeKnowledgeConnector([])

        snippets = KnowledgeLookupTool(connector=connector).run(query="采购校验规则")

        self.assertGreaterEqual(len(snippets), 1)
        self.assertEqual(connector.calls[0]["query"], "采购校验规则")


if __name__ == "__main__":
    unittest.main()
