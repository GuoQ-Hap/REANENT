from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
import urllib.error
import urllib.request
from typing import Any, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.env import load_env_file
from pmc_agent.memory.types import MemoryRecord
from pmc_agent.model import _extract_response_text
from pmc_agent.model_io import generate_time_id, record_model_interaction
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter


logger = get_logger(__name__)


@dataclass(frozen=True)
class MemoryReviewDraft:
    review_markdown: str
    memory_records: list[MemoryRecord]


class MemoryReviewClient(Protocol):
    def review(self, review_date: date, conversations: list[dict[str, Any]]) -> MemoryReviewDraft:
        ...


class OpenAIMemoryReviewClient:
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
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIMemoryReviewClient.")

    def review(self, review_date: date, conversations: list[dict[str, Any]]) -> MemoryReviewDraft:
        content = json.dumps(
            {
                "review_date": review_date.isoformat(),
                "conversations": _compact_conversations(conversations),
                "rules": [
                    "只总结当天运行记录，不要补写未出现的信息。",
                    "长期记忆只允许保存用户偏好、人工反馈、规则口径、失败修复经验、Case 闭环经验。",
                    "实时库存、销量、在途、预测数量、价格、日期等强时效数据不得写入长期记忆。",
                    "如果某条信息只是模型中间推理或未确认猜测，不要写入长期记忆。",
                ],
            },
            ensure_ascii=False,
        )
        route = self.model_router.route(ModelRouteRequest(action=ModelAction.SUMMARY, content=content, metadata={"memory_review": True}))
        selected_model = self.model or route.model
        interaction_id = f"memory_review_{review_date.isoformat()}_{generate_time_id()}"
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 库存供应链智能体的每日记忆审查模型。"
                        "你要审查当天模型交互和工具轨迹，生成中文 Markdown 日报，并抽取可长期复用的业务记忆。"
                        "必须保守：不要把实时库存数值、销量、在途、预测值写入长期记忆。"
                        "记忆要可审计、可复用、短而准。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pmc_memory_daily_review",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "review_markdown": {"type": "string"},
                            "memory_records": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "memory_type": {
                                            "type": "string",
                                            "enum": ["user_preference", "manual_feedback", "business_rule", "case_lesson", "tool_trace"],
                                        },
                                        "scope": {"type": "string", "enum": ["user", "team", "project", "global"]},
                                        "subject_type": {"type": "string"},
                                        "subject_id": {"type": "string"},
                                        "content": {"type": "string"},
                                        "summary": {"type": "string"},
                                        "tags": {"type": "array", "items": {"type": "string"}},
                                        "entities": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "additionalProperties": False,
                                                "properties": {
                                                    "key": {"type": "string"},
                                                    "value": {"type": "string"},
                                                },
                                                "required": ["key", "value"],
                                            },
                                        },
                                        "source_request_id": {"type": "string"},
                                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                                        "expires_at": {"type": ["string", "null"]},
                                    },
                                    "required": [
                                        "memory_type",
                                        "scope",
                                        "subject_type",
                                        "subject_id",
                                        "content",
                                        "summary",
                                        "tags",
                                        "entities",
                                        "source_request_id",
                                        "confidence",
                                        "expires_at",
                                    ],
                                },
                            },
                        },
                        "required": ["review_markdown", "memory_records"],
                    },
                }
            },
        }
        raw: dict[str, Any] | None = None
        try:
            raw = self._post_responses(payload)
            parsed = json.loads(_extract_response_text(raw))
            draft = MemoryReviewDraft(
                review_markdown=str(parsed.get("review_markdown") or ""),
                memory_records=[
                    _record_from_model(item, review_date)
                    for item in parsed.get("memory_records", [])
                    if isinstance(item, dict)
                ],
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error = f"HTTPError {exc.code}: {error_body[:1000]}"
            record_model_interaction("memory_review", interaction_id, payload, output=raw, error=error)
            logger.warning(
                "structured memory review failed; retrying plain json mode",
                extra=log_extra("memory_review_structured_retry", request_id=interaction_id, model=selected_model, status_code=exc.code),
            )
            return self._review_plain_json(review_date, content, selected_model, interaction_id, first_error=error)
        except Exception as exc:
            record_model_interaction("memory_review", interaction_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            raise

        record_model_interaction("memory_review", interaction_id, payload, output=raw)
        logger.info(
            "memory review completed by model",
            extra=log_extra("memory_review_model_completed", request_id=interaction_id, model=selected_model, memory_count=len(draft.memory_records)),
        )
        return draft

    def _review_plain_json(self, review_date: date, content: str, selected_model: str, interaction_id: str, first_error: str) -> MemoryReviewDraft:
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 库存供应链智能体的每日记忆审查模型。"
                        "只返回一个 JSON 对象，不要 Markdown 代码围栏，不要额外解释。"
                        "JSON 字段必须是 review_markdown 和 memory_records。"
                        "memory_records 是数组，每项包含 memory_type, scope, subject_type, subject_id, content, "
                        "summary, tags, entities, source_request_id, confidence, expires_at。entities 用对象即可。"
                        "禁止把实时库存、销量、在途、预测数量写入长期记忆。"
                    ),
                },
                {"role": "user", "content": content},
            ],
        }
        raw: dict[str, Any] | None = None
        try:
            raw = self._post_responses(payload)
            parsed = _parse_json_object(_extract_response_text(raw))
        except Exception as exc:
            record_model_interaction("memory_review", interaction_id, payload, output=raw, error=f"{first_error}; fallback failed: {type(exc).__name__}: {exc}")
            raise RuntimeError(f"{first_error}; fallback failed: {type(exc).__name__}: {exc}") from exc
        draft = MemoryReviewDraft(
            review_markdown=str(parsed.get("review_markdown") or ""),
            memory_records=[
                _record_from_model(item, review_date)
                for item in parsed.get("memory_records", [])
                if isinstance(item, dict)
            ],
        )
        record_model_interaction("memory_review", interaction_id, payload, output=raw)
        logger.info(
            "memory review completed by model fallback",
            extra=log_extra("memory_review_model_fallback_completed", request_id=interaction_id, model=selected_model, memory_count=len(draft.memory_records)),
        )
        return draft

    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


def _record_from_model(item: dict[str, Any], review_date: date) -> MemoryRecord:
    return MemoryRecord(
        id=f"{review_date.isoformat()}_{generate_time_id()}",
        memory_type=str(item.get("memory_type") or "case_lesson"),
        scope=str(item.get("scope") or "project"),
        subject_type=str(item.get("subject_type") or "task_type")[:80],
        subject_id=str(item.get("subject_id") or "pmc_agent")[:120],
        content=str(item.get("content") or "")[:2000],
        summary=str(item.get("summary") or "")[:300],
        tags=[str(tag)[:60] for tag in item.get("tags", []) if str(tag).strip()][:12],
        entities=_entities_from_model(item.get("entities")),
        source_request_id=str(item.get("source_request_id") or ""),
        confidence=max(0.0, min(float(item.get("confidence") or 0.5), 1.0)),
        expires_at=item.get("expires_at") if isinstance(item.get("expires_at"), str) else None,
    )


def _compact_conversations(conversations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for conversation in conversations[:80]:
        interactions = []
        for interaction in conversation.get("interactions", [])[:20]:
            interactions.append(
                {
                    "interaction_type": interaction.get("interaction_type"),
                    "created_at": interaction.get("created_at"),
                    "input": _truncate_jsonable(interaction.get("input"), 3500),
                    "output": _truncate_jsonable(interaction.get("output"), 1200),
                    "error": str(interaction.get("error") or "")[:1200],
                }
            )
        compact.append(
            {
                "id": conversation.get("id"),
                "created_at": conversation.get("created_at"),
                "updated_at": conversation.get("updated_at"),
                "interaction_count": len(conversation.get("interactions", [])),
                "interactions": interactions,
            }
        )
    return compact


def _truncate_jsonable(value: Any, limit: int) -> Any:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return value
    return text[:limit]


def _parse_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("memory review response must be a JSON object")
    return parsed


def _entities_from_model(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key)[:80]: str(item)[:200] for key, item in value.items()}
    if not isinstance(value, list):
        return {}
    entities: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or "").strip()
        if key:
            entities[key[:80]] = str(item.get("value") or "")[:200]
    return entities
