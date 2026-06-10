from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum
from typing import Any

from pmc_agent.domain import RiskLevel


class ReviewStage(str, Enum):
    SALES = "sales"
    SALES_MANAGER = "sales_manager"
    PMC = "pmc"
    ESCALATION = "escalation"


class ReviewStatus(str, Enum):
    DETECTED = "detected"
    SALES_REVIEW_PENDING = "sales_review_pending"
    SALES_REVIEWED = "sales_reviewed"
    SALES_REJECTED = "sales_rejected"
    SALES_MANAGER_PENDING = "sales_manager_pending"
    SALES_MANAGER_REVIEWED = "sales_manager_reviewed"
    SALES_MANAGER_REJECTED = "sales_manager_rejected"
    PMC_REVIEW_PENDING = "pmc_review_pending"
    PMC_APPROVED = "pmc_approved"
    PMC_REJECTED = "pmc_rejected"
    ESCALATED = "escalated"
    RECORDED = "recorded"
    CLOSED = "closed"


@dataclass(frozen=True)
class DailyReviewItem:
    item_id: str
    daily_run_id: str
    business_type: str
    title: str
    summary: str
    risk_level: RiskLevel
    robot_name: str
    owner_open_id: str
    sales_manager_open_id: str
    pmc_open_id: str
    material_code: str = ""
    sales_department: str = ""
    suggested_action: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    status: ReviewStatus = ReviewStatus.DETECTED
    approval_ids: dict[str, str] = field(default_factory=dict)
    review_notes: list[str] = field(default_factory=list)

    def with_status(self, status: ReviewStatus) -> "DailyReviewItem":
        return replace(self, status=status)

    def with_approval(self, stage: ReviewStage, approval_id: str) -> "DailyReviewItem":
        approvals = {**self.approval_ids}
        if approval_id:
            approvals[stage.value] = approval_id
        return replace(self, approval_ids=approvals)

    def with_note(self, note: str) -> "DailyReviewItem":
        if not note:
            return self
        return replace(self, review_notes=[*self.review_notes, note])


@dataclass(frozen=True)
class ReviewDecision:
    item_id: str
    stage: ReviewStage
    action: str
    operator_open_id: str
    comment: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DailyReviewBatch:
    daily_run_id: str
    run_date: date
    items: list[DailyReviewItem]
    status_counts: dict[str, int]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReviewApprovalBatch:
    approval_batch_id: str
    daily_run_id: str
    stage: ReviewStage
    reviewer_open_id: str
    item_ids: list[str]
    approval_id: str = ""
    status: str = "pending_review"
    metadata: dict[str, Any] = field(default_factory=dict)
