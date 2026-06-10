from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pmc_agent.domain import TaskType


class FieldPack(str, Enum):
    """受控字段包。

    模型或计划器只能选择字段包；具体表字段由 catalog 白名单展开。
    """

    INVENTORY_SNAPSHOT = "inventory_snapshot"
    INVENTORY_RISK = "inventory_risk"
    SHORTAGE_TRACE = "shortage_trace"
    PURCHASE_VERIFICATION = "purchase_verification"
    SHIPMENT_VERIFICATION = "shipment_verification"
    AGING_ANALYSIS = "aging_analysis"
    LOGISTICS_TRACE = "logistics_trace"
    CONTROL_TOWER = "control_tower"


@dataclass(frozen=True)
class TableFieldCatalog:
    table_name: str
    identity_fields: tuple[str, ...]
    field_packs: dict[FieldPack, tuple[str, ...]]
    searchable_fields: tuple[str, ...]
    default_limit: int = 50

    def fields_for(self, field_pack: FieldPack | str | None) -> tuple[str, ...]:
        pack = normalize_field_pack(field_pack)
        fields = [*self.identity_fields, *self.field_packs[pack]]
        return tuple(dict.fromkeys(fields))


ALL_WAREHOUSE_CATALOG = TableFieldCatalog(
    table_name="ads_lingxing_all_warehouse_new",
    identity_fields=(
        "msku",
        "sku",
        "fnsku",
        "asin",
        "store_name",
        "country_code",
        "shipments_country",
        "msku_sales_property",
        "seasonality",
        "sku_name",
    ),
    searchable_fields=("msku", "sku", "fnsku"),
    field_packs={
        FieldPack.INVENTORY_SNAPSHOT: (
            "afn_fulfillable_quantity",
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
            "sale_quantity_7",
            "sale_quantity_30",
            "future_30d_sales",
            "safety_stock_sales",
        ),
        FieldPack.INVENTORY_RISK: (
            "afn_fulfillable_quantity",
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
            "sale_quantity_7",
            "sale_quantity_30",
            "future_15d_sales",
            "future_30d_sales",
            "future_60d_sales",
            "future_90d_sales",
            "safety_stock_sales",
            "fnsku_out_of_stock_risk_1",
            "fnsku_out_of_stock_risk_2",
            "fnsku_out_of_stock_risk_3",
            "fnsku_out_of_stock_risk_4",
            "fnsku_out_of_stock_risk_5",
            "fnsku_out_of_stock_risk_6",
        ),
        FieldPack.SHORTAGE_TRACE: (
            "afn_fulfillable_quantity",
            "reserved_fc_transfers",
            "reserved_fc_processing",
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
            "sale_quantity_7",
            "sale_quantity_30",
            "future_15d_sales",
            "future_30d_sales",
            "future_45d_sales",
            "future_60d_sales",
            "future_90d_sales",
            "fnsku_out_of_stock_risk_1",
            "fnsku_out_of_stock_risk_2",
            "fnsku_out_of_stock_risk_3",
            "fnsku_out_of_stock_risk_4",
            "fnsku_out_of_stock_risk_5",
            "fnsku_out_of_stock_risk_6",
        ),
        FieldPack.PURCHASE_VERIFICATION: (
            "afn_fulfillable_quantity",
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
            "procurement_plan_quantity",
            "sale_quantity_30",
            "future_30d_sales",
            "future_60d_sales",
            "future_90d_sales",
            "safety_stock_sales",
        ),
        FieldPack.SHIPMENT_VERIFICATION: (
            "afn_fulfillable_quantity",
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
            "sale_quantity_7",
            "sale_quantity_30",
            "future_15d_sales",
            "future_30d_sales",
            "logistics_model",
            "first_leg_logistics_channel",
        ),
        FieldPack.AGING_ANALYSIS: (
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "inv_age_0_to_30_days",
            "inv_age_31_to_60_days",
            "inv_age_61_to_90_days",
            "inv_age_91_to_180_days",
            "inv_age_181_to_270_days",
            "inv_age_271_to_330_days",
            "inv_age_331_to_365_days",
            "inv_age_365_plus_days",
            "sale_quantity_30",
            "sale_quantity_90",
        ),
        FieldPack.LOGISTICS_TRACE: (
            "logistics_model",
            "first_leg_logistics_channel",
            "order_duration",
            "production_duration",
            "local_warehouse_pick_time",
            "overseas_warehouse_pick_time",
            "local_to_FBA_time",
            "local_to_overseas_warehouse_time",
            "overseas_to_FBA_time",
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
        ),
        FieldPack.CONTROL_TOWER: (
            "afn_fulfillable_quantity",
            "fba_warehouse_quantity",
            "overseas_warehouse_quantity",
            "local_warehouse_quantity",
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
            "sale_quantity_7",
            "sale_quantity_30",
            "sale_quantity_90",
            "future_15d_sales",
            "future_30d_sales",
            "future_60d_sales",
            "future_90d_sales",
            "safety_stock_sales",
            "fnsku_out_of_stock_risk_1",
            "fnsku_out_of_stock_risk_2",
            "fnsku_out_of_stock_risk_3",
            "fnsku_out_of_stock_risk_4",
            "fnsku_out_of_stock_risk_5",
            "fnsku_out_of_stock_risk_6",
            "inv_age_61_to_90_days",
            "inv_age_91_to_180_days",
            "inv_age_181_to_270_days",
            "inv_age_271_to_330_days",
            "inv_age_331_to_365_days",
            "inv_age_365_plus_days",
            "order_duration",
            "production_duration",
            "local_to_FBA_time",
            "local_to_overseas_warehouse_time",
            "overseas_to_FBA_time",
            "logistics_model",
            "first_leg_logistics_channel",
        ),
    },
)


TASK_FIELD_PACKS: dict[TaskType, FieldPack] = {
    TaskType.CONTROL_TOWER: FieldPack.CONTROL_TOWER,
    TaskType.INVENTORY_RISK: FieldPack.INVENTORY_RISK,
    TaskType.SHORTAGE_TRACE: FieldPack.SHORTAGE_TRACE,
    TaskType.SHIPMENT_VERIFICATION: FieldPack.SHIPMENT_VERIFICATION,
    TaskType.PURCHASE_VERIFICATION: FieldPack.PURCHASE_VERIFICATION,
    TaskType.WEEKLY_SHIPMENT_PLAN: FieldPack.SHIPMENT_VERIFICATION,
    TaskType.EXCEPTION_CASE: FieldPack.INVENTORY_RISK,
    TaskType.REPLENISHMENT: FieldPack.PURCHASE_VERIFICATION,
    TaskType.PRODUCTION_CONTROL: FieldPack.SHORTAGE_TRACE,
    TaskType.SUPPLIER_FOLLOWUP: FieldPack.LOGISTICS_TRACE,
    TaskType.GENERAL_ANALYSIS: FieldPack.INVENTORY_SNAPSHOT,
}


def normalize_field_pack(field_pack: FieldPack | str | None) -> FieldPack:
    if isinstance(field_pack, FieldPack):
        return field_pack
    if not field_pack:
        return FieldPack.INVENTORY_SNAPSHOT
    try:
        return FieldPack(str(field_pack))
    except ValueError:
        return FieldPack.INVENTORY_SNAPSHOT


def field_pack_for_task(task_type: TaskType) -> FieldPack:
    return TASK_FIELD_PACKS.get(task_type, FieldPack.INVENTORY_SNAPSHOT)
