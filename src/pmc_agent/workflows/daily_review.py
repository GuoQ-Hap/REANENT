from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from typing import Any, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import RiskLevel
from pmc_agent.external_integrations.feishu import FeishuReviewRequest, FeishuWorkflowService
from pmc_agent.workflows.items import DailyReviewBatch, DailyReviewItem, ReviewApprovalBatch, ReviewDecision, ReviewStage, ReviewStatus
from pmc_agent.workflows.state import DailyReviewStateMachine


logger = get_logger(__name__)


class ReviewRobot(Protocol):
    name: str

    def detect(self, context: dict[str, Any]) -> list[DailyReviewItem]:
        ...


@dataclass
class DailyReviewOrchestrator:
    robots: list[ReviewRobot]
    workflow_service: FeishuWorkflowService
    state_machine: DailyReviewStateMachine = field(default_factory=DailyReviewStateMachine)
    items: dict[str, DailyReviewItem] = field(default_factory=dict)
    approval_batches: dict[str, ReviewApprovalBatch] = field(default_factory=dict)

    def start_daily_run(self, run_date: date | None = None, context: dict[str, Any] | None = None) -> DailyReviewBatch:
        run_date = run_date or date.today()
        context = context or {}
        daily_run_id = str(context.get("daily_run_id") or _daily_run_id(run_date))
        context = {"daily_run_id": daily_run_id, "run_date": run_date.isoformat(), **context}
        detected = self._detect_items(daily_run_id, context)
        for item in detected:
            pending = self.state_machine.transition(item, ReviewStatus.SALES_REVIEW_PENDING, "sales_review_requested", recipient_open_id=item.owner_open_id)
            pending = self._submit_stage_approval(pending, ReviewStage.SALES, [pending.owner_open_id])
            self.items[pending.item_id] = pending
        logger.info(
            "daily review run started",
            extra=log_extra("daily_review_run_started", request_id=daily_run_id, item_count=len(detected)),
        )
        return self._batch(daily_run_id, run_date)

    def apply_sales_decision(self, decision: ReviewDecision) -> DailyReviewItem:
        item = self._item(decision.item_id)
        updated = self.state_machine.apply_decision(item, decision)
        self.items[item.item_id] = updated
        return updated

    def sync_approval_statuses(self, daily_run_id: str, finalize_pmc: bool = True) -> DailyReviewBatch:
        """Pull Feishu approval results and advance the daily review chain in order."""
        for item in list(self.items.values()):
            if item.daily_run_id != daily_run_id or item.status != ReviewStatus.SALES_REVIEW_PENDING:
                continue
            self._sync_item_approval(item, ReviewStage.SALES)
        self.submit_sales_manager_reviews(daily_run_id)

        for approval_batch in list(self.approval_batches.values()):
            if approval_batch.daily_run_id != daily_run_id or approval_batch.stage != ReviewStage.SALES_MANAGER:
                continue
            self._sync_batch_approval(approval_batch)
        self.submit_pmc_reviews(daily_run_id)

        for approval_batch in list(self.approval_batches.values()):
            if approval_batch.daily_run_id != daily_run_id or approval_batch.stage != ReviewStage.PMC:
                continue
            self._sync_batch_approval(approval_batch)

        if finalize_pmc:
            for item in list(self.items.values()):
                if item.daily_run_id == daily_run_id and item.status == ReviewStatus.PMC_APPROVED:
                    self.finalize_pmc_item(item.item_id, escalate=_should_escalate(item), comment="PMC 审批通过，自动记录。")
        return self.batch(daily_run_id)

    def submit_sales_manager_reviews(self, daily_run_id: str) -> list[DailyReviewItem]:
        submitted: list[DailyReviewItem] = []
        for manager_open_id, group in self._groups(daily_run_id, ReviewStatus.SALES_REVIEWED, "sales_manager_open_id").items():
            pending_group = [
                self.state_machine.transition(item, ReviewStatus.SALES_MANAGER_PENDING, "sales_manager_review_requested", recipient_open_id=manager_open_id)
                for item in group
            ]
            approval_batch = self._submit_stage_batch_approval(daily_run_id, ReviewStage.SALES_MANAGER, manager_open_id, pending_group)
            self.approval_batches[approval_batch.approval_batch_id] = approval_batch
            approval_id = approval_batch.approval_id
            item_ids = set(approval_batch.item_ids)
            stage_key = ReviewStage.SALES_MANAGER.value
            for item in group:
                pending = next(updated for updated in pending_group if updated.item_id == item.item_id)
                if pending.item_id in item_ids:
                    pending = pending.with_approval(ReviewStage.SALES_MANAGER, approval_id)
                    pending = replace(pending, metadata={**pending.metadata, f"{stage_key}_approval_batch_id": approval_batch.approval_batch_id})
                self.items[pending.item_id] = pending
                submitted.append(pending)
        return submitted

    def apply_sales_manager_decision(self, decision: ReviewDecision) -> DailyReviewItem:
        item = self._item(decision.item_id)
        updated = self.state_machine.apply_decision(item, decision)
        self.items[item.item_id] = updated
        return updated

    def submit_pmc_reviews(self, daily_run_id: str) -> list[DailyReviewItem]:
        submitted: list[DailyReviewItem] = []
        for pmc_open_id, group in self._groups(daily_run_id, ReviewStatus.SALES_MANAGER_REVIEWED, "pmc_open_id").items():
            pending_group = [
                self.state_machine.transition(item, ReviewStatus.PMC_REVIEW_PENDING, "pmc_review_requested", recipient_open_id=pmc_open_id)
                for item in group
            ]
            approval_batch = self._submit_stage_batch_approval(daily_run_id, ReviewStage.PMC, pmc_open_id, pending_group)
            self.approval_batches[approval_batch.approval_batch_id] = approval_batch
            approval_id = approval_batch.approval_id
            item_ids = set(approval_batch.item_ids)
            stage_key = ReviewStage.PMC.value
            for item in group:
                pending = next(updated for updated in pending_group if updated.item_id == item.item_id)
                if pending.item_id in item_ids:
                    pending = pending.with_approval(ReviewStage.PMC, approval_id)
                    pending = replace(pending, metadata={**pending.metadata, f"{stage_key}_approval_batch_id": approval_batch.approval_batch_id})
                self.items[pending.item_id] = pending
                submitted.append(pending)
        return submitted

    def apply_pmc_decision(self, decision: ReviewDecision) -> DailyReviewItem:
        item = self._item(decision.item_id)
        updated = self.state_machine.apply_decision(item, decision)
        self.items[item.item_id] = updated
        return updated

    def finalize_pmc_item(self, item_id: str, escalate: bool = False, comment: str = "") -> DailyReviewItem:
        item = self._item(item_id)
        if item.status != ReviewStatus.PMC_APPROVED:
            raise ValueError(f"item must be pmc_approved before finalizing: {item.status.value}")
        target = ReviewStatus.ESCALATED if escalate else ReviewStatus.RECORDED
        updated = self.state_machine.transition(item, target, "pmc_finalized", comment=comment)
        if escalate:
            updated = self.state_machine.transition(updated, ReviewStatus.RECORDED, "escalation_recorded")
        self.items[item_id] = updated
        return updated

    def batch(self, daily_run_id: str, run_date: date | None = None) -> DailyReviewBatch:
        return self._batch(daily_run_id, run_date or _date_from_run_id(daily_run_id))

    def _detect_items(self, daily_run_id: str, context: dict[str, Any]) -> list[DailyReviewItem]:
        seen: set[tuple[str, str, str]] = set()
        items: list[DailyReviewItem] = []
        for robot in self.robots:
            for index, item in enumerate(robot.detect(context), start=1):
                key = (item.business_type, item.material_code, item.owner_open_id)
                if key in seen:
                    continue
                seen.add(key)
                item_id = item.item_id or f"{daily_run_id}-{robot.name}-{index:04d}"
                normalized = replace(
                    item,
                    item_id=item_id,
                    daily_run_id=daily_run_id,
                    robot_name=item.robot_name or robot.name,
                    status=ReviewStatus.DETECTED,
                )
                items.append(normalized)
        return items

    def _submit_stage_approval(self, item: DailyReviewItem, stage: ReviewStage, reviewer_open_ids: list[str]) -> DailyReviewItem:
        title_prefix = {
            ReviewStage.SALES: "销售审核",
            ReviewStage.SALES_MANAGER: "销售主管汇总",
            ReviewStage.PMC: "PMC审核",
        }.get(stage, "审核")
        result = self.workflow_service.submit(
            FeishuReviewRequest(
                request_id=f"{item.item_id}-{stage.value}",
                business_type=item.business_type,
                title=f"{title_prefix}：{item.title}",
                summary=item.summary,
                business_object={
                    "material_code": item.material_code,
                    "sales_department": item.sales_department,
                    "robot_name": item.robot_name,
                    **item.evidence,
                },
                suggested_action=item.suggested_action,
                risk_level=item.risk_level.value,
                reviewer_open_ids=tuple(reviewer_open_ids),
                metadata={"daily_run_id": item.daily_run_id, "item_id": item.item_id, "review_stage": stage.value, **item.metadata},
            )
        )
        if not result.ok:
            logger.warning(
                "daily review approval submit failed",
                extra=log_extra("daily_review_approval_submit_failed", request_id=item.daily_run_id, task_type=item.business_type, item_id=item.item_id, stage=stage.value, error=result.error),
            )
            return item.with_note(f"{stage.value} approval submit failed: {result.error}")
        approval_id = str(getattr(result, "approval_id", "") or getattr(result, "review_id", ""))
        return item.with_approval(stage, approval_id)

    def _submit_stage_batch_approval(
        self,
        daily_run_id: str,
        stage: ReviewStage,
        reviewer_open_id: str,
        items: list[DailyReviewItem],
    ) -> ReviewApprovalBatch:
        approval_batch_id = f"{daily_run_id}-{stage.value}-{reviewer_open_id}"
        if not items:
            return ReviewApprovalBatch(
                approval_batch_id=approval_batch_id,
                daily_run_id=daily_run_id,
                stage=stage,
                reviewer_open_id=reviewer_open_id,
                item_ids=[],
                status="empty",
            )
        title_prefix = {
            ReviewStage.SALES_MANAGER: "销售主管汇总",
            ReviewStage.PMC: "PMC审核汇总",
        }.get(stage, "审核汇总")
        result = self.workflow_service.submit(
            FeishuReviewRequest(
                request_id=approval_batch_id,
                business_type=_batch_business_type(stage),
                title=f"{title_prefix}：{len(items)} 条待审核事项",
                summary=_batch_summary(items),
                business_object=_batch_business_object(items),
                suggested_action=_batch_suggested_action(stage, items),
                risk_level=_max_risk_level(items).value,
                reviewer_open_ids=(reviewer_open_id,),
                metadata={
                    "daily_run_id": daily_run_id,
                    "review_stage": stage.value,
                    "approval_batch_id": approval_batch_id,
                    "item_ids": [item.item_id for item in items],
                },
            )
        )
        if not result.ok:
            logger.warning(
                "daily review batch approval submit failed",
                extra=log_extra("daily_review_batch_approval_submit_failed", request_id=daily_run_id, task_type=stage.value, approval_batch_id=approval_batch_id, error=result.error),
            )
            return ReviewApprovalBatch(
                approval_batch_id=approval_batch_id,
                daily_run_id=daily_run_id,
                stage=stage,
                reviewer_open_id=reviewer_open_id,
                item_ids=[item.item_id for item in items],
                status="submit_failed",
                metadata={"error": result.error},
            )
        approval_id = str(getattr(result, "approval_id", "") or getattr(result, "review_id", ""))
        return ReviewApprovalBatch(
            approval_batch_id=approval_batch_id,
            daily_run_id=daily_run_id,
            stage=stage,
            reviewer_open_id=reviewer_open_id,
            item_ids=[item.item_id for item in items],
            approval_id=approval_id,
            status=result.status,
            metadata={"channel": getattr(result, "channel", ""), "risk_level": _max_risk_level(items).value},
        )

    def _sync_item_approval(self, item: DailyReviewItem, stage: ReviewStage) -> DailyReviewItem:
        approval_id = item.approval_ids.get(stage.value, "")
        if not approval_id:
            return item
        instance = self.workflow_service.get_approval_instance(approval_id)
        if not instance.ok:
            updated = item.with_note(instance.error)
            self.items[item.item_id] = updated
            return updated
        action = _decision_action_for_status(instance.status)
        if not action:
            return item
        decision = ReviewDecision(
            item_id=item.item_id,
            stage=stage,
            action=action,
            operator_open_id=instance.operator_open_id,
            comment=instance.comment,
            metadata={"approval_id": approval_id, "approval_status": instance.status},
        )
        if stage == ReviewStage.SALES:
            return self.apply_sales_decision(decision)
        if stage == ReviewStage.SALES_MANAGER:
            return self.apply_sales_manager_decision(decision)
        if stage == ReviewStage.PMC:
            return self.apply_pmc_decision(decision)
        return item

    def _sync_batch_approval(self, approval_batch: ReviewApprovalBatch) -> ReviewApprovalBatch:
        if approval_batch.status in {"approved", "rejected", "cancelled", "deleted", "submit_failed", "empty"}:
            return approval_batch
        if not approval_batch.approval_id:
            return approval_batch
        instance = self.workflow_service.get_approval_instance(approval_batch.approval_id)
        if not instance.ok:
            updated = replace(approval_batch, metadata={**approval_batch.metadata, "sync_error": instance.error})
            self.approval_batches[approval_batch.approval_batch_id] = updated
            return updated
        action = _decision_action_for_status(instance.status)
        if not action:
            updated = replace(approval_batch, status=instance.status or approval_batch.status)
            self.approval_batches[approval_batch.approval_batch_id] = updated
            return updated
        for item_id in approval_batch.item_ids:
            if item_id not in self.items:
                continue
            item = self.items[item_id]
            if not _can_apply_stage_decision(item, approval_batch.stage):
                continue
            decision = ReviewDecision(
                item_id=item_id,
                stage=approval_batch.stage,
                action=action,
                operator_open_id=instance.operator_open_id,
                comment=instance.comment,
                metadata={"approval_id": approval_batch.approval_id, "approval_status": instance.status, "approval_batch_id": approval_batch.approval_batch_id},
            )
            if approval_batch.stage == ReviewStage.SALES_MANAGER:
                self.apply_sales_manager_decision(decision)
            elif approval_batch.stage == ReviewStage.PMC:
                self.apply_pmc_decision(decision)
        updated = replace(approval_batch, status=instance.status, metadata={**approval_batch.metadata, "last_synced_approval_status": instance.status})
        self.approval_batches[approval_batch.approval_batch_id] = updated
        return updated

    def _groups(self, daily_run_id: str, status: ReviewStatus, attr: str) -> dict[str, list[DailyReviewItem]]:
        groups: dict[str, list[DailyReviewItem]] = defaultdict(list)
        for item in self.items.values():
            if item.daily_run_id != daily_run_id or item.status != status:
                continue
            key = str(getattr(item, attr))
            if key:
                groups[key].append(item)
        return groups

    def _item(self, item_id: str) -> DailyReviewItem:
        if item_id not in self.items:
            raise KeyError(f"daily review item not found: {item_id}")
        return self.items[item_id]

    def _batch(self, daily_run_id: str, run_date: date) -> DailyReviewBatch:
        items = [item for item in self.items.values() if item.daily_run_id == daily_run_id]
        counts = Counter(item.status.value for item in items)
        risk_counts = Counter(item.risk_level.value for item in items)
        return DailyReviewBatch(
            daily_run_id=daily_run_id,
            run_date=run_date,
            items=items,
            status_counts=dict(counts),
            metadata={"risk_counts": dict(risk_counts), "item_count": len(items)},
        )


def _daily_run_id(run_date: date) -> str:
    return f"daily-{run_date.strftime('%Y%m%d')}"


def _date_from_run_id(daily_run_id: str) -> date:
    try:
        return datetime.strptime(daily_run_id.removeprefix("daily-"), "%Y%m%d").date()
    except ValueError:
        return date.today()


def _batch_business_type(stage: ReviewStage) -> str:
    return {
        ReviewStage.SALES_MANAGER: "sales_manager_summary",
        ReviewStage.PMC: "pmc_summary",
    }.get(stage, "daily_review_summary")


def _batch_summary(items: list[DailyReviewItem]) -> str:
    risk_counts = Counter(item.risk_level.value for item in items)
    lines = [
        f"本批次共有 {len(items)} 条待审核事项。",
        "风险分布：" + ", ".join(f"{risk}={count}" for risk, count in sorted(risk_counts.items())),
        "",
        "事项明细：",
    ]
    for index, item in enumerate(items[:20], start=1):
        code = f"{item.material_code} " if item.material_code else ""
        lines.append(f"{index}. [{item.risk_level.value}] {code}{item.title} - {item.summary}")
    if len(items) > 20:
        lines.append(f"... 另有 {len(items) - 20} 条事项。")
    return "\n".join(lines)


def _batch_business_object(items: list[DailyReviewItem]) -> dict[str, Any]:
    departments = sorted({item.sales_department for item in items if item.sales_department})
    material_codes = [item.material_code for item in items if item.material_code]
    return {
        "item_count": len(items),
        "risk_counts": dict(Counter(item.risk_level.value for item in items)),
        "sales_departments": departments,
        "material_codes": material_codes[:50],
        "items": [
            {
                "item_id": item.item_id,
                "material_code": item.material_code,
                "risk_level": item.risk_level.value,
                "title": item.title,
                "owner_open_id": item.owner_open_id,
                "summary": item.summary,
            }
            for item in items[:20]
        ],
    }


def _batch_suggested_action(stage: ReviewStage, items: list[DailyReviewItem]) -> str:
    if stage == ReviewStage.SALES_MANAGER:
        return "请销售主管确认本批事项是否属实，并汇总销售侧处理意见后提交 PMC。"
    if stage == ReviewStage.PMC:
        high_count = sum(1 for item in items if item.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL})
        return f"请 PMC 复核本批事项，确认是否进入计划池、创建异常 Case 或上报。高风险事项 {high_count} 条。"
    return "请审核本批每日事项。"


def _max_risk_level(items: list[DailyReviewItem]) -> RiskLevel:
    order = {
        RiskLevel.LOW: 0,
        RiskLevel.MEDIUM: 1,
        RiskLevel.HIGH: 2,
        RiskLevel.CRITICAL: 3,
    }
    return max((item.risk_level for item in items), key=lambda level: order[level], default=RiskLevel.LOW)


def _decision_action_for_status(status: str) -> str:
    normalized = status.strip().lower()
    if normalized == "approved":
        return "approve"
    if normalized in {"rejected", "cancelled", "deleted"}:
        return "reject"
    return ""


def _can_apply_stage_decision(item: DailyReviewItem, stage: ReviewStage) -> bool:
    return {
        ReviewStage.SALES: ReviewStatus.SALES_REVIEW_PENDING,
        ReviewStage.SALES_MANAGER: ReviewStatus.SALES_MANAGER_PENDING,
        ReviewStage.PMC: ReviewStatus.PMC_REVIEW_PENDING,
    }.get(stage) == item.status


def _should_escalate(item: DailyReviewItem) -> bool:
    return bool(item.metadata.get("escalate_after_pmc")) or item.risk_level == RiskLevel.CRITICAL


def review_item_from_signal(
    *,
    business_type: str,
    title: str,
    summary: str,
    risk_level: RiskLevel,
    robot_name: str,
    owner_open_id: str,
    sales_manager_open_id: str,
    pmc_open_id: str,
    material_code: str = "",
    daily_run_id: str = "",
    item_id: str = "",
    sales_department: str = "",
    suggested_action: str = "",
    evidence: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> DailyReviewItem:
    return DailyReviewItem(
        item_id=item_id,
        daily_run_id=daily_run_id,
        business_type=business_type,
        title=title,
        summary=summary,
        risk_level=risk_level,
        robot_name=robot_name,
        owner_open_id=owner_open_id,
        sales_manager_open_id=sales_manager_open_id,
        pmc_open_id=pmc_open_id,
        material_code=material_code,
        sales_department=sales_department,
        suggested_action=suggested_action,
        evidence=evidence or {},
        metadata=metadata or {},
    )
