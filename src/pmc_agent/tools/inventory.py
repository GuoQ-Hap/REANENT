from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.base import BusinessSystemConnector
from pmc_agent.config import InventoryPolicy
from pmc_agent.domain import CaseRecord, ControlDecision, InventorySnapshot, Material, RiskLevel, RiskSignal


logger = get_logger(__name__)

DEFAULT_MATERIALS = {
    "A100": Material(code="A100", name="Main board", safety_stock=80, min_order_qty=100, lead_time_days=10),
    "B200": Material(code="B200", name="Battery pack", safety_stock=120, min_order_qty=200, lead_time_days=14),
}

DEFAULT_INVENTORY = {
    "A100": InventorySnapshot(
        material_code="A100",
        on_hand=160,
        allocated=120,
        inbound=40,
        demand_next_7d=110,
        demand_next_30d=360,
    ),
    "B200": InventorySnapshot(
        material_code="B200",
        on_hand=420,
        allocated=180,
        inbound=80,
        demand_next_7d=90,
        demand_next_30d=310,
    ),
}


@dataclass
class SimpleChatTool:
    name: str = "simple_chat"
    description: str = "Return a brief conversational reply without business analysis."

    def run(self, query: str = "", **_: Any) -> dict[str, str]:
        text = query.strip().lower()
        if text in {"你好", "您好", "hello", "hi", "嗨", "在吗", "hey"}:
            reply = "你好，我在。你可以直接问我库存风险、断货原因、采购建议或发货验证。"
        elif text in {"谢谢", "感谢", "thanks", "thank you"}:
            reply = "不客气。"
        else:
            reply = "我在。请告诉我要看的物料或问题类型。"
        logger.info("simple chat reply generated", extra=log_extra("simple_chat_reply_generated"))
        return {"reply": reply}


@dataclass
class InventorySnapshotTool:
    """演示数据适配器；生产环境应替换为仓库或数仓连接器。"""

    connector: BusinessSystemConnector | None = None
    name: str = "inventory_snapshot"
    description: str = "Return inventory and demand snapshot for a material."

    def run(self, material_code: str | None = None, **_: Any) -> list[InventorySnapshot]:
        if self.connector:
            snapshots = self.connector.get_inventory_snapshot(material_code)
            logger.info(
                "inventory snapshot returned from connector",
                extra=log_extra("inventory_snapshot_connector_returned", material_code=material_code or "-", result_size=len(snapshots)),
            )
            return snapshots
        if material_code:
            snapshot = DEFAULT_INVENTORY.get(material_code.upper())
            if not snapshot:
                logger.warning("inventory snapshot missing", extra=log_extra("inventory_snapshot_missing", material_code=material_code.upper()))
                return []
            logger.info("inventory snapshot returned", extra=log_extra("inventory_snapshot_returned", material_code=material_code.upper(), result_size=1))
            return [snapshot]
        snapshots = list(DEFAULT_INVENTORY.values())
        logger.info("portfolio inventory snapshots returned", extra=log_extra("inventory_snapshot_returned", result_size=len(snapshots)))
        return snapshots


@dataclass
class InventoryRiskTool:
    """基于标准化库存快照计算库存风险。"""

    policy: InventoryPolicy
    name: str = "inventory_risk"
    description: str = "Evaluate inventory shortage risk and recommend PMC control actions."

    def run(self, snapshots: list[InventorySnapshot], **_: Any) -> list[ControlDecision]:
        if not snapshots:
            logger.warning("inventory risk called without snapshots", extra=log_extra("inventory_risk_no_snapshots"))
            return []
        decisions = [self._evaluate(snapshot) for snapshot in snapshots]
        logger.info("inventory risk evaluated", extra=log_extra("inventory_risk_evaluated", result_size=len(decisions)))
        return decisions

    def _evaluate(self, snapshot: InventorySnapshot) -> ControlDecision:
        material = DEFAULT_MATERIALS.get(snapshot.material_code, Material(code=snapshot.material_code, name="Unknown"))
        # 用 30 天需求作为基准日需求，同时避免除零。
        daily_demand = max(snapshot.demand_next_30d / 30, self.policy.default_daily_demand)
        days_of_cover = max(snapshot.projected_7d, 0) / daily_demand

        if snapshot.projected_7d < 0 or days_of_cover <= self.policy.critical_days_of_cover:
            level = RiskLevel.CRITICAL
        elif days_of_cover <= self.policy.high_risk_days_of_cover:
            level = RiskLevel.HIGH
        elif days_of_cover <= self.policy.medium_risk_days_of_cover:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW

        actions = _actions_for(level, material, snapshot)
        if level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
            logger.warning(
                "high inventory risk detected",
                extra=log_extra("inventory_high_risk_detected", material_code=snapshot.material_code, risk_level=level.value),
            )
        summary = (
            f"{snapshot.material_code} projected 7-day inventory is {snapshot.projected_7d:.0f} "
            f"{material.unit}; estimated days of cover is {days_of_cover:.1f}."
        )
        return ControlDecision(
            material_code=snapshot.material_code,
            risk_level=level,
            summary=summary,
            recommended_actions=actions,
            category="inventory_health",
            evidence={
                "on_hand": snapshot.on_hand,
                "allocated": snapshot.allocated,
                "inbound": snapshot.inbound,
                "demand_next_7d": snapshot.demand_next_7d,
                "demand_next_30d": snapshot.demand_next_30d,
                "safety_stock": material.safety_stock,
                "lead_time_days": material.lead_time_days,
            },
        )


@dataclass
class ControlTowerTool:
    """为控制塔看板和下游草稿流程生成风险信号。"""

    name: str = "control_tower"
    description: str = "Return PMC control-tower risk signals."

    def run(self, snapshots: list[InventorySnapshot] | None = None, **_: Any) -> list[RiskSignal]:
        snapshots = snapshots or list(DEFAULT_INVENTORY.values())
        signals: list[RiskSignal] = []
        for snapshot in snapshots:
            if snapshot.projected_7d < 0:
                signals.append(
                    RiskSignal(
                        name="high_risk_shortage",
                        description=f"{snapshot.material_code} projected 7-day inventory is below zero.",
                        source="ads_lingxing_all_warehouse_new_v1",
                        severity=RiskLevel.CRITICAL,
                    )
                )
            if snapshot.on_hand > snapshot.demand_next_30d * 1.5:
                signals.append(
                    RiskSignal(
                        name="redundant_stock",
                        description=f"{snapshot.material_code} on-hand stock is high versus 30-day demand.",
                        source="inventory_health_calculation",
                        severity=RiskLevel.MEDIUM,
                    )
                )
        logger.info("control tower signals generated", extra=log_extra("control_tower_signals_generated", result_size=len(signals)))
        return signals


@dataclass
class ShortageTraceTool:
    name: str = "shortage_trace"
    description: str = "Explain shortage causes for a SKU/FNSKU."

    def run(self, snapshots: list[InventorySnapshot], **_: Any) -> list[ControlDecision]:
        if not snapshots:
            logger.warning("shortage trace called without snapshots", extra=log_extra("shortage_trace_no_snapshots"))
            return []
        decisions: list[ControlDecision] = []
        for snapshot in snapshots:
            causes = [
                "FBA sellable stock is insufficient against near-term demand.",
                "Inbound coverage does not close the 7-day demand gap.",
                "Purchase and shipment windows need review before release.",
            ]
            decisions.append(
                ControlDecision(
                    material_code=snapshot.material_code,
                    risk_level=RiskLevel.CRITICAL if snapshot.projected_7d < 0 else RiskLevel.MEDIUM,
                    summary=f"{snapshot.material_code} shortage trace generated from inventory, demand, inbound, and logistics windows.",
                    recommended_actions=[
                        "Check shipment pull-in feasibility.",
                        "Check purchase replenishment and MOQ/carton constraints.",
                        "Create an exception case if the shortage cannot be closed in time.",
                    ],
                    category="shortage_trace",
                    evidence={"reason_chain": causes, "projected_7d": snapshot.projected_7d},
                )
            )
        logger.info("shortage trace generated", extra=log_extra("shortage_trace_generated", result_size=len(decisions)))
        return decisions


@dataclass
class ShipmentVerificationTool:
    name: str = "shipment_verification"
    description: str = "Recalculate shipment quantities and explain deltas."

    def run(self, snapshots: list[InventorySnapshot], **_: Any) -> list[ControlDecision]:
        if not snapshots:
            logger.warning("shipment verification called without snapshots", extra=log_extra("shipment_verification_no_snapshots"))
            return []
        decisions = []
        for snapshot in snapshots:
            base_qty = max(snapshot.demand_next_7d - snapshot.available, 0)
            correction_qty = max(base_qty - snapshot.inbound, 0)
            decisions.append(
                ControlDecision(
                    material_code=snapshot.material_code,
                    risk_level=RiskLevel.MEDIUM if correction_qty else RiskLevel.LOW,
                    summary=f"Shipment verification suggests base {base_qty:.0f}, correction {correction_qty:.0f}.",
                    recommended_actions=["Review T0/T1/T2/T3/T3' source fields before export."],
                    category="shipment_verification",
                    evidence={"base_shipment_qty": base_qty, "shipment_correction_qty": correction_qty},
                )
            )
        logger.info("shipment verification completed", extra=log_extra("shipment_verification_completed", result_size=len(decisions)))
        return decisions


@dataclass
class PurchaseVerificationTool:
    """生成采购建议草稿，不生成可执行采购单。"""

    name: str = "purchase_verification"
    description: str = "Recalculate purchase quantities with MOQ, carton, and combine-purchase constraints."

    def run(self, snapshots: list[InventorySnapshot], **_: Any) -> list[ControlDecision]:
        if not snapshots:
            logger.warning("purchase verification called without snapshots", extra=log_extra("purchase_verification_no_snapshots"))
            return []
        decisions = []
        for snapshot in snapshots:
            material = DEFAULT_MATERIALS.get(snapshot.material_code, Material(code=snapshot.material_code, name="Unknown"))
            shortage_qty = max(snapshot.demand_next_30d - snapshot.available - snapshot.inbound, 0)
            suggested_qty = max(shortage_qty, material.min_order_qty)
            decisions.append(
                ControlDecision(
                    material_code=snapshot.material_code,
                    risk_level=RiskLevel.HIGH if shortage_qty else RiskLevel.LOW,
                    summary=f"Purchase verification suggests {suggested_qty:.0f} {material.unit} before human approval.",
                    recommended_actions=["Validate MOQ, carton size, supplier, demand-too-low, and combine-purchase rules."],
                    category="purchase_verification",
                    evidence={"shortage_qty": shortage_qty, "suggested_purchase_qty": suggested_qty, "moq": material.min_order_qty},
                )
            )
        logger.warning(
            "purchase verification generated draft advice requiring approval",
            extra=log_extra("purchase_manual_confirmation_required", result_size=len(decisions)),
        )
        return decisions


@dataclass
class WeeklyShipmentPlanTool:
    """基于风险信号生成需要人工复核的周度发货计划草稿。"""

    name: str = "weekly_shipment_plan"
    description: str = "Generate a draft weekly shipment plan."

    def run(self, signals: list[RiskSignal], **_: Any) -> dict[str, Any]:
        if not signals:
            logger.warning("weekly shipment plan generated without risk signals", extra=log_extra("weekly_plan_no_signals"))
        plan = {
            "status": "draft",
            "items": [
                {
                    "risk": signal.name,
                    "plan": "Review shipment time, channel, warehouse allocation, carton quantity, and pending allocation.",
                    "requires_human_confirmation": True,
                }
                for signal in signals
            ],
        }
        logger.warning("weekly shipment plan draft requires human confirmation", extra=log_extra("weekly_plan_manual_confirmation_required", item_count=len(plan["items"])))
        return plan


@dataclass
class ExceptionCaseTool:
    """生成用于异常跟进和审计的 Case 草稿。"""

    name: str = "exception_case"
    description: str = "Create a draft exception case for human-controlled follow-up."

    def run(self, signals: list[RiskSignal], **_: Any) -> list[CaseRecord]:
        cases = [
            CaseRecord(
                case_id=f"CASE-{index + 1:04d}",
                title=signal.description,
                owner_role="PMC",
                status="draft",
                reason_chain=[signal.source, signal.name],
                recommended_actions=["Assign owner.", "Confirm action.", "Record feedback and closure result."],
            )
            for index, signal in enumerate(signals)
        ]
        logger.warning("exception cases created as drafts", extra=log_extra("exception_case_draft_created", result_size=len(cases)))
        return cases


@dataclass
class KnowledgeLookupTool:
    name: str = "knowledge_lookup"
    description: str = "Return rule and SOP knowledge snippets."

    def run(self, query: str = "", **_: Any) -> list[dict[str, str]]:
        snippets = [
            {"title": "Inventory bottom table fields", "content": "Explain fields from ads_lingxing_all_warehouse_new_v1 and forecast tables."},
            {"title": "Shipment verification rules", "content": "Explain base shipment, correction quantity, reference quantity, and delta reasons."},
            {"title": "Purchase verification rules", "content": "Explain MOQ, carton size, combine purchase, demand-too-low, and holiday/stocking rules."},
            {"title": "Exception handling SOP", "content": "High-risk actions require human confirmation and feedback records."},
        ]
        logger.info("knowledge snippets returned", extra=log_extra("knowledge_lookup_completed", result_size=len(snippets), query_present=bool(query)))
        return snippets


def _actions_for(level: RiskLevel, material: Material, snapshot: InventorySnapshot) -> list[str]:
    """将计算出的风险等级映射为 PMC 控制动作。"""

    if level == RiskLevel.CRITICAL:
        return [
            "Freeze non-urgent allocations and re-check production priority.",
            "Expedite inbound supply and request confirmed arrival time from supplier.",
            f"Prepare emergency replenishment at least MOQ {material.min_order_qty:.0f} {material.unit}.",
        ]
    if level == RiskLevel.HIGH:
        return [
            "Review open purchase orders and pull in delivery where possible.",
            "Check substitute or transfer options before releasing new production orders.",
        ]
    if level == RiskLevel.MEDIUM:
        return [
            "Monitor daily consumption and supplier commitment.",
            "Create replenishment advice if demand forecast is confirmed.",
        ]
    return ["No immediate control action required; keep routine monitoring."]
