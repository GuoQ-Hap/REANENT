from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file


logger = get_logger(__name__)


class ModelAction(str, Enum):
    """模型调度动作类型。

    业务代码只声明“这次要做什么动作”，不直接散落模型名。
    """

    INTENT_RECOGNITION = "intent_recognition"
    GOAL_REPAIR = "goal_repair"
    TOOL_ORCHESTRATION = "tool_orchestration"
    CONTEXT_SELECTION = "context_selection"
    FAILURE_HANDLING = "failure_handling"
    BUSINESS_EXPLANATION = "business_explanation"
    SUMMARY = "summary"


@dataclass(frozen=True)
class ModelRouteRequest:
    action: ModelAction
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelRouteDecision:
    action: ModelAction
    model: str
    reason: str
    source: str


@dataclass(frozen=True)
class ModelRoutingPolicy:
    """按动作和内容特征选择模型。

    默认策略偏保守：轻量动作用 mini，复杂编排和业务解释用更强模型。
    环境变量可以覆盖每类动作的模型。
    """

    default_model: str = "gpt-5.1"
    intent_model: str = "gpt-5.1"
    goal_repair_model: str = "gpt-5.1"
    tool_orchestration_model: str = "gpt-5.1"
    context_selection_model: str = "gpt-5.1"
    failure_handling_model: str = "gpt-5.1"
    business_explanation_model: str = "gpt-5.1"
    summary_model: str = "gpt-5.1"
    high_risk_model: str = "gpt-5.1"
    long_context_threshold: int = 4000

    @classmethod
    def from_env(cls) -> "ModelRoutingPolicy":
        load_env_file(override=False)
        legacy_intent = os.getenv("PMC_AGENT_INTENT_MODEL", cls.intent_model)
        return cls(
            default_model=os.getenv("PMC_AGENT_MODEL_DEFAULT", legacy_intent or cls.default_model),
            intent_model=os.getenv("PMC_AGENT_MODEL_INTENT_RECOGNITION", legacy_intent or cls.intent_model),
            goal_repair_model=os.getenv("PMC_AGENT_MODEL_GOAL_REPAIR", cls.goal_repair_model),
            tool_orchestration_model=os.getenv("PMC_AGENT_MODEL_TOOL_ORCHESTRATION", cls.tool_orchestration_model),
            context_selection_model=os.getenv("PMC_AGENT_MODEL_CONTEXT_SELECTION", legacy_intent or cls.context_selection_model),
            failure_handling_model=os.getenv("PMC_AGENT_MODEL_FAILURE_HANDLING", cls.failure_handling_model),
            business_explanation_model=os.getenv("PMC_AGENT_MODEL_BUSINESS_EXPLANATION", cls.business_explanation_model),
            summary_model=os.getenv("PMC_AGENT_MODEL_SUMMARY", cls.summary_model),
            high_risk_model=os.getenv("PMC_AGENT_MODEL_HIGH_RISK", cls.high_risk_model),
            long_context_threshold=_env_int("PMC_AGENT_MODEL_LONG_CONTEXT_THRESHOLD", cls.long_context_threshold),
        )


@dataclass
class ModelRouter:
    policy: ModelRoutingPolicy = field(default_factory=ModelRoutingPolicy.from_env)

    def route(self, request: ModelRouteRequest) -> ModelRouteDecision:
        if request.action == ModelAction.FAILURE_HANDLING:
            decision = ModelRouteDecision(
                action=request.action,
                model=self.policy.failure_handling_model,
                reason="selected by failure handling action",
                source="action_policy",
            )
            self._log(decision)
            return decision

        if _is_high_risk(request):
            decision = ModelRouteDecision(
                action=request.action,
                model=self.policy.high_risk_model,
                reason="high-risk or approval-sensitive business content",
                source="risk_policy",
            )
            self._log(decision)
            return decision

        if len(request.content) >= self.policy.long_context_threshold:
            decision = ModelRouteDecision(
                action=request.action,
                model=self.policy.business_explanation_model,
                reason="long context requires stronger reasoning",
                source="content_policy",
            )
            self._log(decision)
            return decision

        model_by_action = {
            ModelAction.INTENT_RECOGNITION: self.policy.intent_model,
            ModelAction.GOAL_REPAIR: self.policy.goal_repair_model,
            ModelAction.TOOL_ORCHESTRATION: self.policy.tool_orchestration_model,
            ModelAction.CONTEXT_SELECTION: self.policy.context_selection_model,
            ModelAction.BUSINESS_EXPLANATION: self.policy.business_explanation_model,
            ModelAction.SUMMARY: self.policy.summary_model,
        }
        decision = ModelRouteDecision(
            action=request.action,
            model=model_by_action.get(request.action, self.policy.default_model),
            reason=f"selected by action {request.action.value}",
            source="action_policy",
        )
        self._log(decision)
        return decision

    def _log(self, decision: ModelRouteDecision) -> None:
        logger.info(
            "model route selected",
            extra=log_extra(
                "model_route_selected",
                task_type=decision.action.value,
                model=decision.model,
                route_source=decision.source,
            ),
        )


def route_model(action: ModelAction, content: str = "", metadata: dict[str, Any] | None = None) -> ModelRouteDecision:
    return ModelRouter().route(ModelRouteRequest(action=action, content=content, metadata=metadata or {}))


def _is_high_risk(request: ModelRouteRequest) -> bool:
    if request.metadata.get("needs_write_or_approval") or request.metadata.get("high_risk"):
        return True
    text = request.content.lower()
    risk_terms = [
        "采购",
        "下单",
        "确认",
        "审批",
        "异常",
        "高风险",
        "critical",
        "approval",
        "purchase",
        "exception",
    ]
    return any(term in text for term in risk_terms)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("invalid integer env value", extra=log_extra("model_router_invalid_env", task_type=name))
        return default
