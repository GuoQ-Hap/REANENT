from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.config import InventoryPolicy
from pmc_agent.connectors.database import StiDatabaseConnector
from pmc_agent.domain import InventorySnapshot
from pmc_agent.env import load_env_file
from pmc_agent.model import _extract_response_text
from pmc_agent.model_io import generate_time_id, record_model_interaction
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter
from pmc_agent.tools.inventory import InventoryRiskTool


logger = get_logger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[2]


class AgenticAction(str, Enum):
    DECIDE_CONTEXT = "decide_context"
    QUERY_INVENTORY_SNAPSHOT = "query_inventory_snapshot"
    EVALUATE_INVENTORY_RISK = "evaluate_inventory_risk"
    FINAL_ANSWER = "final_answer"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class AgenticDecision:
    action: AgenticAction
    arguments: dict[str, Any] = field(default_factory=dict)
    final_text: str = ""
    reasoning_summary: str = ""


@dataclass(frozen=True)
class AgenticStep:
    iteration: int
    decision: AgenticDecision
    observation: dict[str, Any]


@dataclass(frozen=True)
class AgenticRunResult:
    ok: bool
    reply: str
    steps: list[AgenticStep]
    model: str
    error: str | None = None


class AgenticPlannerClient(Protocol):
    def decide_next(self, messages: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> AgenticDecision:
        ...


class OpenAIAgenticPlannerClient:
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
            raise RuntimeError("OPENAI_API_KEY is required for OpenAIAgenticPlannerClient.")

    def decide_next(self, messages: list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> AgenticDecision:
        content = json.dumps(messages[-4:], ensure_ascii=False)
        route = self.model_router.route(
            ModelRouteRequest(
                action=ModelAction.TOOL_ORCHESTRATION,
                content=content,
                metadata=metadata or {},
            )
        )
        selected_model = self.model or route.model
        interaction_id = str((metadata or {}).get("request_id") or generate_time_id())
        payload = {
            "model": selected_model,
            "input": messages,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "pmc_agentic_decision",
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": [item.value for item in AgenticAction],
                            },
                            "arguments": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "material_code": {
                                        "type": "string",
                                        "description": "Material/MSKU/SKU/FNSKU/ASIN-like code selected by the model for inventory lookup. Use empty string when not applicable.",
                                    },
                                    "scope": {
                                        "type": "string",
                                        "enum": ["", "single_material", "portfolio"],
                                        "description": "single_material for a specific material query; portfolio only for explicit overall inventory queries.",
                                    },
                                    "use_context": {
                                        "type": "boolean",
                                        "description": "For decide_context only: true when the hidden recent context is needed for this request.",
                                    },
                                    "context_limit": {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": 8,
                                        "description": "For decide_context only: number of recent context entries to load when use_context is true.",
                                    },
                                },
                                "required": ["material_code", "scope", "use_context", "context_limit"],
                            },
                            "final_text": {"type": "string"},
                            "reasoning_summary": {"type": "string"},
                        },
                        "required": ["action", "arguments", "final_text", "reasoning_summary"],
                    },
                }
            },
        }
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
            parsed = json.loads(_extract_response_text(raw))
            decision = AgenticDecision(
                action=AgenticAction(parsed["action"]),
                arguments=dict(parsed.get("arguments") or {}),
                final_text=str(parsed.get("final_text") or ""),
                reasoning_summary=str(parsed.get("reasoning_summary") or ""),
            )
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error = f"HTTPError {exc.code}: {error_body[:1000]}"
            record_model_interaction("agentic_orchestration", interaction_id, payload, output=raw, error=error)
            raise RuntimeError(error) from exc
        except Exception as exc:
            record_model_interaction("agentic_orchestration", interaction_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            raise

        record_model_interaction("agentic_orchestration", interaction_id, payload, output=raw)
        logger.info(
            "agentic decision parsed",
            extra=log_extra("agentic_decision_parsed", request_id=interaction_id, model=selected_model, action=decision.action.value),
        )
        return decision


@dataclass
class AgenticPmcLoop:
    planner: AgenticPlannerClient
    model: str
    db_connector: StiDatabaseConnector = field(default_factory=StiDatabaseConnector)
    inventory_policy: InventoryPolicy = field(default_factory=InventoryPolicy)
    max_iterations: int = 20

    def run(self, user_text: str, recent_context: list[dict[str, Any]] | None = None, request_id: str | None = None) -> AgenticRunResult:
        request_id = request_id or generate_time_id()
        hidden_context = _normalize_recent_context(recent_context)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _agent_system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": user_text,
                        "hidden_context_available": bool(hidden_context),
                        "hidden_context_count": len(hidden_context),
                        "data_catalog": _load_data_catalog(),
                        "available_tools": _available_tools(),
                        "constraints": [
                            "只允许执行 available_tools 中列出的动作。",
                            "最近对话上下文默认隐藏；如果本轮问题依赖上一轮对象、代词、继续追问或省略范围，先选择 decide_context 并设置 use_context=true。",
                            "如果本轮问题独立完整，或已包含明确物料/范围，则不要加载上下文，直接选择业务动作。",
                            "程序不会替你抽取物料编码；如果用户问题包含单个物料，必须由你在 action.arguments.material_code 中返回要查询的编码。",
                            "除非用户明确要求整体/全局/组合库存分析，否则 query_inventory_snapshot 必须携带 material_code。",
                            "真实数据库查不到时不能编造结果，必须把 observation 交回模型决策。",
                            "回答用户前必须基于 observation 判断是否足够。",
                            "当 action 是 ask_user 或 final_answer 时，final_text 必须是面向用户的非空中文文本。",
                        ],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        steps: list[AgenticStep] = []
        snapshots: list[InventorySnapshot] = []
        context_loaded = False

        for iteration in range(1, self.max_iterations + 1):
            decision = self.planner.decide_next(messages, metadata={"request_id": request_id})
            observation = self._execute(decision, snapshots, hidden_context, context_loaded)
            if observation.get("context_loaded"):
                context_loaded = True
            if "snapshots" in observation:
                snapshots = [_snapshot_from_json(item) for item in observation["snapshots"]]
            steps.append(AgenticStep(iteration=iteration, decision=decision, observation=observation))

            if decision.action in {AgenticAction.FINAL_ANSWER, AgenticAction.ASK_USER}:
                reply = _user_visible_text(decision, observation)
                return AgenticRunResult(ok=True, reply=reply, steps=steps, model=self.model)

            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "decision": _to_jsonable(decision),
                            "observation": observation,
                        },
                        ensure_ascii=False,
                    ),
                }
            )

        summary_decision = self._summarize_at_limit(messages, steps, request_id)
        reply = summary_decision.final_text.strip() or "模型执行循环达到上限，且未能生成最终总结。"
        summary_observation = {"ok": True, "message": reply, "forced_summary": True}
        steps.append(AgenticStep(iteration=self.max_iterations + 1, decision=summary_decision, observation=summary_observation))
        return AgenticRunResult(
            ok=True,
            reply=reply,
            steps=steps,
            model=self.model,
            error="max_iterations_reached",
        )

    def _summarize_at_limit(self, messages: list[dict[str, Any]], steps: list[AgenticStep], request_id: str) -> AgenticDecision:
        summary_messages = [
            *messages,
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "event": "max_iterations_reached",
                        "instruction": "动作循环已达到上限。请基于已有 observation 直接总结给用户，只允许返回 final_answer，不要再请求执行工具。",
                        "steps": [_to_jsonable(step) for step in steps],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        decision = self.planner.decide_next(summary_messages, metadata={"request_id": request_id, "forced_summary": True})
        if decision.action == AgenticAction.FINAL_ANSWER:
            return decision
        fallback_text = decision.final_text.strip() or "模型执行循环达到上限，未形成可执行的最终答案。"
        return AgenticDecision(
            action=AgenticAction.FINAL_ANSWER,
            final_text=fallback_text,
            reasoning_summary="Forced final answer after max iteration limit.",
        )

    def _execute(
        self,
        decision: AgenticDecision,
        snapshots: list[InventorySnapshot],
        hidden_context: list[dict[str, Any]],
        context_loaded: bool,
    ) -> dict[str, Any]:
        try:
            if decision.action == AgenticAction.DECIDE_CONTEXT:
                use_context = bool(decision.arguments.get("use_context"))
                limit = _bounded_int(decision.arguments.get("context_limit"), default=8, minimum=0, maximum=8)
                if not use_context:
                    return {"ok": True, "use_context": False, "context_loaded": False, "selected_context": []}
                if context_loaded:
                    return {"ok": True, "use_context": True, "context_loaded": True, "selected_context": [], "message": "Context was already loaded earlier in this run."}
                selected_context = hidden_context[-limit:] if limit else []
                return {
                    "ok": True,
                    "use_context": bool(selected_context),
                    "context_loaded": bool(selected_context),
                    "selected_context": selected_context,
                    "hidden_context_count": len(hidden_context),
                }

            if decision.action == AgenticAction.QUERY_INVENTORY_SNAPSHOT:
                material_code = _optional_str(decision.arguments.get("material_code"))
                if not material_code and not _is_explicit_portfolio_query(decision.arguments):
                    return {
                        "ok": False,
                        "error_type": "MissingModelArgument",
                        "error": "query_inventory_snapshot requires action.arguments.material_code unless the model explicitly sets scope='portfolio'. The program will not extract the code locally.",
                    }
                rows = self.db_connector.get_inventory_snapshot(material_code)
                return {
                    "ok": True,
                    "query_material_code": material_code,
                    "resolved_aliases": list(getattr(self.db_connector, "last_resolved_aliases", []) or []),
                    "note": "Rows may be returned under mapped SKU/MSKU/FNSKU values; they are the database-resolved inventory records for query_material_code.",
                    "snapshots": [_to_jsonable(item) for item in rows],
                    "row_count": len(rows),
                }

            if decision.action == AgenticAction.EVALUATE_INVENTORY_RISK:
                if not snapshots:
                    return {"ok": False, "error": "No snapshots available. Query inventory snapshot first."}
                decisions = InventoryRiskTool(policy=self.inventory_policy).run(snapshots=snapshots)
                return {"ok": True, "decisions": [_to_jsonable(item) for item in decisions], "decision_count": len(decisions)}

            if decision.action == AgenticAction.FINAL_ANSWER:
                return {"ok": True, "message": decision.final_text}

            if decision.action == AgenticAction.ASK_USER:
                return {"ok": True, "message": decision.final_text}
        except Exception as exc:
            return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}

        return {"ok": False, "error": f"Unsupported action: {decision.action.value}"}


def _agent_system_prompt() -> str:
    return (
        "你是 PMC 库存供应链智能体。你必须先理解用户目标，再基于可用表池和工具决定下一步动作。"
        "你不能假设程序已经知道该做什么；每一步都由你选择 action。程序会执行你的 action 并返回 observation。"
        "上下文记忆也是一个可选动作，不是默认输入；需要时你必须先选择 decide_context。"
        "拿到 observation 后，你要判断是否足以回答；不够就继续选择下一步，足够才 final_answer。"
        "不要编造库存、销量、在途、采购数据。"
    )


def _available_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": AgenticAction.DECIDE_CONTEXT.value,
            "description": "Decide whether hidden recent conversation context is needed. If use_context=true, the program returns selected context as observation.",
            "arguments": {"use_context": "boolean", "context_limit": "0-8"},
        },
        {
            "name": AgenticAction.QUERY_INVENTORY_SNAPSHOT.value,
            "description": "Read inventory snapshot from the read-only STI database. Main table: ads_lingxing_all_warehouse_new_v1.",
            "arguments": {
                "material_code": "required msku/sku/fnsku/ASIN-like code for a single-material user request",
                "scope": "set to 'portfolio' only when the user explicitly asks for an overall inventory query",
            },
        },
        {
            "name": AgenticAction.EVALUATE_INVENTORY_RISK.value,
            "description": "Evaluate inventory risk from the latest inventory snapshots returned by query_inventory_snapshot.",
            "arguments": {},
        },
        {"name": AgenticAction.ASK_USER.value, "description": "Ask user for missing code, scope, or confirmation.", "arguments": {}},
        {"name": AgenticAction.FINAL_ANSWER.value, "description": "Return final answer to user.", "arguments": {}},
    ]


def _load_data_catalog() -> dict[str, Any]:
    path = ROOT_DIR / "docs" / "inventory_traceability_table_pools.json"
    if not path.exists():
        return {"main_tables": ["ads_lingxing_all_warehouse_new_v1"]}
    data = json.loads(path.read_text(encoding="utf-8"))
    main = data.get("pools", {}).get("main", {})
    return {
        "notes": data.get("notes", [])[:4],
        "main_tables": [
            {"name": name, "reason": info.get("reason"), "description": info.get("description")}
            for name, info in main.items()
        ],
    }


def _snapshot_from_json(item: dict[str, Any]) -> InventorySnapshot:
    return InventorySnapshot(
        material_code=str(item["material_code"]),
        on_hand=float(item["on_hand"]),
        allocated=float(item["allocated"]),
        inbound=float(item["inbound"]),
        demand_next_7d=float(item["demand_next_7d"]),
        demand_next_30d=float(item["demand_next_30d"]),
        metadata=dict(item.get("metadata") or {}),
    )


def _optional_str(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _is_explicit_portfolio_query(arguments: dict[str, Any]) -> bool:
    scope = _optional_str(arguments.get("scope") or arguments.get("query_scope"))
    return bool(scope and scope.lower() in {"portfolio", "overall", "global", "all"})


def _user_visible_text(decision: AgenticDecision, observation: dict[str, Any]) -> str:
    text = decision.final_text.strip() or str(observation.get("message") or "").strip()
    if text:
        return text
    if decision.action == AgenticAction.ASK_USER and decision.reasoning_summary.strip():
        return f"我需要再确认一下：{decision.reasoning_summary.strip()}"
    return "我需要更多信息才能继续，请补充物料编码或要查询的范围。"


def _normalize_recent_context(recent_context: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not isinstance(recent_context, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in recent_context[-8:]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "")[:20]
        content = str(item.get("content") or "")[:1200]
        if role and content:
            normalized.append({"role": role, "content": content})
    return normalized


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    return value
