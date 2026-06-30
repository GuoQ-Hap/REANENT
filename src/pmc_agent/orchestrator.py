from __future__ import annotations

from dataclasses import dataclass

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.config import AgentConfig
from pmc_agent.connectors.database import StiDatabaseConnector
from pmc_agent.connectors.vector_database import MilvusVectorConnector
from pmc_agent.domain import AgentRunResult, ControlDecision, GoalRunResult, TaskRequest
from pmc_agent.goal_loop import GoalLoop
from pmc_agent.model import FailureHandlingModelClient, IntentModelClient, OpenAIIntentModelClient
from pmc_agent.model_io import generate_time_id
from pmc_agent.planning import build_plan, classify_task
from pmc_agent.planning.classifier import enrich_request
from pmc_agent.schema_catalog import field_pack_for_task
from pmc_agent.state import RunStateMachine, RunStatus
from pmc_agent.tools import InventoryRiskTool, InventorySnapshotTool, ToolRegistry
from pmc_agent.tools import (
    ControlTowerTool,
    ExceptionCaseTool,
    KnowledgeLookupTool,
    PurchaseVerificationTool,
    ShipmentVerificationTool,
    SimpleChatTool,
    ShortageTraceTool,
    SkuFullChainDiagnosisTool,
    WeeklyShipmentPlanTool,
)
from pmc_agent.verifier import verify_decisions


logger = get_logger(__name__)


@dataclass
class PmcAgent:
    """协调意图识别、计划生成、工具执行和结果验证。"""

    config: AgentConfig
    tools: ToolRegistry
    intent_model: IntentModelClient
    failure_model: FailureHandlingModelClient | None = None

    @classmethod
    def create_default(cls, intent_model: IntentModelClient | None = None) -> "PmcAgent":
        config = AgentConfig()
        if intent_model is None:
            intent_model = OpenAIIntentModelClient()
        failure_model = _resolve_failure_model(intent_model)
        db_connector = StiDatabaseConnector()
        vector_connector = MilvusVectorConnector()
        knowledge_connector = vector_connector if vector_connector.config.ready else None
        tools = ToolRegistry(
            tools={
                "inventory_snapshot": InventorySnapshotTool(connector=db_connector),
                "simple_chat": SimpleChatTool(),
                "sku_full_chain_diagnosis": SkuFullChainDiagnosisTool(connector=db_connector),
                "inventory_risk": InventoryRiskTool(policy=config.inventory_policy, connector=db_connector),
                "control_tower": ControlTowerTool(connector=db_connector),
                "shortage_trace": ShortageTraceTool(connector=db_connector),
                "shipment_verification": ShipmentVerificationTool(),
                "purchase_verification": PurchaseVerificationTool(),
                "weekly_shipment_plan": WeeklyShipmentPlanTool(),
                "exception_case": ExceptionCaseTool(),
                "knowledge_lookup": KnowledgeLookupTool(connector=knowledge_connector),
            }
        )
        return cls(config=config, tools=tools, intent_model=intent_model, failure_model=failure_model)

    def run(self, text: str) -> AgentRunResult:
        enriched = enrich_request(text)
        request_id = str(enriched.metadata.get("request_id") or generate_time_id())
        request = TaskRequest(text=enriched.text, material_code=enriched.material_code, metadata={**enriched.metadata, "request_id": request_id})
        state = RunStateMachine(request_id=request_id)
        logger.info("agent task started", extra=log_extra("task_started", request_id=request_id))

        # 意图由模型识别，但计划保持确定性，保证同一任务类型映射到可审查的执行路径。
        state.transition(RunStatus.INTENT_RECOGNIZING, "intent_recognition_started")
        try:
            intent = classify_task(request, self.intent_model)
        except Exception:
            state.transition(RunStatus.MODEL_FAILED, "intent_recognition_failed")
            raise
        state.transition(RunStatus.INTENT_RECOGNIZED, "intent_recognition_completed", task_type=intent.task_type.value, confidence=intent.confidence)

        state.transition(RunStatus.PLAN_BUILDING, "plan_building_started", task_type=intent.task_type.value)
        plan = build_plan(request, intent.task_type, intent.confidence)
        state.transition(RunStatus.PLAN_BUILT, "plan_built", task_type=plan.task_type.value, step_count=len(plan.steps))
        logger.info(
            "agent plan ready",
            extra=log_extra("agent_plan_ready", request_id=request_id, task_type=plan.task_type.value, step_count=len(plan.steps)),
        )

        snapshots = []
        decisions: list[ControlDecision] = []
        signals = []
        artifacts = {}
        tool_calls = 0
        field_pack = field_pack_for_task(plan.task_type)

        # decisions 是可执行建议；artifacts 是草稿表、计划、Case 或知识片段，需要人工复核。
        for step in plan.steps:
            if not step.tool:
                continue
            tool_calls += 1
            if tool_calls > self.config.max_tool_calls:
                logger.warning(
                    "tool call budget exceeded",
                    extra=log_extra("tool_budget_exceeded", request_id=request_id, task_type=plan.task_type.value, max_tool_calls=self.config.max_tool_calls),
                )
                break
            logger.info(
                "agent step executing",
                extra=log_extra("agent_step_executing", request_id=request_id, task_type=plan.task_type.value, step=step.name, tool=step.tool),
            )
            state.transition(RunStatus.TOOL_RUNNING, "tool_started", task_type=plan.task_type.value, step=step.name, tool=step.tool)
            try:
                if step.tool == "simple_chat":
                    artifacts["chat_reply"] = self.tools.run(step.tool, query=request.text)
                elif step.tool == "sku_full_chain_diagnosis":
                    artifacts["sku_full_chain_diagnosis"] = self.tools.run(step.tool, material_code=request.material_code)
                elif step.tool == "inventory_snapshot":
                    snapshots = self.tools.run(step.tool, material_code=request.material_code, field_pack=field_pack)
                elif step.tool == "inventory_risk":
                    decisions = self.tools.run(step.tool, snapshots=snapshots)
                elif step.tool == "control_tower":
                    signals = self.tools.run(step.tool, material_code=request.material_code)
                    artifacts["risk_signals"] = signals
                elif step.tool in {"shortage_trace", "shipment_verification", "purchase_verification"}:
                    if not snapshots:
                        snapshots = self.tools.run("inventory_snapshot", material_code=request.material_code, field_pack=field_pack)
                    decisions = self.tools.run(step.tool, snapshots=snapshots)
                elif step.tool == "weekly_shipment_plan":
                    artifacts["weekly_shipment_plan"] = self.tools.run(step.tool, signals=signals)
                elif step.tool == "exception_case":
                    artifacts["cases"] = self.tools.run(step.tool, signals=signals)
                elif step.tool == "knowledge_lookup":
                    artifacts["knowledge"] = self.tools.run(step.tool, query=request.text)
            except Exception as exc:
                state.transition(RunStatus.TOOL_FAILED, "tool_failed", task_type=plan.task_type.value, step=step.name, tool=step.tool)
                if _is_data_fetch_failure(exc) or not self.failure_model:
                    raise
                failure_decision = self.failure_model.handle_failure(
                    request=request,
                    plan_task_type=plan.task_type,
                    failed_step=step.name,
                    failed_tool=step.tool,
                    error=exc,
                    context={
                        "snapshots_count": len(snapshots),
                        "decisions_count": len(decisions),
                        "artifact_keys": list(artifacts.keys()),
                        "assumptions": plan.assumptions,
                    },
                )
                artifacts["failure_decision"] = failure_decision
                logger.warning(
                    "tool failure handled by model",
                    extra=log_extra(
                        "tool_failure_handled_by_model",
                        request_id=request_id,
                        task_type=plan.task_type.value,
                        step=step.name,
                        tool=step.tool,
                        failure_type=failure_decision.failure_type,
                        next_action=failure_decision.next_action,
                    ),
                )
                break
            state.transition(RunStatus.TOOL_COMPLETED, "tool_completed", task_type=plan.task_type.value, step=step.name, tool=step.tool)

        if plan.assumptions:
            logger.warning(
                "agent plan contains assumptions",
                extra=log_extra("agent_plan_has_assumptions", request_id=request_id, task_type=plan.task_type.value, assumption_count=len(plan.assumptions)),
            )
        state.transition(RunStatus.VERIFYING, "verification_started", task_type=plan.task_type.value)
        try:
            verification = verify_decisions(plan, decisions, artifacts)
        except Exception:
            state.transition(RunStatus.VERIFICATION_FAILED, "verification_failed", task_type=plan.task_type.value)
            raise
        state.transition(RunStatus.COMPLETED, "task_completed", task_type=plan.task_type.value)
        logger.info(
            "agent task completed",
            extra=log_extra(
                "task_completed",
                request_id=request_id,
                task_type=plan.task_type.value,
                decision_count=len(decisions),
                artifact_count=len(artifacts),
                verification_count=len(verification),
            ),
        )
        return AgentRunResult(
            request=request,
            plan=plan,
            decisions=decisions,
            verification=verification,
            artifacts=artifacts,
            state_history=state.history,
        )

    def run_goal(self, goal: str, feedback: list[str] | None = None, max_iterations: int = 3) -> GoalRunResult:
        """以目标为中心执行多轮观察和反馈修正。

        feedback 中的每一条会在上一轮完成后合入下一轮请求，用于模拟用户要求
        “按新条件重算、补充口径、修改输出范围”等闭环修正。
        """

        return GoalLoop(self, max_iterations=max_iterations, feedback=feedback or []).run(goal)


def _resolve_failure_model(intent_model: IntentModelClient) -> FailureHandlingModelClient | None:
    if hasattr(intent_model, "handle_failure"):
        return intent_model  # type: ignore[return-value]
    try:
        return OpenAIIntentModelClient()
    except RuntimeError:
        logger.warning("failure model unavailable", extra=log_extra("failure_model_unavailable"))
    return None


def _is_data_fetch_failure(error: Exception) -> bool:
    return str(error).startswith("数据获取失败")
