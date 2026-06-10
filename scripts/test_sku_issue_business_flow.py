from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pmc_agent.domain import RiskLevel
from pmc_agent.env import load_env_file
from pmc_agent.external_integrations.feishu import FeishuReviewResult, FeishuWorkflowCallback, FeishuWorkflowService
from pmc_agent.workflows import (
    JsonlSkuIssueRepository,
    SkuFeedbackAction,
    SkuIssueAssignment,
    SkuIssueDepartment,
    SkuIssueFeedback,
    SkuIssueSignal,
    SkuIssueType,
    SkuIssueWorkflow,
)


@dataclass
class DryReviewClient:
    submitted: list = field(default_factory=list)

    def submit_review(self, request):
        self.submitted.append(request)
        return FeishuReviewResult(
            ok=True,
            review_id=f"dry-review-{request.request_id}",
            status="pending_review",
            channel="dry_card",
        )


@dataclass
class DryWorkflowService:
    review_client: DryReviewClient = field(default_factory=DryReviewClient)
    submitted: list = field(default_factory=list)

    def submit(self, request):
        self.submitted.append(request)
        return FeishuReviewResult(
            ok=True,
            review_id=f"dry-approval-{request.request_id}",
            status="pending_review",
            channel="dry_approval",
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the SKU issue business workflow: PMC review, owner feedback, reminders, and summary.")
    parser.add_argument("--send", action="store_true", help="Use real Feishu for PMC review and owner feedback notifications.")
    parser.add_argument("--simulate", action="store_true", help="Simulate PMC approval and owner feedback after detection.")
    parser.add_argument("--simulate-callbacks", action="store_true", help="Simulate Feishu card callbacks instead of calling workflow methods directly.")
    parser.add_argument("--pmc-open-id", default="", help="PMC reviewer open_id. Defaults to FEISHU_TEST_REVIEWER_OPEN_ID or FEISHU_APPROVAL_START_OPEN_ID.")
    parser.add_argument("--owner-open-id", default="", help="Owner open_id for sales/purchase/shipment feedback. Defaults to pmc open_id in this demo.")
    parser.add_argument("--table", default="output/sku_issue_records.jsonl", help="JSONL table path for issue records.")
    args = parser.parse_args()

    load_env_file(override=False)
    import os

    pmc_open_id = args.pmc_open_id or os.getenv("FEISHU_TEST_REVIEWER_OPEN_ID") or os.getenv("FEISHU_APPROVAL_START_OPEN_ID")
    if not pmc_open_id:
        print("Missing PMC open_id. Set FEISHU_TEST_REVIEWER_OPEN_ID or pass --pmc-open-id.")
        return 2
    owner_open_id = args.owner_open_id or pmc_open_id

    service = FeishuWorkflowService() if args.send else DryWorkflowService()
    workflow = SkuIssueWorkflow(
        workflow_service=service,
        repository=JsonlSkuIssueRepository(args.table),
    )

    issues = [workflow.detect_issue(signal, pmc_open_id=pmc_open_id) for signal in _demo_signals(owner_open_id)]
    print("Detected issues:")
    for issue in issues:
        print(f"- {issue.issue_id}: {issue.sku} / {issue.issue_type} / {issue.status} / pmc={issue.pmc_approval_id}")

    if args.simulate_callbacks:
        for issue in issues:
            workflow.handle_feishu_callback(
                {
                    "request_id": f"{issue.issue_id}-pmc-review",
                    "action": "approve",
                    "operator_open_id": pmc_open_id,
                    "comment": "demo callback: pmc approved",
                    "fields": {
                        "issue_id": issue.issue_id,
                        "review_stage": "pmc_initial_review",
                        "assignment_department": {
                            "A100": SkuIssueDepartment.SALES,
                            "B200": SkuIssueDepartment.PURCHASE,
                            "C300": SkuIssueDepartment.SHIPMENT,
                        }.get(issue.sku, issue.suggested_department),
                        "assignment_owner_open_id": owner_open_id,
                        "assignment_owner_name": "Demo Owner",
                    },
                }
            )
        workflow.handle_feishu_callback(
            {
                "request_id": f"{issues[0].issue_id}-owner-feedback-0",
                "action": SkuFeedbackAction.SALES_CONTROL,
                "operator_open_id": owner_open_id,
                "comment": "demo callback: sales control applied",
                "value": {
                    "issue_id": issues[0].issue_id,
                    "review_stage": "owner_feedback",
                },
            }
        )
        future = datetime.now(timezone.utc) + timedelta(hours=3, minutes=1)
        reminded = workflow.remind_overdue(future)
        print("\nSimulated callbacks and reminders:")
        for issue in reminded:
            print(f"- {issue.issue_id}: {issue.status} / reminders={issue.reminder_count}")
    elif args.simulate:
        for issue in issues:
            department = {
                "A100": SkuIssueDepartment.SALES,
                "B200": SkuIssueDepartment.PURCHASE,
                "C300": SkuIssueDepartment.SHIPMENT,
            }.get(issue.sku, issue.suggested_department)
            workflow.apply_pmc_review(
                issue.issue_id,
                approved=True,
                operator_open_id=pmc_open_id,
                assignment=SkuIssueAssignment(
                    department=department,
                    owner_open_id=owner_open_id,
                    owner_name="Demo Owner",
                    reason="demo assignment confirmed by PMC",
                ),
                comment="demo pmc approved",
            )
        workflow.apply_owner_feedback(
            issues[0].issue_id,
            SkuIssueFeedback(
                action=SkuFeedbackAction.SALES_CONTROL,
                operator_open_id=owner_open_id,
                comment="demo: sales control applied",
            ),
        )
        future = datetime.now(timezone.utc) + timedelta(hours=3, minutes=1)
        reminded = workflow.remind_overdue(future)
        print("\nSimulated feedback and reminders:")
        for issue in reminded:
            print(f"- {issue.issue_id}: {issue.status} / reminders={issue.reminder_count}")

    summary = workflow.daily_summary(date.today())
    print("\nDaily summary:")
    print(f"- total: {summary.total}")
    print(f"- by_status: {summary.by_status}")
    print(f"- by_department: {summary.by_department}")
    print(f"- overdue_count: {summary.overdue_count}")
    print(f"- high_risk_open_count: {summary.high_risk_open_count}")
    print(f"\nTable: {Path(args.table).resolve()}")
    print("Mode:", "SEND" if args.send else "DRY RUN")
    return 0


def _demo_signals(owner_open_id: str) -> list[SkuIssueSignal]:
    return [
        SkuIssueSignal(
            sku="A100",
            issue_type=SkuIssueType.SHORTAGE,
            risk_level=RiskLevel.HIGH,
            summary="A100 projected stock is negative in 7 days; sales confirmation is needed.",
            suggested_department=SkuIssueDepartment.SALES,
            suggested_owner_open_id=owner_open_id,
            suggested_owner_name="Demo Sales",
            evidence={"projected_7d": -20, "demand_next_30d": 500},
        ),
        SkuIssueSignal(
            sku="B200",
            issue_type=SkuIssueType.REDUNDANT,
            risk_level=RiskLevel.MEDIUM,
            summary="B200 has redundant stock risk; purchase or promotion action may be needed.",
            suggested_department=SkuIssueDepartment.PURCHASE,
            suggested_owner_open_id=owner_open_id,
            suggested_owner_name="Demo Buyer",
            evidence={"projected_7d": 120, "demand_next_30d": 20},
        ),
        SkuIssueSignal(
            sku="C300",
            issue_type=SkuIssueType.SHORTAGE,
            risk_level=RiskLevel.CRITICAL,
            summary="C300 critical shortage risk; shipment acceleration should be checked.",
            suggested_department=SkuIssueDepartment.SHIPMENT,
            suggested_owner_open_id=owner_open_id,
            suggested_owner_name="Demo Shipment",
            evidence={"projected_7d": -60, "demand_next_30d": 760},
        ),
    ]


if __name__ == "__main__":
    raise SystemExit(main())
