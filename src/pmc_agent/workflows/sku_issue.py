from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import RiskLevel
from pmc_agent.external_integrations.feishu import FeishuReviewRequest, FeishuWorkflowCallback, FeishuWorkflowService


logger = get_logger(__name__)


class SkuIssueType(str):
    SHORTAGE = "shortage"
    REDUNDANT = "redundant"


class SkuIssueDepartment(str):
    SALES = "sales"
    PURCHASE = "purchase"
    SHIPMENT = "shipment"
    PMC = "pmc"


class SkuIssueStatus(str):
    AGENT_DETECTED = "agent_detected"
    PMC_REVIEW_PENDING = "pmc_review_pending"
    PMC_REJECTED = "pmc_rejected"
    OWNER_FEEDBACK_PENDING = "owner_feedback_pending"
    OWNER_FEEDBACK_REMINDED = "owner_feedback_reminded"
    OWNER_FEEDBACK_DONE = "owner_feedback_done"
    RECORDED = "recorded"
    ESCALATED = "escalated"
    CLOSED = "closed"


class SkuFeedbackAction(str):
    EXPEDITE_SHIPMENT = "expedite_shipment"
    PURCHASE_REPLENISHMENT = "purchase_replenishment"
    SALES_CONTROL = "sales_control"
    PROMOTION = "promotion"
    NO_ACTION = "no_action"
    DATA_ISSUE = "data_issue"
    NEED_DECISION = "need_decision"


@dataclass(frozen=True)
class SkuIssueSignal:
    sku: str
    issue_type: str
    risk_level: RiskLevel
    summary: str
    suggested_department: str
    suggested_owner_open_id: str = ""
    suggested_owner_name: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    detected_at: str = ""
    issue_id: str = ""


@dataclass(frozen=True)
class SkuIssueAssignment:
    department: str
    owner_open_id: str
    owner_name: str = ""
    due_hours: int = 3
    modified_by_open_id: str = ""
    reason: str = ""


@dataclass(frozen=True)
class SkuIssueFeedback:
    action: str
    operator_open_id: str
    actions: list[str] = field(default_factory=list)
    comment: str = ""
    eta: str = ""
    feedback_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkuIssueRecord:
    issue_id: str
    sku: str
    issue_type: str
    risk_level: RiskLevel
    summary: str
    suggested_department: str
    suggested_owner_open_id: str = ""
    suggested_owner_name: str = ""
    status: str = SkuIssueStatus.AGENT_DETECTED
    pmc_open_id: str = ""
    pmc_approval_id: str = ""
    assignment: SkuIssueAssignment | None = None
    feedback: SkuIssueFeedback | None = None
    reminder_count: int = 0
    detected_at: str = ""
    pmc_reviewed_at: str = ""
    feedback_requested_at: str = ""
    last_reminded_at: str = ""
    recorded_at: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def with_note(self, note: str) -> "SkuIssueRecord":
        if not note:
            return self
        return replace(self, notes=[*self.notes, note])


@dataclass(frozen=True)
class SkuIssueSummary:
    start_date: date
    end_date: date
    total: int
    by_status: dict[str, int]
    by_department: dict[str, int]
    by_issue_type: dict[str, int]
    overdue_count: int
    high_risk_open_count: int


class SkuIssueRepository(Protocol):
    def save(self, issue: SkuIssueRecord) -> None:
        ...

    def get(self, issue_id: str) -> SkuIssueRecord:
        ...

    def list(self) -> list[SkuIssueRecord]:
        ...


class InMemorySkuIssueRepository:
    def __init__(self) -> None:
        self.records: dict[str, SkuIssueRecord] = {}

    def save(self, issue: SkuIssueRecord) -> None:
        self.records[issue.issue_id] = issue

    def get(self, issue_id: str) -> SkuIssueRecord:
        if issue_id not in self.records:
            raise KeyError(f"sku issue not found: {issue_id}")
        return self.records[issue_id]

    def list(self) -> list[SkuIssueRecord]:
        return list(self.records.values())


class JsonlSkuIssueRepository:
    def __init__(self, path: str | Path = "output/sku_issue_records.jsonl") -> None:
        self.path = Path(path)

    def save(self, issue: SkuIssueRecord) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(_issue_to_dict(issue), ensure_ascii=False) + "\n")

    def get(self, issue_id: str) -> SkuIssueRecord:
        records = {issue.issue_id: issue for issue in self.list()}
        if issue_id not in records:
            raise KeyError(f"sku issue not found: {issue_id}")
        return records[issue_id]

    def list(self) -> list[SkuIssueRecord]:
        if not self.path.exists():
            return []
        latest: dict[str, SkuIssueRecord] = {}
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                payload = json.loads(line)
                issue = _issue_from_dict(payload)
                latest[issue.issue_id] = issue
        return list(latest.values())


@dataclass
class SkuIssueWorkflow:
    workflow_service: FeishuWorkflowService
    repository: SkuIssueRepository = field(default_factory=InMemorySkuIssueRepository)

    def detect_issue(self, signal: SkuIssueSignal, pmc_open_id: str) -> SkuIssueRecord:
        now = _now()
        issue = SkuIssueRecord(
            issue_id=signal.issue_id or _issue_id(signal, now),
            sku=signal.sku,
            issue_type=signal.issue_type,
            risk_level=signal.risk_level,
            summary=signal.summary,
            suggested_department=signal.suggested_department,
            suggested_owner_open_id=signal.suggested_owner_open_id,
            suggested_owner_name=signal.suggested_owner_name,
            status=SkuIssueStatus.PMC_REVIEW_PENDING,
            pmc_open_id=pmc_open_id,
            detected_at=signal.detected_at or now,
            evidence=signal.evidence,
        )
        issue = self._submit_pmc_review(issue)
        self.repository.save(issue)
        logger.info(
            "sku issue detected",
            extra=log_extra("sku_issue_detected", request_id=issue.issue_id, task_type=issue.issue_type, sku=issue.sku, status=issue.status),
        )
        return issue

    def apply_pmc_review(
        self,
        issue_id: str,
        *,
        approved: bool,
        operator_open_id: str,
        assignment: SkuIssueAssignment | None = None,
        comment: str = "",
    ) -> SkuIssueRecord:
        issue = self.repository.get(issue_id)
        if issue.status != SkuIssueStatus.PMC_REVIEW_PENDING:
            raise ValueError(f"issue must be pmc_review_pending: {issue.status}")
        now = _now()
        if not approved:
            updated = replace(
                issue.with_note(comment),
                status=SkuIssueStatus.PMC_REJECTED,
                pmc_reviewed_at=now,
            )
            self.repository.save(updated)
            return updated

        resolved_assignment = assignment or _default_assignment(issue, operator_open_id)
        updated = replace(
            issue.with_note(comment),
            status=SkuIssueStatus.OWNER_FEEDBACK_PENDING,
            assignment=resolved_assignment,
            pmc_reviewed_at=now,
            feedback_requested_at=now,
        )
        updated = self._submit_owner_feedback(updated, is_reminder=False)
        self.repository.save(updated)
        return updated

    def apply_owner_feedback(self, issue_id: str, feedback: SkuIssueFeedback) -> SkuIssueRecord:
        issue = self.repository.get(issue_id)
        if issue.status == SkuIssueStatus.RECORDED:
            return issue
        if issue.status not in {SkuIssueStatus.OWNER_FEEDBACK_PENDING, SkuIssueStatus.OWNER_FEEDBACK_REMINDED}:
            raise ValueError(f"issue must wait for owner feedback: {issue.status}")
        now = _now()
        feedback = replace(feedback, feedback_at=feedback.feedback_at or now)
        updated = replace(
            issue.with_note(feedback.comment),
            status=SkuIssueStatus.RECORDED,
            feedback=feedback,
            recorded_at=now,
        )
        self.repository.save(updated)
        return updated

    def handle_feishu_callback(self, payload: dict[str, Any]) -> SkuIssueRecord:
        callback = self.workflow_service.parse_callback(payload)
        return self.apply_callback(callback)

    def apply_callback(self, callback: FeishuWorkflowCallback) -> SkuIssueRecord:
        fields = callback.fields
        issue_id = str(fields.get("issue_id") or _issue_id_from_request_id(callback.request_id) or callback.request_id)
        review_stage = str(fields.get("review_stage") or "")
        action = callback.action.strip().lower()
        if review_stage == "pmc_initial_review":
            return self.apply_pmc_review(
                issue_id,
                approved=action in {"approve", "approved", "pass"},
                operator_open_id=callback.operator_open_id,
                assignment=_assignment_from_callback(fields, callback.operator_open_id),
                comment=callback.comment,
            )
        if review_stage == "owner_feedback":
            feedback_actions = _feedback_actions_from_callback(action, fields)
            return self.apply_owner_feedback(
                issue_id,
                SkuIssueFeedback(
                    action=feedback_actions[0],
                    actions=feedback_actions,
                    operator_open_id=callback.operator_open_id,
                    comment=str(fields.get("feedback_comment") or fields.get("comment") or callback.comment),
                    eta=str(fields.get("eta") or ""),
                    metadata={key: value for key, value in fields.items() if key not in {"issue_id", "review_stage", "eta"}},
                ),
            )
        raise ValueError(f"unsupported sku issue callback stage: {review_stage or '-'}")

    def remind_overdue(self, now: datetime | None = None, max_reminders: int = 2) -> list[SkuIssueRecord]:
        now = now or datetime.now(timezone.utc)
        reminded: list[SkuIssueRecord] = []
        for issue in self.repository.list():
            if not _is_waiting_for_feedback(issue):
                continue
            if not _is_feedback_overdue(issue, now):
                continue
            if issue.reminder_count >= max_reminders:
                updated = replace(issue, status=SkuIssueStatus.ESCALATED, last_reminded_at=_iso(now)).with_note("owner feedback overdue; escalated to PMC")
                self.repository.save(updated)
                reminded.append(updated)
                continue
            updated = replace(
                issue,
                status=SkuIssueStatus.OWNER_FEEDBACK_REMINDED,
                reminder_count=issue.reminder_count + 1,
                last_reminded_at=_iso(now),
            )
            updated = self._submit_owner_feedback(updated, is_reminder=True)
            self.repository.save(updated)
            reminded.append(updated)
        return reminded

    def daily_summary(self, day: date) -> SkuIssueSummary:
        return self.summary(day, day)

    def weekly_summary(self, week_start: date) -> SkuIssueSummary:
        return self.summary(week_start, week_start + timedelta(days=6))

    def summary(self, start_date: date, end_date: date) -> SkuIssueSummary:
        issues = [issue for issue in self.repository.list() if _date_in_range(_issue_date(issue), start_date, end_date)]
        by_status = Counter(issue.status for issue in issues)
        by_department = Counter((issue.assignment.department if issue.assignment else issue.suggested_department) for issue in issues)
        by_issue_type = Counter(issue.issue_type for issue in issues)
        overdue_count = sum(1 for issue in issues if _is_waiting_for_feedback(issue) and _is_feedback_overdue(issue, datetime.now(timezone.utc)))
        high_risk_open_count = sum(
            1
            for issue in issues
            if issue.risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL} and issue.status not in {SkuIssueStatus.RECORDED, SkuIssueStatus.CLOSED}
        )
        return SkuIssueSummary(
            start_date=start_date,
            end_date=end_date,
            total=len(issues),
            by_status=dict(by_status),
            by_department=dict(by_department),
            by_issue_type=dict(by_issue_type),
            overdue_count=overdue_count,
            high_risk_open_count=high_risk_open_count,
        )

    def _submit_pmc_review(self, issue: SkuIssueRecord) -> SkuIssueRecord:
        result = self.workflow_service.submit(
            FeishuReviewRequest(
                request_id=f"{issue.issue_id}-pmc-review",
                business_type="pmc_sku_issue_review",
                title=f"PMC初审：{issue.sku} {issue.issue_type}",
                summary=issue.summary,
                business_object={
                    "sku": issue.sku,
                    "issue_type": issue.issue_type,
                    "suggested_department": issue.suggested_department,
                    "suggested_owner": issue.suggested_owner_name or issue.suggested_owner_open_id,
                    **issue.evidence,
                },
                suggested_action="请 PMC 确认问题、处理部门和具体处理人；可修改处理人后再分派。",
                risk_level=issue.risk_level.value,
                reviewer_open_ids=(issue.pmc_open_id,),
                metadata={
                    "issue_id": issue.issue_id,
                    "review_stage": "pmc_initial_review",
                    "assignment_department": issue.suggested_department,
                    "assignment_owner_open_id": issue.suggested_owner_open_id,
                    "assignment_owner_name": issue.suggested_owner_name,
                },
            )
        )
        if not result.ok:
            return issue.with_note(f"pmc review submit failed: {result.error}")
        approval_id = str(getattr(result, "approval_id", "") or getattr(result, "review_id", ""))
        return replace(issue, pmc_approval_id=approval_id)

    def _submit_owner_feedback(self, issue: SkuIssueRecord, *, is_reminder: bool) -> SkuIssueRecord:
        if not issue.assignment or not issue.assignment.owner_open_id:
            return issue.with_note("owner feedback not sent: missing owner_open_id")
        title_prefix = "反馈催办" if is_reminder else "处理反馈"
        result = self.workflow_service.review_client.submit_review(
            FeishuReviewRequest(
                request_id=f"{issue.issue_id}-owner-feedback-{issue.reminder_count}",
                business_type=f"{issue.assignment.department}_sku_feedback",
                title=f"{title_prefix}：{issue.sku} {issue.issue_type}",
                summary=issue.summary,
                business_object={
                    "sku": issue.sku,
                    "issue_type": issue.issue_type,
                    "department": issue.assignment.department,
                    "owner": issue.assignment.owner_name or issue.assignment.owner_open_id,
                    "reminder_count": issue.reminder_count,
                },
                suggested_action="请反馈处理方式：加急发货、补采购、销售控销、促销、数据有误、暂不处理或需上级决策。",
                risk_level=issue.risk_level.value,
                reviewer_open_ids=(issue.assignment.owner_open_id,),
                metadata={"issue_id": issue.issue_id, "review_stage": "owner_feedback", "is_reminder": is_reminder},
            )
        )
        if not result.ok:
            return issue.with_note(f"owner feedback submit failed: {result.error}")
        return issue


def _default_assignment(issue: SkuIssueRecord, operator_open_id: str) -> SkuIssueAssignment:
    return SkuIssueAssignment(
        department=issue.suggested_department,
        owner_open_id=issue.suggested_owner_open_id,
        owner_name=issue.suggested_owner_name,
        modified_by_open_id=operator_open_id,
        reason="pmc accepted agent suggestion",
    )


def _assignment_from_callback(fields: dict[str, Any], operator_open_id: str) -> SkuIssueAssignment | None:
    department = str(fields.get("assignment_department") or fields.get("department") or "")
    owner_open_id = str(fields.get("assignment_owner_open_id") or fields.get("owner_open_id") or "")
    owner_name = str(fields.get("assignment_owner_name") or fields.get("owner_name") or "")
    if not department and not owner_open_id and not owner_name:
        return None
    return SkuIssueAssignment(
        department=department,
        owner_open_id=owner_open_id,
        owner_name=owner_name,
        due_hours=_int_value(fields.get("due_hours"), default=3),
        modified_by_open_id=operator_open_id,
        reason=str(fields.get("assignment_reason") or "pmc callback assignment"),
    )


def _feedback_actions_from_callback(action: str, fields: dict[str, Any]) -> list[str]:
    selected = fields.get("feedback_actions")
    if isinstance(selected, str):
        selected = [selected]
    if isinstance(selected, list):
        valid = [str(item) for item in selected if _is_feedback_action(str(item))]
        if valid:
            return valid
    explicit = str(fields.get("feedback_action") or fields.get("owner_feedback_action") or "")
    candidate = explicit or action
    if _is_feedback_action(candidate):
        return [candidate]
    return [SkuFeedbackAction.NEED_DECISION]


def _is_feedback_action(candidate: str) -> bool:
    return candidate in {
        SkuFeedbackAction.EXPEDITE_SHIPMENT,
        SkuFeedbackAction.PURCHASE_REPLENISHMENT,
        SkuFeedbackAction.SALES_CONTROL,
        SkuFeedbackAction.PROMOTION,
        SkuFeedbackAction.NO_ACTION,
        SkuFeedbackAction.DATA_ISSUE,
        SkuFeedbackAction.NEED_DECISION,
    }


def _issue_id_from_request_id(request_id: str) -> str:
    for suffix in ("-pmc-review", "-owner-feedback-0", "-owner-feedback-1", "-owner-feedback-2"):
        if request_id.endswith(suffix):
            return request_id[: -len(suffix)]
    marker = "-owner-feedback-"
    if marker in request_id:
        return request_id.split(marker, 1)[0]
    return ""


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _issue_id(signal: SkuIssueSignal, now: str) -> str:
    stamp = now.replace("-", "").replace(":", "").replace("+", "").replace(".", "")[:15]
    return f"sku-{signal.sku}-{signal.issue_type}-{stamp}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_waiting_for_feedback(issue: SkuIssueRecord) -> bool:
    return issue.status in {SkuIssueStatus.OWNER_FEEDBACK_PENDING, SkuIssueStatus.OWNER_FEEDBACK_REMINDED}


def _is_feedback_overdue(issue: SkuIssueRecord, now: datetime) -> bool:
    requested_at = _parse_time(issue.last_reminded_at or issue.feedback_requested_at)
    if not requested_at:
        return False
    due_hours = issue.assignment.due_hours if issue.assignment else 3
    return now.astimezone(timezone.utc) - requested_at.astimezone(timezone.utc) >= timedelta(hours=due_hours)


def _issue_date(issue: SkuIssueRecord) -> date:
    parsed = _parse_time(issue.detected_at)
    return parsed.date() if parsed else date.today()


def _date_in_range(value: date, start_date: date, end_date: date) -> bool:
    return start_date <= value <= end_date


def _issue_to_dict(issue: SkuIssueRecord) -> dict[str, Any]:
    payload = asdict(issue)
    payload["risk_level"] = issue.risk_level.value
    return payload


def _issue_from_dict(payload: dict[str, Any]) -> SkuIssueRecord:
    assignment = payload.get("assignment")
    feedback = payload.get("feedback")
    return SkuIssueRecord(
        issue_id=str(payload.get("issue_id") or ""),
        sku=str(payload.get("sku") or ""),
        issue_type=str(payload.get("issue_type") or ""),
        risk_level=RiskLevel(str(payload.get("risk_level") or RiskLevel.MEDIUM.value)),
        summary=str(payload.get("summary") or ""),
        suggested_department=str(payload.get("suggested_department") or ""),
        suggested_owner_open_id=str(payload.get("suggested_owner_open_id") or ""),
        suggested_owner_name=str(payload.get("suggested_owner_name") or ""),
        status=str(payload.get("status") or SkuIssueStatus.AGENT_DETECTED),
        pmc_open_id=str(payload.get("pmc_open_id") or ""),
        pmc_approval_id=str(payload.get("pmc_approval_id") or ""),
        assignment=SkuIssueAssignment(**assignment) if isinstance(assignment, dict) else None,
        feedback=SkuIssueFeedback(**feedback) if isinstance(feedback, dict) else None,
        reminder_count=int(payload.get("reminder_count") or 0),
        detected_at=str(payload.get("detected_at") or ""),
        pmc_reviewed_at=str(payload.get("pmc_reviewed_at") or ""),
        feedback_requested_at=str(payload.get("feedback_requested_at") or ""),
        last_reminded_at=str(payload.get("last_reminded_at") or ""),
        recorded_at=str(payload.get("recorded_at") or ""),
        evidence=dict(payload.get("evidence") or {}),
        notes=list(payload.get("notes") or []),
    )
