from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from pmc_agent.app_logging import get_logger, log_extra


logger = get_logger(__name__)


class RunStatus(str, Enum):
    CREATED = "created"
    INTENT_RECOGNIZING = "intent_recognizing"
    INTENT_RECOGNIZED = "intent_recognized"
    PLAN_BUILDING = "plan_building"
    PLAN_BUILT = "plan_built"
    TOOL_RUNNING = "tool_running"
    TOOL_COMPLETED = "tool_completed"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    MODEL_FAILED = "model_failed"
    TOOL_FAILED = "tool_failed"
    VERIFICATION_FAILED = "verification_failed"


@dataclass(frozen=True)
class StateTransition:
    """一次状态流转记录，用于审计和前端进度展示。"""

    from_status: RunStatus
    to_status: RunStatus
    event: str
    timestamp: str
    detail: dict[str, object] = field(default_factory=dict)


class RunStateMachine:
    """智能体单次运行的轻量状态机。"""

    def __init__(self, request_id: str, initial: RunStatus = RunStatus.CREATED) -> None:
        self.request_id = request_id
        self.status = initial
        self.history: list[StateTransition] = []

    def transition(self, to_status: RunStatus, event: str, task_type: str = "-", **detail: object) -> None:
        previous = self.status
        self.status = to_status
        transition = StateTransition(
            from_status=previous,
            to_status=to_status,
            event=event,
            timestamp=datetime.now(timezone.utc).isoformat(),
            detail=detail,
        )
        self.history.append(transition)
        logger.info(
            "run state transitioned",
            extra=log_extra(
                "state_transition",
                request_id=self.request_id,
                task_type=task_type,
                from_status=previous.value,
                to_status=to_status.value,
                transition_event=event,
                **detail,
            ),
        )
