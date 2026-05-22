from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import TaskRequest, TaskType
from pmc_agent.env import load_env_file
from pmc_agent.model_io import generate_time_id, record_model_interaction
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter


logger = get_logger(__name__)


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelDecision:
    thought_summary: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    final_text: str | None = None


class ModelClient(Protocol):
    def decide(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> ModelDecision:
        """返回工具调用请求，或直接返回最终响应。"""
        ...


@dataclass(frozen=True)
class IntentAssessment:
    """计划开始前由模型返回的结构化意图识别结果。"""

    task_type: TaskType
    confidence: float
    user_expectation: str
    needs_data_context: bool
    needs_calculation: bool
    needs_write_or_approval: bool
    risk_level: str
    reasoning_summary: str


@dataclass(frozen=True)
class FailureHandlingDecision:
    """工具或数据库失败后由模型给出的下一步处理决策。"""

    failure_type: str
    user_message: str
    next_action: str
    needs_user_input: bool
    retryable: bool
    suggested_inputs: list[str] = field(default_factory=list)
    reasoning_summary: str = ""


class IntentModelClient(Protocol):
    def assess_intent(self, request: TaskRequest, recent_context: list[dict[str, Any]] | None = None) -> IntentAssessment:
        """基于语义和对话上下文识别用户请求意图。"""
        ...


class FailureHandlingModelClient(Protocol):
    def handle_failure(
        self,
        request: TaskRequest,
        plan_task_type: TaskType,
        failed_step: str,
        failed_tool: str,
        error: Exception,
        context: dict[str, Any] | None = None,
    ) -> FailureHandlingDecision:
        """基于失败上下文给出用户可理解的处理决策。"""
        ...


class OpenAIIntentModelClient:
    """基于 OpenAI 接口的语义意图识别器。

    分类器向模型请求结构化业务判断，而不是匹配固定关键词。
    这里刻意隔离为客户端接口，方便测试和本地演示注入其他 IntentModelClient，
    不需要改动计划生成逻辑。
    """

    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        load_env_file(override=False)
        self.model = model
        self.model_router = model_router or ModelRouter()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout or float(os.getenv("PMC_AGENT_HTTP_TIMEOUT", "30"))
        if not self.api_key:
            logger.critical("missing OpenAI API key", extra=log_extra("model_api_key_missing"))
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIIntentModelClient.")

    def assess_intent(self, request: TaskRequest, recent_context: list[dict[str, Any]] | None = None) -> IntentAssessment:
        interaction_id = str(request.metadata.get("request_id") or generate_time_id())
        route = self.model_router.route(
            ModelRouteRequest(
                action=ModelAction.INTENT_RECOGNITION,
                content=request.text,
                metadata=request.metadata,
            )
        )
        selected_model = self.model or route.model
        route_reason = "explicit model override" if self.model else route.reason
        logger.info("intent model request started", extra=log_extra("intent_model_request_started", request_id=interaction_id, model=selected_model))
        # 这里模型只负责识别意图；业务数量仍由 pmc_agent.tools 中的确定性工具计算。
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 库存供应链智能体的意图识别模型。"
                        "请基于语义和上下文判断用户期待的是解释、查询、复算、追因、生成计划、"
                        "异常闭环、简单寒暄还是一般分析。不要依赖固定关键词。"
                        "重点判断：是否需要业务数据、是否需要规则计算、是否需要人工确认、风险高低。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "request": request.text,
                            "material_code": request.material_code,
                            "recent_context": recent_context or [],
                            "allowed_task_types": [task.value for task in TaskType],
                            "model_route": {
                                "action": route.action.value,
                                "model": selected_model,
                                "reason": route_reason,
                                "source": "override" if self.model else route.source,
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pmc_intent_assessment",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "task_type": {"type": "string", "enum": [task.value for task in TaskType]},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "user_expectation": {"type": "string"},
                            "needs_data_context": {"type": "boolean"},
                            "needs_calculation": {"type": "boolean"},
                            "needs_write_or_approval": {"type": "boolean"},
                            "risk_level": {"type": "string", "enum": ["low", "medium", "high"]},
                            "reasoning_summary": {"type": "string"},
                        },
                        "required": [
                            "task_type",
                            "confidence",
                            "user_expectation",
                            "needs_data_context",
                            "needs_calculation",
                            "needs_write_or_approval",
                            "risk_level",
                            "reasoning_summary",
                        ],
                    },
                }
            },
        }
        request_body = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            error = f"intent model request failed: HTTP {exc.code} {exc.reason}; {response_body[:1000]}"
            record_model_interaction("intent_recognition", interaction_id, payload, error=error)
            logger.error(
                "intent model request failed",
                extra=log_extra("intent_model_request_failed", request_id=interaction_id, model=selected_model, status_code=exc.code),
                exc_info=True,
            )
            raise
        except urllib.error.URLError as exc:
            error = f"intent model request failed: URL error {exc.reason!r}"
            record_model_interaction("intent_recognition", interaction_id, payload, error=error)
            logger.error("intent model request failed", extra=log_extra("intent_model_request_failed", request_id=interaction_id, model=selected_model), exc_info=True)
            raise
        except Exception as exc:
            error = f"intent model request failed: {type(exc).__name__}: {exc}"
            record_model_interaction("intent_recognition", interaction_id, payload, error=error)
            logger.error("intent model request failed", extra=log_extra("intent_model_request_failed", request_id=interaction_id, model=selected_model), exc_info=True)
            raise

        try:
            content = _extract_response_text(raw)
            parsed = json.loads(content)
            assessment = IntentAssessment(
                task_type=TaskType(parsed["task_type"]),
                confidence=float(parsed["confidence"]),
                user_expectation=parsed["user_expectation"],
                needs_data_context=bool(parsed["needs_data_context"]),
                needs_calculation=bool(parsed["needs_calculation"]),
                needs_write_or_approval=bool(parsed["needs_write_or_approval"]),
                risk_level=parsed["risk_level"],
                reasoning_summary=parsed["reasoning_summary"],
            )
        except Exception:
            error = "intent model response parse failed"
            record_model_interaction("intent_recognition", interaction_id, payload, output=raw, error=error)
            logger.error("intent model response parse failed", extra=log_extra("intent_model_response_parse_failed", request_id=interaction_id, model=selected_model), exc_info=True)
            raise

        record_model_interaction("intent_recognition", interaction_id, payload, output=raw)
        logger.info(
            "intent model response parsed",
            extra=log_extra(
                "intent_model_response_parsed",
                request_id=interaction_id,
                task_type=assessment.task_type.value,
                model=selected_model,
                confidence=assessment.confidence,
            ),
        )
        return assessment

    def handle_failure(
        self,
        request: TaskRequest,
        plan_task_type: TaskType,
        failed_step: str,
        failed_tool: str,
        error: Exception,
        context: dict[str, Any] | None = None,
    ) -> FailureHandlingDecision:
        interaction_id = str(request.metadata.get("request_id") or generate_time_id())
        failure_payload = {
            "request": request.text,
            "material_code": request.material_code,
            "task_type": plan_task_type.value,
            "failed_step": failed_step,
            "failed_tool": failed_tool,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context or {},
        }
        route = self.model_router.route(
            ModelRouteRequest(
                action=ModelAction.FAILURE_HANDLING,
                content=json.dumps(failure_payload, ensure_ascii=False),
                metadata={"failure": True, "error_type": type(error).__name__},
            )
        )
        selected_model = self.model or route.model
        logger.info("failure handling model request started", extra=log_extra("failure_model_request_started", request_id=interaction_id, model=selected_model))
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 库存供应链智能体的失败处理决策模型。"
                        "真实数据库或工具失败时，不允许编造库存数据，也不允许用演示数据替代。"
                        "请基于失败上下文决定下一步：要求用户补充编码、建议改查范围、说明数据缺口、"
                        "建议检查数据库连接或权限，或给出可重试方案。输出必须面向业务用户，简洁明确。"
                    ),
                },
                {"role": "user", "content": json.dumps(failure_payload, ensure_ascii=False)},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pmc_failure_handling_decision",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "failure_type": {"type": "string"},
                            "user_message": {"type": "string"},
                            "next_action": {
                                "type": "string",
                                "enum": ["ask_user_for_input", "retry_with_adjustment", "report_data_gap", "check_system_config", "escalate_to_owner"],
                            },
                            "needs_user_input": {"type": "boolean"},
                            "retryable": {"type": "boolean"},
                            "suggested_inputs": {"type": "array", "items": {"type": "string"}},
                            "reasoning_summary": {"type": "string"},
                        },
                        "required": [
                            "failure_type",
                            "user_message",
                            "next_action",
                            "needs_user_input",
                            "retryable",
                            "suggested_inputs",
                            "reasoning_summary",
                        ],
                    },
                }
            },
        }
        request_body = json.dumps(payload).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            content = _extract_response_text(raw)
            parsed = json.loads(content)
            decision = FailureHandlingDecision(
                failure_type=str(parsed["failure_type"]),
                user_message=str(parsed["user_message"]),
                next_action=str(parsed["next_action"]),
                needs_user_input=bool(parsed["needs_user_input"]),
                retryable=bool(parsed["retryable"]),
                suggested_inputs=[str(item) for item in parsed.get("suggested_inputs", [])],
                reasoning_summary=str(parsed["reasoning_summary"]),
            )
        except Exception as exc:
            record_model_interaction("failure_handling", interaction_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            logger.error("failure handling model request failed", extra=log_extra("failure_model_request_failed", request_id=interaction_id, model=selected_model), exc_info=True)
            raise

        record_model_interaction("failure_handling", interaction_id, payload, output=raw)
        logger.info(
            "failure handling model response parsed",
            extra=log_extra(
                "failure_model_response_parsed",
                request_id=interaction_id,
                task_type=plan_task_type.value,
                model=selected_model,
                next_action=decision.next_action,
            ),
        )
        return decision


def _extract_response_text(response: dict[str, Any]) -> str:
    """兼容 output_text 和原始 output content 两种响应形态。"""

    if response.get("output_text"):
        return str(response["output_text"])
    for item in response.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and "text" in content:
                return str(content["text"])
    raise ValueError("No text content returned by model response.")
