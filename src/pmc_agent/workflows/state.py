from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.workflows.items import DailyReviewItem, ReviewDecision, ReviewStage, ReviewStatus


logger = get_logger(__name__)


@dataclass(frozen=True)
class DailyReviewTransition:
    item_id: str
    from_status: ReviewStatus
    to_status: ReviewStatus
    event: str
    timestamp: str
    operator_open_id: str = ""
    comment: str = ""
    detail: dict[str, object] = field(default_factory=dict)


_ALLOWED_TRANSITIONS: dict[ReviewStatus, set[ReviewStatus]] = {
    ReviewStatus.DETECTED: {ReviewStatus.SALES_REVIEW_PENDING},
    ReviewStatus.SALES_REVIEW_PENDING: {ReviewStatus.SALES_REVIEWED, ReviewStatus.SALES_REJECTED},
    ReviewStatus.SALES_REVIEWED: {ReviewStatus.SALES_MANAGER_PENDING},
    ReviewStatus.SALES_REJECTED: {ReviewStatus.RECORDED, ReviewStatus.CLOSED},
    ReviewStatus.SALES_MANAGER_PENDING: {ReviewStatus.SALES_MANAGER_REVIEWED, ReviewStatus.SALES_MANAGER_REJECTED},
    ReviewStatus.SALES_MANAGER_REVIEWED: {ReviewStatus.PMC_REVIEW_PENDING},
    ReviewStatus.SALES_MANAGER_REJECTED: {ReviewStatus.SALES_REVIEW_PENDING, ReviewStatus.RECORDED, ReviewStatus.CLOSED},
    ReviewStatus.PMC_REVIEW_PENDING: {ReviewStatus.PMC_APPROVED, ReviewStatus.PMC_REJECTED},
    ReviewStatus.PMC_APPROVED: {ReviewStatus.RECORDED, ReviewStatus.ESCALATED},
    ReviewStatus.PMC_REJECTED: {ReviewStatus.SALES_REVIEW_PENDING, ReviewStatus.RECORDED, ReviewStatus.CLOSED},
    ReviewStatus.ESCALATED: {ReviewStatus.RECORDED, ReviewStatus.CLOSED},
    ReviewStatus.RECORDED: {ReviewStatus.CLOSED},
    ReviewStatus.CLOSED: set(),
}


class DailyReviewStateMachine:
    def __init__(self) -> None:
        self.history: list[DailyReviewTransition] = []

    def transition(
        self,
        item: DailyReviewItem,
        to_status: ReviewStatus,
        event: str,
        operator_open_id: str = "",
        comment: str = "",
        **detail: object,
    ) -> DailyReviewItem:
        allowed = _ALLOWED_TRANSITIONS.get(item.status, set())
        if to_status not in allowed:
            raise ValueError(f"invalid daily review transition: {item.status.value} -> {to_status.value}")
        transition = DailyReviewTransition(
            item_id=item.item_id,
            from_status=item.status,
            to_status=to_status,
            event=event,
            timestamp=datetime.now(timezone.utc).isoformat(),
            operator_open_id=operator_open_id,
            comment=comment,
            detail=detail,
        )
        self.history.append(transition)
        logger.info(
            "daily review item transitioned",
            extra=log_extra(
                "daily_review_state_transition",
                request_id=item.daily_run_id,
                task_type=item.business_type,
                item_id=item.item_id,
                from_status=item.status.value,
                to_status=to_status.value,
                transition_event=event,
                operator_open_id=operator_open_id or "-",
                **detail,
            ),
        )
        updated = item.with_status(to_status)
        return updated.with_note(comment) if comment else updated

    def apply_decision(self, item: DailyReviewItem, decision: ReviewDecision) -> DailyReviewItem:
        action = decision.action.strip().lower()
        if decision.stage == ReviewStage.SALES:
            target = ReviewStatus.SALES_REVIEWED if action in {"approve", "approved", "pass"} else ReviewStatus.SALES_REJECTED
        elif decision.stage == ReviewStage.SALES_MANAGER:
            target = ReviewStatus.SALES_MANAGER_REVIEWED if action in {"approve", "approved", "pass"} else ReviewStatus.SALES_MANAGER_REJECTED
        elif decision.stage == ReviewStage.PMC:
            target = ReviewStatus.PMC_APPROVED if action in {"approve", "approved", "pass"} else ReviewStatus.PMC_REJECTED
        else:
            raise ValueError(f"unsupported review decision stage: {decision.stage.value}")
        return self.transition(
            item,
            target,
            f"{decision.stage.value}_{action}",
            operator_open_id=decision.operator_open_id,
            comment=decision.comment,
            **decision.metadata,
        )
