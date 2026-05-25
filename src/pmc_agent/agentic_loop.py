from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from typing import Any, Callable, Protocol

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.config import InventoryPolicy
from pmc_agent.connectors.database import StiDatabaseConnector
from pmc_agent.connectors.vector_database import MilvusVectorConnector
from pmc_agent.domain import InventorySnapshot
from pmc_agent.env import load_env_file
from pmc_agent.model import _extract_response_text
from pmc_agent.model_io import generate_time_id, record_model_interaction
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter
from pmc_agent.query_spec import QuerySpec
from pmc_agent.schema_catalog import FieldPack, normalize_field_pack
from pmc_agent.tools.inventory import InventoryRiskTool, KnowledgeLookupTool


logger = get_logger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[2]


class AgenticAction(str, Enum):
    DECIDE_CONTEXT = "decide_context"
    INSPECT_RUN_TRACE = "inspect_run_trace"
    RUN_SERIAL_SPACE = "run_serial_space"
    QUERY_INVENTORY_SNAPSHOT = "query_inventory_snapshot"
    EVALUATE_INVENTORY_RISK = "evaluate_inventory_risk"
    KNOWLEDGE_LOOKUP = "knowledge_lookup"
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


class SubBehaviorClient(Protocol):
    def run_behavior(
        self,
        behavior: str,
        prompt: str,
        context: dict[str, Any],
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
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
                                    "field_pack": {
                                        "type": "string",
                                        "enum": ["", *[item.value for item in FieldPack]],
                                        "description": "Controlled field pack for query_inventory_snapshot. Use empty string for default inventory snapshot.",
                                    },
                                    "filters": _inventory_filters_schema(),
                                    "query": {
                                        "type": "string",
                                        "description": "For knowledge_lookup only: text query used to retrieve SOP/rule/vector knowledge snippets. Use empty string when not applicable.",
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
                                    "tasks": {
                                        "type": "array",
                                        "description": "For run_serial_space only: ordered subtask list. Tool subtasks run serially; model_behavior subtasks inside a parallel group may run concurrently.",
                                        "items": _serial_task_schema(),
                                    },
                                    "self_review_passed": {
                                        "type": "boolean",
                                        "description": "For final_answer only: set false when your own review rejects the draft; the program will keep the answer internal and continue within the same max iteration budget.",
                                    },
                                    "review_notes": {
                                        "type": "string",
                                        "description": "For final_answer self-review failure or inspect_run_trace: concise reason why the draft failed and what should change next.",
                                    },
                                    "include_prompts": {
                                        "type": "boolean",
                                        "description": "For inspect_run_trace only: whether to return the system prompt and initial user payload.",
                                    },
                                    "include_observations": {
                                        "type": "boolean",
                                        "description": "For inspect_run_trace only: whether to include compact observations from previous actions.",
                                    },
                                },
                                "required": [
                                    "material_code",
                                    "scope",
                                    "field_pack",
                                    "filters",
                                    "query",
                                    "use_context",
                                    "context_limit",
                                    "tasks",
                                    "self_review_passed",
                                    "review_notes",
                                    "include_prompts",
                                    "include_observations",
                                ],
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


def _inventory_filters_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sales_property": {
                "type": "string",
                "enum": ["", "爆", "旺", "平", "滞"],
                "description": "MSKU sales property filter. Use 爆 for 爆款, 旺 for 旺款; empty string means no filter.",
            },
            "risk_only": {
                "type": "boolean",
                "description": "True when the user asks for possible shortage/out-of-stock risk rows.",
            },
            "positive_demand": {
                "type": "boolean",
                "description": "True when rows should have recent or forecast demand.",
            },
            "order_by": {
                "type": "string",
                "enum": ["", "demand_desc", "risk_then_demand"],
                "description": "Controlled ordering for portfolio queries.",
            },
        },
        "required": ["sales_property", "risk_only", "positive_demand", "order_by"],
    }


def _action_arguments_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "material_code": {"type": "string"},
            "scope": {"type": "string"},
            "field_pack": {"type": "string", "enum": ["", *[item.value for item in FieldPack]]},
            "filters": _inventory_filters_schema(),
            "query": {"type": "string"},
            "use_context": {"type": "boolean"},
            "context_limit": {"type": "integer", "minimum": 0, "maximum": 8},
            "self_review_passed": {"type": "boolean"},
            "review_notes": {"type": "string"},
            "include_prompts": {"type": "boolean"},
            "include_observations": {"type": "boolean"},
        },
        "required": [
            "material_code",
            "scope",
            "field_pack",
            "filters",
            "query",
            "use_context",
            "context_limit",
            "self_review_passed",
            "review_notes",
            "include_prompts",
            "include_observations",
        ],
    }


def _serial_task_schema() -> dict[str, Any]:
    child_task = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string"},
            "type": {"type": "string"},
            "action": {"type": "string"},
            "name": {"type": "string"},
            "arguments": _action_arguments_schema(),
            "behavior": {"type": "string"},
            "prompt": {"type": "string"},
            "instruction": {"type": "string"},
            "purpose": {"type": "string"},
            "model": {"type": "string"},
            "final_text": {"type": "string"},
            "reasoning_summary": {"type": "string"},
        },
        "required": [
            "kind",
            "type",
            "action",
            "name",
            "arguments",
            "behavior",
            "prompt",
            "instruction",
            "purpose",
            "model",
            "final_text",
            "reasoning_summary",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "kind": {"type": "string"},
            "type": {"type": "string"},
            "action": {"type": "string"},
            "name": {"type": "string"},
            "arguments": _action_arguments_schema(),
            "behavior": {"type": "string"},
            "prompt": {"type": "string"},
            "instruction": {"type": "string"},
            "purpose": {"type": "string"},
            "model": {"type": "string"},
            "final_text": {"type": "string"},
            "reasoning_summary": {"type": "string"},
            "tasks": {"type": "array", "items": child_task},
            "subtasks": {"type": "array", "items": child_task},
            "parallel": {"type": "array", "items": child_task},
        },
        "required": [
            "kind",
            "type",
            "action",
            "name",
            "arguments",
            "behavior",
            "prompt",
            "instruction",
            "purpose",
            "model",
            "final_text",
            "reasoning_summary",
            "tasks",
            "subtasks",
            "parallel",
        ],
    }


class OpenAISubBehaviorClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        load_env_file(override=False)
        self.model_router = model_router or ModelRouter()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout or float(os.getenv("PMC_AGENT_HTTP_TIMEOUT", "30"))
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAISubBehaviorClient.")

    def run_behavior(
        self,
        behavior: str,
        prompt: str,
        context: dict[str, Any],
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        behavior = _normalize_behavior(behavior)
        route = self.model_router.route(
            ModelRouteRequest(
                action=_model_action_for_behavior(behavior),
                content=json.dumps({"prompt": prompt, "context": context}, ensure_ascii=False),
                metadata=metadata or {},
            )
        )
        selected_model = model or route.model
        interaction_id = str((metadata or {}).get("request_id") or generate_time_id())
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 智能体的快速子行为模块。只完成主控模型分配给你的局部任务，"
                        "不要越权调用工具，不要编造业务数据，输出简洁中文结论。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "behavior": behavior,
                            "prompt": prompt,
                            "context": context,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
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
            output_text = _extract_response_text(raw).strip()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error = f"HTTPError {exc.code}: {error_body[:1000]}"
            record_model_interaction("agentic_sub_behavior", interaction_id, payload, output=raw, error=error)
            raise RuntimeError(error) from exc
        except Exception as exc:
            record_model_interaction("agentic_sub_behavior", interaction_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            raise

        record_model_interaction("agentic_sub_behavior", interaction_id, payload, output=raw)
        logger.info(
            "agentic sub behavior completed",
            extra=log_extra("agentic_sub_behavior_completed", request_id=interaction_id, model=selected_model, behavior=behavior),
        )
        return {"ok": True, "behavior": behavior, "model": selected_model, "output": output_text}


@dataclass
class AgenticPmcLoop:
    planner: AgenticPlannerClient
    model: str
    db_connector: StiDatabaseConnector = field(default_factory=StiDatabaseConnector)
    inventory_policy: InventoryPolicy = field(default_factory=InventoryPolicy)
    knowledge_tool: KnowledgeLookupTool | None = None
    max_iterations: int = 20
    sub_behavior_client: SubBehaviorClient | None = None
    max_serial_space_tasks: int = 8
    max_parallel_model_tasks: int = 4
    event_sink: Callable[[dict[str, Any]], None] | None = None

    def __post_init__(self) -> None:
        if self.knowledge_tool is None:
            vector_connector = MilvusVectorConnector()
            self.knowledge_tool = KnowledgeLookupTool(connector=vector_connector if vector_connector.config.ready else None)
        if self.sub_behavior_client is None and isinstance(self.planner, OpenAIAgenticPlannerClient):
            self.sub_behavior_client = OpenAISubBehaviorClient(
                api_key=self.planner.api_key,
                base_url=self.planner.base_url,
                timeout=self.planner.timeout,
                model_router=self.planner.model_router,
            )

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
                            "复杂目标可以选择 run_serial_space，一次提交多个受控子任务；主模型仍负责下一轮方向和最终回答。",
                            "run_serial_space 中工具子任务按顺序执行；互不依赖的 model_behavior 子任务可以放入 parallel 组并发执行。",
                            "需要查询制度、SOP、规则或知识库片段时，可以选择 knowledge_lookup；它会优先走向量库连接，查不到时返回内置知识提示。",
                            "最终回答前必须自审；如果自审不通过，返回 final_answer 且 arguments.self_review_passed=false，并写明 review_notes，程序会在同一个 20 轮预算内继续。",
                            "自审失败后可以选择 inspect_run_trace 查看路径、行为、关键提示词和剩余轮次，再生成新一轮尝试。",
                            "最近对话上下文默认隐藏；如果本轮问题依赖上一轮对象、代词、继续追问或省略范围，先选择 decide_context 并设置 use_context=true。",
                            "如果本轮问题独立完整，或已包含明确物料/范围，则不要加载上下文，直接选择业务动作。",
                            "程序不会替你抽取物料编码；如果用户问题包含单个物料，必须由你在 action.arguments.material_code 中返回要查询的编码。",
                            "除非用户明确要求整体/全局/组合库存分析，否则 query_inventory_snapshot 必须携带 material_code。",
                            "用户问“爆款/旺款/平款/滞销”等组合范围时，query_inventory_snapshot 使用 scope=portfolio，并在 filters.sales_property 填入对应值；问“可能断货/缺货风险”时设置 filters.risk_only=true，通常选择 field_pack=inventory_risk 或 shortage_trace。",
                            "组合范围查询不要只取默认 LIMIT 样本后再概括，要用受控 filters 和 order_by 让数据库先筛选、排序。",
                            "真实数据库查不到时不能编造结果，必须把 observation 交回模型决策。",
                            "回答用户前必须基于 observation 判断是否足够。",
                            "最终回答中的表格必须使用稳定 Markdown 表格，且表头必须是固定业务字段名，不要用空格对齐或纯文本表格；前端会把 Markdown 表格抽取为定式表格组件。",
                            "字段表头要简洁稳定，例如“字段名称”“字段说明”“物料编码”“店铺”“国家”“可用库存”“近7天销量”“近30天销量”“近30天需求预测”。字段含义放在表格前后文字或字段说明列，不要塞进表头导致过长。",
                            "涉及风险、采购、发货或缺口判断时，最终回答必须单独写“计算逻辑”，用编号说明公式或判断规则。",
                            "只有当用户明确要求 Excel、附件、导出、下载或回传表格文件时，才提示附件能力；不要默认声称已生成附件。",
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
            self._emit(
                "model_thinking",
                iteration=iteration,
                label="模型思考中",
                detail="主模型正在判断下一步动作。",
                status="running",
            )
            decision = self.planner.decide_next(messages, metadata={"request_id": request_id})
            self._emit(
                "model_returned",
                iteration=iteration,
                label="模型返回",
                detail=f"主模型选择动作 {decision.action.value}。",
                status="completed",
                action=decision.action.value,
                arguments=_redact_sensitive(_to_jsonable(decision.arguments)),
                reasoning_summary=decision.reasoning_summary,
            )
            if decision.action == AgenticAction.INSPECT_RUN_TRACE:
                observation = self._inspect_run_trace(decision, messages, steps, iteration)
            else:
                observation = self._execute(decision, snapshots, hidden_context, context_loaded)
            if observation.get("context_loaded"):
                context_loaded = True
            if "snapshots" in observation:
                snapshots = [_snapshot_from_json(item) for item in observation["snapshots"]]
            steps.append(AgenticStep(iteration=iteration, decision=decision, observation=observation))
            self._emit(
                "observation_returned",
                iteration=iteration,
                label="节点返回",
                detail=f"{decision.action.value} 返回 observation。",
                status="completed" if observation.get("ok") else "failed",
                action=decision.action.value,
                observation=_compact_observation(observation),
            )

            if decision.action in {AgenticAction.FINAL_ANSWER, AgenticAction.ASK_USER}:
                if observation.get("self_review_failed"):
                    self._emit(
                        "self_review_failed",
                        iteration=iteration,
                        label="自审未通过",
                        detail=str(observation.get("review_notes") or "模型自审未通过，准备重试。"),
                        status="failed",
                        action=decision.action.value,
                    )
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
                    continue
                reply = _user_visible_text(decision, observation)
                self._emit(
                    "final_returned",
                    iteration=iteration,
                    label="最终返回",
                    detail="模型已生成可返回给用户的结果。",
                    status="completed",
                    action=decision.action.value,
                )
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
        self._emit(
            "final_returned",
            iteration=self.max_iterations + 1,
            label="最终返回",
            detail="达到轮次上限后强制总结。",
            status="completed",
            action=summary_decision.action.value,
        )
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
                self._emit_action_running(decision.action.value, "查看上下文", "判断是否需要加载最近对话上下文。")
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

            if decision.action == AgenticAction.RUN_SERIAL_SPACE:
                return self._execute_serial_space(decision, snapshots, hidden_context, context_loaded)

            if decision.action == AgenticAction.INSPECT_RUN_TRACE:
                return {"ok": False, "error": "inspect_run_trace is handled by the main loop so it can access messages and prior steps."}

            if decision.action == AgenticAction.QUERY_INVENTORY_SNAPSHOT:
                self._emit_action_running(decision.action.value, "调用工具", "正在读取库存快照。")
                material_code = _optional_str(decision.arguments.get("material_code"))
                if not material_code and not _is_explicit_portfolio_query(decision.arguments):
                    return {
                        "ok": False,
                        "error_type": "MissingModelArgument",
                        "error": "query_inventory_snapshot requires action.arguments.material_code unless the model explicitly sets scope='portfolio'. The program will not extract the code locally.",
                    }
                field_pack = normalize_field_pack(decision.arguments.get("field_pack"))
                query_spec = QuerySpec.inventory(
                    material_code=material_code,
                    field_pack=field_pack,
                    scope=_optional_str(decision.arguments.get("scope")),
                    filters=_inventory_filters_from_arguments(decision.arguments),
                    limit=_bounded_int(decision.arguments.get("limit"), default=50, minimum=1, maximum=500),
                )
                try:
                    rows = self.db_connector.get_inventory_snapshot(material_code, field_pack=field_pack, query_spec=query_spec)
                except TypeError:
                    rows = self.db_connector.get_inventory_snapshot(material_code)
                return {
                    "ok": True,
                    "query_material_code": material_code,
                    "field_pack": field_pack.value,
                    "filters": query_spec.filters,
                    "resolved_aliases": list(getattr(self.db_connector, "last_resolved_aliases", []) or []),
                    "note": "Rows may be returned under mapped SKU/MSKU/FNSKU values; they are the database-resolved inventory records for query_material_code.",
                    "snapshots": [_to_jsonable(item) for item in rows],
                    "row_count": len(rows),
                }

            if decision.action == AgenticAction.EVALUATE_INVENTORY_RISK:
                self._emit_action_running(decision.action.value, "调用工具", "正在计算库存风险。")
                if not snapshots:
                    return {"ok": False, "error": "No snapshots available. Query inventory snapshot first."}
                decisions = InventoryRiskTool(policy=self.inventory_policy).run(snapshots=snapshots)
                return {"ok": True, "decisions": [_to_jsonable(item) for item in decisions], "decision_count": len(decisions)}

            if decision.action == AgenticAction.KNOWLEDGE_LOOKUP:
                self._emit_action_running(decision.action.value, "调用知识库", "正在检索规则、SOP 或向量知识片段。")
                query = str(decision.arguments.get("query") or decision.arguments.get("material_code") or "").strip()
                if not query:
                    return {
                        "ok": False,
                        "error_type": "MissingKnowledgeQuery",
                        "error": "knowledge_lookup requires action.arguments.query.",
                    }
                snippets = self.knowledge_tool.run(query=query) if self.knowledge_tool else []
                return {
                    "ok": True,
                    "mode": "knowledge_lookup",
                    "query": query,
                    "snippets": snippets,
                    "snippet_count": len(snippets),
                }

            if decision.action == AgenticAction.FINAL_ANSWER:
                self._emit_action_running(decision.action.value, "生成回复", "正在准备最终回答。")
                if decision.arguments.get("self_review_passed") is False:
                    return {
                        "ok": False,
                        "self_review_failed": True,
                        "draft_answer": decision.final_text,
                        "review_notes": str(decision.arguments.get("review_notes") or decision.reasoning_summary or "").strip(),
                        "message": "Self review failed. Inspect run trace or create a revised attempt within the remaining iteration budget.",
                    }
                return {"ok": True, "message": decision.final_text}

            if decision.action == AgenticAction.ASK_USER:
                self._emit_action_running(decision.action.value, "准备追问", "正在生成需要用户补充的信息。")
                return {"ok": True, "message": decision.final_text}
        except Exception as exc:
            return {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}

        return {"ok": False, "error": f"Unsupported action: {decision.action.value}"}

    def _execute_serial_space(
        self,
        decision: AgenticDecision,
        snapshots: list[InventorySnapshot],
        hidden_context: list[dict[str, Any]],
        context_loaded: bool,
    ) -> dict[str, Any]:
        raw_tasks = decision.arguments.get("tasks") or decision.arguments.get("serial_tasks") or decision.arguments.get("serial_space") or []
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return {"ok": False, "error_type": "InvalidSerialSpace", "error": "run_serial_space requires a non-empty tasks array."}

        self._emit(
            "route_started",
            label="正在构建路线",
            detail=f"主模型下发 {min(len(raw_tasks), self.max_serial_space_tasks)} 个子任务。",
            status="running",
            action=decision.action.value,
        )
        local_snapshots = list(snapshots)
        local_context_loaded = context_loaded
        subtask_results: list[dict[str, Any]] = []
        latest_risk_decisions: list[dict[str, Any]] = []

        for index, task in enumerate(raw_tasks[: self.max_serial_space_tasks], start=1):
            if not isinstance(task, dict):
                result = {"index": index, "ok": False, "error_type": "InvalidSubtask", "error": "Subtask must be an object."}
            elif _is_parallel_group(task):
                self._emit(
                    "parallel_group_started",
                    label=f"并行组 {index}",
                    detail="多个子行为开始并行执行。",
                    status="running",
                    route_index=index,
                )
                result = self._execute_parallel_model_group(task, index, local_snapshots, hidden_context, subtask_results)
                self._emit(
                    "parallel_group_completed",
                    label=f"并行组 {index} 返回",
                    detail=f"并行组完成 {result.get('subtask_count', 0)} 个子行为。",
                    status="completed" if result.get("ok") else "failed",
                    route_index=index,
                )
            else:
                action_name = str(task.get("action") or task.get("name") or task.get("behavior") or "subtask")
                self._emit(
                    "route_node_started",
                    label=f"节点 {index}",
                    detail=f"{action_name} 执行中。",
                    status="running",
                    route_index=index,
                    action=action_name,
                )
                result = self._execute_serial_subtask(task, index, local_snapshots, hidden_context, local_context_loaded, subtask_results)
                self._emit(
                    "route_node_completed",
                    label=f"节点 {index} 返回",
                    detail=f"{action_name} 执行完成。",
                    status="completed" if result.get("ok") else "failed",
                    route_index=index,
                    action=action_name,
                    observation=_compact_observation(result),
                )

            if result.get("context_loaded"):
                local_context_loaded = True
            if "snapshots" in result:
                local_snapshots = [_snapshot_from_json(item) for item in result["snapshots"]]
            if "decisions" in result:
                latest_risk_decisions = list(result["decisions"])
            subtask_results.append(result)

        observation: dict[str, Any] = {
            "ok": all(bool(item.get("ok")) for item in subtask_results),
            "mode": "serial_space",
            "subtask_count": len(subtask_results),
            "subtasks": subtask_results,
        }
        if local_context_loaded and not context_loaded:
            observation["context_loaded"] = True
        if local_snapshots:
            observation["snapshots"] = [_to_jsonable(item) for item in local_snapshots]
            observation["row_count"] = len(local_snapshots)
        if latest_risk_decisions:
            observation["decisions"] = latest_risk_decisions
            observation["decision_count"] = len(latest_risk_decisions)
        self._emit(
            "route_completed",
            label="路线返回",
            detail=f"串行空间返回 {len(subtask_results)} 个节点结果。",
            status="completed" if observation.get("ok") else "failed",
            action=decision.action.value,
        )
        return observation

    def _execute_serial_subtask(
        self,
        task: dict[str, Any],
        index: int,
        snapshots: list[InventorySnapshot],
        hidden_context: list[dict[str, Any]],
        context_loaded: bool,
        previous_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        kind = str(task.get("kind") or task.get("type") or "").strip().lower()
        action = str(task.get("action") or task.get("name") or "").strip()
        arguments = dict(task.get("arguments") or {})

        if kind in {"model", "model_behavior", "sub_behavior"} or action in {"model_behavior", "sub_behavior"}:
            return self._execute_model_behavior_task(task, index, snapshots, hidden_context, previous_results)

        try:
            sub_decision = AgenticDecision(
                action=AgenticAction(action),
                arguments=arguments,
                final_text=str(task.get("final_text") or ""),
                reasoning_summary=str(task.get("reasoning_summary") or task.get("purpose") or ""),
            )
        except ValueError:
            return {"index": index, "ok": False, "error_type": "UnsupportedSubtaskAction", "error": f"Unsupported serial subtask action: {action}"}

        observation = self._execute(sub_decision, snapshots, hidden_context, context_loaded)
        return {"index": index, "kind": "tool", "action": sub_decision.action.value, **observation}

    def _execute_parallel_model_group(
        self,
        task: dict[str, Any],
        index: int,
        snapshots: list[InventorySnapshot],
        hidden_context: list[dict[str, Any]],
        previous_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        raw_group = task.get("tasks") or task.get("subtasks") or task.get("parallel") or []
        if not isinstance(raw_group, list) or not raw_group:
            return {"index": index, "ok": False, "kind": "parallel_model_group", "error_type": "InvalidParallelGroup", "error": "Parallel group requires subtasks."}
        group = [item for item in raw_group[: self.max_parallel_model_tasks] if isinstance(item, dict)]
        results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, min(self.max_parallel_model_tasks, len(group)))) as executor:
            future_map = {
                executor.submit(self._execute_model_behavior_task, item, child_index, snapshots, hidden_context, previous_results, index): child_index
                for child_index, item in enumerate(group, start=1)
            }
            for future in as_completed(future_map):
                try:
                    results.append(future.result())
                except Exception as exc:
                    results.append({"index": future_map[future], "ok": False, "error_type": type(exc).__name__, "error": str(exc)})
        results.sort(key=lambda item: int(item.get("index", 0)))
        return {
            "index": index,
            "ok": all(bool(item.get("ok")) for item in results),
            "kind": "parallel_model_group",
            "subtask_count": len(results),
            "subtasks": results,
        }

    def _execute_model_behavior_task(
        self,
        task: dict[str, Any],
        index: int,
        snapshots: list[InventorySnapshot],
        hidden_context: list[dict[str, Any]],
        previous_results: list[dict[str, Any]],
        parent_index: int | None = None,
    ) -> dict[str, Any]:
        if not self.sub_behavior_client:
            return {"index": index, "ok": False, "kind": "model_behavior", "error_type": "SubBehaviorUnavailable", "error": "No sub behavior client is configured."}
        behavior = _normalize_behavior(task.get("behavior") or task.get("action") or "summary")
        prompt = str(task.get("prompt") or task.get("instruction") or task.get("purpose") or "").strip()
        model = _optional_str(task.get("model"))
        context = {
            "snapshots": [_to_jsonable(item) for item in snapshots],
            "hidden_context_available": bool(hidden_context),
            "previous_results": previous_results[-4:],
            "task_context": task.get("context") if isinstance(task.get("context"), dict) else {},
        }
        self._emit(
            "sub_model_thinking",
            label=f"子模型 {index} 思考中",
            detail=f"{behavior} 子行为正在执行。",
            status="running",
            route_index=parent_index,
            parallel_index=index if parent_index is not None else None,
            behavior=behavior,
            model=model,
        )
        try:
            result = self.sub_behavior_client.run_behavior(
                behavior=behavior,
                prompt=prompt,
                context=context,
                model=model,
                metadata={"behavior": behavior},
            )
        except Exception as exc:
            self._emit(
                "sub_model_returned",
                label=f"子模型 {index} 返回",
                detail=f"{behavior} 子行为失败。",
                status="failed",
                route_index=parent_index,
                parallel_index=index if parent_index is not None else None,
                behavior=behavior,
                error=f"{type(exc).__name__}: {exc}",
            )
            return {"index": index, "ok": False, "kind": "model_behavior", "behavior": behavior, "error_type": type(exc).__name__, "error": str(exc)}
        self._emit(
            "sub_model_returned",
            label=f"子模型 {index} 返回",
            detail=f"{behavior} 子行为完成。",
            status="completed" if result.get("ok") else "failed",
            route_index=parent_index,
            parallel_index=index if parent_index is not None else None,
            behavior=behavior,
            model=result.get("model"),
        )
        return {"index": index, "kind": "model_behavior", **result}

    def _emit_action_running(self, action: str, label: str, detail: str) -> None:
        self._emit("action_running", label=label, detail=detail, status="running", action=action)

    def _emit(self, event: str, **payload: Any) -> None:
        if not self.event_sink:
            return
        try:
            self.event_sink({"event": event, **_to_jsonable(payload)})
        except Exception:
            logger.warning("agentic event sink failed", extra=log_extra("agentic_event_sink_failed", task_type=event))

    def _inspect_run_trace(
        self,
        decision: AgenticDecision,
        messages: list[dict[str, Any]],
        steps: list[AgenticStep],
        iteration: int,
    ) -> dict[str, Any]:
        include_prompts = bool(decision.arguments.get("include_prompts", True))
        include_observations = bool(decision.arguments.get("include_observations", True))
        trace: dict[str, Any] = {
            "ok": True,
            "mode": "run_trace",
            "current_iteration": iteration,
            "max_iterations": self.max_iterations,
            "remaining_iterations_after_this": max(self.max_iterations - iteration, 0),
            "review_notes": str(decision.arguments.get("review_notes") or decision.reasoning_summary or "").strip(),
            "action_path": [
                {
                    "iteration": step.iteration,
                    "action": step.decision.action.value,
                    "arguments": _redact_sensitive(_to_jsonable(step.decision.arguments)),
                    "reasoning_summary": step.decision.reasoning_summary,
                    "observation_ok": bool(step.observation.get("ok")),
                    "observation_mode": step.observation.get("mode"),
                    "error_type": step.observation.get("error_type"),
                    "error": step.observation.get("error"),
                }
                for step in steps
            ],
            "behavior_path": _extract_behavior_path(steps),
        }
        failed_drafts = [
            {
                "iteration": step.iteration,
                "draft_answer": step.observation.get("draft_answer"),
                "review_notes": step.observation.get("review_notes"),
            }
            for step in steps
            if step.observation.get("self_review_failed")
        ]
        if failed_drafts:
            trace["failed_drafts"] = failed_drafts[-3:]
        if include_prompts:
            trace["prompts"] = _compact_prompts(messages)
        if include_observations:
            trace["observations"] = [
                {
                    "iteration": step.iteration,
                    "action": step.decision.action.value,
                    "observation": _compact_observation(step.observation),
                }
                for step in steps
            ]
        return trace


def _agent_system_prompt() -> str:
    return (
        "你是 PMC 库存供应链智能体。你必须先理解用户目标，再基于可用表池和工具决定下一步动作。"
        "你不能假设程序已经知道该做什么；每一步都由你选择 action。程序会执行你的 action 并返回 observation。"
        "复杂目标可以用 run_serial_space 编排多个子任务，但每轮结束后仍由你检查 observation 并决定下一步。"
        "最终回答前要自审；自审不通过时不要把草稿交给用户，应触发同轮次预算内的修正尝试。"
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
            "name": AgenticAction.INSPECT_RUN_TRACE.value,
            "description": "Inspect the current run path after self-review fails. Returns action path, behavior path, compact prompts, compact observations, failed drafts, and remaining iteration budget.",
            "arguments": {"include_prompts": "boolean", "include_observations": "boolean", "review_notes": "string"},
        },
        {
            "name": AgenticAction.RUN_SERIAL_SPACE.value,
            "description": "Execute an ordered serial space of subtasks under main-model control. Tool subtasks run serially; independent model_behavior subtasks can be grouped under parallel.",
            "arguments": {
                "tasks": [
                    {
                        "kind": "tool",
                        "action": "decide_context | query_inventory_snapshot | evaluate_inventory_risk | knowledge_lookup",
                        "arguments": "same arguments as the selected tool action",
                    },
                    {
                        "kind": "parallel",
                        "tasks": [
                            {
                                "kind": "model_behavior",
                                "behavior": "summary | business_explanation | context_selection | failure_handling",
                                "prompt": "focused instruction for the sub model",
                                "model": "optional explicit model name",
                            }
                        ],
                    },
                ]
            },
        },
        {
            "name": AgenticAction.QUERY_INVENTORY_SNAPSHOT.value,
            "description": "Read inventory snapshot from the read-only STI database. Main table: ads_lingxing_all_warehouse_new_v1.",
                "arguments": {
                    "material_code": "required msku/sku/fnsku/ASIN-like code for a single-material user request",
                    "scope": "set to 'portfolio' only when the user explicitly asks for an overall inventory query",
                    "field_pack": "optional controlled field pack: inventory_snapshot, inventory_risk, shortage_trace, purchase_verification, shipment_verification, aging_analysis, logistics_trace",
                    "filters": "optional controlled filters: sales_property='爆' for 爆款, '旺' for 旺款; risk_only=true for possible shortage risk; positive_demand=true; order_by='risk_then_demand' or 'demand_desc'",
                },
        },
        {
            "name": AgenticAction.EVALUATE_INVENTORY_RISK.value,
            "description": "Evaluate inventory risk from the latest inventory snapshots returned by query_inventory_snapshot.",
            "arguments": {},
        },
        {
            "name": AgenticAction.KNOWLEDGE_LOOKUP.value,
            "description": "Search SOP, rule, and vector knowledge snippets. Prefer this when the user asks about process rules, table meanings, verification logic, or operational guidance.",
            "arguments": {"query": "required text query"},
        },
        {"name": AgenticAction.ASK_USER.value, "description": "Ask user for missing code, scope, or confirmation.", "arguments": {}},
        {
            "name": AgenticAction.FINAL_ANSWER.value,
            "description": "Return final answer to user only when self-review passes. Use stable Markdown tables with short fixed headers for queried facts, and a numbered calculation-logic section for computed results. If self-review fails, set self_review_passed=false and provide review_notes; this consumes one normal iteration and continues.",
            "arguments": {"self_review_passed": "boolean", "review_notes": "string"},
        },
    ]


def _is_parallel_group(task: dict[str, Any]) -> bool:
    kind = str(task.get("kind") or task.get("type") or "").strip().lower()
    if kind in {"parallel", "parallel_model_group"}:
        return True
    parallel = task.get("parallel")
    return isinstance(parallel, list) and bool(parallel)


def _normalize_behavior(value: Any) -> str:
    behavior = str(value or "summary").strip().lower()
    allowed = {"summary", "business_explanation", "context_selection", "failure_handling"}
    return behavior if behavior in allowed else "summary"


def _model_action_for_behavior(behavior: str) -> ModelAction:
    return {
        "business_explanation": ModelAction.BUSINESS_EXPLANATION,
        "context_selection": ModelAction.CONTEXT_SELECTION,
        "failure_handling": ModelAction.FAILURE_HANDLING,
        "summary": ModelAction.SUMMARY,
    }.get(behavior, ModelAction.SUMMARY)


def _extract_behavior_path(steps: list[AgenticStep]) -> list[dict[str, Any]]:
    behavior_path: list[dict[str, Any]] = []
    for step in steps:
        _collect_behaviors(step.observation, behavior_path, step.iteration)
    return behavior_path


def _collect_behaviors(value: Any, behavior_path: list[dict[str, Any]], iteration: int) -> None:
    if isinstance(value, dict):
        if value.get("kind") == "model_behavior":
            behavior_path.append(
                {
                    "iteration": iteration,
                    "index": value.get("index"),
                    "behavior": value.get("behavior"),
                    "model": value.get("model"),
                    "ok": value.get("ok"),
                    "error_type": value.get("error_type"),
                }
            )
        for key in ("subtasks", "tasks", "parallel"):
            items = value.get(key)
            if isinstance(items, list):
                for item in items:
                    _collect_behaviors(item, behavior_path, iteration)
    elif isinstance(value, list):
        for item in value:
            _collect_behaviors(item, behavior_path, iteration)


def _compact_prompts(messages: list[dict[str, Any]]) -> dict[str, Any]:
    prompts: dict[str, Any] = {"system": "", "initial_user_payload": {}}
    if messages:
        prompts["system"] = str(messages[0].get("content") or "")[:2000]
    if len(messages) > 1:
        raw = str(messages[1].get("content") or "")
        try:
            prompts["initial_user_payload"] = _redact_sensitive(json.loads(raw))
        except json.JSONDecodeError:
            prompts["initial_user_payload"] = raw[:2000]
    return prompts


def _compact_observation(observation: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for key in (
        "ok",
        "mode",
        "error_type",
        "error",
        "message",
        "query_material_code",
        "resolved_aliases",
        "row_count",
        "decision_count",
        "snippet_count",
        "query",
        "subtask_count",
        "self_review_failed",
        "review_notes",
    ):
        if key in observation:
            compact[key] = observation[key]
    if "draft_answer" in observation:
        compact["draft_answer"] = str(observation.get("draft_answer") or "")[:1200]
    if "subtasks" in observation and isinstance(observation["subtasks"], list):
        compact["subtasks"] = [_compact_subtask(item) for item in observation["subtasks"][:8]]
    return _redact_sensitive(compact)


def _compact_subtask(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    compact: dict[str, Any] = {}
    for key in ("index", "ok", "kind", "action", "behavior", "model", "error_type", "error", "row_count", "decision_count", "snippet_count", "query", "subtask_count"):
        if key in value:
            compact[key] = value[key]
    if "subtasks" in value and isinstance(value["subtasks"], list):
        compact["subtasks"] = [_compact_subtask(item) for item in value["subtasks"][:8]]
    return compact


def _redact_sensitive(value: Any) -> Any:
    sensitive_terms = ("api_key", "password", "token", "secret", "authorization")
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            if any(term in key_text.lower() for term in sensitive_terms):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_sensitive(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


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


def _inventory_filters_from_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    raw_filters = arguments.get("filters")
    filters = dict(raw_filters) if isinstance(raw_filters, dict) else {}
    sales_property = _optional_str(filters.get("sales_property") or filters.get("msku_sales_property"))
    if sales_property in {"爆", "旺", "平", "滞"}:
        filters["sales_property"] = sales_property
    else:
        filters.pop("sales_property", None)
        filters.pop("msku_sales_property", None)

    filters["risk_only"] = bool(filters.get("risk_only"))
    filters["positive_demand"] = bool(filters.get("positive_demand"))
    order_by = _optional_str(filters.get("order_by"))
    filters["order_by"] = order_by if order_by in {"demand_desc", "risk_then_demand"} else ""
    return filters


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
    if value is None:
        return None
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if is_dataclass(value):
        return _to_jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_to_jsonable(item) for item in value]
    return value
