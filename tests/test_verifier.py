import unittest

from pmc_agent.domain import ControlDecision, ExecutionPlan, PlanStep, RiskLevel, TaskType
from pmc_agent.verifier import verify_decisions


class VerifierTests(unittest.TestCase):
    def test_verifier_logs_error_when_no_output(self):
        plan = ExecutionPlan(task_type=TaskType.INVENTORY_RISK, confidence=0.8, steps=[])

        with self.assertLogs("pmc_agent.verifier", level="ERROR") as logs:
            messages = verify_decisions(plan, [])

        self.assertIn("No decision was produced", messages[0])
        self.assertEqual(logs.records[0].event, "verification_no_output")

    def test_verifier_logs_artifact_human_review_warning(self):
        plan = ExecutionPlan(
            task_type=TaskType.WEEKLY_SHIPMENT_PLAN,
            confidence=0.8,
            steps=[PlanStep("generate_plan", "Generate weekly plan.")],
            assumptions=["portfolio-level analysis"],
        )

        with self.assertLogs("pmc_agent.verifier", level="WARNING") as logs:
            messages = verify_decisions(plan, [], {"weekly_shipment_plan": {"status": "draft"}})

        self.assertIn("Artifact output", messages[0])
        self.assertEqual(logs.records[0].event, "artifact_requires_human_review")

    def test_verifier_logs_missing_actions(self):
        plan = ExecutionPlan(task_type=TaskType.INVENTORY_RISK, confidence=0.8, steps=[])
        decision = ControlDecision(
            material_code="A100",
            risk_level=RiskLevel.MEDIUM,
            summary="No action fixture.",
            recommended_actions=[],
        )

        with self.assertLogs("pmc_agent.verifier", level="ERROR") as logs:
            messages = verify_decisions(plan, [decision])

        self.assertIn("missing recommended actions", messages[0])
        self.assertEqual(logs.records[0].event, "decision_missing_actions")


if __name__ == "__main__":
    unittest.main()
