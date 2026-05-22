from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol

from pmc_agent.env import load_env_file
from pmc_agent.model import _extract_response_text
from pmc_agent.model_io import generate_time_id, record_model_interaction
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter


@dataclass(frozen=True)
class ContextDecision:
    use_context: bool
    selected_context: list[dict[str, str]] = field(default_factory=list)
    reasoning_summary: str = ""


class ContextDecisionClient(Protocol):
    def decide_context(self, user_text: str, recent_context: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> ContextDecision:
        ...


class HeuristicContextDecisionClient:
    def decide_context(self, user_text: str, recent_context: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> ContextDecision:
        if not recent_context:
            return ContextDecision(use_context=False, reasoning_summary="No prior context.")
        text = user_text.lower()
        if _contains_explicit_material_code(user_text):
            return ContextDecision(use_context=False, reasoning_summary="Standalone request contains explicit material code.")
        followup_terms = ["这个", "它", "刚才", "上一", "继续", "链路", "风险呢", "仓库", "明细", "there", "it", "that", "continue"]
        use_context = any(term in text for term in followup_terms)
        return ContextDecision(
            use_context=use_context,
            selected_context=recent_context[-8:] if use_context else [],
            reasoning_summary="Heuristic follow-up detection." if use_context else "Standalone request.",
        )


class OpenAIContextDecisionClient:
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
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIContextDecisionClient.")

    def decide_context(self, user_text: str, recent_context: list[dict[str, str]], metadata: dict[str, Any] | None = None) -> ContextDecision:
        request_id = str((metadata or {}).get("request_id") or generate_time_id())
        content = json.dumps({"request": user_text, "recent_context": recent_context[-8:]}, ensure_ascii=False)
        route = self.model_router.route(ModelRouteRequest(action=ModelAction.CONTEXT_SELECTION, content=content, metadata=metadata or {}))
        selected_model = self.model or route.model
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 智能体的上下文管理模型。判断用户本轮问题是否需要最近对话上下文。"
                        "只有当问题依赖代词、追问、上一轮物料、上一轮查询结果、继续分析或省略对象时才 use_context=true。"
                        "如果问题是独立新问题、寒暄、或已包含完整物料/范围，则 use_context=false。"
                        "不要回答业务问题，只判断是否注入上下文。"
                    ),
                },
                {"role": "user", "content": content},
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pmc_context_decision",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "use_context": {"type": "boolean"},
                            "selected_context_count": {"type": "integer", "minimum": 0, "maximum": 8},
                            "reasoning_summary": {"type": "string"},
                        },
                        "required": ["use_context", "selected_context_count", "reasoning_summary"],
                    },
                }
            },
        }
        raw: dict[str, Any] | None = None
        try:
            request = urllib.request.Request(
                f"{self.base_url}/responses",
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            parsed = json.loads(_extract_response_text(raw))
            count = int(parsed.get("selected_context_count") or 0)
            use_context = bool(parsed.get("use_context"))
            selected_context = recent_context[-max(0, min(count, 8)) :] if use_context else []
            decision = ContextDecision(
                use_context=use_context,
                selected_context=selected_context,
                reasoning_summary=str(parsed.get("reasoning_summary") or ""),
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error = f"HTTPError {exc.code}: {error_body[:1000]}"
            record_model_interaction("context_selection", request_id, payload, output=raw, error=error)
            raise RuntimeError(error) from exc
        except Exception as exc:
            record_model_interaction("context_selection", request_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            raise

        record_model_interaction("context_selection", request_id, payload, output=raw)
        return decision


@dataclass
class ContextManager:
    decision_client: ContextDecisionClient

    def select_context(self, user_text: str, recent_context: Any, metadata: dict[str, Any] | None = None) -> ContextDecision:
        normalized = normalize_recent_context(recent_context)
        if not normalized:
            return ContextDecision(use_context=False, reasoning_summary="No prior context.")
        return self.decision_client.decide_context(user_text, normalized, metadata=metadata)


def normalize_recent_context(recent_context: Any) -> list[dict[str, str]]:
    if not isinstance(recent_context, list):
        return []
    normalized: list[dict[str, str]] = []
    for item in recent_context[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")[:20]
        content = str(item.get("content") or "")[:1200]
        if role and content:
            normalized.append({"role": role, "content": content})
    return normalized


def _contains_explicit_material_code(text: str) -> bool:
    patterns = [
        r"(?<![A-Z0-9])B0[A-Z0-9]{8}(?![A-Z0-9])",
        r"(?<![A-Z0-9])[A-Z]{1,4}\d{2,6}(?![A-Z0-9])",
    ]
    return any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns)
