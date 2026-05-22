from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import json
import os
from pathlib import Path
import subprocess
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from pmc_agent.agentic_loop import AgenticPmcLoop, OpenAIAgenticPlannerClient
from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.context_manager import ContextManager, HeuristicContextDecisionClient
from pmc_agent.domain import TaskRequest, TaskType
from pmc_agent.env import load_env_file
from pmc_agent.model import IntentAssessment, OpenAIIntentModelClient
from pmc_agent.model_io import generate_time_id
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter, ModelRoutingPolicy
from pmc_agent.orchestrator import PmcAgent
from pmc_agent.planning.classifier import enrich_request


logger = get_logger(__name__)
ROOT_DIR = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT_DIR / "web"

MODEL_OPTIONS = [
    "gpt-5.1",
    "gpt-5.4-mini",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-4.1",
    "gpt-3.5-turbo",
]


TEST_TARGETS = [
    {"id": "all", "name": "全部测试", "target": "discover", "description": "运行 tests 目录下所有单元测试。", "uses_real_model": False},
    {"id": "planning", "name": "计划模块", "target": "tests.test_planning", "description": "验证模型意图承接和计划生成。", "uses_real_model": False},
    {"id": "model", "name": "模型模块", "target": "tests.test_model", "description": "验证模型响应解析，不发起真实接口请求。", "uses_real_model": False},
    {"id": "model_router", "name": "模型调度", "target": "tests.test_model_router", "description": "验证不同动作和风险内容会路由到不同模型。", "uses_real_model": False},
    {"id": "model_io", "name": "模型记录", "target": "tests.test_model_io", "description": "验证模型交互落盘路径和内容。", "uses_real_model": False},
    {"id": "state", "name": "状态机", "target": "tests.test_state", "description": "验证状态流转和日志绑定。", "uses_real_model": False},
    {"id": "tools_inventory", "name": "库存工具", "target": "tests.test_tools_inventory", "description": "验证库存、控制塔、采购、周度计划等工具。", "uses_real_model": False},
    {"id": "verifier", "name": "验证器", "target": "tests.test_verifier", "description": "验证决策和 artifact 复核逻辑。", "uses_real_model": False},
    {"id": "env_logging", "name": "环境与日志", "target": "tests.test_env_and_logging", "description": "验证 .env 加载和结构化日志。", "uses_real_model": False},
    {"id": "orchestrator", "name": "编排器", "target": "tests.test_orchestrator", "description": "验证端到端编排和状态历史。", "uses_real_model": False},
]

LLM_MODULES = [
    {
        "id": "model_routing",
        "name": "模型调度",
        "description": "根据动作类型、业务内容和风险信号选择应该调用的模型。",
        "input_schema": {
            "text": "待判断的业务内容，必填",
            "action": "动作类型，可选：intent_recognition / goal_repair / tool_orchestration / business_explanation / summary",
            "metadata": "附加调度信号，例如 needs_write_or_approval 或 high_risk",
        },
        "standard_input": {
            "text": "请确认 A100 采购下单并生成异常处理建议",
            "action": "intent_recognition",
            "metadata": {"needs_write_or_approval": True},
        },
        "expected_output": {
            "action": "动作类型",
            "model": "被选中的模型",
            "reason": "选择原因",
            "source": "命中的调度策略",
        },
    },
    {
        "id": "intent_recognition",
        "name": "意图识别",
        "description": "单模块诊断：只识别任务类型和执行约束，不负责返回查询动作或物料参数。",
        "input_schema": {
            "text": "用户原始请求，必填",
            "material_code": "物料编码，可为空；为空时会从 text 中尝试抽取",
            "recent_context": "最近上下文数组，可为空",
        },
        "standard_input": {
            "text": "检查 A100 是否有缺料风险",
            "material_code": "A100",
            "recent_context": [],
        },
        "expected_output": {
            "task_type": "inventory_risk",
            "confidence": "0 到 1 的置信度",
            "needs_data_context": True,
            "needs_calculation": True,
            "needs_write_or_approval": False,
            "risk_level": "low / medium / high",
        },
    }
    ,
    {
        "id": "agentic_orchestration",
        "name": "模型驱动执行循环",
        "description": "真实执行入口：大模型先返回动作和参数，程序执行白名单动作并把 observation 交回模型，直到最终回答。",
        "input_schema": {
            "text": "用户原始请求，必填",
        },
        "standard_input": {
            "text": "B0BXD4MCCK这个有多少库存",
        },
        "expected_output": {
            "mode": "agentic_model",
            "reply": "最终用户回答",
            "steps": "模型决策、程序 observation 和最终回答",
        },
    }
]


MODULE_CONTRACTS = [
    {
        "module": "model_router",
        "input": "ModelAction + content + metadata",
        "expected_output": "ModelRouteDecision，包含 action、model、reason、source",
        "expected_nodes": ["model_route_selected"],
    },
    {
        "module": "planning",
        "input": "TaskRequest + 模型返回的 IntentAssessment",
        "expected_output": "ExecutionPlan，包含 task_type、confidence、steps、assumptions",
        "expected_nodes": ["intent_recognized", "plan_built"],
    },
    {
        "module": "tools.inventory_snapshot",
        "input": "material_code，例如 A100",
        "expected_output": "InventorySnapshot 列表；缺数据时返回空列表并输出 WARNING",
        "expected_nodes": ["tool_started:inventory_snapshot", "tool_completed:inventory_snapshot"],
    },
    {
        "module": "tools.inventory_risk",
        "input": "InventorySnapshot 列表",
        "expected_output": "ControlDecision 列表，包含 risk_level、summary、recommended_actions、evidence",
        "expected_nodes": ["tool_started:inventory_risk", "tool_completed:inventory_risk"],
    },
    {
        "module": "tools.purchase_verification",
        "input": "InventorySnapshot 列表",
        "expected_output": "采购验证 ControlDecision 草稿，必须保留人工确认边界",
        "expected_nodes": ["tool_started:purchase_verification", "tool_completed:purchase_verification"],
    },
    {
        "module": "tools.weekly_shipment_plan",
        "input": "RiskSignal 列表",
        "expected_output": "weekly_shipment_plan artifact，状态为 draft",
        "expected_nodes": ["tool_started:control_tower", "tool_completed:weekly_shipment_plan"],
    },
    {
        "module": "verifier",
        "input": "ExecutionPlan + decisions/artifacts",
        "expected_output": "验证消息列表；草稿类 artifact 必须提示人工复核",
        "expected_nodes": ["verification_started", "task_completed"],
    },
    {
        "module": "state",
        "input": "状态目标 + 事件名 + 上下文字段",
        "expected_output": "StateTransition 历史记录 + state_transition 日志",
        "expected_nodes": ["created", "intent_recognizing", "completed"],
    },
]


SCENARIOS = [
    {
        "id": "simple_chat",
        "name": "简单聊天",
        "text": "你好",
        "task_type": TaskType.SIMPLE_CHAT,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:simple_chat", "task_completed"],
    },
    {
        "id": "inventory_risk",
        "name": "库存风险",
        "text": "检查 A100 是否有缺料风险",
        "task_type": TaskType.INVENTORY_RISK,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:inventory_snapshot", "tool_completed:inventory_risk", "task_completed"],
    },
    {
        "id": "shortage_trace",
        "name": "断货追因",
        "text": "请做 A100 断货追因",
        "task_type": TaskType.SHORTAGE_TRACE,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:inventory_snapshot", "tool_completed:shortage_trace", "task_completed"],
    },
    {
        "id": "shipment_verification",
        "name": "发货验证",
        "text": "请按 A100 做发货验证",
        "task_type": TaskType.SHIPMENT_VERIFICATION,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:inventory_snapshot", "tool_completed:shipment_verification", "task_completed"],
    },
    {
        "id": "purchase_verification",
        "name": "采购验证",
        "text": "请按 A100 做采购验证",
        "task_type": TaskType.PURCHASE_VERIFICATION,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:inventory_snapshot", "tool_completed:purchase_verification", "task_completed"],
    },
    {
        "id": "weekly_plan",
        "name": "周度计划",
        "text": "生成周度发货计划草稿",
        "task_type": TaskType.WEEKLY_SHIPMENT_PLAN,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:control_tower", "tool_completed:weekly_shipment_plan", "task_completed"],
    },
    {
        "id": "exception_case",
        "name": "异常 Case",
        "text": "为当前高风险库存创建异常 Case",
        "task_type": TaskType.EXCEPTION_CASE,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:control_tower", "tool_completed:exception_case", "task_completed"],
    },
    {
        "id": "knowledge_qa",
        "name": "规则问答",
        "text": "解释发货验证和采购验证的规则口径",
        "task_type": TaskType.KNOWLEDGE_QA,
        "expected_nodes": ["intent_recognized", "plan_built", "tool_completed:knowledge_lookup", "task_completed"],
    },
]


class FakeIntentModel:
    """测试前端使用的意图模型，避免本地验收消耗真实模型调用。"""

    def __init__(self, task_type: TaskType) -> None:
        self.task_type = task_type

    def assess_intent(self, request, recent_context=None) -> IntentAssessment:
        return IntentAssessment(
            task_type=self.task_type,
            confidence=0.95,
            user_expectation="测试前端指定的场景意图",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=self.task_type in {TaskType.PURCHASE_VERIFICATION, TaskType.WEEKLY_SHIPMENT_PLAN, TaskType.EXCEPTION_CASE},
            risk_level="medium",
            reasoning_summary="由测试前端注入，绕过真实模型调用。",
        )


class HeuristicIntentModel:
    """简易对话页使用的本地意图模型，让前端不依赖真实模型也能体验。"""

    def assess_intent(self, request, recent_context=None) -> IntentAssessment:
        text = request.text
        task_type = infer_task_type(text)
        return IntentAssessment(
            task_type=task_type,
            confidence=0.75,
            user_expectation="本地简易对话意图识别",
            needs_data_context=True,
            needs_calculation=True,
            needs_write_or_approval=task_type in {TaskType.PURCHASE_VERIFICATION, TaskType.WEEKLY_SHIPMENT_PLAN, TaskType.EXCEPTION_CASE},
            risk_level="medium",
            reasoning_summary="由对话页本地规则推断；如需语义识别，请开启真实模型。",
        )


class TestConsoleHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def do_GET(self) -> None:
        path = _request_path(self.path)
        if path == "/api/health":
            self._send_json({"ok": True})
            return
        if path == "/api/tests":
            self._send_json({"tests": TEST_TARGETS})
            return
        if path == "/api/scenarios":
            self._send_json({"scenarios": [_scenario_to_json(item) for item in SCENARIOS]})
            return
        if path == "/api/contracts":
            self._send_json({"contracts": MODULE_CONTRACTS})
            return
        if path == "/api/model-options":
            self._send_json(get_model_options())
            return
        if path == "/api/llm/modules":
            self._send_json({"modules": LLM_MODULES})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = _request_path(self.path)
        if path == "/api/tests/run":
            payload = self._read_json()
            self._send_json(run_test_target(str(payload.get("id", "all"))))
            return
        if path == "/api/scenarios/run":
            payload = self._read_json()
            self._send_json(run_scenario(str(payload.get("id", "")), payload.get("text"), bool(payload.get("use_real_model", False)), payload.get("model")))
            return
        if path == "/api/llm/run":
            payload = self._read_json()
            self._send_json(run_llm_module(str(payload.get("id", "")), payload.get("input"), payload.get("model")))
            return
        if path == "/api/chat/run":
            payload = self._read_json()
            self._send_json(run_chat(payload))
            return
        self.send_error(404, "Not found")

    def log_message(self, format: str, *args: Any) -> None:
        logger.info("test frontend request", extra=log_extra("test_frontend_request", path=self.path))

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=_to_jsonable).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_test_target(test_id: str) -> dict[str, Any]:
    target = next((item for item in TEST_TARGETS if item["id"] == test_id), None)
    if target is None:
        return {"ok": False, "error": f"未知测试 ID: {test_id}"}

    if target["target"] == "discover":
        command = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    else:
        command = [sys.executable, "-m", "unittest", str(target["target"])]

    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT_DIR / "src")
    completed = subprocess.run(command, cwd=ROOT_DIR, env=env, capture_output=True, text=True, timeout=120)
    return {
        "ok": completed.returncode == 0,
        "id": test_id,
        "name": target["name"],
        "command": " ".join(command),
        "returncode": completed.returncode,
        "uses_real_model": bool(target.get("uses_real_model")),
        "model_mode": "单元测试/mock，不调用真实大模型",
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def get_model_options() -> dict[str, Any]:
    load_env_file(override=False)
    policy = ModelRoutingPolicy.from_env()
    default_model = policy.intent_model
    options = [
        default_model,
        policy.default_model,
        policy.goal_repair_model,
        policy.tool_orchestration_model,
        policy.business_explanation_model,
        policy.summary_model,
        policy.high_risk_model,
        *MODEL_OPTIONS,
    ]
    deduped = list(dict.fromkeys(item for item in options if item))
    return {"default_model": default_model, "options": deduped, "routing_policy": _to_jsonable(policy)}


def _resolve_model(model: Any = None) -> str:
    load_env_file(override=False)
    selected = str(model or "").strip()
    return selected or os.getenv("PMC_AGENT_INTENT_MODEL", "gpt-5.4-mini")


def run_scenario(scenario_id: str, text_override: Any = None, use_real_model: bool = False, model: Any = None) -> dict[str, Any]:
    scenario = next((item for item in SCENARIOS if item["id"] == scenario_id), None)
    if scenario is None:
        return {"ok": False, "error": f"未知场景 ID: {scenario_id}"}

    text = str(text_override or scenario["text"])
    selected_model = _resolve_model(model)
    if use_real_model:
        try:
            loop = AgenticPmcLoop(planner=OpenAIAgenticPlannerClient(model=selected_model), model=selected_model)
            result = loop.run(text)
        except Exception as exc:
            return {
                "ok": False,
                "scenario": _scenario_to_json(scenario),
                "mode": "agentic_model",
                "model": selected_model,
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "真实模型驱动循环失败，请检查 OPENAI_API_KEY、OPENAI_BASE_URL、模型名和数据库配置。",
                "model_record_hint": "logs/model_interactions/conversations/<request_id>.txt",
            }
        return {
            "ok": result.ok,
            "scenario": _scenario_to_json(scenario),
            "mode": "agentic_model",
            "model": selected_model,
            "model_record_hint": "logs/model_interactions/conversations/<request_id>.txt",
            "state_check": None,
            "reply": result.reply,
            "result": _to_jsonable(result),
            "error": result.error,
        }

    intent_model = OpenAIIntentModelClient(model=selected_model) if use_real_model else FakeIntentModel(scenario["task_type"])
    agent = PmcAgent.create_default(intent_model)
    try:
        result = agent.run(text)
    except Exception as exc:
        return {
            "ok": False,
            "scenario": _scenario_to_json(scenario),
            "mode": "real_model" if use_real_model else "fake_intent_model",
            "model": selected_model if use_real_model else None,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "如果启用了真实数据库，请检查物料编码是否存在、数据库连接是否可用；如果启用了真实模型，请检查模型 API 配置。",
            "model_record_hint": "logs/model_interactions/conversations/<request_id>.txt" if use_real_model else None,
        }
    state_check = check_expected_nodes(result.state_history, scenario["expected_nodes"])
    return {
        "ok": True,
        "scenario": _scenario_to_json(scenario),
        "mode": "real_model" if use_real_model else "fake_intent_model",
        "model": selected_model if use_real_model else None,
        "model_record_hint": "logs/model_interactions/conversations/<request_id>.txt" if use_real_model else None,
        "state_check": state_check,
        "result": _to_jsonable(result),
    }


def run_chat(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "请输入内容"}

    use_real_model = bool(payload.get("use_real_model", False))
    selected_model = _resolve_model(payload.get("model")) if use_real_model else None
    recent_context = payload.get("recent_context")
    if not isinstance(recent_context, list):
        recent_context = []
    if use_real_model:
        request_id = generate_time_id()
        try:
            loop = AgenticPmcLoop(planner=OpenAIAgenticPlannerClient(model=selected_model), model=selected_model)
            result = loop.run(text, recent_context=recent_context, request_id=request_id)
        except Exception as exc:
            return {
                "ok": False,
                "mode": "agentic_model",
                "model": selected_model,
                "record_path": f"logs/model_interactions/conversations/{request_id}.txt",
                "error": f"{type(exc).__name__}: {exc}",
                "hint": "真实模型驱动循环失败，请检查 OPENAI_API_KEY、OPENAI_BASE_URL、模型名和数据库配置。",
            }
        return {
            "ok": result.ok,
            "mode": "agentic_model",
            "model": selected_model,
            "reply": result.reply,
            "result": _to_jsonable(result),
            "record_path": f"logs/model_interactions/conversations/{request_id}.txt",
            "error": result.error,
        }

    intent_model = OpenAIIntentModelClient(model=selected_model) if use_real_model else HeuristicIntentModel()
    agent = PmcAgent.create_default(intent_model)
    try:
        result = agent.run(text)
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "hint": "如果启用了真实数据库，请检查物料编码是否存在、数据库连接是否可用；如果启用了真实模型，请检查模型 API 配置。",
        }

    return {
        "ok": True,
        "mode": "real_model" if use_real_model else "local_heuristic",
        "model": selected_model,
        "reply": format_chat_reply(result),
        "result": _to_jsonable(result),
        "context_decision": _to_jsonable(ContextManager(HeuristicContextDecisionClient()).select_context(text, recent_context)),
    }


def run_llm_module(module_id: str, input_payload: Any = None, model: Any = None) -> dict[str, Any]:
    module = next((item for item in LLM_MODULES if item["id"] == module_id), None)
    if module is None:
        return {"ok": False, "error": f"未知大模型模块 ID: {module_id}"}
    if module_id == "model_routing":
        return run_model_routing_module(module, input_payload)
    if module_id == "agentic_orchestration":
        return run_agentic_orchestration_module(module, input_payload, model)
    if module_id != "intent_recognition":
        return {"ok": False, "error": f"暂不支持的大模型模块: {module_id}"}

    payload = input_payload if isinstance(input_payload, dict) else {}
    text = str(payload.get("text") or module["standard_input"]["text"]).strip()
    if not text:
        return {"ok": False, "error": "text 不能为空"}

    enriched = enrich_request(text)
    material_code = str(payload.get("material_code") or enriched.material_code or "").strip() or None
    recent_context = payload.get("recent_context")
    if not isinstance(recent_context, list):
        recent_context = []

    selected_model = _resolve_model(model)
    request_id = generate_time_id()
    request = TaskRequest(text=text, material_code=material_code, metadata={"request_id": request_id, "debug_module": module_id})
    try:
        assessment = OpenAIIntentModelClient(model=selected_model).assess_intent(request, recent_context=recent_context)
    except Exception as exc:
        return {
            "ok": False,
            "module": module,
            "model": selected_model,
            "request": _to_jsonable(request),
            "error": f"{type(exc).__name__}: {exc}",
            "record_path": f"logs/model_interactions/conversations/{request_id}.txt",
        }

    return {
        "ok": True,
        "module": module,
        "model": selected_model,
        "request": _to_jsonable(request),
        "recent_context": recent_context,
        "output": _to_jsonable(assessment),
        "record_path": f"logs/model_interactions/conversations/{request_id}.txt",
    }


def run_agentic_orchestration_module(module: dict[str, Any], input_payload: Any = None, model: Any = None) -> dict[str, Any]:
    payload = input_payload if isinstance(input_payload, dict) else {}
    text = str(payload.get("text") or module["standard_input"]["text"]).strip()
    if not text:
        return {"ok": False, "module": module, "error": "text 不能为空"}

    selected_model = _resolve_model(model)
    try:
        loop = AgenticPmcLoop(planner=OpenAIAgenticPlannerClient(model=selected_model), model=selected_model)
        result = loop.run(text)
    except Exception as exc:
        return {
            "ok": False,
            "module": module,
            "mode": "agentic_model",
            "model": selected_model,
            "error": f"{type(exc).__name__}: {exc}",
            "record_path": "logs/model_interactions/conversations/<request_id>.txt",
        }

    return {
        "ok": result.ok,
        "module": module,
        "mode": "agentic_model",
        "model": selected_model,
        "reply": result.reply,
        "output": {
            "reply": result.reply,
            "steps": _to_jsonable(result.steps),
            "error": result.error,
        },
        "result": _to_jsonable(result),
        "record_path": "logs/model_interactions/conversations/<request_id>.txt",
        "error": result.error,
    }


def run_model_routing_module(module: dict[str, Any], input_payload: Any = None) -> dict[str, Any]:
    payload = input_payload if isinstance(input_payload, dict) else {}
    text = str(payload.get("text") or module["standard_input"]["text"]).strip()
    action_value = str(payload.get("action") or module["standard_input"]["action"]).strip()
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    try:
        action = ModelAction(action_value)
    except ValueError:
        return {"ok": False, "module": module, "error": f"未知模型动作类型: {action_value}"}

    decision = ModelRouter().route(ModelRouteRequest(action=action, content=text, metadata=metadata))
    return {
        "ok": True,
        "module": module,
        "request": {"text": text, "action": action.value, "metadata": metadata},
        "output": _to_jsonable(decision),
        "record_path": "model routing does not call a remote model",
    }


def create_server(host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), TestConsoleHandler)


def main() -> None:
    load_env_file(override=False)
    server = create_server()
    host, port = server.server_address
    print(f"PMC 测试前端已启动: http://{host}:{port}")
    server.serve_forever()


def _scenario_to_json(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "task_type": item["task_type"].value}


def _request_path(raw_path: str) -> str:
    path = urlparse(raw_path).path
    if path != "/":
        path = path.rstrip("/")
    return path


def infer_task_type(text: str) -> TaskType:
    lowered = text.lower()
    if is_simple_chat(text):
        return TaskType.SIMPLE_CHAT
    if any(word in text for word in ("断货", "追因", "原因链")):
        return TaskType.SHORTAGE_TRACE
    if "发货" in text and any(word in text for word in ("验证", "复算", "校验")):
        return TaskType.SHIPMENT_VERIFICATION
    if "采购" in text and any(word in text for word in ("验证", "复算", "建议", "下单")):
        return TaskType.PURCHASE_VERIFICATION
    if any(word in text for word in ("周度", "计划草稿", "发货计划")):
        return TaskType.WEEKLY_SHIPMENT_PLAN
    if any(word in text for word in ("异常", "case", "Case")):
        return TaskType.EXCEPTION_CASE
    if any(word in text for word in ("规则", "口径", "解释", "sop", "SOP")):
        return TaskType.KNOWLEDGE_QA
    if any(word in text for word in ("控制塔", "看板", "风险列表")):
        return TaskType.CONTROL_TOWER
    if "risk" in lowered or any(word in text for word in ("风险", "缺料", "库存")):
        return TaskType.INVENTORY_RISK
    return TaskType.GENERAL_ANALYSIS


def format_chat_reply(result) -> str:
    failure_decision = result.artifacts.get("failure_decision")
    if failure_decision:
        if isinstance(failure_decision, dict):
            message = str(failure_decision.get("user_message") or "当前查询失败，模型已生成处理建议。")
            suggested = failure_decision.get("suggested_inputs") or []
        else:
            message = str(getattr(failure_decision, "user_message", "当前查询失败，模型已生成处理建议。"))
            suggested = getattr(failure_decision, "suggested_inputs", [])
        if suggested:
            return message + "\n\n可补充：" + "；".join(str(item) for item in suggested)
        return message

    chat_reply = result.artifacts.get("chat_reply")
    if isinstance(chat_reply, dict) and chat_reply.get("reply"):
        return str(chat_reply["reply"])

    lines = []
    if result.decisions:
        for decision in result.decisions:
            level = _risk_label(decision.risk_level.value)
            lines.append(f"{decision.material_code}：{level}。{_localize_summary(decision.summary)}")
            if decision.recommended_actions:
                lines.append("建议：" + "；".join(_localize_action(item) for item in decision.recommended_actions[:2]))
    visible_artifacts = {key: value for key, value in result.artifacts.items() if key != "chat_reply"}
    if visible_artifacts:
        lines.append("已生成草稿：" + "、".join(visible_artifacts.keys()))
    if not lines:
        return "我还没有拿到足够的信息。可以补充物料编码，比如 A100，或说明你要看库存、采购还是发货。"
    if result.plan.assumptions:
        lines.append("提示：未识别到具体物料，当前按整体库存范围处理。")
    return "\n\n".join(lines)


def is_simple_chat(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"你好", "您好", "hello", "hi", "嗨", "在吗", "hey", "谢谢", "感谢", "thanks", "thank you"}


def _risk_label(value: str) -> str:
    return {
        "critical": "严重风险",
        "high": "高风险",
        "medium": "中风险",
        "low": "低风险",
    }.get(value, value)


def _localize_summary(summary: str) -> str:
    replacements = {
        "projected 7-day inventory is": "预计 7 天库存为",
        "estimated days of cover is": "预计可覆盖天数为",
        "pcs": "件",
    }
    for source, target in replacements.items():
        summary = summary.replace(source, target)
    return summary


def _localize_action(action: str) -> str:
    translations = {
        "Freeze non-urgent allocations and re-check production priority.": "暂停非紧急分配，复核生产优先级。",
        "Expedite inbound supply and request confirmed arrival time from supplier.": "催进入库供应，并向供应商确认到货时间。",
        "Prepare emergency replenishment at least MOQ 100 pcs.": "准备不少于 MOQ 100 件的紧急补货。",
        "No immediate control action required; keep routine monitoring.": "暂无紧急动作，保持日常监控。",
    }
    return translations.get(action, action)


def check_expected_nodes(history: list[Any], expected_nodes: list[str]) -> dict[str, Any]:
    observed = []
    for item in history:
        observed.append(item.event)
        observed.append(item.to_status.value if hasattr(item.to_status, "value") else str(item.to_status))
        tool = item.detail.get("tool") if hasattr(item, "detail") else None
        if tool:
            observed.append(f"{item.event}:{tool}")
    missing = [node for node in expected_nodes if node not in observed]
    return {"ok": not missing, "expected": expected_nodes, "observed": observed, "missing": missing}


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


if __name__ == "__main__":
    main()
