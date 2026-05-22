import unittest

from pmc_agent.domain import TaskRequest, TaskType
from pmc_agent.model import IntentAssessment
from pmc_agent.planning import build_plan, classify_task
from pmc_agent.planning.classifier import enrich_request


class FakeIntentModel:
    def __init__(self, assessment):
        self.assessment = assessment

    def assess_intent(self, request, recent_context=None):
        return self.assessment


class PlanningTests(unittest.TestCase):
    def test_classify_task_uses_model_assessment(self):
        assessment = IntentAssessment(
            task_type=TaskType.PURCHASE_VERIFICATION,
            confidence=0.91,
            user_expectation="verify purchase advice",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=True,
            risk_level="medium",
            reasoning_summary="semantic fixture",
        )

        result = classify_task(TaskRequest(text="帮我看看这批要不要买"), FakeIntentModel(assessment))

        self.assertEqual(result.task_type, TaskType.PURCHASE_VERIFICATION)
        self.assertEqual(result.confidence, 0.91)

    def test_build_plan_logs_missing_material_assumption(self):
        request = TaskRequest(text="生成周度计划")

        with self.assertLogs("pmc_agent.planning.planner", level="WARNING") as logs:
            plan = build_plan(request, TaskType.WEEKLY_SHIPMENT_PLAN, 0.8)

        self.assertTrue(plan.assumptions)
        self.assertEqual(logs.records[0].event, "plan_assumption_added")

    def test_enrich_request_extracts_amazon_style_code(self):
        request = enrich_request("B0BXD4MCCK 这个库存还有多少")

        self.assertEqual(request.material_code, "B0BXD4MCCK")

    def test_enrich_request_extracts_code_next_to_chinese_text(self):
        request = enrich_request("B0BXD4MCCK这个库存有风险吗")

        self.assertEqual(request.material_code, "B0BXD4MCCK")


if __name__ == "__main__":
    unittest.main()
