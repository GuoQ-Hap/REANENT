from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest

from pmc_agent.domain import RiskLevel
from pmc_agent.external_integrations.feishu import FeishuReviewResult, FeishuWorkflowCallback
from pmc_agent.workflows import (
    InMemorySkuIssueRepository,
    JsonlSkuIssueRepository,
    SkuFeedbackAction,
    SkuIssueAssignment,
    SkuIssueDepartment,
    SkuIssueFeedback,
    SkuIssueSignal,
    SkuIssueStatus,
    SkuIssueType,
    SkuIssueWorkflow,
)


@dataclass
class FakeReviewClient:
    submitted: list = field(default_factory=list)

    def submit_review(self, request):
        self.submitted.append(request)
        return FeishuReviewResult(
            ok=True,
            review_id=f"review-{request.request_id}",
            status="pending_review",
            channel="review_card",
        )


@dataclass
class FakeWorkflowService:
    review_client: FakeReviewClient = field(default_factory=FakeReviewClient)
    submitted: list = field(default_factory=list)

    def submit(self, request):
        self.submitted.append(request)
        return FeishuReviewResult(
            ok=True,
            review_id=f"approval-{request.request_id}",
            status="pending_review",
            channel="approval_flow",
        )

    def parse_callback(self, payload):
        value = payload.get("value") if isinstance(payload.get("value"), dict) else {}
        return FeishuWorkflowCallback(
            source="feishu_review",
            workflow_id=str(payload.get("workflow_id") or ""),
            request_id=str(payload.get("request_id") or value.get("request_id") or ""),
            action=str(payload.get("action") or value.get("action") or ""),
            operator_open_id=str(payload.get("operator_open_id") or ""),
            comment=str(payload.get("comment") or ""),
            fields=dict(payload.get("fields") or value),
            raw=payload,
        )


def _signal(sku="A100", issue_type=SkuIssueType.SHORTAGE):
    return SkuIssueSignal(
        issue_id=f"issue-{sku}",
        sku=sku,
        issue_type=issue_type,
        risk_level=RiskLevel.HIGH,
        summary=f"{sku} has inventory risk",
        suggested_department=SkuIssueDepartment.SALES,
        suggested_owner_open_id="ou_sales_agent_suggestion",
        suggested_owner_name="Sales A",
        evidence={"projected_7d": -20},
        detected_at="2026-06-04T01:00:00+00:00",
    )


class SkuIssueWorkflowTests(unittest.TestCase):
    def test_agent_detects_issue_and_submits_pmc_initial_review(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)

        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")

        self.assertEqual(SkuIssueStatus.PMC_REVIEW_PENDING, issue.status)
        self.assertEqual("approval-issue-A100-pmc-review", issue.pmc_approval_id)
        self.assertEqual(1, len(service.submitted))
        request = service.submitted[0]
        self.assertEqual("pmc_sku_issue_review", request.business_type)
        self.assertEqual("ou_pmc", request.reviewer_open_ids[0])
        self.assertEqual("pmc_initial_review", request.metadata["review_stage"])

    def test_pmc_can_modify_owner_then_owner_feedback_is_requested(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)
        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")

        assigned = workflow.apply_pmc_review(
            issue.issue_id,
            approved=True,
            operator_open_id="ou_pmc",
            assignment=SkuIssueAssignment(
                department=SkuIssueDepartment.PURCHASE,
                owner_open_id="ou_purchase_owner",
                owner_name="Buyer A",
                reason="PMC changed owner after review",
            ),
            comment="change to purchase",
        )

        self.assertEqual(SkuIssueStatus.OWNER_FEEDBACK_PENDING, assigned.status)
        self.assertEqual(SkuIssueDepartment.PURCHASE, assigned.assignment.department)
        self.assertEqual("ou_purchase_owner", assigned.assignment.owner_open_id)
        self.assertEqual(1, len(service.review_client.submitted))
        owner_request = service.review_client.submitted[0]
        self.assertEqual("purchase_sku_feedback", owner_request.business_type)
        self.assertEqual("ou_purchase_owner", owner_request.reviewer_open_ids[0])

    def test_owner_feedback_records_final_action(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)
        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")
        workflow.apply_pmc_review(issue.issue_id, approved=True, operator_open_id="ou_pmc")

        recorded = workflow.apply_owner_feedback(
            issue.issue_id,
            SkuIssueFeedback(
                action=SkuFeedbackAction.SALES_CONTROL,
                operator_open_id="ou_sales_agent_suggestion",
                comment="limit sales for two days",
                eta="2026-06-05",
            ),
        )

        self.assertEqual(SkuIssueStatus.RECORDED, recorded.status)
        self.assertEqual(SkuFeedbackAction.SALES_CONTROL, recorded.feedback.action)
        self.assertTrue(recorded.recorded_at)

    def test_pmc_callback_assigns_owner_and_requests_feedback(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)
        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")

        assigned = workflow.handle_feishu_callback(
            {
                "request_id": f"{issue.issue_id}-pmc-review",
                "action": "approve",
                "operator_open_id": "ou_pmc",
                "comment": "assign to shipment",
                "fields": {
                    "issue_id": issue.issue_id,
                    "review_stage": "pmc_initial_review",
                    "assignment_department": SkuIssueDepartment.SHIPMENT,
                    "assignment_owner_open_id": "ou_ship_owner",
                    "assignment_owner_name": "Ship A",
                },
            }
        )

        self.assertEqual(SkuIssueStatus.OWNER_FEEDBACK_PENDING, assigned.status)
        self.assertEqual(SkuIssueDepartment.SHIPMENT, assigned.assignment.department)
        self.assertEqual("ou_ship_owner", assigned.assignment.owner_open_id)
        self.assertEqual(1, len(service.review_client.submitted))

    def test_owner_feedback_callback_records_action(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)
        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")
        workflow.apply_pmc_review(issue.issue_id, approved=True, operator_open_id="ou_pmc")

        recorded = workflow.handle_feishu_callback(
            {
                "request_id": f"{issue.issue_id}-owner-feedback-0",
                "action": "submit_owner_feedback",
                "operator_open_id": "ou_sales_agent_suggestion",
                "comment": "",
                "value": {
                    "issue_id": issue.issue_id,
                    "review_stage": "owner_feedback",
                    "feedback_actions": [SkuFeedbackAction.PURCHASE_REPLENISHMENT, SkuFeedbackAction.PROMOTION],
                    "feedback_comment": "will replenish and promote",
                },
            }
        )

        self.assertEqual(SkuIssueStatus.RECORDED, recorded.status)
        self.assertEqual(SkuFeedbackAction.PURCHASE_REPLENISHMENT, recorded.feedback.action)
        self.assertEqual([SkuFeedbackAction.PURCHASE_REPLENISHMENT, SkuFeedbackAction.PROMOTION], recorded.feedback.actions)
        self.assertEqual("will replenish and promote", recorded.feedback.comment)

        repeated = workflow.handle_feishu_callback(
            {
                "request_id": f"{issue.issue_id}-owner-feedback-0",
                "action": SkuFeedbackAction.SALES_CONTROL,
                "operator_open_id": "ou_sales_agent_suggestion",
                "comment": "clicked again",
                "value": {
                    "issue_id": issue.issue_id,
                    "review_stage": "owner_feedback",
                },
            }
        )

        self.assertEqual(SkuIssueStatus.RECORDED, repeated.status)
        self.assertEqual(SkuFeedbackAction.PURCHASE_REPLENISHMENT, repeated.feedback.action)

    def test_pmc_reject_callback_marks_issue_rejected(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)
        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")

        rejected = workflow.apply_callback(
            FeishuWorkflowCallback(
                source="feishu_review",
                workflow_id="",
                request_id=f"{issue.issue_id}-pmc-review",
                action="reject",
                operator_open_id="ou_pmc",
                comment="not valid",
                fields={"review_stage": "pmc_initial_review"},
            )
        )

        self.assertEqual(SkuIssueStatus.PMC_REJECTED, rejected.status)
        self.assertIn("not valid", rejected.notes)

    def test_three_hour_overdue_feedback_is_reminded_and_then_escalated(self):
        service = FakeWorkflowService()
        repository = InMemorySkuIssueRepository()
        workflow = SkuIssueWorkflow(workflow_service=service, repository=repository)
        issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")
        workflow.apply_pmc_review(issue.issue_id, approved=True, operator_open_id="ou_pmc")
        waiting = repository.get(issue.issue_id)
        waiting = waiting.__class__(
            **{
                **waiting.__dict__,
                "feedback_requested_at": "2026-06-04T01:00:00+00:00",
            }
        )
        repository.save(waiting)

        reminded = workflow.remind_overdue(datetime(2026, 6, 4, 4, 1, tzinfo=timezone.utc), max_reminders=1)

        self.assertEqual(1, len(reminded))
        self.assertEqual(SkuIssueStatus.OWNER_FEEDBACK_REMINDED, reminded[0].status)
        self.assertEqual(1, reminded[0].reminder_count)
        self.assertEqual(2, len(service.review_client.submitted))

        escalated = workflow.remind_overdue(datetime(2026, 6, 4, 7, 2, tzinfo=timezone.utc), max_reminders=1)

        self.assertEqual(SkuIssueStatus.ESCALATED, escalated[0].status)

    def test_daily_and_weekly_summary_counts_records(self):
        service = FakeWorkflowService()
        workflow = SkuIssueWorkflow(workflow_service=service)
        for sku, issue_type in [("A100", SkuIssueType.SHORTAGE), ("B200", SkuIssueType.REDUNDANT)]:
            issue = workflow.detect_issue(_signal(sku=sku, issue_type=issue_type), pmc_open_id="ou_pmc")
            workflow.apply_pmc_review(issue.issue_id, approved=True, operator_open_id="ou_pmc")

        summary = workflow.daily_summary(date(2026, 6, 4))
        weekly = workflow.weekly_summary(date(2026, 6, 1))

        self.assertEqual(2, summary.total)
        self.assertEqual(2, summary.by_status[SkuIssueStatus.OWNER_FEEDBACK_PENDING])
        self.assertEqual(2, weekly.total)
        self.assertEqual(2, weekly.high_risk_open_count)

    def test_jsonl_repository_keeps_latest_issue_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sku_issues.jsonl"
            repository = JsonlSkuIssueRepository(path)
            service = FakeWorkflowService()
            workflow = SkuIssueWorkflow(workflow_service=service, repository=repository)
            issue = workflow.detect_issue(_signal(), pmc_open_id="ou_pmc")
            workflow.apply_pmc_review(issue.issue_id, approved=False, operator_open_id="ou_pmc", comment="not a real issue")

            loaded = repository.get(issue.issue_id)

            self.assertEqual(SkuIssueStatus.PMC_REJECTED, loaded.status)
            self.assertIn("not a real issue", loaded.notes)


if __name__ == "__main__":
    unittest.main()
