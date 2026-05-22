from __future__ import annotations

from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import ControlDecision, ExecutionPlan, TaskType


logger = get_logger(__name__)


def verify_decisions(plan: ExecutionPlan, decisions: list[ControlDecision], artifacts: dict[str, Any] | None = None) -> list[str]:
    """验证本次运行是否产生了可复核的决策或产物。"""

    messages: list[str] = []
    artifacts = artifacts or {}
    if not decisions:
        if plan.task_type == TaskType.SIMPLE_CHAT and artifacts.get("chat_reply"):
            messages.append("Simple chat reply produced.")
            logger.info("simple chat verified", extra=log_extra("simple_chat_verified", task_type=plan.task_type.value))
            return messages
        if artifacts:
            messages.append("Artifact output was produced and should be reviewed by a human owner.")
            logger.warning(
                "artifact output requires human review",
                extra=log_extra("artifact_requires_human_review", task_type=plan.task_type.value, artifact_count=len(artifacts)),
            )
            if plan.assumptions:
                messages.append("Plan contains assumptions that should be reviewed with business data owners.")
                logger.warning("plan assumptions require review", extra=log_extra("plan_assumptions_require_review", task_type=plan.task_type.value))
            return messages
        messages.append("No decision was produced; source data may be missing.")
        logger.error("verification found no output", extra=log_extra("verification_no_output", task_type=plan.task_type.value))
        return messages

    for decision in decisions:
        if not decision.recommended_actions:
            messages.append(f"{decision.material_code}: missing recommended actions.")
            logger.error(
                "decision missing recommended actions",
                extra=log_extra("decision_missing_actions", task_type=plan.task_type.value, material_code=decision.material_code),
            )
        else:
            messages.append(f"{decision.material_code}: decision contains actionable PMC controls.")
            logger.info(
                "decision verified",
                extra=log_extra("decision_verified", task_type=plan.task_type.value, material_code=decision.material_code, risk_level=decision.risk_level.value),
            )

    if plan.assumptions:
        messages.append("Plan contains assumptions that should be reviewed with business data owners.")
        logger.warning("plan assumptions require review", extra=log_extra("plan_assumptions_require_review", task_type=plan.task_type.value))
    return messages
