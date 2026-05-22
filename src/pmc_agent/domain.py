from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskType(str, Enum):
    SIMPLE_CHAT = "simple_chat"
    CONTROL_TOWER = "control_tower"
    INVENTORY_RISK = "inventory_risk"
    SHORTAGE_TRACE = "shortage_trace"
    SHIPMENT_VERIFICATION = "shipment_verification"
    PURCHASE_VERIFICATION = "purchase_verification"
    WEEKLY_SHIPMENT_PLAN = "weekly_shipment_plan"
    EXCEPTION_CASE = "exception_case"
    KNOWLEDGE_QA = "knowledge_qa"
    REPLENISHMENT = "replenishment"
    PRODUCTION_CONTROL = "production_control"
    SUPPLIER_FOLLOWUP = "supplier_followup"
    GENERAL_ANALYSIS = "general_analysis"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass(frozen=True)
class Material:
    code: str
    name: str
    unit: str = "pcs"
    safety_stock: float = 0
    min_order_qty: float = 0
    lead_time_days: int = 0


@dataclass(frozen=True)
class InventorySnapshot:
    """规则工具消费的标准化库存视图。"""

    material_code: str
    on_hand: float
    allocated: float
    inbound: float
    demand_next_7d: float
    demand_next_30d: float
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> float:
        return self.on_hand - self.allocated

    @property
    def projected_7d(self) -> float:
        return self.available + self.inbound - self.demand_next_7d


@dataclass(frozen=True)
class ControlDecision:
    """可执行的规则输出，必须可解释、可审计。"""

    material_code: str
    risk_level: RiskLevel
    summary: str
    recommended_actions: list[str]
    category: str = "inventory"
    status: str = "draft"
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RiskSignal:
    name: str
    description: str
    source: str
    severity: RiskLevel


@dataclass(frozen=True)
class CaseRecord:
    case_id: str
    title: str
    owner_role: str
    status: str
    reason_chain: list[str]
    recommended_actions: list[str]


@dataclass(frozen=True)
class TaskRequest:
    text: str
    material_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlanStep:
    name: str
    purpose: str
    tool: str | None = None


@dataclass(frozen=True)
class ExecutionPlan:
    task_type: TaskType
    confidence: float
    steps: list[PlanStep]
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentRunResult:
    """智能体完成计划、执行和验证后返回的完整结果。"""

    request: TaskRequest
    plan: ExecutionPlan
    decisions: list[ControlDecision]
    verification: list[str]
    artifacts: dict[str, Any] = field(default_factory=dict)
    state_history: list[Any] = field(default_factory=list)


class GoalLoopStatus(str, Enum):
    COMPLETED = "completed"
    NEEDS_USER_FEEDBACK = "needs_user_feedback"
    MAX_ITERATIONS_REACHED = "max_iterations_reached"


@dataclass(frozen=True)
class GoalIteration:
    """目标闭环中的一次执行和观察。"""

    iteration: int
    request_text: str
    applied_feedback: str | None
    result: AgentRunResult
    observation: str


@dataclass(frozen=True)
class GoalRunResult:
    """围绕同一业务目标进行多轮执行、观察和修正后的结果。"""

    goal: str
    status: GoalLoopStatus
    iterations: list[GoalIteration]
    final_answer: str
    pending_questions: list[str] = field(default_factory=list)
