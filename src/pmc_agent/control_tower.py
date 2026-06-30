from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from pmc_agent.connectors.database import StiDatabaseConnector
from pmc_agent.query_spec import QuerySpec
from pmc_agent.schema_catalog import ALL_WAREHOUSE_CATALOG, FieldPack


SOURCE_TABLE = ALL_WAREHOUSE_CATALOG.table_name
DAILY_SALES_TABLE = "ads_lingxing_sc_sales_daily_new"
PICI_SALE_TABLE = "temp_lingxing_pici_sale"
MONTHLY_FORECAST_REVIEW_TABLE = "ads_lingxing_all_warehouse_new_sh_v1"
MONTHLY_SALES_ESTIMATE_TABLE = "ods_lingxing_sales_estimates_monthly_v1"
FORECAST_VERSION_OFFSETS = (3, 2, 1, 0)
FORECAST_DETAIL_HORIZON_DAYS = 180
ANOMALY_RISK_MARKER_VALUES = {"", "数据缺失", "none", "null"}
PICI_HORIZONS = (7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84, 98)
STOCKOUT_RISK_WINDOW_DAYS = 45


@dataclass(frozen=True)
class ControlTowerFieldDecision:
    name: str
    label: str
    group: str
    included: bool
    role: str
    reason: str


@dataclass(frozen=True)
class ControlTowerItem:
    material_code: str
    msku: str
    fnsku: str
    asin: str
    sku_name: str
    store_name: str
    country_code: str
    shipments_country: str
    sales_department: str
    salesman: str
    product_manager: str
    seller_id: str
    sales_property: str
    product_property: str
    seasonality: str
    msku_status: str
    msku_life_process: str
    risk_type: str
    risk_level: str
    warning_type: str
    suggested_action: str
    risk_score: int
    stockout_risk_level: str
    stockout_warning: str
    overstock_risk_level: str
    overstock_warning: str
    total_inventory: float
    fba_sellable: float
    fba_inventory: float
    overseas_inventory: float
    local_inventory: float
    inbound_total: float
    daily_sales_volume: float
    pici_first_shortage_days: int | None
    pici_min_gap_quantity: float | None
    pici_key_gap: str
    pici_gap_values: dict[str, str]
    demand_7d: float
    demand_30d: float
    daily_demand: float
    last_30_order_price: float | None
    last_30_order_us_price: float | None
    last_90_gross_margin: float | None
    sellable_days: float | None
    projected_7d: float
    lead_time_days: float
    long_age_inventory: float
    fba_age_61_to_90: float
    fba_age_91_to_180: float
    fba_age_181_to_270: float
    fba_age_271_to_330: float
    fba_age_331_to_365: float
    fba_age_365_plus: float
    fba_long_age_ratio: float | None
    redundancy_sellable_days: dict[str, float | None]
    logistics_model: str = ""
    first_leg_logistics_channel: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    stock_up_inventory: float = 0
    afn_inbound_receiving_quantity: float = 0
    afn_inbound_working_quantity: float = 0
    overseas_afn_inbound_shipped_quantity: float = 0
    local_afn_inbound_shipped_quantity: float = 0
    overseas_wh_product_onway: float = 0
    local_wh_product_onway: float = 0
    planned_quantity: float = 0


@dataclass(frozen=True)
class ControlTowerMapNode:
    country_code: str
    country_name: str
    sku_count: int
    total_inventory: float
    stockout_count: int
    overstock_count: int
    critical_count: int
    high_count: int
    risk_level: str
    risk_score: int


@dataclass(frozen=True)
class ControlTowerWarehouseInventory:
    country_code: str
    country_name: str
    warehouse_code: str
    warehouse_name: str
    display_name: str
    sku_count: int
    product_total: float
    product_valid_num: float
    product_lock_num: float
    product_onway: float


@dataclass(frozen=True)
class ControlTowerRiskDimensionSlice:
    key: str
    label: str
    total_count: int
    risk_count: int
    risk_rate: float
    stockout_count: int
    overstock_count: int
    anomaly_count: int
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    normal_count: int
    max_risk_score: int
    total_inventory: float
    demand_30d: float
    daily_sales_volume: float


@dataclass(frozen=True)
class MonthlyForecastReviewSnapshotRow:
    sku: str
    msku: str
    fnsku: str
    asin: str
    store_name: str
    country_code: str
    shipments_country: str
    sku_name: str
    forecast_quantity: float
    historical_30d_sales: float


@dataclass(frozen=True)
class MonthlyForecastReviewWeeklyEstimate:
    week: str
    week_start_date: str
    week_end_date: str
    forecast_quantity: float
    actual_sales: float
    ad_spend: float
    ad_sales_amount: float
    ad_order_quantity: float
    organic_sales: float
    ad_acos: float | None
    difference: float
    variance_ratio: float | None
    variance_percent: float | None
    day_count: int


@dataclass(frozen=True)
class MonthlyForecastReviewForecastPoint:
    week: str
    week_start_date: str
    week_end_date: str
    forecast_quantity: float
    row_count: int


@dataclass(frozen=True)
class MonthlyForecastReviewActualPoint:
    week: str
    week_start_date: str
    week_end_date: str
    actual_sales: float
    row_count: int


@dataclass(frozen=True)
class MonthlyForecastReviewMonthlyTotal:
    month: str
    forecast_quantity: float
    actual_sales: float
    actual_sales_projected: float
    actual_sales_virtual: float
    actual_covered_days: int
    month_day_count: int
    forecast_month: str
    forecast_month_offset: int | None
    forecast_label: str
    forecast_row_count: int
    forecast_version_totals: list[dict[str, Any]]
    actual_row_count: int
    selected_variance_percent: float | None
    sales_gap_direction: str
    sales_gap_label: str
    sales_gap_reason: str
    forecast_variance_checks: list[dict[str, Any]]
    forecast_anomaly: bool
    forecast_anomaly_reasons: list[str]


@dataclass(frozen=True)
class MonthlyForecastReviewForecastVersion:
    month_offset: int
    target_month: str
    target_start_date: str
    target_end_date: str
    label: str
    forecast_quantity: float
    forecast_row_count: int
    weekly_estimates: list[MonthlyForecastReviewForecastPoint]


@dataclass(frozen=True)
class MonthlyForecastReviewDailyPricePoint:
    date: str
    price: float | None
    listing_price: float | None
    landed_price: float | None
    currency_code: str
    source_row_count: int


@dataclass(frozen=True)
class MonthlyForecastReview:
    data_source: str
    sales_source: str
    forecast_source: str
    target_month: str
    target_start_date: str
    target_end_date: str
    comparison_month: str
    comparison_start_date: str
    comparison_end_date: str
    review_start_date: str
    review_end_date: str
    month_offset: int
    snapshot_date: str
    forecast_field: str
    actual_field: str
    forecast_quantity: float
    actual_sales: float
    ad_spend: float
    ad_sales_amount: float
    ad_order_quantity: float
    organic_sales: float
    ad_acos: float | None
    difference: float
    variance_ratio: float | None
    variance_percent: float | None
    result_type: str
    result_label: str
    snapshot_row_count: int
    forecast_row_count: int
    actual_row_count: int
    notes: list[str]
    snapshot_rows: list[MonthlyForecastReviewSnapshotRow]
    weekly_estimates: list[MonthlyForecastReviewWeeklyEstimate]
    forecast_versions: list[MonthlyForecastReviewForecastVersion]
    detail_forecast_versions: list[MonthlyForecastReviewForecastVersion]
    detail_actual_sales: list[MonthlyForecastReviewActualPoint]
    detail_monthly_totals: list[MonthlyForecastReviewMonthlyTotal]
    daily_price_points: list[MonthlyForecastReviewDailyPricePoint]
    forecast_anomalies: list[dict[str, Any]]
    sales_anomalies: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlTowerSummary:
    data_source: str
    sales_stat_date: str
    sales_start_date: str
    sales_end_date: str
    sales_day_count: int
    notes: list[str]
    kpis: dict[str, Any]
    risk_distribution: dict[str, int]
    risk_type_distribution: dict[str, int]
    risk_dimensions: dict[str, list[ControlTowerRiskDimensionSlice]]
    pagination: dict[str, int]
    map_nodes: list[ControlTowerMapNode]
    warehouse_inventory: list[ControlTowerWarehouseInventory]
    field_decisions: list[ControlTowerFieldDecision]
    filter_options: dict[str, list[str]]
    items: list[ControlTowerItem]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def get_control_tower_summary(
    material_code: str | None = None,
    filters: dict[str, Any] | None = None,
    sales_date: str | date | None = None,
    sales_start_date: str | date | None = None,
    sales_end_date: str | date | None = None,
    page: int = 1,
    page_size: int = 100,
    max_rows: int = 20000,
    connector: StiDatabaseConnector | None = None,
) -> ControlTowerSummary:
    connector = connector or StiDatabaseConnector()
    rows: list[dict[str, Any]]
    data_source = SOURCE_TABLE
    country_filter = _selected_country(filters)
    sales_period = _sales_period(sales_date=sales_date, sales_start_date=sales_start_date, sales_end_date=sales_end_date)
    bounded_max_rows = _bounded_int(max_rows, default=20000, minimum=1, maximum=20000)
    if not connector.config.ready:
        raise RuntimeError("数据获取失败：STI 数据库未启用或连接信息不完整。")
    spec = QuerySpec.inventory(
        material_code=material_code,
        field_pack=FieldPack.CONTROL_TOWER,
        intent="inventory_control_tower",
        filters=filters or {"order_by": "risk_then_demand"},
        limit=bounded_max_rows,
    )
    rows = connector.get_inventory_rows(spec)
    if not rows:
        return _empty_control_tower_summary(
            connector=connector,
            data_source=data_source,
            sales_period=sales_period,
            country_filter=country_filter,
            page=page,
            page_size=page_size,
            max_rows=bounded_max_rows,
        )

    rows = _with_daily_sales(rows, connector, sales_period["start"], sales_period["end"], filters, data_source)
    rows = _with_pici_shortage(rows, connector, filters, data_source)
    all_items = [_build_item(row) for row in rows]
    if (filters or {}).get("risk_only"):
        all_items = [item for item in all_items if _item_has_active_risk(item)]
    risk_type_filters = _selected_risk_types(filters)
    if risk_type_filters:
        all_items = [item for item in all_items if any(_item_matches_risk_type(item, risk_type) for risk_type in risk_type_filters)]
    all_items = sorted(all_items, key=_risk_sort_key)
    total_count = len(all_items)
    bounded_page_size = _bounded_int(page_size, default=100, minimum=1, maximum=bounded_max_rows)
    total_pages = max(1, (total_count + bounded_page_size - 1) // bounded_page_size)
    bounded_page = min(_bounded_int(page, default=1, minimum=1, maximum=total_pages), total_pages)
    start = (bounded_page - 1) * bounded_page_size
    items = all_items[start : start + bounded_page_size]
    risk_distribution = dict(Counter(item.risk_level for item in all_items))
    risk_type_distribution = dict(Counter(item.risk_type for item in all_items))
    risk_dimensions = _build_risk_dimensions(all_items)
    total_inventory = sum(item.total_inventory for item in all_items)
    total_demand_30d = sum(item.demand_30d for item in all_items)
    total_daily_sales = sum(item.daily_sales_volume for item in all_items)
    local_inventory = sum(item.local_inventory for item in all_items)
    overseas_inventory = sum(item.overseas_inventory for item in all_items)
    fba_inventory = sum(item.fba_inventory for item in all_items)
    stock_up_inventory = sum(item.stock_up_inventory for item in all_items)
    fba_sellable = sum(item.fba_sellable for item in all_items)
    afn_inbound_receiving_quantity = sum(item.afn_inbound_receiving_quantity for item in all_items)
    afn_inbound_working_quantity = sum(item.afn_inbound_working_quantity for item in all_items)
    overseas_afn_inbound_shipped_quantity = sum(item.overseas_afn_inbound_shipped_quantity for item in all_items)
    local_afn_inbound_shipped_quantity = sum(item.local_afn_inbound_shipped_quantity for item in all_items)
    overseas_wh_product_onway = sum(item.overseas_wh_product_onway for item in all_items)
    local_wh_product_onway = sum(item.local_wh_product_onway for item in all_items)
    planned_quantity = sum(item.planned_quantity for item in all_items)
    kpis = {
        "sku_count": total_count,
        "total_inventory": round(total_inventory, 2),
        "fba_sellable": round(fba_sellable, 2),
        "fba_inventory": round(fba_inventory, 2),
        "overseas_inventory": round(overseas_inventory, 2),
        "local_inventory": round(local_inventory, 2),
        "stock_up_inventory": round(stock_up_inventory, 2),
        "domestic_supply_inventory": round(local_inventory + stock_up_inventory, 2),
        "overseas_sellable_inventory": round(fba_sellable + overseas_inventory, 2),
        "inbound_total": round(sum(item.inbound_total for item in all_items), 2),
        "afn_inbound_receiving_quantity": round(afn_inbound_receiving_quantity, 2),
        "afn_inbound_working_quantity": round(afn_inbound_working_quantity, 2),
        "overseas_afn_inbound_shipped_quantity": round(overseas_afn_inbound_shipped_quantity, 2),
        "local_afn_inbound_shipped_quantity": round(local_afn_inbound_shipped_quantity, 2),
        "overseas_wh_product_onway": round(overseas_wh_product_onway, 2),
        "local_wh_product_onway": round(local_wh_product_onway, 2),
        "planned_quantity": round(planned_quantity, 2),
        "daily_sales_volume": round(total_daily_sales, 2),
        "demand_30d": round(total_demand_30d, 2),
        "critical_count": risk_distribution.get("critical", 0),
        "high_count": risk_distribution.get("high", 0),
        "medium_count": risk_distribution.get("medium", 0),
        "low_count": risk_distribution.get("low", 0),
        "stockout_count": sum(1 for item in all_items if _is_active_level(item.stockout_risk_level)),
        "overstock_count": sum(1 for item in all_items if _is_active_level(item.overstock_risk_level)),
        "healthy_count": sum(
            1
            for item in all_items
            if not _is_active_level(item.stockout_risk_level)
            and not _is_active_level(item.overstock_risk_level)
            and item.risk_type != "anomaly"
        ),
        "inventory_to_30d_demand": round(total_inventory / total_demand_30d, 2) if total_demand_30d else None,
    }
    return ControlTowerSummary(
        data_source=data_source,
        sales_stat_date=sales_period["label"],
        sales_start_date=sales_period["start"],
        sales_end_date=sales_period["end"],
        sales_day_count=sales_period["day_count"],
        notes=_control_tower_notes(sales_period["label"]),
        kpis=kpis,
        risk_distribution=risk_distribution,
        risk_type_distribution=risk_type_distribution,
        risk_dimensions=risk_dimensions,
        pagination={
            "page": bounded_page,
            "page_size": bounded_page_size,
            "total_count": total_count,
            "total_pages": total_pages,
            "max_rows": bounded_max_rows,
            "returned_count": len(items),
        },
        map_nodes=_build_map_nodes(all_items),
        warehouse_inventory=_build_warehouse_inventory(connector, country_filter, data_source),
        field_decisions=control_tower_field_decisions(),
        filter_options=_build_filter_options(all_items, connector=connector),
        items=items,
    )


def _control_tower_notes(sales_label: str) -> list[str]:
    return [
        f"{SOURCE_TABLE} 作为控制塔主宽表和月度基准快照使用。",
        f"{DAILY_SALES_TABLE} 按 {sales_label} 的 volume 聚合为区间销量，可在前端选择单日或多日。",
        f"{PICI_SALE_TABLE} 的 chazhi 字段作为断货排查关键字段：库存量/预测销量（缺口数量）。",
        "断货风险按 0-45 天内 chazhi 负数天数判断：1-7 天中等、8-14 天高、15 天以上严重；45 天后只提示补货。",
        "参考 SOP：冗余风险按销售属性区分爆旺/平滞的可售天数 1-6 阈值，并叠加 FBA 库龄动作判定。",
        "实时库存变动、采购在途和发货在途应继续接入 DWD/ODS 明细表复核。",
    ]


def _build_filter_options(
    items: list[ControlTowerItem],
    connector: StiDatabaseConnector | None = None,
) -> dict[str, list[str]]:
    options = {
        "country_code": _unique_item_values(items, "country_code"),
        "shipments_country": _unique_item_values(items, "shipments_country"),
        "store_name": _unique_item_values(items, "store_name"),
        "sales_department": _unique_item_values(items, "sales_department"),
        "salesman": _unique_item_values(items, "salesman"),
        "product_manager": _unique_item_values(items, "product_manager"),
        "seller_id": _unique_item_values(items, "seller_id"),
        "product_property": _unique_item_values(items, "product_property"),
        "seasonality": _unique_item_values(items, "seasonality"),
        "msku_status": _unique_item_values(items, "msku_status"),
        "msku_life_process": _life_process_filter_options(items),
    }
    product_property_values = _inventory_filter_option_values(connector, "msku_product_property")
    if product_property_values:
        options["product_property"] = _merge_unique_options(options["product_property"], product_property_values)
    return options


def _build_risk_dimensions(items: list[ControlTowerItem]) -> dict[str, list[ControlTowerRiskDimensionSlice]]:
    return {
        "country_code": _build_risk_dimension_slices(items, "country_code"),
        "store_name": _build_risk_dimension_slices(items, "store_name"),
        "sales_department": _build_risk_dimension_slices(items, "sales_department"),
        "salesman": _build_risk_dimension_slices(items, "salesman"),
        "sales_property": _build_risk_dimension_slices(items, "sales_property"),
        "seasonality": _build_risk_dimension_slices(items, "seasonality"),
    }


def _build_risk_dimension_slices(items: list[ControlTowerItem], field_name: str) -> list[ControlTowerRiskDimensionSlice]:
    grouped: dict[str, list[ControlTowerItem]] = {}
    labels: dict[str, str] = {}
    for item in items:
        value = _text(getattr(item, field_name, "")).strip()
        key = value or "__blank__"
        labels[key] = value or "未维护"
        grouped.setdefault(key, []).append(item)

    slices = []
    for key, group_items in grouped.items():
        total_count = len(group_items)
        risk_count = sum(1 for item in group_items if _item_has_active_risk(item))
        real_risk_count = sum(1 for item in group_items if _item_is_real_risk(item))
        slices.append(
            ControlTowerRiskDimensionSlice(
                key=key,
                label=labels[key],
                total_count=total_count,
                risk_count=risk_count,
                risk_rate=round(real_risk_count / total_count, 4) if total_count else 0,
                stockout_count=sum(1 for item in group_items if _is_active_level(item.stockout_risk_level)),
                overstock_count=sum(1 for item in group_items if _is_active_level(item.overstock_risk_level)),
                anomaly_count=sum(1 for item in group_items if _item_has_anomaly_risk(item)),
                critical_count=sum(1 for item in group_items if item.risk_level == "critical"),
                high_count=sum(1 for item in group_items if item.risk_level == "high"),
                medium_count=sum(1 for item in group_items if item.risk_level == "medium"),
                low_count=sum(1 for item in group_items if item.risk_level == "low"),
                normal_count=sum(1 for item in group_items if item.risk_level == "normal"),
                max_risk_score=max((item.risk_score for item in group_items), default=0),
                total_inventory=round(sum(item.total_inventory for item in group_items), 2),
                demand_30d=round(sum(item.demand_30d for item in group_items), 2),
                daily_sales_volume=round(sum(item.daily_sales_volume for item in group_items), 2),
            )
        )
    return sorted(
        slices,
        key=lambda item: (item.risk_count, item.max_risk_score, item.total_count, item.label),
        reverse=True,
    )


def _life_process_filter_options(items: list[ControlTowerItem]) -> list[str]:
    if not items:
        return []
    return ["新品期", "非新品期"]


def _unique_item_values(items: list[ControlTowerItem], field_name: str) -> list[str]:
    values = {_text(getattr(item, field_name, "")).strip() for item in items}
    return sorted(value for value in values if value)


def _inventory_filter_option_values(connector: StiDatabaseConnector | None, source_field: str) -> list[str]:
    if connector is None or not hasattr(connector, "get_inventory_filter_option_values"):
        return []
    try:
        raw_options = connector.get_inventory_filter_option_values((source_field,), limit=200)
    except Exception:
        return []
    values = raw_options.get(source_field, []) if isinstance(raw_options, dict) else []
    return [value for value in (_text(item).strip() for item in values) if value]


def _merge_unique_options(primary: list[str], extra: list[str]) -> list[str]:
    return sorted(dict.fromkeys([*primary, *extra]))


def _empty_control_tower_summary(
    connector: StiDatabaseConnector,
    data_source: str,
    sales_period: dict[str, Any],
    country_filter: str | None,
    page: int,
    page_size: int,
    max_rows: int,
) -> ControlTowerSummary:
    bounded_page_size = _bounded_int(page_size, default=100, minimum=1, maximum=max_rows)
    bounded_page = _bounded_int(page, default=1, minimum=1, maximum=1)
    return ControlTowerSummary(
        data_source=data_source,
        sales_stat_date=sales_period["label"],
        sales_start_date=sales_period["start"],
        sales_end_date=sales_period["end"],
        sales_day_count=sales_period["day_count"],
        notes=_control_tower_notes(sales_period["label"]),
        kpis={
            "sku_count": 0,
            "total_inventory": 0,
            "fba_sellable": 0,
            "fba_inventory": 0,
            "overseas_inventory": 0,
            "local_inventory": 0,
            "stock_up_inventory": 0,
            "domestic_supply_inventory": 0,
            "overseas_sellable_inventory": 0,
            "inbound_total": 0,
            "afn_inbound_receiving_quantity": 0,
            "afn_inbound_working_quantity": 0,
            "overseas_afn_inbound_shipped_quantity": 0,
            "local_afn_inbound_shipped_quantity": 0,
            "overseas_wh_product_onway": 0,
            "local_wh_product_onway": 0,
            "planned_quantity": 0,
            "daily_sales_volume": 0,
            "demand_30d": 0,
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "stockout_count": 0,
            "overstock_count": 0,
            "healthy_count": 0,
            "inventory_to_30d_demand": None,
        },
        risk_distribution={},
        risk_type_distribution={},
        risk_dimensions=_build_risk_dimensions([]),
        pagination={
            "page": bounded_page,
            "page_size": bounded_page_size,
            "total_count": 0,
            "total_pages": 1,
            "max_rows": max_rows,
            "returned_count": 0,
        },
        map_nodes=[],
        warehouse_inventory=_build_warehouse_inventory(connector, country_filter, data_source),
        field_decisions=control_tower_field_decisions(),
        filter_options=_build_filter_options([], connector=connector),
        items=[],
    )


def get_monthly_forecast_review(
    material_code: str | None = None,
    msku: str | None = None,
    fnsku: str | None = None,
    asin: str | None = None,
    store_name: str | None = None,
    country_code: str | None = None,
    as_of_date: str | date | None = None,
    month_offset: int = 2,
    connector: StiDatabaseConnector | None = None,
) -> MonthlyForecastReview:
    connector = connector or StiDatabaseConnector()
    if not connector.config.ready:
        raise RuntimeError("数据获取失败：STI 数据库未启用或连接信息不完整。")
    month_offset = _bounded_int(month_offset, default=2, minimum=0, maximum=24)
    target_start, target_end = _target_month_window(as_of_date=as_of_date, month_offset=month_offset)
    trigger_date = _as_date(as_of_date) or date.today()
    review_end = _week_start(trigger_date) - timedelta(days=1)
    codes = _unique_text([_text(material_code), _text(msku), _text(fnsku), _text(asin)])
    if not codes:
        raise ValueError("material_code、msku、fnsku、asin 至少需要一个。")
    try:
        snapshot_rows = connector.get_monthly_forecast_snapshot_rows(
            material_codes=codes,
            target_start_date=target_start.isoformat(),
            target_end_date=target_end.isoformat(),
            store_name=store_name,
            country_code=country_code,
            table_name=MONTHLY_FORECAST_REVIEW_TABLE,
        )
    except Exception as exc:
        raise RuntimeError("数据获取失败：月度库存监控备份表读取失败。") from exc
    snapshot_start = max((_as_date(row.get("date")) for row in snapshot_rows if _as_date(row.get("date"))), default=None)
    snapshot_date = snapshot_start.isoformat() if snapshot_start else ""
    review_start = _next_week_start(snapshot_start or target_start)
    if review_end < review_start:
        review_end = review_start
    try:
        actual_rows = connector.get_daily_sales_detail_rows(
            review_start.isoformat(),
            sales_end_date=review_end.isoformat(),
            country_code=country_code,
            store_name=store_name,
            material_codes=codes,
        )
    except Exception as exc:
        raise RuntimeError("数据获取失败：月度实际销量读取失败。") from exc
    try:
        forecast_versions, forecast_version_rows = _monthly_forecast_versions(
            connector=connector,
            material_codes=codes,
            as_of_date=as_of_date,
            review_start=review_start,
            review_end=review_end,
            store_name=store_name,
            country_code=country_code,
            primary_month_offset=month_offset,
        )
        detail_forecast_versions, detail_forecast_rows = _monthly_forecast_versions(
            connector=connector,
            material_codes=codes,
            as_of_date=as_of_date,
            review_start=_detail_forecast_start(as_of_date=as_of_date),
            review_end=_detail_forecast_end(as_of_date=as_of_date),
            store_name=store_name,
            country_code=country_code,
            primary_month_offset=month_offset,
            aligned_to_version_window=True,
        )
    except Exception as exc:
        raise RuntimeError("数据获取失败：月度销量预估表读取失败。") from exc
    estimate_rows = forecast_version_rows.get(month_offset, [])

    forecast_quantity = _forecast_rows_quantity(estimate_rows, review_start, review_end)
    matched_actual_rows = _matching_sales_rows(actual_rows, codes)
    detail_start = _detail_forecast_start(as_of_date=as_of_date)
    detail_end = _detail_forecast_end(as_of_date=as_of_date)
    try:
        detail_actual_rows = connector.get_daily_sales_detail_rows(
            detail_start.isoformat(),
            sales_end_date=min(review_end, detail_end).isoformat(),
            country_code=country_code,
            store_name=store_name,
            material_codes=codes,
        )
    except Exception as exc:
        raise RuntimeError("数据获取失败：销量预估详情实际销量读取失败。") from exc
    matched_detail_actual_rows = _matching_sales_rows(detail_actual_rows, codes)
    detail_actual_points = _trim_first_actual_point(_weekly_actual_points(matched_detail_actual_rows, detail_start, min(review_end, detail_end)))
    detail_monthly_totals = _detail_monthly_totals(
        forecast_rows_by_offset=detail_forecast_rows,
        actual_rows=matched_detail_actual_rows,
        detail_start=detail_start,
        detail_end=detail_end,
        actual_end=min(review_end, detail_end),
        as_of_date=as_of_date,
    )
    actual_sales = sum(_number(row.get("daily_sales_volume")) for row in matched_actual_rows)
    ad_spend = sum(_number(row.get("ad_spend")) for row in matched_actual_rows)
    ad_sales_amount = sum(_number(row.get("ad_sales_amount")) for row in matched_actual_rows)
    ad_order_quantity = sum(_number(row.get("ad_order_quantity")) for row in matched_actual_rows)
    organic_sales = actual_sales - ad_order_quantity
    ad_acos = ad_spend / ad_sales_amount if ad_sales_amount else None
    difference = actual_sales - forecast_quantity
    variance_ratio = difference / forecast_quantity if forecast_quantity else None
    result_type, result_label = _forecast_review_result(difference, forecast_quantity, actual_sales)
    try:
        daily_price_rows = connector.get_daily_listing_price_rows(
            material_codes=codes,
            start_date=review_start.isoformat(),
            end_date=review_end.isoformat(),
            store_name=store_name,
            country_code=country_code,
        )
    except AttributeError:
        daily_price_rows = []
    except Exception as exc:
        raise RuntimeError("数据获取失败：Listing 日价格读取失败。") from exc
    daily_price_points = _daily_price_points(daily_price_rows) or _daily_sales_price_points(matched_actual_rows)
    weekly_estimate_points = _weekly_estimates(estimate_rows, matched_actual_rows, review_start, review_end)
    forecast_anomalies = _forecast_anomalies_from_monthly_totals(detail_monthly_totals)
    sales_anomalies = _weekly_sales_anomalies(weekly_estimate_points)

    return MonthlyForecastReview(
        data_source=MONTHLY_FORECAST_REVIEW_TABLE,
        sales_source=DAILY_SALES_TABLE,
        forecast_source=MONTHLY_SALES_ESTIMATE_TABLE,
        target_month=target_start.strftime("%Y-%m"),
        target_start_date=target_start.isoformat(),
        target_end_date=target_end.isoformat(),
        comparison_month=_month_range_label(review_start, review_end),
        comparison_start_date=review_start.isoformat(),
        comparison_end_date=review_end.isoformat(),
        review_start_date=review_start.isoformat(),
        review_end_date=review_end.isoformat(),
        month_offset=month_offset,
        snapshot_date=snapshot_date,
        forecast_field="value",
        actual_field="volume",
        forecast_quantity=round(forecast_quantity, 2),
        actual_sales=round(actual_sales, 2),
        ad_spend=round(ad_spend, 2),
        ad_sales_amount=round(ad_sales_amount, 2),
        ad_order_quantity=round(ad_order_quantity, 2),
        organic_sales=round(organic_sales, 2),
        ad_acos=round(ad_acos, 4) if ad_acos is not None else None,
        difference=round(difference, 2),
        variance_ratio=round(variance_ratio, 4) if variance_ratio is not None else None,
        variance_percent=round(variance_ratio * 100, 2) if variance_ratio is not None else None,
        result_type=result_type,
        result_label=result_label,
        snapshot_row_count=len(snapshot_rows),
        forecast_row_count=len(estimate_rows),
        actual_row_count=len(matched_actual_rows),
        notes=[
            f"默认按运行日月份 -{month_offset} 取预测版本月；例如 6 月运行取 4 月最后一张备份。",
            "趋势对比区间从预测版本月最后一张备份取值日期的下一周开始，截止到触发日所在周的上一周。",
            f"{MONTHLY_FORECAST_REVIEW_TABLE} 先取目标月份内全表最大 date，作为该月最后一次库存监控底表备份快照。",
            f"预测口径使用 {MONTHLY_SALES_ESTIMATE_TABLE}.value，先取版本月内最后一次 date，value 按日预测处理，再按 start_date/end_date 覆盖天数汇总为周销量。",
            "详情图使用独立口径：各版本预估线从自己的版本月月初开始，延展 180 天；3个月前预估线剔除首尾周，其余预估线只剔除末周；实际销量线剔除首周后展示。",
            "月度柱图的预估总量按错位月份对比：销售月份优先使用提前两个月的可用预估版本月，早于可用版本时用最早版本兜底；销量总量使用日销量明细按月汇总，未完整当前月按已发生天数 / 当月天数推算虚拟可能销量。",
            f"实际销量和广告指标使用 {DAILY_SALES_TABLE}，按趋势对比区间和周聚合。",
            "价格曲线优先使用 ods_lingxing_sc_listing 日价格；缺失时使用销售日报 amount / volume 推算日成交均价。",
            "ACOS = 广告花费 / 广告销售额。",
            "自然销量估算 = 实际销量 - 广告订单量。",
            "差值 = 实际销量 - 预测销量；比例 = 差值 / 预测销量。",
        ],
        snapshot_rows=[
            MonthlyForecastReviewSnapshotRow(
                sku=_text(row.get("sku")),
                msku=_text(row.get("msku")),
                fnsku=_text(row.get("fnsku")),
                asin=_text(row.get("asin")),
                store_name=_text(row.get("store_name")),
                country_code=_text(row.get("country_code")),
                shipments_country=_text(row.get("shipments_country")),
                sku_name=_text(row.get("sku_name")),
                forecast_quantity=round(_number(row.get("future_30d_sales")), 2),
                historical_30d_sales=round(_number(row.get("sale_quantity_30")), 2),
            )
            for row in snapshot_rows[:20]
        ],
        weekly_estimates=weekly_estimate_points,
        forecast_versions=forecast_versions,
        detail_forecast_versions=detail_forecast_versions,
        detail_actual_sales=detail_actual_points,
        detail_monthly_totals=detail_monthly_totals,
        daily_price_points=daily_price_points,
        forecast_anomalies=forecast_anomalies,
        sales_anomalies=sales_anomalies,
    )


def control_tower_field_decisions() -> list[ControlTowerFieldDecision]:
    fields = set(ALL_WAREHOUSE_CATALOG.fields_for(FieldPack.CONTROL_TOWER))
    decisions = [
        _include("sku", "SKU", "身份维度", "主物料编码，用于明细定位和搜索。"),
        _include("msku", "MSKU", "身份维度", "商户 SKU，用于店铺和销售口径聚合。"),
        _include("fnsku", "FNSKU", "身份维度", "亚马逊履约库存口径，用于断货追踪。"),
        _include("asin", "ASIN", "身份维度", "商品链接和平台侧识别。"),
        _include("sku_name", "商品名称", "身份维度", "帮助业务用户识别 SKU。"),
        _include("store_name", "店铺", "筛选维度", "控制塔常用切片。"),
        _include("country_code", "国家", "筛选维度", "用于国家站点风险聚合。"),
        _include("shipments_country", "发货国家", "筛选维度", "用于物流和补货区域判断。"),
        _include("sales_apartment", "销售部门", "筛选维度", "来自主宽表 sales_apartment，用于销售组织责任切片。"),
        _include("salesman", "销售员", "筛选维度", "来自主宽表 salesman，用于销售负责人切片。"),
        _include("product_manager", "产品经理", "筛选维度", "来自主宽表 product_manager，用于产品责任人切片。"),
        _include("seller_id", "账号", "筛选维度", "来自主宽表 seller_id，用于店铺账号切片。"),
        _include("msku_sales_property", "销售属性", "筛选维度", "爆/旺/平/滞会影响冗余阈值、风险解释和后续补货规则。"),
        _include("msku_product_property", "产品属性", "筛选维度", "来自主宽表 msku_product_property，用于款式/产品口径切片。"),
        _include("seasonality", "季节属性", "筛选维度", "季节款的冗余和补货动作需要单独判断。"),
        _include("msku_status", "MSKU 状态", "筛选维度", "来自主宽表 msku_status，用于在售/停售等状态切片。"),
        _include("msku_life_process", "MSKU 生命周期", "筛选维度", "来自主宽表 msku_life_process，用于新品期、成熟期等生命周期切片。"),
        _include("afn_fulfillable_quantity", "FBA 可售", "库存状态", "断货风险的第一视角。"),
        _include("fba_warehouse_quantity", "FBA 库存", "库存状态", "当前平台库存水位。"),
        _include("overseas_warehouse_quantity", "海外仓库存", "库存状态", "判断可补 FBA 的海外库存。"),
        _include("local_warehouse_quantity", "本地仓库存", "库存状态", "判断国内可调拨和发货能力。"),
        _include("afn_inbound_receiving_quantity", "FBA 接收中", "在途状态", "补足缺口的近期供应。"),
        _include("afn_inbound_working_quantity", "FBA 处理中", "在途状态", "补足缺口的未来供应。"),
        _include("oversease_afn_inbound_shipped_quantity", "海外发 FBA 在途", "在途状态", "评估断货是否可被在途覆盖。"),
        _include("local_afn_inbound_shipped_quantity", "本地发 FBA 在途", "在途状态", "评估断货是否可被在途覆盖。"),
        _include("overseas_wh_product_onway", "海外仓在途", "在途状态", "判断海外仓补货链路。"),
        _include("local_wh_product_onway", "本地仓在途", "在途状态", "判断本地仓补货链路。"),
        _include("planned_quantity", "计划量", "供应状态", "补货计划是否已经覆盖风险。"),
        _include("daily_sales_volume", "日销量", "需求状态", "来自日销量表 volume，支持按统计日期切换。"),
        _include("pici_shortage_gap", "断货缺口", "断货排查", "来自 chazhi：库存量/预测销量（缺口数量），用于判断最早缺口窗口。"),
        _include("sale_quantity_7", "近 7 天销量", "需求状态", "短期需求和销量突变判断。"),
        _include("sale_quantity_30", "近 30 天销量", "需求状态", "无预测时回退为日均需求。"),
        _include("future_30d_sales", "未来 30 天预测", "需求状态", "断货和冗余规则的核心需求口径。"),
        _include("future_60d_sales", "未来 60 天预测", "需求状态", "辅助看中期库存压力。"),
        _include("future_90d_sales", "未来 90 天预测", "需求状态", "辅助看长期冗余压力。"),
        _include("safety_stock_sales", "安全库存销量", "规则参数", "后续正式安全库存规则会使用。"),
        _include("last_30_order_price", "近 30 天成交价", "利润估算", "来自主宽表，用于把补货运费差额折算到毛利率影响。"),
        _include("last_30_order_us_price", "近 30 天美元成交价", "利润估算", "辅助跨站点核对成交价口径。"),
        _include("last_90_gross_margin", "近 90 天毛利率", "利润估算", "来自主宽表，用作补货运费差额影响前的基准毛利率。"),
        _include("fnsku_out_of_stock_risk_1", "断货风险 1", "风险标记", "保留底表已有风险信号。"),
        _include("fnsku_out_of_stock_risk_6", "断货风险 6", "风险标记", "保留底表已有风险信号。"),
        _include("inv_age_61_to_90_days", "61-90 天库龄", "冗余判断", "SOP 中对应预警监控，用于冗余早期提醒。"),
        _include("inv_age_91_to_180_days", "91-180 天库龄", "冗余判断", "SOP 中对应预警监控，用于冗余早期提醒。"),
        _include("inv_age_181_to_270_days", "181-270 天库龄", "冗余判断", "长库龄库存用于冗余识别。"),
        _include("inv_age_271_to_330_days", "271-330 天库龄", "冗余判断", "接近长期仓储费窗口，用于中风险冗余识别。"),
        _include("inv_age_331_to_365_days", "331-365 天库龄", "冗余判断", "临近 365+ 长期滞留，用于中高风险冗余识别。"),
        _include("inv_age_365_plus_days", "365 天以上库龄", "冗余判断", "长期滞留库存用于冗余识别。"),
        _include("order_duration", "下单时长", "提前期", "用于断货提前期判断。"),
        _include("production_duration", "生产时长", "提前期", "用于断货提前期判断。"),
        _include("logistics_model", "物流模式", "解释字段", "用于解释建议动作和后续物流优化。"),
        _exclude("basic_purchase_quantity", "基础采购量", "采购验证", "控制塔首屏不直接复算采购建议，放在采购验证页。"),
        _exclude("jypurchase_quantity", "建议采购量", "采购验证", "属于确认前草稿动作，控制塔只展示风险入口。"),
        _exclude("basic_fh_quantity", "基础发货量", "发货验证", "属于发货验证页复算字段。"),
        _exclude("jyfahuo_quantity", "建议发货量", "发货验证", "属于周度计划和发货验证动作，不作为库存状态核心指标。"),
        _exclude("stock_up_num", "备货数", "候选字段", "规则文档提到，但当前 v1 白名单未确认，首版不直接查询。"),
        _exclude("fba_safety_days_fn", "FBA 安全天数", "候选字段", "规则文档提到，但当前 v1 白名单未确认，先用保留规则默认值。"),
    ]
    return [
        decision
        for decision in decisions
        if (decision.included and (decision.name in fields or decision.name in {"daily_sales_volume", "pici_shortage_gap"})) or not decision.included
    ]


def _build_item(row: dict[str, Any]) -> ControlTowerItem:
    material_code = _text(row.get("sku") or row.get("fnsku") or row.get("msku") or "UNKNOWN")
    fba_sellable = _number(row.get("afn_fulfillable_quantity"))
    fba_inventory = _number(row.get("fba_warehouse_quantity")) or fba_sellable
    overseas_inventory = _number(row.get("overseas_warehouse_quantity"))
    local_inventory = _number(row.get("local_warehouse_quantity"))
    stock_up = _number(row.get("stock_up_num"))
    total_inventory = fba_inventory + overseas_inventory + local_inventory + stock_up
    afn_inbound_receiving_quantity = _number(row.get("afn_inbound_receiving_quantity"))
    afn_inbound_working_quantity = _number(row.get("afn_inbound_working_quantity"))
    overseas_afn_inbound_shipped_quantity = _number(row.get("oversease_afn_inbound_shipped_quantity") or row.get("overseas_afn_inbound_shipped_quantity"))
    local_afn_inbound_shipped_quantity = _number(row.get("local_afn_inbound_shipped_quantity"))
    overseas_wh_product_onway = _number(row.get("overseas_wh_product_onway"))
    local_wh_product_onway = _number(row.get("local_wh_product_onway"))
    planned_quantity = _number(row.get("planned_quantity"))
    inbound_total = sum(
        (
            afn_inbound_receiving_quantity,
            afn_inbound_working_quantity,
            overseas_afn_inbound_shipped_quantity,
            local_afn_inbound_shipped_quantity,
            overseas_wh_product_onway,
            local_wh_product_onway,
            planned_quantity,
        )
    )
    demand_7d = _number(row.get("sale_quantity_7"))
    demand_30d = _number(row.get("future_30d_sales")) or _number(row.get("sale_quantity_30"))
    daily_demand = demand_30d / 30 if demand_30d > 0 else max(demand_7d / 7, 0)
    sellable_days = _table_available_days(row, 1)
    if sellable_days is None:
        sellable_days = fba_inventory / daily_demand if daily_demand else None
    lead_time_days = _lead_time_days(row)
    fba_age = _fba_age_breakdown(row)
    long_age_inventory = sum(fba_age.values())
    fba_long_age_ratio = long_age_inventory / fba_inventory if fba_inventory else None
    projected_7d = fba_sellable - demand_7d
    risk_flags = _risk_flags(row)
    pici_summary = _pici_gap_summary(row)
    sales_property = _text(row.get("msku_sales_property"))
    is_pici_shortage = pici_summary["first_shortage_days"] is not None
    is_stockout = is_pici_shortage
    redundancy_sellable_days = _redundancy_sellable_days(
        daily_demand=daily_demand,
        fba_sellable=fba_sellable,
        overseas_inventory=overseas_inventory,
        local_inventory=local_inventory,
        row=row,
    )
    overstock = _overstock_assessment(redundancy_sellable_days, fba_age, sales_property)
    is_overstock = overstock["is_overstock"]
    is_anomaly = bool(risk_flags)

    pici_first_shortage_days = pici_summary["first_shortage_days"]
    stockout_risk_level, stockout_risk_score = _stockout_assessment(
        is_stockout=is_stockout,
        pici_first_shortage_days=pici_first_shortage_days,
        pici_shortage_days_0_45=pici_summary["shortage_days_0_45"],
        sellable_days=sellable_days,
    )
    overstock_risk_level = overstock["risk_level"] if is_overstock else "normal"
    overstock_risk_score = overstock["risk_score"] if is_overstock else 10
    anomaly_score = 65 if is_anomaly else 10
    risk_level = _max_level((stockout_risk_level, overstock_risk_level, "medium" if is_anomaly else "normal"))
    risk_score = max(stockout_risk_score, overstock_risk_score, anomaly_score)
    stockout_warning = _risk_warning("断货", stockout_risk_level)
    if stockout_risk_level == "normal" and pici_summary["future_replenishment_hint_days"] is not None:
        stockout_warning = f"第 {pici_summary['future_replenishment_hint_days']} 天后补货提示"
    overstock_warning = _risk_warning("冗余", overstock_risk_level)

    action_parts = []
    if _is_active_level(stockout_risk_level):
        action_parts.append("断货：按 0-45 天 chazhi 缺口天数复核 FBA 可售、在途覆盖和最快补货窗口")
    elif pici_summary["future_replenishment_hint_days"] is not None:
        action_parts.append(f"补货提示：第 {pici_summary['future_replenishment_hint_days']} 天后 chazhi 出现负数，请提前排补货")
    if _is_active_level(overstock_risk_level):
        action_parts.append(f"冗余：{overstock['suggested_action'].rstrip('。')}")
    if is_anomaly:
        action_parts.append("异常：复核底表风险标记、销量波动和库存明细差异")
    suggested_action = "；".join(action_parts) + "。" if action_parts else "继续例行监控。"
    warning_parts = [
        warning
        for warning in (stockout_warning, overstock_warning, "库存异常" if is_anomaly else "")
        if warning and not warning.startswith("无")
    ]
    warning_type = " / ".join(warning_parts) if warning_parts else "正常"

    if _is_active_level(stockout_risk_level):
        risk_type = "stockout"
    elif _is_active_level(overstock_risk_level):
        risk_type = "overstock"
    elif is_anomaly:
        risk_type = "anomaly"
    else:
        risk_type = "healthy"

    return ControlTowerItem(
        material_code=material_code,
        msku=_text(row.get("msku")),
        fnsku=_text(row.get("fnsku")),
        asin=_text(row.get("asin")),
        sku_name=_text(row.get("sku_name")),
        store_name=_text(row.get("store_name")),
        country_code=_text(row.get("country_code")),
        shipments_country=_text(row.get("shipments_country")),
        sales_department=_text(row.get("sales_apartment")),
        salesman=_text(row.get("salesman")),
        product_manager=_text(row.get("product_manager")),
        seller_id=_text(row.get("seller_id")),
        sales_property=sales_property,
        product_property=_text(row.get("msku_product_property")),
        seasonality=_text(row.get("seasonality")),
        msku_status=_text(row.get("msku_status")),
        msku_life_process=_text(row.get("msku_life_process")),
        logistics_model=_text(row.get("logistics_model")),
        first_leg_logistics_channel=_text(row.get("first_leg_logistics_channel")),
        risk_type=risk_type,
        risk_level=risk_level,
        warning_type=warning_type,
        suggested_action=suggested_action,
        risk_score=risk_score,
        stockout_risk_level=stockout_risk_level,
        stockout_warning=stockout_warning,
        overstock_risk_level=overstock_risk_level,
        overstock_warning=overstock_warning,
        total_inventory=round(total_inventory, 2),
        fba_sellable=round(fba_sellable, 2),
        fba_inventory=round(fba_inventory, 2),
        overseas_inventory=round(overseas_inventory, 2),
        local_inventory=round(local_inventory, 2),
        inbound_total=round(inbound_total, 2),
        daily_sales_volume=round(_number(row.get("_daily_sales_volume")), 2),
        pici_first_shortage_days=pici_summary["first_shortage_days"],
        pici_min_gap_quantity=pici_summary["min_gap_quantity"],
        pici_key_gap=pici_summary["key_gap"],
        pici_gap_values=pici_summary["values"],
        demand_7d=round(demand_7d, 2),
        demand_30d=round(demand_30d, 2),
        daily_demand=round(daily_demand, 2),
        last_30_order_price=_optional_number(row.get("last_30_order_price")),
        last_30_order_us_price=_optional_number(row.get("last_30_order_us_price")),
        last_90_gross_margin=_optional_ratio(row.get("last_90_gross_margin")),
        sellable_days=round(sellable_days, 1) if sellable_days is not None else None,
        projected_7d=round(projected_7d, 2),
        lead_time_days=round(lead_time_days, 1),
        long_age_inventory=round(long_age_inventory, 2),
        fba_age_61_to_90=round(fba_age["61_90"], 2),
        fba_age_91_to_180=round(fba_age["91_180"], 2),
        fba_age_181_to_270=round(fba_age["181_270"], 2),
        fba_age_271_to_330=round(fba_age["271_330"], 2),
        fba_age_331_to_365=round(fba_age["331_365"], 2),
        fba_age_365_plus=round(fba_age["365_plus"], 2),
        fba_long_age_ratio=round(fba_long_age_ratio, 3) if fba_long_age_ratio is not None else None,
        redundancy_sellable_days={key: round(value, 1) if value is not None else None for key, value in redundancy_sellable_days.items()},
        stock_up_inventory=round(stock_up, 2),
        afn_inbound_receiving_quantity=round(afn_inbound_receiving_quantity, 2),
        afn_inbound_working_quantity=round(afn_inbound_working_quantity, 2),
        overseas_afn_inbound_shipped_quantity=round(overseas_afn_inbound_shipped_quantity, 2),
        local_afn_inbound_shipped_quantity=round(local_afn_inbound_shipped_quantity, 2),
        overseas_wh_product_onway=round(overseas_wh_product_onway, 2),
        local_wh_product_onway=round(local_wh_product_onway, 2),
        planned_quantity=round(planned_quantity, 2),
        evidence={
            "risk_flags": risk_flags,
            "stockout_rule": "0-45天内 chazhi 负数天数：1-7天中等、8-14天高、15天以上严重；45天后负数只提示补货",
            "stockout_shortage_days_0_45": pici_summary["shortage_days_0_45"],
            "stockout_future_replenishment_hint_days": pici_summary["future_replenishment_hint_days"],
            "overstock_rule": overstock["rule"],
            "overstock_reason": overstock["reason"],
            "source_table": SOURCE_TABLE,
            "daily_sales_table": DAILY_SALES_TABLE,
            "pici_sale_table": PICI_SALE_TABLE,
            "pici_gap_rule": "chazhi_0_N = inventory_plus_inbound_0_N / forecast_sales_0_N (gap_quantity)",
            "pici_gap_missing": not bool(pici_summary["values"]),
        },
    )


def _with_daily_sales(
    rows: list[dict[str, Any]],
    connector: StiDatabaseConnector,
    sales_start_date: str,
    sales_end_date: str,
    filters: dict[str, Any] | None,
    data_source: str,
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    if not connector.config.ready:
        raise RuntimeError("数据获取失败：STI 数据库未启用，无法读取日销量。")
    try:
        daily_rows = connector.get_daily_sales_rows(
            sales_start_date,
            sales_end_date=sales_end_date,
            country_code=_selected_country(filters),
            store_name=_selected_store(filters),
        )
    except Exception as exc:
        raise RuntimeError("数据获取失败：日销量数据获取失败。") from exc
    sales_by_sku_store_country: dict[tuple[str, str, str], float] = {}
    sales_by_seller_country: dict[tuple[str, str], float] = {}
    for daily_row in daily_rows:
        volume = _number(daily_row.get("daily_sales_volume"))
        sku_key = (
            _norm(daily_row.get("sku")),
            _text(daily_row.get("store_name")),
            _norm(daily_row.get("country_code")),
        )
        sales_by_sku_store_country[sku_key] = sales_by_sku_store_country.get(sku_key, 0) + volume
        seller_sku = _norm(daily_row.get("seller_sku"))
        if seller_sku:
            seller_key = (seller_sku, _norm(daily_row.get("country_code")))
            sales_by_seller_country[seller_key] = sales_by_seller_country.get(seller_key, 0) + volume

    enriched = []
    for row in rows:
        primary_key = (_norm(row.get("sku")), _text(row.get("store_name")), _norm(row.get("country_code")))
        seller_key = (_norm(row.get("msku")), _norm(row.get("country_code")))
        volume = sales_by_sku_store_country.get(primary_key)
        if volume is None:
            volume = sales_by_seller_country.get(seller_key, 0)
        enriched.append({**row, "_daily_sales_volume": volume})
    return enriched


def _fba_age_breakdown(row: dict[str, Any]) -> dict[str, float]:
    return {
        "61_90": _number(row.get("inv_age_61_to_90_days")),
        "91_180": _number(row.get("inv_age_91_to_180_days")),
        "181_270": _number(row.get("inv_age_181_to_270_days")),
        "271_330": _number(row.get("inv_age_271_to_330_days")),
        "331_365": _number(row.get("inv_age_331_to_365_days")),
        "365_plus": _number(row.get("inv_age_365_plus_days")),
    }


SELLABLE_DAY_RULES: dict[str, dict[str, Any]] = {
    "sellable_1": {
        "label": "可售天数1",
        "meaning": "FBA仓当前库存可售天数",
        "reasonable_thresholds": {"boom_wang": 45, "flat_stagnant": 30},
        "overstock_thresholds": {"boom_wang": 90, "flat_stagnant": 60},
        "level": "low",
        "action": "重点监控运营清货进度",
    },
    "sellable_2": {
        "label": "可售天数2",
        "meaning": "FBA仓 + FBA在途可售天数",
        "reasonable_thresholds": {"boom_wang": 90, "flat_stagnant": 75},
        "overstock_thresholds": {"boom_wang": 120, "flat_stagnant": 105},
        "level": "medium",
        "action": "禁止向FBA补货",
    },
    "sellable_3": {
        "label": "可售天数3",
        "meaning": "海外仓库存可售天数",
        "reasonable_thresholds": {"boom_wang": 90, "flat_stagnant": 75},
        "overstock_thresholds": {"boom_wang": 120, "flat_stagnant": 105},
        "level": "medium",
        "action": "禁止向FBA补货",
    },
    "sellable_4": {
        "label": "可售天数4",
        "meaning": "海外仓 + 全链路在途可售天数",
        "reasonable_thresholds": {"boom_wang": 90, "flat_stagnant": 75},
        "overstock_thresholds": {"boom_wang": 120, "flat_stagnant": 105},
        "level": "medium",
        "action": "禁止向海外仓补货；禁止向FBA补货",
    },
    "sellable_5": {
        "label": "可售天数5",
        "meaning": "本地仓库存可售天数",
        "reasonable_thresholds": {"boom_wang": 120, "flat_stagnant": 120},
        "overstock_thresholds": {"boom_wang": 180, "flat_stagnant": 150},
        "level": "high",
        "action": "禁止本地仓补货",
    },
    "sellable_6": {
        "label": "可售天数6",
        "meaning": "本地仓 + 全链路可售天数",
        "reasonable_thresholds": {"boom_wang": 120, "flat_stagnant": 120},
        "overstock_thresholds": {"boom_wang": 180, "flat_stagnant": 150},
        "level": "high",
        "action": "禁止本地仓补货；停止下采购单",
    },
}


FBA_AGE_RULES: tuple[dict[str, Any], ...] = (
    {"key": "365_plus", "label": "FBA库龄365+", "level": "high", "score": 86, "action": "批量清货"},
    {"key": "331_365", "label": "FBA库龄331-365天", "level": "high", "score": 82, "action": "批量清货"},
    {"key": "271_330", "label": "FBA库龄271-330天", "level": "high", "score": 80, "action": "批量清货"},
    {"key": "181_270", "label": "FBA库龄181-270天", "level": "medium", "score": 68, "action": "重点清货"},
    {"key": "91_180", "label": "FBA库龄91-180天", "level": "low", "score": 42, "action": "预警监控"},
    {"key": "61_90", "label": "FBA库龄61-90天", "level": "low", "score": 38, "action": "预警监控"},
)


def _redundancy_sellable_days(
    daily_demand: float,
    fba_sellable: float,
    overseas_inventory: float,
    local_inventory: float,
    row: dict[str, Any],
) -> dict[str, float | None]:
    table_days = _table_sellable_days(row, daily_demand)
    if any(value is not None for value in table_days.values()):
        return table_days
    if daily_demand <= 0:
        return {key: None for key in SELLABLE_DAY_RULES}
    fba_inventory = _number(row.get("fba_warehouse_quantity")) or fba_sellable
    fba_inbound = sum(
        _number(row.get(name))
        for name in (
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
        )
    )
    overseas_inbound = _number(row.get("oversease_afn_inbound_shipped_quantity")) + _number(row.get("overseas_wh_product_onway"))
    local_inbound = _number(row.get("local_afn_inbound_shipped_quantity")) + _number(row.get("local_wh_product_onway"))
    planned_quantity = _number(row.get("planned_quantity"))
    inventory_1 = fba_inventory
    inventory_2 = inventory_1 + fba_inbound
    inventory_3 = inventory_2 + overseas_inventory
    inventory_4 = inventory_3 + overseas_inbound
    inventory_5 = inventory_4 + local_inventory
    inventory_6 = inventory_5 + local_inbound + planned_quantity
    return {
        "sellable_1": inventory_1 / daily_demand,
        "sellable_2": inventory_2 / daily_demand,
        "sellable_3": inventory_3 / daily_demand,
        "sellable_4": inventory_4 / daily_demand,
        "sellable_5": inventory_5 / daily_demand,
        "sellable_6": inventory_6 / daily_demand,
    }


def _table_sellable_days(row: dict[str, Any], daily_demand: float) -> dict[str, float | None]:
    days: dict[str, float | None] = {}
    for index in range(1, 7):
        value = _table_available_days(row, index)
        if value is None and daily_demand > 0:
            inventory = _optional_number(row.get(f"fnsku_inventory_{index}"))
            if inventory is not None:
                value = inventory / daily_demand
        days[f"sellable_{index}"] = value
    return days


def _table_available_days(row: dict[str, Any], index: int) -> float | None:
    return _optional_number(row.get(f"fnsku_available_days_{index}"))


def _overstock_assessment(
    redundancy_sellable_days: dict[str, float | None],
    fba_age: dict[str, float],
    sales_property: str,
) -> dict[str, Any]:
    sales_group = _sales_property_threshold_group(sales_property)
    sales_group_label = "平滞" if sales_group == "flat_stagnant" else "爆旺"
    sellable_hits = []
    for key, value in redundancy_sellable_days.items():
        rule = SELLABLE_DAY_RULES[key]
        threshold = rule["overstock_thresholds"][sales_group]
        if value is not None and value > threshold:
            sellable_hits.append(
                {
                    **rule,
                    "key": key,
                    "days": value,
                    "threshold": threshold,
                    "threshold_group": sales_group_label,
                }
            )
    age_hit = next((rule for rule in FBA_AGE_RULES if fba_age.get(rule["key"], 0) > 0), None)
    if not sellable_hits and not age_hit:
        return {
            "is_overstock": False,
            "risk_level": "normal",
            "risk_score": 10,
            "warning_type": "正常",
            "suggested_action": "继续例行监控。",
            "reason": "",
            "rule": "SOP: 可售天数1-6按爆旺/平滞冗余阈值判定，或 FBA库龄进入预警/清货区间。",
        }

    max_sellable_level = _max_level((hit["level"] for hit in sellable_hits), default="normal")
    age_level = age_hit["level"] if age_hit else "normal"
    risk_level = _max_level((max_sellable_level, age_level), default="normal")
    sellable_score = {"high": 84, "medium": 66, "low": 40, "normal": 10}[max_sellable_level]
    age_score = int(age_hit["score"]) if age_hit else 10
    risk_score = max(sellable_score, age_score)
    if risk_level == "high":
        warning_type = "SOP 冗余-批量/拦截"
    elif risk_level == "medium":
        warning_type = "SOP 冗余-重点清货"
    else:
        warning_type = "SOP 冗余-预警监控"

    actions: list[str] = []
    for hit in sellable_hits:
        actions.extend(part for part in str(hit["action"]).split("；") if part)
    if age_hit:
        actions.append(str(age_hit["action"]))
    reason_parts = [
        f'{hit["label"]}({hit["threshold_group"]}) {hit["days"]:.1f}天 > {hit["threshold"]}天'
        for hit in sellable_hits
    ]
    if age_hit:
        reason_parts.append(f'{age_hit["label"]} 库存 {fba_age[age_hit["key"]]:.0f}，动作：{age_hit["action"]}')

    return {
        "is_overstock": True,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "warning_type": warning_type,
        "suggested_action": "按 SOP 冗余处理："
        + "；".join(_unique_text(["冻结SKU", "取消未下单采购", "复核发货计划", *actions]))
        + "。",
        "reason": "；".join(reason_parts),
        "rule": (
            "SOP: 爆旺口径：可售天数1超过90天监控清货，可售天数2或3超过120天停止向FBA补货，"
            "可售天数4超过120天停止向海外仓和FBA补货，可售天数5超过180天停止本地仓补货，"
            "可售天数6超过180天停止本地仓补货并停止下采购单；"
            "平滞口径：可售天数1超过60天监控清货，可售天数2或3超过105天停止向FBA补货，"
            "可售天数4超过105天停止向海外仓和FBA补货，可售天数5超过150天停止本地仓补货，"
            "可售天数6超过150天停止本地仓补货并停止下采购单；"
            "FBA库龄61-180预警、181-270重点清货、271+批量清货。"
        ),
    }


def _sales_property_threshold_group(sales_property: str) -> str:
    text = str(sales_property or "").strip()
    return "flat_stagnant" if "平" in text or "滞" in text else "boom_wang"


def _max_level(levels: Any, default: str = "normal") -> str:
    order = {"normal": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
    return max((level for level in levels if level in order), key=lambda level: order[level], default=default)


def _unique_text(values: list[str]) -> list[str]:
    unique = []
    for value in values:
        text = value.strip()
        if text and text not in unique:
            unique.append(text)
    return unique


def _pici_stockout_level(shortage_days: int) -> tuple[str, int]:
    if shortage_days <= 0:
        return "normal", 10
    if shortage_days <= 7:
        return "medium", 65
    if shortage_days <= 14:
        return "high", 86
    return "critical", 100


def _stockout_assessment(
    is_stockout: bool,
    pici_first_shortage_days: int | None,
    pici_shortage_days_0_45: int = 0,
    sellable_days: float | None = None,
) -> tuple[str, int]:
    if pici_first_shortage_days is not None:
        return _pici_stockout_level(pici_shortage_days_0_45)
    if not is_stockout:
        return "normal", 10
    if (sellable_days or 0) <= 7:
        return "high", 86
    if (sellable_days or 0) <= 42:
        return "medium", 65
    return "low", 38


def _risk_warning(prefix: str, level: str) -> str:
    labels = {"high": "高风险", "medium": "中等风险", "low": "低风险", "normal": "正常"}
    if level == "normal":
        return f"无{prefix}风险"
    if level == "critical":
        return "严重断货风险" if prefix == "断货" else f"{prefix}严重风险"
    return f"{prefix}{labels.get(level, level)}"


def _is_active_level(level: str | None) -> bool:
    return level in {"critical", "high", "medium", "low"}


def _item_has_anomaly_risk(item: ControlTowerItem) -> bool:
    return item.risk_type == "anomaly" or bool(item.evidence.get("risk_flags"))


def _item_is_real_risk(item: ControlTowerItem) -> bool:
    return item.risk_level in {"critical", "high"}


def _item_has_active_risk(item: ControlTowerItem) -> bool:
    return (
        item.risk_type != "healthy"
        or _is_active_level(item.stockout_risk_level)
        or _is_active_level(item.overstock_risk_level)
        or _item_has_anomaly_risk(item)
    )


def _item_matches_risk_type(item: ControlTowerItem, risk_type: str) -> bool:
    if risk_type == "stockout":
        return _is_active_level(item.stockout_risk_level)
    if risk_type == "overstock":
        return _is_active_level(item.overstock_risk_level)
    if risk_type == "healthy":
        return (
            not _is_active_level(item.stockout_risk_level)
            and not _is_active_level(item.overstock_risk_level)
            and item.risk_type == "healthy"
        )
    return item.risk_type == risk_type


def _risk_sort_key(item: ControlTowerItem) -> tuple[int, int, float, float]:
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "normal": 4}
    type_rank = {"stockout": 0, "overstock": 1, "anomaly": 2, "healthy": 3}
    first_shortage_days = item.pici_first_shortage_days if item.pici_first_shortage_days is not None else 9999
    gap_magnitude = abs(item.pici_min_gap_quantity or 0)
    return (
        severity_rank.get(item.risk_level, 9),
        type_rank.get(item.risk_type, 9),
        first_shortage_days,
        -gap_magnitude,
    )


def _with_pici_shortage(
    rows: list[dict[str, Any]],
    connector: StiDatabaseConnector,
    filters: dict[str, Any] | None,
    data_source: str,
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    if not connector.config.ready:
        raise RuntimeError("数据获取失败：STI 数据库未启用，无法读取批次断货数据。")
    try:
        pici_rows = connector.get_pici_shortage_rows(store_name=_selected_store(filters), table_name=PICI_SALE_TABLE)
    except Exception as exc:
        raise RuntimeError("数据获取失败：批次断货 chazhi 数据获取失败。") from exc
    by_fnsku_store = {
        (_norm(row.get("fnsku")), _text(row.get("store_name"))): row
        for row in pici_rows
        if _norm(row.get("fnsku"))
    }
    enriched = []
    for row in rows:
        pici_row = by_fnsku_store.get((_norm(row.get("fnsku")), _text(row.get("store_name"))))
        if not pici_row:
            enriched.append(row)
            continue
        patch = {f"_chazhi_0_{horizon}": _text(pici_row.get(f"chazhi_0_{horizon}")) for horizon in PICI_HORIZONS}
        patch["_pici_inventory"] = _number(pici_row.get("fnsku_inventory_1"))
        enriched.append({**row, **patch})
    return enriched


def _pici_gap_summary(row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, str] = {}
    parsed: list[dict[str, Any]] = []
    for horizon in PICI_HORIZONS:
        key = f"0_{horizon}"
        value = _text(row.get(f"_chazhi_0_{horizon}"))
        if not value:
            continue
        values[key] = value
        parts = _parse_chazhi_parts(value)
        if parts:
            parsed.append({"horizon": horizon, "value": value, **parts})
    shortage = [item for item in parsed if item["gap"] < 0]
    first_shortage = min(shortage, key=lambda item: item["horizon"]) if shortage else None
    min_gap = min((item["gap"] for item in parsed), default=None)
    shortage_days_0_45 = _stockout_days_in_window(parsed, STOCKOUT_RISK_WINDOW_DAYS)
    future_replenishment_hint_days = (
        first_shortage["horizon"]
        if first_shortage and shortage_days_0_45 <= 0 and first_shortage["horizon"] > STOCKOUT_RISK_WINDOW_DAYS
        else None
    )
    key_gap = first_shortage["value"] if first_shortage else (parsed[-1]["value"] if parsed else "")
    return {
        "values": values,
        "first_shortage_days": first_shortage["horizon"] if first_shortage else None,
        "shortage_days_0_45": shortage_days_0_45,
        "future_replenishment_hint_days": future_replenishment_hint_days,
        "min_gap_quantity": round(min_gap, 2) if min_gap is not None else None,
        "key_gap": key_gap,
    }


def _stockout_days_in_window(parsed: list[dict[str, Any]], window_days: int) -> int:
    previous_horizon = 0
    previous_available = 0.0
    previous_forecast = 0.0
    available_pool = 0.0
    shortage_days = 0
    for entry in parsed:
        horizon = int(entry["horizon"])
        interval_days = max(horizon - previous_horizon, 0)
        if interval_days <= 0:
            previous_horizon = horizon
            previous_available = float(entry["available"])
            previous_forecast = float(entry["forecast"])
            continue
        interval_supply = max(float(entry["available"]) - previous_available, 0)
        interval_forecast = max(float(entry["forecast"]) - previous_forecast, 0)
        daily_forecast = interval_forecast / interval_days if interval_days else 0
        available_pool += interval_supply
        for day in range(previous_horizon + 1, min(horizon, window_days) + 1):
            demand = max(daily_forecast, 0)
            used = min(available_pool, demand)
            available_pool -= used
            if demand - used > 0.000001:
                shortage_days += 1
        previous_horizon = horizon
        previous_available = float(entry["available"])
        previous_forecast = float(entry["forecast"])
        if previous_horizon >= window_days:
            break
    return shortage_days


def _parse_chazhi_parts(value: str) -> dict[str, float] | None:
    text = _text(value).strip()
    if not text or "/" not in text:
        return None
    left, rest = text.split("/", 1)
    forecast_text = rest.split("(", 1)[0].strip()
    gap = _parse_chazhi_gap(text)
    available = _optional_number(left.strip())
    forecast = _optional_number(forecast_text)
    if available is None or forecast is None or gap is None:
        return None
    return {"available": available, "forecast": forecast, "gap": gap}


def _parse_chazhi_gap(value: str) -> float | None:
    text = _text(value).strip()
    if not text or "(" not in text or ")" not in text:
        return None
    tail = text.rsplit("(", 1)[-1].split(")", 1)[0]
    try:
        return float(tail)
    except ValueError:
        return None


def _build_map_nodes(items: list[ControlTowerItem]) -> list[ControlTowerMapNode]:
    grouped: dict[str, list[ControlTowerItem]] = {}
    for item in items:
        country = (item.country_code or item.shipments_country or "UNKNOWN").upper()
        grouped.setdefault(country, []).append(item)

    nodes = []
    for country, country_items in grouped.items():
        stockout_count = sum(1 for item in country_items if _is_active_level(item.stockout_risk_level))
        overstock_count = sum(1 for item in country_items if _is_active_level(item.overstock_risk_level))
        critical_count = sum(1 for item in country_items if item.risk_level == "critical")
        high_count = sum(1 for item in country_items if item.risk_level == "high")
        risk_score = max((item.risk_score for item in country_items), default=0)
        nodes.append(
            ControlTowerMapNode(
                country_code=country,
                country_name=_country_name(country),
                sku_count=len(country_items),
                total_inventory=round(sum(item.total_inventory for item in country_items), 2),
                stockout_count=stockout_count,
                overstock_count=overstock_count,
                critical_count=critical_count,
                high_count=high_count,
                risk_level=_risk_level_from_score(risk_score),
                risk_score=risk_score,
            )
        )
    return sorted(nodes, key=lambda node: (node.risk_score, node.stockout_count, node.total_inventory), reverse=True)


def _build_warehouse_inventory(
    connector: StiDatabaseConnector,
    country_code: str | None,
    data_source: str,
) -> list[ControlTowerWarehouseInventory]:
    if not connector.config.ready:
        raise RuntimeError("数据获取失败：STI 数据库未启用，无法读取仓库库存。")
    try:
        rows = connector.get_warehouse_inventory_rows(country_code=country_code, limit=80)
    except Exception as exc:
        raise RuntimeError("数据获取失败：仓库库存数据获取失败。") from exc
    return [
        ControlTowerWarehouseInventory(
            country_code=_text(row.get("country_code")).upper(),
            country_name=_country_name(_text(row.get("country_code"))),
            warehouse_code=_text(row.get("warehouse_code")),
            warehouse_name=_text(row.get("warehouse_name")),
            display_name=_text(row.get("warehouse_display_name")),
            sku_count=int(_number(row.get("sku_count"))),
            product_total=round(_number(row.get("product_total")), 2),
            product_valid_num=round(_number(row.get("product_valid_num")), 2),
            product_lock_num=round(_number(row.get("product_lock_num")), 2),
            product_onway=round(_number(row.get("product_onway")), 2),
        )
        for row in rows
    ]


def _matching_sales_rows(rows: list[dict[str, Any]], codes: list[str]) -> list[dict[str, Any]]:
    code_set = {_norm(code) for code in codes if _norm(code)}
    if not code_set:
        return []
    matched = []
    for row in rows:
        row_codes = {
            _norm(row.get("sku")),
            _norm(row.get("seller_sku")),
            _norm(row.get("fnsku")),
            _norm(row.get("asin")),
        }
        if code_set.intersection(row_codes):
            matched.append(row)
    return matched


def _monthly_forecast_versions(
    connector: StiDatabaseConnector,
    material_codes: list[str],
    as_of_date: str | date | None,
    review_start: date,
    review_end: date,
    store_name: str | None,
    country_code: str | None,
    primary_month_offset: int,
    aligned_to_version_window: bool = False,
) -> tuple[list[MonthlyForecastReviewForecastVersion], dict[int, list[dict[str, Any]]]]:
    versions: list[MonthlyForecastReviewForecastVersion] = []
    rows_by_offset: dict[int, list[dict[str, Any]]] = {}
    for offset in _forecast_version_offsets(primary_month_offset):
        version_start, version_end = _target_month_window(as_of_date=as_of_date, month_offset=offset)
        range_start = version_start if aligned_to_version_window else review_start
        range_end = version_start + timedelta(days=FORECAST_DETAIL_HORIZON_DAYS) if aligned_to_version_window else review_end
        target_month = version_start.strftime("%Y-%m")
        if hasattr(connector, "get_weekly_sales_estimate_rows"):
            rows = connector.get_weekly_sales_estimate_rows(
                material_codes=material_codes,
                version_start_date=version_start.isoformat(),
                version_end_date=version_end.isoformat(),
                target_start_date=range_start.isoformat(),
                target_end_date=range_end.isoformat(),
                store_name=store_name,
                country_code=country_code,
            )
        else:
            rows = connector.get_monthly_sales_estimate_rows(
                material_codes=material_codes,
                target_month=target_month,
                target_start_date=range_start.isoformat(),
                target_end_date=range_end.isoformat(),
                store_name=store_name,
                country_code=country_code,
            )
        display_rows = _trim_forecast_boundary_rows(rows, trim_first=offset == max(FORECAST_VERSION_OFFSETS)) if aligned_to_version_window else rows
        rows_by_offset[offset] = display_rows
        forecast_quantity = _forecast_rows_quantity(display_rows, range_start, range_end)
        versions.append(
            MonthlyForecastReviewForecastVersion(
                month_offset=offset,
                target_month=target_month,
                target_start_date=(range_start if aligned_to_version_window else version_start).isoformat(),
                target_end_date=(range_end if aligned_to_version_window else version_end).isoformat(),
                label=_forecast_version_label(offset),
                forecast_quantity=round(forecast_quantity, 2),
                forecast_row_count=len(display_rows),
                weekly_estimates=_weekly_forecast_points(display_rows, range_start, range_end),
            )
        )
    return versions, rows_by_offset


def _forecast_version_offsets(primary_month_offset: int) -> tuple[int, ...]:
    offsets: list[int] = []
    for offset in (*FORECAST_VERSION_OFFSETS, primary_month_offset):
        bounded = _bounded_int(offset, default=2, minimum=0, maximum=24)
        if bounded not in offsets:
            offsets.append(bounded)
    return tuple(offsets)


def _forecast_version_label(month_offset: int) -> str:
    if month_offset == 0:
        return "当前月的预估线"
    return f"{month_offset}个月之前的预估线"


def _detail_forecast_start(as_of_date: str | date | None = None) -> date:
    return _target_month_window(as_of_date=as_of_date, month_offset=max(FORECAST_VERSION_OFFSETS))[0]


def _detail_forecast_end(as_of_date: str | date | None = None) -> date:
    current_start = _target_month_window(as_of_date=as_of_date, month_offset=0)[0]
    return current_start + timedelta(days=FORECAST_DETAIL_HORIZON_DAYS)


def _forecast_row_date(row: dict[str, Any]) -> date | None:
    return _as_date(row.get("start_date")) or _as_date(row.get("date"))


def _forecast_row_end_date(row: dict[str, Any]) -> date | None:
    return _as_date(row.get("end_date")) or _forecast_row_date(row)


def _forecast_row_quantity(row: dict[str, Any]) -> float:
    if "forecast_quantity" in row:
        return _number(row.get("forecast_quantity"))
    if "value" in row:
        return _number(row.get("value"))
    return _number(row.get("daily_sales_quantity"))


def _trim_forecast_boundary_rows(estimate_rows: list[dict[str, Any]], trim_first: bool = True) -> list[dict[str, Any]]:
    rows = sorted(
        estimate_rows,
        key=lambda row: (
            _forecast_row_date(row) or date.max,
            _forecast_row_end_date(row) or date.max,
        ),
    )
    trim_count = int(trim_first) + 1
    if len(rows) <= trim_count:
        return []
    return rows[1:-1] if trim_first else rows[:-1]


def _forecast_row_total_quantity(row: dict[str, Any], review_start: date, review_end: date) -> float:
    row_start = _forecast_row_date(row)
    row_end = _forecast_row_end_date(row)
    if not row_start or not row_end or row_start > review_end or row_end < review_start:
        return 0.0
    display_start = max(row_start, review_start)
    display_end = min(row_end, review_end)
    day_count = max((display_end - display_start).days + 1, 0)
    return _forecast_row_quantity(row) * day_count


def _forecast_rows_quantity(estimate_rows: list[dict[str, Any]], review_start: date, review_end: date) -> float:
    return round(sum(_forecast_row_total_quantity(row, review_start, review_end) for row in estimate_rows), 2)


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _next_month_start(value: date) -> date:
    return date(value.year + 1, 1, 1) if value.month == 12 else date(value.year, value.month + 1, 1)


def _previous_month_start(value: date) -> date:
    return date(value.year - 1, 12, 1) if value.month == 1 else date(value.year, value.month - 1, 1)


def _month_end(value: date) -> date:
    return _next_month_start(value) - timedelta(days=1)


def _add_forecast_row_to_months(grouped: dict[str, dict[str, Any]], row: dict[str, Any]) -> None:
    row_start = _forecast_row_date(row)
    row_end = _forecast_row_end_date(row)
    if not row_start or not row_end:
        return
    cursor = row_start
    daily_quantity = _forecast_row_quantity(row)
    while cursor <= row_end:
        next_month = _next_month_start(cursor)
        display_end = min(row_end, next_month - timedelta(days=1))
        day_count = max((display_end - cursor).days + 1, 0)
        month_key = cursor.strftime("%Y-%m")
        bucket = grouped.setdefault(month_key, {"forecast_quantity": 0.0, "forecast_row_count": 0})
        bucket["forecast_quantity"] += daily_quantity * day_count
        bucket["forecast_row_count"] = int(bucket.get("forecast_row_count", 0)) + 1
        cursor = display_end + timedelta(days=1)


def _detail_monthly_totals(
    forecast_rows_by_offset: dict[int, list[dict[str, Any]]],
    actual_rows: list[dict[str, Any]],
    detail_start: date,
    detail_end: date,
    actual_end: date,
    as_of_date: str | date | None = None,
) -> list[MonthlyForecastReviewMonthlyTotal]:
    forecast_candidates: dict[str, dict[int, dict[str, Any]]] = {}
    version_month_by_offset: dict[int, str] = {}
    for offset, rows in forecast_rows_by_offset.items():
        version_month_by_offset[offset] = _target_month_window(as_of_date=as_of_date, month_offset=offset)[0].strftime("%Y-%m")
        monthly_rows: dict[str, dict[str, Any]] = {}
        for row in rows:
            _add_forecast_row_to_months(monthly_rows, row)
        for month_key, values in monthly_rows.items():
            forecast_candidates.setdefault(month_key, {})[offset] = values

    actual_start = _next_week_start(detail_start)
    actual_buckets: dict[str, dict[str, Any]] = {}
    for row in actual_rows:
        row_date = _as_date(row.get("date"))
        if not row_date or row_date < actual_start or row_date > actual_end:
            continue
        month_key = row_date.strftime("%Y-%m")
        bucket = actual_buckets.setdefault(month_key, {"actual_sales": 0.0, "actual_row_count": 0})
        bucket["actual_sales"] += _number(row.get("daily_sales_volume"))
        bucket["actual_row_count"] = int(bucket.get("actual_row_count", 0)) + 1

    months: set[str] = set(actual_buckets.keys())
    month_cursor = _month_start(detail_start)
    final_month = _month_start(detail_end)
    while month_cursor <= final_month:
        month_key = month_cursor.strftime("%Y-%m")
        if month_key in forecast_candidates or month_key in actual_buckets:
            months.add(month_key)
        month_cursor = _next_month_start(month_cursor)

    totals: list[MonthlyForecastReviewMonthlyTotal] = []
    current_month_key = _month_start(actual_end).strftime("%Y-%m")
    for month_key in sorted(months):
        offset_candidates = forecast_candidates.get(month_key, {})
        month_start_date = date.fromisoformat(f"{month_key}-01")
        comparison_month = _previous_month_start(_previous_month_start(month_start_date)).strftime("%Y-%m")
        eligible_offsets = [
            offset
            for offset in offset_candidates
            if version_month_by_offset.get(offset, "") and version_month_by_offset[offset] <= comparison_month
        ]
        selected_offset = max(eligible_offsets, key=lambda offset: version_month_by_offset[offset]) if eligible_offsets else None
        if selected_offset is None and offset_candidates:
            selected_offset = min(offset_candidates, key=lambda offset: version_month_by_offset.get(offset, "9999-99"))
        forecast_values = offset_candidates.get(selected_offset, {}) if selected_offset is not None else {}
        forecast_month = version_month_by_offset.get(selected_offset, "") if selected_offset is not None else ""
        actual_values = actual_buckets.get(month_key, {})
        month_end_date = _month_end(month_start_date)
        month_day_count = max((month_end_date - month_start_date).days + 1, 0)
        actual_sales = round(_number(actual_values.get("actual_sales")), 2)
        actual_covered_days = 0
        actual_sales_projected = actual_sales
        actual_sales_virtual = 0.0
        if month_start_date <= actual_end:
            actual_covered_days = month_day_count if month_end_date <= actual_end else min(actual_end.day, month_day_count)
        if month_start_date <= actual_end < month_end_date and actual_covered_days > 0:
            actual_sales_projected = round(actual_sales / actual_covered_days * month_day_count, 2)
            actual_sales_virtual = round(max(actual_sales_projected - actual_sales, 0.0), 2)
        forecast_quantity = round(_number(forecast_values.get("forecast_quantity")), 2)
        forecast_version_totals = [
            {
                "forecast_month_offset": offset,
                "forecast_month": version_month_by_offset.get(offset, ""),
                "forecast_label": _forecast_version_label(offset),
                "forecast_quantity": round(_number(values.get("forecast_quantity")), 2),
                "forecast_row_count": int(_number(values.get("forecast_row_count"))),
            }
            for offset, values in sorted(
                offset_candidates.items(),
                key=lambda pair: version_month_by_offset.get(pair[0], ""),
            )
            if _number(values.get("forecast_quantity")) > 0
        ]
        selected_variance_percent = _forecast_variance_percent(
            forecast_quantity,
            actual_sales_projected,
            actual_covered_days,
        )
        sales_gap = _monthly_sales_gap(selected_variance_percent)
        forecast_checks = (
            _monthly_forecast_variance_checks(
                month_key=month_key,
                offset_candidates=offset_candidates,
                version_month_by_offset=version_month_by_offset,
            )
            if month_key == current_month_key
            else []
        )
        forecast_anomaly_reasons = [
            str(check["reason"])
            for check in forecast_checks
            if check.get("is_anomaly")
        ]
        totals.append(
            MonthlyForecastReviewMonthlyTotal(
                month=month_key,
                forecast_quantity=forecast_quantity,
                actual_sales=actual_sales,
                actual_sales_projected=actual_sales_projected,
                actual_sales_virtual=actual_sales_virtual,
                actual_covered_days=actual_covered_days,
                month_day_count=month_day_count,
                forecast_month=forecast_month,
                forecast_month_offset=selected_offset,
                forecast_label=_forecast_version_label(selected_offset) if selected_offset is not None else "",
                forecast_row_count=int(_number(forecast_values.get("forecast_row_count"))),
                forecast_version_totals=forecast_version_totals,
                actual_row_count=int(_number(actual_values.get("actual_row_count"))),
                selected_variance_percent=selected_variance_percent,
                sales_gap_direction=sales_gap["direction"],
                sales_gap_label=sales_gap["label"],
                sales_gap_reason=sales_gap["reason"],
                forecast_variance_checks=forecast_checks,
                forecast_anomaly=bool(forecast_anomaly_reasons),
                forecast_anomaly_reasons=forecast_anomaly_reasons,
            )
        )
    return totals


def _forecast_variance_percent(forecast_quantity: float, actual_reference: float, actual_covered_days: int) -> float | None:
    if actual_covered_days <= 0 or forecast_quantity <= 0:
        return None
    return round((actual_reference - forecast_quantity) / forecast_quantity * 100, 2)


def _monthly_sales_gap(variance_percent: float | None) -> dict[str, str]:
    if variance_percent is None:
        return {
            "direction": "unknown",
            "label": "缺少可比月度销量",
            "reason": "缺少图表同口径的预估或实际销量，无法判断月度超卖/低卖。",
        }
    if variance_percent > 10:
        return {
            "direction": "actual_over_forecast",
            "label": "可能超卖",
            "reason": f"图表同口径实际销量高于预估 {variance_percent:g}%，超过10%。",
        }
    if variance_percent < -10:
        return {
            "direction": "forecast_over_actual",
            "label": "预估高于实际",
            "reason": f"图表同口径实际销量低于预估 {abs(variance_percent):g}%，超过10%。",
        }
    return {
        "direction": "within_10_percent",
        "label": "计划异常观察",
        "reason": f"图表同口径实际与预估偏差 {variance_percent:g}%，未超过10%。",
    }


def _monthly_forecast_variance_checks(
    *,
    month_key: str,
    offset_candidates: dict[int, dict[str, Any]],
    version_month_by_offset: dict[int, str],
) -> list[dict[str, Any]]:
    version_rows: list[dict[str, Any]] = []
    for offset in (2, 1, 0):
        values = offset_candidates.get(offset)
        if not values:
            continue
        forecast_quantity = round(_number(values.get("forecast_quantity")), 2)
        version_month = version_month_by_offset.get(offset, "")
        label = _forecast_version_label(offset)
        version_rows.append(
            {
                "month": month_key,
                "forecast_month_offset": offset,
                "forecast_month": version_month,
                "forecast_label": label,
                "forecast_quantity": forecast_quantity,
            }
        )
    checks: list[dict[str, Any]] = []
    first_row = version_rows[0] if version_rows else None
    previous_row: dict[str, Any] | None = None
    for row in version_rows:
        comparison_parts: list[str] = []
        anomaly_flags: list[bool] = []
        if previous_row is not None:
            comparison = _forecast_quantity_comparison(row, previous_row)
            row.update({f"previous_{key}": value for key, value in comparison.items()})
            if comparison.get("variance_percent") is not None:
                anomaly_flags.append(bool(comparison.get("is_anomaly")))
                comparison_parts.append(
                    f"较{comparison['base_forecast_label']} {comparison['base_forecast_quantity']:g} "
                    f"差异 {comparison['difference_quantity']:g}，差异率 {comparison['variance_percent']:g}%"
                )
        if first_row is not None and previous_row is not None and row is not first_row and first_row is not previous_row:
            first_comparison = _forecast_quantity_comparison(row, first_row)
            row.update({f"first_{key}": value for key, value in first_comparison.items()})
            if first_comparison.get("variance_percent") is not None:
                anomaly_flags.append(bool(first_comparison.get("is_anomaly")))
                comparison_parts.append(
                    f"较{first_comparison['base_forecast_label']} {first_comparison['base_forecast_quantity']:g} "
                    f"差异 {first_comparison['difference_quantity']:g}，差异率 {first_comparison['variance_percent']:g}%"
                )
        is_anomaly = any(anomaly_flags)
        status_text = "命中预估异常" if is_anomaly else "未命中预估异常"
        reason = f"{row['forecast_label']}({row['forecast_month']})对{month_key}预估 {row['forecast_quantity']:g}"
        if comparison_parts:
            reason += "，" + "；".join(comparison_parts)
        row["is_anomaly"] = is_anomaly
        row["threshold_percent"] = 30
        row["comparison_basis"] = "forecast_version_quantity"
        row["reason"] = f"{reason}，{status_text}。"
        checks.append(row)
        previous_row = row
    return checks


def _forecast_quantity_comparison(current: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    current_quantity = _number(current.get("forecast_quantity"))
    base_quantity = _number(base.get("forecast_quantity"))
    difference_quantity = round(current_quantity - base_quantity, 2)
    variance_percent = round(difference_quantity / base_quantity * 100, 2) if base_quantity else None
    is_anomaly = abs(variance_percent) >= 30 if variance_percent is not None else False
    return {
        "base_forecast_month_offset": base.get("forecast_month_offset"),
        "base_forecast_month": base.get("forecast_month"),
        "base_forecast_label": base.get("forecast_label"),
        "base_forecast_quantity": round(base_quantity, 2),
        "difference_quantity": difference_quantity,
        "variance_percent": variance_percent,
        "is_anomaly": is_anomaly,
    }


def _forecast_anomalies_from_monthly_totals(totals: list[MonthlyForecastReviewMonthlyTotal]) -> list[dict[str, Any]]:
    checked_totals = [total for total in totals if total.forecast_variance_checks]
    if not checked_totals:
        return []
    latest_month = max(total.month for total in checked_totals)
    anomalies = []
    for total in totals:
        if total.month != latest_month or not total.forecast_anomaly:
            continue
        anomalies.append(
            {
                "type": "forecast_anomaly",
                "month": total.month,
                "label": "预估异常",
                "reasons": list(total.forecast_anomaly_reasons),
                "anomaly_reasons": list(total.forecast_anomaly_reasons),
                "checks": list(total.forecast_variance_checks),
            }
        )
    return anomalies


def _weekly_forecast_points(
    estimate_rows: list[dict[str, Any]],
    review_start: date,
    review_end: date,
) -> list[MonthlyForecastReviewForecastPoint]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in estimate_rows:
        row_start = _forecast_row_date(row)
        row_end = _forecast_row_end_date(row)
        if not row_start or not row_end or row_start > review_end or row_end < review_start:
            continue
        display_start = max(row_start, review_start)
        display_end = min(row_end, review_end)
        iso_year, iso_week, _ = display_start.isocalendar()
        week = f"{iso_year}W{iso_week:02d}"
        key = f"{display_start.isoformat()}|{display_end.isoformat()}"
        bucket = grouped.setdefault(
            key,
            {
                "week": week,
                "week_start": display_start,
                "display_start": display_start,
                "display_end": display_end,
                "forecast_quantity": 0.0,
                "forecast_row_count": 0,
            },
        )
        bucket["forecast_quantity"] += _forecast_row_total_quantity(row, review_start, review_end)
        bucket["forecast_row_count"] = int(bucket.get("forecast_row_count", 0)) + 1

    points: list[MonthlyForecastReviewForecastPoint] = []
    for values in sorted(grouped.values(), key=lambda item: item["week_start"]):
        points.append(
            MonthlyForecastReviewForecastPoint(
                week=values["week"],
                week_start_date=values["display_start"].isoformat(),
                week_end_date=values["display_end"].isoformat(),
                forecast_quantity=round(values["forecast_quantity"], 2),
                row_count=int(values.get("forecast_row_count", 0)),
            )
        )
    return points


def _weekly_actual_points(
    actual_rows: list[dict[str, Any]],
    review_start: date,
    review_end: date,
) -> list[MonthlyForecastReviewActualPoint]:
    grouped: dict[str, dict[str, Any]] = {}
    week_cursor = _week_start(review_start)
    while week_cursor <= review_end:
        bucket = _weekly_bucket(grouped, week_cursor, review_start, review_end)
        bucket.setdefault("actual_row_count", 0)
        week_cursor += timedelta(days=7)

    for row in actual_rows:
        row_date = _as_date(row.get("date"))
        if not row_date:
            continue
        bucket = _weekly_bucket(grouped, row_date, review_start, review_end)
        bucket["actual_sales"] += _number(row.get("daily_sales_volume"))
        bucket["actual_row_count"] = int(bucket.get("actual_row_count", 0)) + 1

    points: list[MonthlyForecastReviewActualPoint] = []
    for values in sorted(grouped.values(), key=lambda item: item["week_start"]):
        points.append(
            MonthlyForecastReviewActualPoint(
                week=values["week"],
                week_start_date=values["display_start"].isoformat(),
                week_end_date=values["display_end"].isoformat(),
                actual_sales=round(values["actual_sales"], 2),
                row_count=int(values.get("actual_row_count", 0)),
            )
        )
    return points


def _trim_first_actual_point(points: list[MonthlyForecastReviewActualPoint]) -> list[MonthlyForecastReviewActualPoint]:
    if len(points) <= 1:
        return []
    return points[1:]


def _weekly_estimates(
    estimate_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    review_start: date,
    review_end: date,
) -> list[MonthlyForecastReviewWeeklyEstimate]:
    grouped: dict[str, dict[str, Any]] = {}
    week_cursor = _week_start(review_start)
    while week_cursor <= review_end:
        _weekly_bucket(grouped, week_cursor, review_start, review_end)
        week_cursor += timedelta(days=7)

    for row in estimate_rows:
        row_date = _forecast_row_date(row)
        if not row_date:
            continue
        bucket = _weekly_bucket(grouped, row_date, review_start, review_end)
        bucket["forecast_quantity"] += _forecast_row_total_quantity(row, review_start, review_end)

    for row in actual_rows:
        row_date = _as_date(row.get("date"))
        if not row_date:
            continue
        bucket = _weekly_bucket(grouped, row_date, review_start, review_end)
        bucket["actual_sales"] += _number(row.get("daily_sales_volume"))
        bucket["ad_spend"] += _number(row.get("ad_spend"))
        bucket["ad_sales_amount"] += _number(row.get("ad_sales_amount"))
        bucket["ad_order_quantity"] += _number(row.get("ad_order_quantity"))

    estimates: list[MonthlyForecastReviewWeeklyEstimate] = []
    for values in sorted(grouped.values(), key=lambda item: item["week_start"]):
        forecast_quantity = values["forecast_quantity"]
        actual_sales = values["actual_sales"]
        ad_spend = values["ad_spend"]
        ad_sales_amount = values["ad_sales_amount"]
        ad_order_quantity = values["ad_order_quantity"]
        organic_sales = actual_sales - ad_order_quantity
        ad_acos = ad_spend / ad_sales_amount if ad_sales_amount else None
        difference = actual_sales - forecast_quantity
        variance_ratio = difference / forecast_quantity if forecast_quantity else None
        estimates.append(
            MonthlyForecastReviewWeeklyEstimate(
                week=values["week"],
                week_start_date=values["display_start"].isoformat(),
                week_end_date=values["display_end"].isoformat(),
                forecast_quantity=round(forecast_quantity, 2),
                actual_sales=round(actual_sales, 2),
                ad_spend=round(ad_spend, 2),
                ad_sales_amount=round(ad_sales_amount, 2),
                ad_order_quantity=round(ad_order_quantity, 2),
                organic_sales=round(organic_sales, 2),
                ad_acos=round(ad_acos, 4) if ad_acos is not None else None,
                difference=round(difference, 2),
                variance_ratio=round(variance_ratio, 4) if variance_ratio is not None else None,
                variance_percent=round(variance_ratio * 100, 2) if variance_ratio is not None else None,
                day_count=max((values["display_end"] - values["display_start"]).days + 1, 0),
            )
        )
    return estimates


def _weekly_sales_anomalies(weekly_estimates: list[MonthlyForecastReviewWeeklyEstimate]) -> list[dict[str, Any]]:
    anomalies: list[dict[str, Any]] = []
    deviations = [
        {
            "week": item.week,
            "week_start_date": item.week_start_date,
            "week_end_date": item.week_end_date,
            "period_label": _date_range_label(item.week_start_date, item.week_end_date),
            "forecast_quantity": item.forecast_quantity,
            "actual_sales": item.actual_sales,
            "variance_percent": item.variance_percent,
        }
        for item in weekly_estimates
        if item.variance_percent is not None and abs(item.variance_percent) >= 20
    ]
    for run in _consecutive_week_runs(deviations):
        if len(run) < 2:
            continue
        anomalies.append(
            {
                "type": "sales_volatility_anomaly",
                "label": "销量波动异常",
                "threshold_percent": 20,
                "weeks": run,
                "periods": run,
                "reason": (
                    f"{_date_range_label(run[0]['week_start_date'], run[-1]['week_end_date'])} "
                    f"连续 {len(run)} 个区间实际销量偏离预估±20%以上。"
                ),
            }
        )

    actual_points = [
        {
            "week": item.week,
            "week_start_date": item.week_start_date,
            "week_end_date": item.week_end_date,
            "period_label": _date_range_label(item.week_start_date, item.week_end_date),
            "actual_sales": item.actual_sales,
        }
        for item in weekly_estimates
        if item.actual_sales > 0
    ]
    if len(actual_points) >= 3:
        if all(actual_points[index]["actual_sales"] > actual_points[index - 1]["actual_sales"] for index in range(1, len(actual_points))):
            anomalies.append(
                {
                    "type": "sales_continuous_increase",
                    "label": "销量持续增加",
                    "weeks": actual_points,
                    "periods": actual_points,
                    "reason": f"{_date_range_label(actual_points[0]['week_start_date'], actual_points[-1]['week_end_date'])} 销量连续上升。",
                }
            )
        elif all(actual_points[index]["actual_sales"] < actual_points[index - 1]["actual_sales"] for index in range(1, len(actual_points))):
            anomalies.append(
                {
                    "type": "sales_continuous_decrease",
                    "label": "销量持续降低",
                    "weeks": actual_points,
                    "periods": actual_points,
                    "reason": f"{_date_range_label(actual_points[0]['week_start_date'], actual_points[-1]['week_end_date'])} 销量连续下降。",
                }
            )

    for previous, current in zip(actual_points, actual_points[1:]):
        previous_sales = previous["actual_sales"]
        current_sales = current["actual_sales"]
        if previous_sales <= 0:
            continue
        change_percent = round((current_sales - previous_sales) / previous_sales * 100, 2)
        if change_percent >= 50:
            anomalies.append(
                {
                    "type": "sales_spike",
                    "label": "销量陡增",
                    "from_week": previous,
                    "to_week": current,
                    "from_period": previous,
                    "to_period": current,
                    "change_percent": change_percent,
                    "threshold_percent": 50,
                    "reason": (
                        f"{_date_range_label(previous['week_start_date'], previous['week_end_date'])} 至 "
                        f"{_date_range_label(current['week_start_date'], current['week_end_date'])} 销量陡增 {change_percent:g}%。"
                    ),
                }
            )
        elif change_percent <= -50:
            anomalies.append(
                {
                    "type": "sales_drop",
                    "label": "销量骤降",
                    "from_week": previous,
                    "to_week": current,
                    "from_period": previous,
                    "to_period": current,
                    "change_percent": change_percent,
                    "threshold_percent": 50,
                    "reason": (
                        f"{_date_range_label(previous['week_start_date'], previous['week_end_date'])} 至 "
                        f"{_date_range_label(current['week_start_date'], current['week_end_date'])} 销量骤降 {abs(change_percent):g}%。"
                    ),
                }
            )
    return anomalies


def _date_range_label(start_value: Any, end_value: Any) -> str:
    start = _as_date(start_value)
    end = _as_date(end_value)
    if not start and not end:
        return ""
    if not start:
        return _date_label(end)
    if not end or start == end:
        return _date_label(start)
    return f"{_date_label(start)}到{_date_label(end)}"


def _date_label(value: date | None) -> str:
    if value is None:
        return ""
    return f"{value.month}月{value.day}日"


def _consecutive_week_runs(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    runs: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    previous_start: date | None = None
    for item in items:
        start = _as_date(item.get("week_start_date"))
        if current and previous_start and start and (start - previous_start).days == 7:
            current.append(item)
        else:
            if current:
                runs.append(current)
            current = [item]
        previous_start = start
    if current:
        runs.append(current)
    return runs


def _daily_price_points(price_rows: list[dict[str, Any]]) -> list[MonthlyForecastReviewDailyPricePoint]:
    points: list[MonthlyForecastReviewDailyPricePoint] = []
    for row in price_rows:
        row_date = _as_date(row.get("date"))
        if not row_date:
            continue
        points.append(
            MonthlyForecastReviewDailyPricePoint(
                date=row_date.isoformat(),
                price=_optional_number(row.get("price")),
                listing_price=_optional_number(row.get("listing_price")),
                landed_price=_optional_number(row.get("landed_price")),
                currency_code=_text(row.get("currency_code")),
                source_row_count=int(_number(row.get("source_row_count"))),
            )
        )
    return points


def _daily_sales_price_points(actual_rows: list[dict[str, Any]]) -> list[MonthlyForecastReviewDailyPricePoint]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in actual_rows:
        row_date = _as_date(row.get("date"))
        if not row_date:
            continue
        key = row_date.isoformat()
        bucket = grouped.setdefault(
            key,
            {
                "sales_amount": 0.0,
                "sales_volume": 0.0,
                "plan_total": 0.0,
                "plan_count": 0,
                "currency_code": _text(row.get("currency_code")),
                "source_row_count": 0,
            },
        )
        bucket["sales_amount"] += _number(row.get("daily_sales_amount"))
        bucket["sales_volume"] += _number(row.get("daily_sales_volume"))
        plan_price = _optional_number(row.get("selling_price_plan"))
        if plan_price is not None:
            bucket["plan_total"] += plan_price
            bucket["plan_count"] += 1
        if not bucket["currency_code"]:
            bucket["currency_code"] = _text(row.get("currency_code"))
        bucket["source_row_count"] += 1

    points: list[MonthlyForecastReviewDailyPricePoint] = []
    for row_date, values in sorted(grouped.items()):
        sales_volume = values["sales_volume"]
        plan_price = values["plan_total"] / values["plan_count"] if values["plan_count"] else None
        price = values["sales_amount"] / sales_volume if sales_volume else plan_price
        if price is None:
            continue
        points.append(
            MonthlyForecastReviewDailyPricePoint(
                date=row_date,
                price=round(price, 2),
                listing_price=round(plan_price, 2) if plan_price is not None else None,
                landed_price=None,
                currency_code=values["currency_code"],
                source_row_count=int(values["source_row_count"]),
            )
        )
    return points


def _weekly_bucket(
    grouped: dict[str, dict[str, Any]],
    row_date: date,
    review_start: date,
    review_end: date,
) -> dict[str, Any]:
    week_start = row_date - timedelta(days=row_date.weekday())
    week_end = week_start + timedelta(days=6)
    iso_year, iso_week, _ = row_date.isocalendar()
    week = f"{iso_year}W{iso_week:02d}"
    display_start = max(week_start, review_start)
    display_end = min(week_end, review_end)
    return grouped.setdefault(
        week,
        {
            "week": week,
            "week_start": week_start,
            "display_start": display_start,
            "display_end": display_end,
            "forecast_quantity": 0.0,
            "actual_sales": 0.0,
            "ad_spend": 0.0,
            "ad_sales_amount": 0.0,
            "ad_order_quantity": 0.0,
        },
    )


def _month_range_label(start: date, end: date) -> str:
    start_label = start.strftime("%Y-%m")
    end_label = end.strftime("%Y-%m")
    if start_label == end_label:
        return start_label
    return f"{start_label} 至 {end_label}"


def _forecast_review_result(difference: float, forecast_quantity: float, actual_sales: float) -> tuple[str, str]:
    if not forecast_quantity and not actual_sales:
        return "no_sales", "无预测且无销量"
    if difference > 0:
        return "over_sold", "超额"
    if difference < 0:
        return "under_sold", "低卖"
    return "matched", "持平"


def _target_month_window(as_of_date: str | date | None = None, month_offset: int = 2) -> tuple[date, date]:
    offset = _bounded_int(month_offset, default=2, minimum=0, maximum=24)
    as_of = _as_date(as_of_date) or date.today()
    month_index = as_of.year * 12 + (as_of.month - 1) - offset
    return _month_window(month_index)


def _week_start(value: date) -> date:
    return value - timedelta(days=value.weekday())


def _next_week_start(value: date) -> date:
    return _week_start(value) + timedelta(days=7)


def _next_month_window(value: date) -> tuple[date, date]:
    month_index = value.year * 12 + value.month
    return _month_window(month_index)


def _month_window(month_index: int) -> tuple[date, date]:
    year = month_index // 12
    month = month_index % 12 + 1
    start = date(year, month, 1)
    next_month_index = month_index + 1
    next_month = date(next_month_index // 12, next_month_index % 12 + 1, 1)
    return start, next_month - timedelta(days=1)


def _as_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _selected_country(filters: dict[str, Any] | None) -> str | None:
    if not filters:
        return None
    value = filters.get("country_code") or filters.get("shipments_country")
    value = _single_filter_value(value)
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _selected_store(filters: dict[str, Any] | None) -> str | None:
    if not filters:
        return None
    value = filters.get("store_name")
    value = _single_filter_value(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _selected_risk_types(filters: dict[str, Any] | None) -> set[str]:
    if not filters:
        return set()
    values = _filter_values(filters.get("risk_type"))
    aliases = {
        "stockout": "stockout",
        "断货": "stockout",
        "断货预警": "stockout",
        "overstock": "overstock",
        "冗余": "overstock",
        "冗余库存": "overstock",
        "anomaly": "anomaly",
        "异常": "anomaly",
        "healthy": "healthy",
        "正常": "healthy",
    }
    return {aliases[value] for value in values if value in aliases}


def _single_filter_value(value: Any) -> Any | None:
    values = _filter_values(value)
    if len(values) != 1:
        return None
    return values[0]


def _filter_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = [value]
    return [text for text in (_text(item).strip() for item in raw_values) if text]


def _sales_stat_date(value: str | date | None) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if text:
        try:
            return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
        except ValueError:
            pass
    return (date.today() - timedelta(days=1)).isoformat()


def _sales_period(
    sales_date: str | date | None = None,
    sales_start_date: str | date | None = None,
    sales_end_date: str | date | None = None,
) -> dict[str, Any]:
    start = _sales_stat_date(sales_start_date or sales_date)
    end = _sales_stat_date(sales_end_date or sales_start_date or sales_date)
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    if start_date > end_date:
        raise ValueError("sales_start_date cannot be later than sales_end_date.")
    day_count = (end_date - start_date).days + 1
    label = start if start == end else f"{start} 至 {end}"
    return {"start": start, "end": end, "day_count": day_count, "label": label}


def _risk_level_from_score(score: int) -> str:
    if score >= 100:
        return "critical"
    if score >= 80:
        return "high"
    if score >= 60:
        return "medium"
    if score >= 30:
        return "low"
    return "normal"


def _country_name(country_code: str) -> str:
    names = {
        "US": "United States",
        "CA": "Canada",
        "MX": "Mexico",
        "BR": "Brazil",
        "UK": "United Kingdom",
        "GB": "United Kingdom",
        "DE": "Germany",
        "FR": "France",
        "ES": "Spain",
        "IT": "Italy",
        "PL": "Poland",
        "CZ": "Czech Republic",
        "NL": "Netherlands",
        "AU": "Australia",
        "JP": "Japan",
        "IN": "India",
        "CN": "China",
    }
    return names.get(country_code.upper(), country_code.upper() or "Unknown")


def _lead_time_days(row: dict[str, Any]) -> float:
    logistics_time = max(
        _number(row.get("local_to_FBA_time")),
        _number(row.get("local_to_overseas_warehouse_time")),
        _number(row.get("overseas_to_FBA_time")),
    )
    lead_time = _number(row.get("order_duration")) + _number(row.get("production_duration")) + logistics_time
    return lead_time if lead_time > 0 else 7


def _risk_flags(row: dict[str, Any]) -> list[dict[str, str]]:
    flags = []
    for index in range(1, 7):
        field = f"fnsku_out_of_stock_risk_{index}"
        value = _text(row.get(field))
        normalized = value.strip().lower()
        if normalized in ANOMALY_RISK_MARKER_VALUES:
            display_value = value if value else "空"
            flags.append(
                {
                    "field": field,
                    "label": f"断货风险 {index}",
                    "value": display_value,
                    "reason": f"{field} 底表风险标记为 {display_value}",
                }
            )
    return flags


def _include(name: str, label: str, group: str, reason: str) -> ControlTowerFieldDecision:
    return ControlTowerFieldDecision(name=name, label=label, group=group, included=True, role="展示/计算/筛选", reason=reason)


def _exclude(name: str, label: str, group: str, reason: str) -> ControlTowerFieldDecision:
    return ControlTowerFieldDecision(name=name, label=label, group=group, included=False, role="暂不加入首屏", reason=reason)


def _number(value: Any) -> float:
    if value is None:
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _optional_ratio(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _norm(value: Any) -> str:
    return _text(value).strip().upper()


def _bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(number, maximum))
