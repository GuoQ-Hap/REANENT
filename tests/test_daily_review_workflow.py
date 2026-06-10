from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import unittest

from pmc_agent.domain import RiskLevel
from pmc_agent.external_integrations.feishu import FeishuApprovalInstance, FeishuReviewResult
from pmc_agent.workflows import DailyReviewOrchestrator, ReviewDecision, ReviewStage, ReviewStatus
from pmc_agent.workflows.daily_review import review_item_from_signal


@dataclass
class FakeRobot:
    name: str = "inventory_robot"
    items_count: int = 1

    def detect(self, context):
        items = []
        fixtures = [
            ("A100", "ou_sales", RiskLevel.HIGH),
            ("B200", "ou_sales_2", RiskLevel.MEDIUM),
            ("C300", "ou_sales_3", RiskLevel.CRITICAL),
        ]
        for material_code, owner_open_id, risk_level in fixtures[: self.items_count]:
            items.append(
                review_item_from_signal(
                    item_id="",
                    daily_run_id="",
                    business_type="purchase_confirmation",
                    title=f"{material_code} 断货风险",
                    summary=f"{material_code} 预计 7 天后库存不足，需要销售确认需求。",
                    risk_level=risk_level,
                    robot_name=self.name,
                    owner_open_id=owner_open_id,
                    sales_manager_open_id="ou_sales_manager",
                    pmc_open_id="ou_pmc",
                    material_code=material_code,
                    sales_department="销售一部",
                    suggested_action="请确认是否控销或调整预测。",
                    evidence={"projected_7d": -20},
                )
            )
        return items


class FakeWorkflowService:
    def __init__(self):
        self.submitted = []
        self.statuses = {}

    def submit(self, request):
        self.submitted.append(request)
        return FeishuReviewResult(
            ok=True,
            review_id=f"approval-{request.request_id}",
            status="pending_review",
            channel="approval_flow",
        )

    def get_approval_instance(self, approval_id):
        return FeishuApprovalInstance(
            ok=True,
            approval_id=approval_id,
            status=self.statuses.get(approval_id, "pending"),
            operator_open_id="ou_reviewer",
        )


class DailyReviewWorkflowTests(unittest.TestCase):
    def test_daily_run_starts_sales_review_for_detected_items(self):
        workflow = FakeWorkflowService()
        orchestrator = DailyReviewOrchestrator(robots=[FakeRobot()], workflow_service=workflow)

        batch = orchestrator.start_daily_run(run_date=date(2026, 6, 4))

        self.assertEqual("daily-20260604", batch.daily_run_id)
        self.assertEqual(1, batch.status_counts[ReviewStatus.SALES_REVIEW_PENDING.value])
        item = batch.items[0]
        self.assertEqual("daily-20260604-inventory_robot-0001", item.item_id)
        self.assertEqual(ReviewStatus.SALES_REVIEW_PENDING, item.status)
        self.assertEqual("approval-daily-20260604-inventory_robot-0001-sales", item.approval_ids[ReviewStage.SALES.value])
        self.assertEqual("ou_sales", workflow.submitted[0].reviewer_open_ids[0])

    def test_item_flows_from_sales_to_manager_to_pmc_to_recorded(self):
        workflow = FakeWorkflowService()
        orchestrator = DailyReviewOrchestrator(robots=[FakeRobot()], workflow_service=workflow)
        orchestrator.start_daily_run(run_date=date(2026, 6, 4))
        item_id = "daily-20260604-inventory_robot-0001"

        sales_reviewed = orchestrator.apply_sales_decision(
            ReviewDecision(
                item_id=item_id,
                stage=ReviewStage.SALES,
                action="approve",
                operator_open_id="ou_sales",
                comment="销售确认需求属实。",
            )
        )
        self.assertEqual(ReviewStatus.SALES_REVIEWED, sales_reviewed.status)

        manager_pending = orchestrator.submit_sales_manager_reviews("daily-20260604")
        self.assertEqual(1, len(manager_pending))
        self.assertEqual(ReviewStatus.SALES_MANAGER_PENDING, manager_pending[0].status)
        self.assertEqual("ou_sales_manager", workflow.submitted[-1].reviewer_open_ids[0])

        manager_reviewed = orchestrator.apply_sales_manager_decision(
            ReviewDecision(
                item_id=item_id,
                stage=ReviewStage.SALES_MANAGER,
                action="approve",
                operator_open_id="ou_sales_manager",
            )
        )
        self.assertEqual(ReviewStatus.SALES_MANAGER_REVIEWED, manager_reviewed.status)

        pmc_pending = orchestrator.submit_pmc_reviews("daily-20260604")
        self.assertEqual(1, len(pmc_pending))
        self.assertEqual(ReviewStatus.PMC_REVIEW_PENDING, pmc_pending[0].status)
        self.assertEqual("ou_pmc", workflow.submitted[-1].reviewer_open_ids[0])

        pmc_reviewed = orchestrator.apply_pmc_decision(
            ReviewDecision(
                item_id=item_id,
                stage=ReviewStage.PMC,
                action="approve",
                operator_open_id="ou_pmc",
            )
        )
        self.assertEqual(ReviewStatus.PMC_APPROVED, pmc_reviewed.status)

        recorded = orchestrator.finalize_pmc_item(item_id)
        self.assertEqual(ReviewStatus.RECORDED, recorded.status)
        self.assertEqual(7, len(orchestrator.state_machine.history))

    def test_state_machine_rejects_skipping_sales_review(self):
        workflow = FakeWorkflowService()
        orchestrator = DailyReviewOrchestrator(robots=[FakeRobot()], workflow_service=workflow)
        orchestrator.start_daily_run(run_date=date(2026, 6, 4))

        with self.assertRaises(ValueError):
            orchestrator.apply_sales_manager_decision(
                ReviewDecision(
                    item_id="daily-20260604-inventory_robot-0001",
                    stage=ReviewStage.SALES_MANAGER,
                    action="approve",
                    operator_open_id="ou_sales_manager",
                )
            )

    def test_manager_and_pmc_reviews_are_submitted_as_batches(self):
        workflow = FakeWorkflowService()
        orchestrator = DailyReviewOrchestrator(robots=[FakeRobot(items_count=3)], workflow_service=workflow)
        batch = orchestrator.start_daily_run(run_date=date(2026, 6, 4))

        self.assertEqual(3, len(workflow.submitted))
        self.assertEqual(["ou_sales", "ou_sales_2", "ou_sales_3"], [request.reviewer_open_ids[0] for request in workflow.submitted])

        for item in batch.items:
            orchestrator.apply_sales_decision(
                ReviewDecision(
                    item_id=item.item_id,
                    stage=ReviewStage.SALES,
                    action="approve",
                    operator_open_id=item.owner_open_id,
                )
            )

        manager_pending = orchestrator.submit_sales_manager_reviews(batch.daily_run_id)

        self.assertEqual(3, len(manager_pending))
        self.assertEqual(4, len(workflow.submitted))
        manager_request = workflow.submitted[-1]
        self.assertEqual("sales_manager", manager_request.metadata["review_stage"])
        self.assertEqual("ou_sales_manager", manager_request.reviewer_open_ids[0])
        self.assertEqual(3, manager_request.business_object["item_count"])
        self.assertIn("3 条待审核事项", manager_request.title)

        for item in manager_pending:
            orchestrator.apply_sales_manager_decision(
                ReviewDecision(
                    item_id=item.item_id,
                    stage=ReviewStage.SALES_MANAGER,
                    action="approve",
                    operator_open_id="ou_sales_manager",
                )
            )

        pmc_pending = orchestrator.submit_pmc_reviews(batch.daily_run_id)

        self.assertEqual(3, len(pmc_pending))
        self.assertEqual(5, len(workflow.submitted))
        pmc_request = workflow.submitted[-1]
        self.assertEqual("pmc", pmc_request.metadata["review_stage"])
        self.assertEqual("ou_pmc", pmc_request.reviewer_open_ids[0])
        self.assertEqual(3, pmc_request.business_object["item_count"])
        self.assertIn("3 条待审核事项", pmc_request.title)

    def test_sync_approval_statuses_advances_stages_in_order(self):
        workflow = FakeWorkflowService()
        orchestrator = DailyReviewOrchestrator(robots=[FakeRobot(items_count=2)], workflow_service=workflow)
        batch = orchestrator.start_daily_run(run_date=date(2026, 6, 4))

        orchestrator.sync_approval_statuses(batch.daily_run_id)

        self.assertEqual(2, len(workflow.submitted))
        self.assertEqual(2, orchestrator.batch(batch.daily_run_id).status_counts[ReviewStatus.SALES_REVIEW_PENDING.value])

        for item in batch.items:
            workflow.statuses[item.approval_ids[ReviewStage.SALES.value]] = "approved"

        sales_synced = orchestrator.sync_approval_statuses(batch.daily_run_id)

        self.assertEqual(3, len(workflow.submitted))
        self.assertEqual(2, sales_synced.status_counts[ReviewStatus.SALES_MANAGER_PENDING.value])
        manager_batch = next(batch for batch in orchestrator.approval_batches.values() if batch.stage == ReviewStage.SALES_MANAGER)

        workflow.statuses[manager_batch.approval_id] = "approved"
        manager_synced = orchestrator.sync_approval_statuses(batch.daily_run_id)

        self.assertEqual(4, len(workflow.submitted))
        self.assertEqual(2, manager_synced.status_counts[ReviewStatus.PMC_REVIEW_PENDING.value])
        pmc_batch = next(batch for batch in orchestrator.approval_batches.values() if batch.stage == ReviewStage.PMC)

        workflow.statuses[pmc_batch.approval_id] = "approved"
        pmc_synced = orchestrator.sync_approval_statuses(batch.daily_run_id, finalize_pmc=False)

        self.assertEqual(2, pmc_synced.status_counts[ReviewStatus.PMC_APPROVED.value])


if __name__ == "__main__":
    unittest.main()
