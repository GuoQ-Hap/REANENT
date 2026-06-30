from __future__ import annotations

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.domain import ExecutionPlan, PlanStep, TaskRequest, TaskType


logger = get_logger(__name__)


def build_plan(request: TaskRequest, task_type: TaskType, confidence: float) -> ExecutionPlan:
    """将模型识别出的任务类型映射为确定性的执行步骤。"""

    assumptions: list[str] = []
    if not request.material_code and task_type != TaskType.SIMPLE_CHAT:
        assumptions.append("No explicit material code was detected; use portfolio-level analysis.")
        logger.warning(
            "material code missing; portfolio-level plan assumed",
            extra=log_extra("plan_assumption_added", task_type=task_type.value),
        )

    if task_type == TaskType.SIMPLE_CHAT:
        steps = [
            PlanStep("reply_briefly", "Reply briefly without running business data tools.", "simple_chat"),
        ]
    elif task_type == TaskType.CONTROL_TOWER:
        steps = [
            PlanStep("collect_risk_signals", "Collect shortage, redundant stock, logistics, purchase, and forecast risk signals.", "control_tower"),
            PlanStep("rank_risks", "Rank risks by severity, role, country, MSKU, and FNSKU."),
            PlanStep("prepare_followup", "Prepare case creation or human confirmation suggestions."),
        ]
    elif task_type == TaskType.SKU_FULL_CHAIN_DIAGNOSIS:
        steps = [
            PlanStep("diagnose_sku_full_chain", "Analyze inventory, sales, shortage risk, overstock risk, attribution, handling logic, and remedies for one SKU.", "sku_full_chain_diagnosis"),
            PlanStep("summarize_diagnosis", "Summarize the full-chain SKU diagnosis into owner-oriented next actions."),
        ]
    elif task_type == TaskType.INVENTORY_RISK:
        steps = [
            PlanStep("collect_inventory", "Collect on-hand, allocated, inbound, and demand data.", "inventory_snapshot"),
            PlanStep("evaluate_risk", "Calculate projected inventory and days of cover.", "inventory_risk"),
            PlanStep("recommend_actions", "Generate PMC control actions based on risk level."),
        ]
    elif task_type == TaskType.SHORTAGE_TRACE:
        steps = [
            PlanStep("collect_inventory", "Collect FBA sellable, forecast, local stock, overseas stock, in-transit, and inbound status.", "inventory_snapshot"),
            PlanStep("trace_shortage", "Explain shortage causes across demand, stock, purchase, shipment, and logistics windows.", "shortage_trace"),
            PlanStep("recommend_actions", "Recommend shipment, purchase, transfer, or logistics actions."),
        ]
    elif task_type == TaskType.SHIPMENT_VERIFICATION:
        steps = [
            PlanStep("collect_inventory", "Collect shipment T0/T1/T2/T3/T3' baseline data.", "inventory_snapshot"),
            PlanStep("recalculate_shipment", "Recalculate base shipment, correction, and reference quantities.", "shipment_verification"),
            PlanStep("explain_delta", "Explain deltas from source fields and rules."),
        ]
    elif task_type == TaskType.PURCHASE_VERIFICATION:
        steps = [
            PlanStep("collect_inventory", "Collect purchase T0/T1/T2/T3/T3' baseline data.", "inventory_snapshot"),
            PlanStep("recalculate_purchase", "Recalculate base purchase, correction, reference quantities, MOQ, carton rules, and combine-purchase limits.", "purchase_verification"),
            PlanStep("explain_delta", "Explain purchase differences and human approval points."),
        ]
    elif task_type == TaskType.WEEKLY_SHIPMENT_PLAN:
        steps = [
            PlanStep("collect_risk_signals", "Collect inventory, demand forecast, shipment, purchase, and logistics constraints.", "control_tower"),
            PlanStep("generate_plan", "Generate weekly shipment draft with timing, channel, warehouse allocation, carton quantity, and pending allocation.", "weekly_shipment_plan"),
            PlanStep("prepare_approval", "Prepare human confirmation and feedback record."),
        ]
    elif task_type == TaskType.EXCEPTION_CASE:
        steps = [
            PlanStep("collect_risk_signals", "Collect related risk signals and prior handling records.", "control_tower"),
            PlanStep("create_case", "Create a draft exception case with owner, reason chain, actions, and status.", "exception_case"),
            PlanStep("record_feedback", "Record manual edits, confirmation, closure, and review notes."),
        ]
    elif task_type == TaskType.KNOWLEDGE_QA:
        steps = [
            PlanStep("retrieve_knowledge", "Retrieve field definitions, SOP, stocking rules, and calculation rules.", "knowledge_lookup"),
            PlanStep("answer_with_sources", "Explain the rule path and business meaning."),
        ]
    elif task_type == TaskType.REPLENISHMENT:
        steps = [
            PlanStep("collect_inventory", "Collect current supply-demand balance.", "inventory_snapshot"),
            PlanStep("evaluate_replenishment", "Estimate replenishment quantity and timing.", "inventory_risk"),
            PlanStep("prepare_order_advice", "Prepare purchase or transfer advice for human approval."),
        ]
    elif task_type == TaskType.PRODUCTION_CONTROL:
        steps = [
            PlanStep("check_kitting", "Check material readiness for production plan.", "inventory_snapshot"),
            PlanStep("identify_constraints", "Identify shortage items blocking production.", "inventory_risk"),
            PlanStep("recommend_plan_control", "Recommend hold, split, expedite, or substitute actions."),
        ]
    elif task_type == TaskType.SUPPLIER_FOLLOWUP:
        steps = [
            PlanStep("collect_open_supply", "Collect open inbound and supplier commitment data.", "inventory_snapshot"),
            PlanStep("evaluate_delivery_risk", "Assess lead-time and arrival risk.", "inventory_risk"),
            PlanStep("recommend_followup", "Draft supplier follow-up actions."),
        ]
    else:
        steps = [
            PlanStep("collect_context", "Collect relevant PMC data.", "inventory_snapshot"),
            PlanStep("analyze", "Analyze the request with available operational data.", "inventory_risk"),
            PlanStep("summarize", "Summarize findings and next actions."),
        ]

    plan = ExecutionPlan(task_type=task_type, confidence=confidence, steps=steps, assumptions=assumptions)
    logger.info(
        "execution plan built",
        extra=log_extra("plan_built", task_type=task_type.value, step_count=len(steps), assumption_count=len(assumptions)),
    )
    return plan
