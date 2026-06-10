from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.base import BusinessSystemConnector
from pmc_agent.config import InventoryPolicy
from pmc_agent.domain import CaseRecord, ControlDecision, InventorySnapshot, Material, RiskLevel, RiskSignal
from pmc_agent.schema_catalog import FieldPack


logger = get_logger(__name__)


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
    """从真实业务系统读取库存快照；缺数据时直接失败。"""

    connector: BusinessSystemConnector | None = None
    name: str = "inventory_snapshot"
    description: str = "Return inventory and demand snapshot for a material."

    def run(self, material_code: str | None = None, field_pack: FieldPack | str | None = None, **_: Any) -> list[InventorySnapshot]:
        if not self.connector:
            raise RuntimeError("数据获取失败：库存数据连接器未配置。")
        try:
            snapshots = self.connector.get_inventory_snapshot(material_code, field_pack=field_pack)
        except TypeError:
            snapshots = self.connector.get_inventory_snapshot(material_code)
        if not snapshots:
            raise LookupError("数据获取失败：库存快照未返回数据。")
        logger.info(
            "inventory snapshot returned from connector",
            extra=log_extra("inventory_snapshot_connector_returned", material_code=material_code or "-", result_size=len(snapshots), field_pack=str(field_pack or "-")),
        )
        return snapshots


@dataclass
class InventoryRiskTool:
    """基于控制塔主规则输出库存风险，禁止使用本地兜底规则。"""

    policy: InventoryPolicy
    connector: Any | None = None
    name: str = "inventory_risk"
    description: str = "Evaluate inventory shortage risk and recommend PMC control actions."

    def run(self, snapshots: list[InventorySnapshot], **_: Any) -> list[ControlDecision]:
        if not self.connector:
            raise RuntimeError("数据获取失败：库存风险判定缺少控制塔数据连接器。")
        material_codes = [snapshot.material_code for snapshot in snapshots] if snapshots else [None]
        decisions = []
        for material_code in material_codes:
            decisions.extend(self._evaluate_from_control_tower(material_code))
        logger.info("inventory risk evaluated", extra=log_extra("inventory_risk_evaluated", result_size=len(decisions)))
        return decisions

    def _evaluate_from_control_tower(self, material_code: str | None) -> list[ControlDecision]:
        from pmc_agent.control_tower import get_control_tower_summary

        summary = get_control_tower_summary(material_code=material_code, connector=self.connector)
        decisions = []
        for item in summary.items:
            level = _risk_level_from_text(item.risk_level)
            if level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
                logger.warning(
                    "high inventory risk detected",
                    extra=log_extra("inventory_high_risk_detected", material_code=item.material_code, risk_level=level.value),
                )
            decisions.append(
                ControlDecision(
                    material_code=item.material_code,
                    risk_level=level,
                    summary=f"{item.material_code} {item.warning_type}",
                    recommended_actions=[item.suggested_action],
                    category="inventory_health",
                    evidence={
                        **item.evidence,
                        "on_hand": item.total_inventory,
                        "allocated": 0,
                        "inbound": item.inbound_total,
                        "demand_next_7d": item.demand_7d,
                        "demand_next_30d": item.demand_30d,
                        "projected_7d": item.projected_7d,
                        "stockout_risk_level": item.stockout_risk_level,
                        "overstock_risk_level": item.overstock_risk_level,
                        "pici_first_shortage_days": item.pici_first_shortage_days,
                        "pici_key_gap": item.pici_key_gap,
                        "redundancy_sellable_days": item.redundancy_sellable_days,
                    },
                )
            )
        return decisions


@dataclass
class ControlTowerTool:
    """为控制塔看板和下游草稿流程生成风险信号。"""

    connector: Any | None = None
    name: str = "control_tower"
    description: str = "Return PMC control-tower risk signals."

    def run(self, material_code: str | None = None, filters: dict[str, Any] | None = None, **_: Any) -> list[RiskSignal]:
        from pmc_agent.control_tower import get_control_tower_summary

        summary = get_control_tower_summary(material_code=material_code, filters=filters, connector=self.connector)
        signals: list[RiskSignal] = []
        for item in summary.items:
            if item.stockout_risk_level != "normal":
                signals.append(
                    RiskSignal(
                        name="high_risk_shortage",
                        description=f"{item.material_code} 命中断货风险：{item.stockout_warning}",
                        source="control_tower_main_rule",
                        severity=_risk_level_from_text(item.stockout_risk_level),
                    )
                )
            if item.overstock_risk_level != "normal":
                signals.append(
                    RiskSignal(
                        name="redundant_stock",
                        description=f"{item.material_code} 命中冗余风险：{item.overstock_warning}",
                        source="control_tower_main_rule",
                        severity=_risk_level_from_text(item.overstock_risk_level),
                    )
                )
        logger.info("control tower signals generated", extra=log_extra("control_tower_signals_generated", result_size=len(signals)))
        return signals


@dataclass
class ShortageTraceTool:
    connector: Any | None = None
    name: str = "shortage_trace"
    description: str = "Explain shortage causes for a SKU/FNSKU."

    def run(self, snapshots: list[InventorySnapshot], **_: Any) -> list[ControlDecision]:
        if not self.connector:
            raise RuntimeError("数据获取失败：断货追因缺少控制塔数据连接器。")
        from pmc_agent.control_tower import get_control_tower_summary

        material_codes = [snapshot.material_code for snapshot in snapshots] if snapshots else [None]
        decisions: list[ControlDecision] = []
        for material_code in material_codes:
            summary = get_control_tower_summary(material_code=material_code, filters={"risk_type": "stockout"}, connector=self.connector)
            for item in summary.items:
                decisions.append(
                    ControlDecision(
                        material_code=item.material_code,
                        risk_level=_risk_level_from_text(item.stockout_risk_level),
                        summary=f"{item.material_code} 断货追因：{item.stockout_warning}",
                        recommended_actions=["核查 chazhi 最早缺口窗口、在途覆盖、最快补货窗口，并由 PMC 分派处理人。"],
                        category="shortage_trace",
                        evidence={
                            "pici_first_shortage_days": item.pici_first_shortage_days,
                            "pici_min_gap_quantity": item.pici_min_gap_quantity,
                            "pici_key_gap": item.pici_key_gap,
                            "pici_gap_values": item.pici_gap_values,
                        },
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
            material = Material(code=snapshot.material_code, name=snapshot.material_code)
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
    connector: Any | None = None
    name: str = "knowledge_lookup"
    description: str = "Return rule and SOP knowledge snippets."

    def run(self, query: str = "", query_vector: list[float] | None = None, limit: int = 5, **_: Any) -> list[dict[str, Any]]:
        if self.connector:
            snippets = self.connector.search(query=query, query_vector=query_vector, limit=limit)
            if snippets:
                logger.info("knowledge snippets returned from connector", extra=log_extra("knowledge_lookup_connector_completed", result_size=len(snippets), query_present=bool(query)))
                return snippets
        snippets = [
            {"title": "Inventory bottom table fields", "content": "Explain fields from ads_lingxing_all_warehouse_new and forecast tables."},
            {"title": "Shipment verification rules", "content": "Explain base shipment, correction quantity, reference quantity, and delta reasons."},
            {"title": "Purchase verification rules", "content": "Explain MOQ, carton size, combine purchase, demand-too-low, and holiday/stocking rules."},
            {"title": "Exception handling SOP", "content": "High-risk actions require human confirmation and feedback records."},
        ]
        logger.info("knowledge snippets returned", extra=log_extra("knowledge_lookup_completed", result_size=len(snippets), query_present=bool(query)))
        return snippets


def _risk_level_from_text(value: str) -> RiskLevel:
    if value == "high":
        return RiskLevel.HIGH
    if value == "medium":
        return RiskLevel.MEDIUM
    if value == "critical":
        return RiskLevel.CRITICAL
    return RiskLevel.LOW
