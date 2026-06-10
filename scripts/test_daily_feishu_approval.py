from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pmc_agent.domain import RiskLevel
from pmc_agent.env import load_env_file
from pmc_agent.external_integrations.feishu import FeishuWorkflowService
from pmc_agent.workflows import DailyReviewOrchestrator, ReviewDecision, ReviewStage
from pmc_agent.workflows.daily_review import review_item_from_signal


@dataclass
class DemoDailyRobot:
    reviewer_open_id: str
    name: str = "demo_inventory_robot"

    def detect(self, context):
        fixtures = [
            ("A100", RiskLevel.HIGH, -20, 500),
            ("B200", RiskLevel.MEDIUM, 12, 320),
            ("C300", RiskLevel.CRITICAL, -60, 760),
        ]
        return [
            review_item_from_signal(
                business_type="purchase_confirmation",
                title=f"{material_code} 每日库存风险",
                summary=f"{material_code} 触发每日 PMC 风险检查，预计 7 天后库存 {projected_7d}，未来 30 天需求 {demand_30d}。",
                risk_level=risk_level,
                robot_name=self.name,
                owner_open_id=self.reviewer_open_id,
                sales_manager_open_id=self.reviewer_open_id,
                pmc_open_id=self.reviewer_open_id,
                material_code=material_code,
                sales_department="测试销售部",
                suggested_action="请确认销售预测、控销动作，并决定是否进入 PMC 计划池。",
                evidence={"projected_7d": projected_7d, "demand_next_30d": demand_30d},
            )
            for material_code, risk_level, projected_7d, demand_30d in fixtures
        ]


class DryRunWorkflowService:
    def __init__(self) -> None:
        self.submitted = []

    def submit(self, request):
        self.submitted.append(request)
        return _DryResult(request)


class _DryResult:
    ok = True
    status = "pending_review"
    channel = "dry_run"
    error = ""

    def __init__(self, request) -> None:
        self.approval_id = f"dry-{request.request_id}"
        self.review_id = self.approval_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a demo daily PMC approval workflow against Feishu or as a dry run.")
    parser.add_argument("--send", action="store_true", help="Actually create Feishu approval instances. Without this, only prints a dry run.")
    parser.add_argument("--watch", action="store_true", help="Poll Feishu approval status and submit the next stage only after the previous stage is approved.")
    parser.add_argument("--poll-seconds", type=int, default=15, help="Seconds between Feishu approval status polls when --watch is used.")
    parser.add_argument("--max-minutes", type=int, default=30, help="Maximum minutes to watch before exiting.")
    parser.add_argument("--simulate-decisions", action="store_true", help="Locally simulate all approvals instead of waiting for Feishu decisions.")
    parser.add_argument("--reviewer-open-id", default="", help="Open ID used as sales, sales manager, and PMC reviewer. Defaults to FEISHU_TEST_REVIEWER_OPEN_ID or FEISHU_APPROVAL_START_OPEN_ID.")
    parser.add_argument("--run-date", default="", help="YYYY-MM-DD. Defaults to today.")
    args = parser.parse_args()

    load_env_file(override=False)
    if args.send:
        os.environ["FEISHU_REVIEW_MODE"] = "approval"
        os.environ["FEISHU_APPROVAL_ENABLED"] = "true"
    reviewer_open_id = args.reviewer_open_id or os.getenv("FEISHU_TEST_REVIEWER_OPEN_ID") or os.getenv("FEISHU_APPROVAL_START_OPEN_ID")
    if not reviewer_open_id:
        print("Missing reviewer open_id. Set FEISHU_TEST_REVIEWER_OPEN_ID or pass --reviewer-open-id.")
        return 2

    missing = _missing_config(args.send)
    if missing:
        print("Missing required Feishu config:")
        for name in missing:
            print(f"- {name}")
        return 2

    run_date = date.fromisoformat(args.run_date) if args.run_date else date.today()
    workflow_service = FeishuWorkflowService() if args.send else DryRunWorkflowService()
    orchestrator = DailyReviewOrchestrator(
        robots=[DemoDailyRobot(reviewer_open_id=reviewer_open_id)],
        workflow_service=workflow_service,
    )

    context = {"daily_run_id": f"daily-{run_date.strftime('%Y%m%d')}-test-{datetime.now().strftime('%H%M%S')}-{os.getpid()}"}
    batch = orchestrator.start_daily_run(run_date=run_date, context=context)
    print(f"daily_run_id: {batch.daily_run_id}")
    print(f"detected_items: {len(batch.items)}")

    if args.simulate_decisions or not args.send:
        _simulate_decisions(orchestrator, batch.daily_run_id, reviewer_open_id)
    elif args.watch:
        _watch_approvals(orchestrator, batch.daily_run_id, args.poll_seconds, args.max_minutes)

    print("\nSubmitted approvals:")
    submitted = getattr(workflow_service, "submitted", None)
    if submitted is not None:
        for request in submitted:
            stage = request.metadata.get("review_stage", "-")
            print(f"- {stage}: {request.title} -> {', '.join(request.reviewer_open_ids)}")
    else:
        for item in orchestrator.batch(batch.daily_run_id).items:
            sales_approval_id = item.approval_ids.get(ReviewStage.SALES.value, "")
            if sales_approval_id:
                print(f"- sales: {item.title} -> {reviewer_open_id} / {sales_approval_id}")
        for approval_batch in orchestrator.approval_batches.values():
            print(
                f"- {approval_batch.stage.value}: {len(approval_batch.item_ids)} items -> "
                f"{approval_batch.reviewer_open_id} / {approval_batch.approval_id or approval_batch.status}"
            )
    print("\nCurrent item statuses:")
    for item in orchestrator.batch(batch.daily_run_id).items:
        print(f"- {item.item_id}: {item.material_code} / {item.status.value}")
        for note in item.review_notes:
            print(f"  note: {note}")
    failed_batches = [batch for batch in orchestrator.approval_batches.values() if batch.status == "submit_failed"]
    if failed_batches:
        print("\nFailed approval batches:")
        for approval_batch in failed_batches:
            print(f"- {approval_batch.approval_batch_id}: {approval_batch.metadata.get('error', '')}")
    print("\nMode:", "SEND" if args.send else "DRY RUN")
    return 0


def _simulate_decisions(orchestrator: DailyReviewOrchestrator, daily_run_id: str, reviewer_open_id: str) -> None:
    for item in _items_with_status(orchestrator, daily_run_id, "sales_review_pending"):
        orchestrator.apply_sales_decision(
            ReviewDecision(
                item_id=item.item_id,
                stage=ReviewStage.SALES,
                action="approve",
                operator_open_id=reviewer_open_id,
                comment="测试：销售审核通过。",
            )
        )
    orchestrator.submit_sales_manager_reviews(daily_run_id)

    for item in _items_with_status(orchestrator, daily_run_id, "sales_manager_pending"):
        orchestrator.apply_sales_manager_decision(
            ReviewDecision(
                item_id=item.item_id,
                stage=ReviewStage.SALES_MANAGER,
                action="approve",
                operator_open_id=reviewer_open_id,
                comment="测试：销售主管汇总通过。",
            )
        )
    orchestrator.submit_pmc_reviews(daily_run_id)


def _watch_approvals(orchestrator: DailyReviewOrchestrator, daily_run_id: str, poll_seconds: int, max_minutes: int) -> None:
    deadline = datetime.now().timestamp() + max(1, max_minutes) * 60
    poll_seconds = max(3, poll_seconds)
    print("\nWatching Feishu approvals. Approve sales first, then sales manager, then PMC.")
    while datetime.now().timestamp() < deadline:
        batch = orchestrator.sync_approval_statuses(daily_run_id)
        print("\nCurrent item statuses:")
        for item in batch.items:
            print(f"- {item.material_code}: {item.status.value}")
        if all(item.status.value in {"recorded", "closed", "sales_rejected", "sales_manager_rejected", "pmc_rejected"} for item in batch.items):
            print("\nWorkflow reached terminal statuses.")
            return
        import time

        time.sleep(poll_seconds)
    print("\nWatch timed out. Run again with a longer --max-minutes if approvals are still pending.")


def _missing_config(send: bool) -> list[str]:
    if not send:
        return []
    names = [
        "FEISHU_ENABLED",
        "FEISHU_APP_ID",
        "FEISHU_APP_SECRET",
        "FEISHU_APPROVAL_ENABLED",
        "FEISHU_APPROVAL_START_OPEN_ID",
        "FEISHU_APPROVAL_PURCHASE_CODE",
    ]
    return [name for name in names if not os.getenv(name)]


def _items_with_status(orchestrator: DailyReviewOrchestrator, daily_run_id: str, status: str):
    return [item for item in orchestrator.batch(daily_run_id).items if item.status.value == status]


if __name__ == "__main__":
    raise SystemExit(main())
