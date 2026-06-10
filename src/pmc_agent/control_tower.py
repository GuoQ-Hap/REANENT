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
MONTHLY_SALES_ESTIMATE_TABLE = "dim_lingxing_sales_estimates_monthly_v1"
SAFE_RISK_VALUES = {"", "安全", "正常", "数据缺失", "none", "null", "safe"}
PICI_HORIZONS = (7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84, 98)


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
    sales_property: str
    seasonality: str
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
    evidence: dict[str, Any] = field(default_factory=dict)


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
    difference: float
    variance_ratio: float | None
    variance_percent: float | None
    day_count: int


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
    pagination: dict[str, int]
    map_nodes: list[ControlTowerMapNode]
    warehouse_inventory: list[ControlTowerWarehouseInventory]
    field_decisions: list[ControlTowerFieldDecision]
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
        raise LookupError("数据获取失败：控制塔主宽表未返回库存数据。")

    rows = _with_daily_sales(rows, connector, sales_period["start"], sales_period["end"], filters, data_source)
    rows = _with_pici_shortage(rows, connector, filters, data_source)
    all_items = [_build_item(row) for row in rows]
    risk_type_filter = _selected_risk_type(filters)
    if risk_type_filter:
        all_items = [item for item in all_items if _item_matches_risk_type(item, risk_type_filter)]
    all_items = sorted(all_items, key=_risk_sort_key)
    total_count = len(all_items)
    bounded_page_size = _bounded_int(page_size, default=100, minimum=20, maximum=500)
    total_pages = max(1, (total_count + bounded_page_size - 1) // bounded_page_size)
    bounded_page = min(_bounded_int(page, default=1, minimum=1, maximum=total_pages), total_pages)
    start = (bounded_page - 1) * bounded_page_size
    items = all_items[start : start + bounded_page_size]
    risk_distribution = dict(Counter(item.risk_level for item in all_items))
    risk_type_distribution = dict(Counter(item.risk_type for item in all_items))
    total_inventory = sum(item.total_inventory for item in all_items)
    total_demand_30d = sum(item.demand_30d for item in all_items)
    total_daily_sales = sum(item.daily_sales_volume for item in all_items)
    kpis = {
        "sku_count": total_count,
        "total_inventory": round(total_inventory, 2),
        "fba_sellable": round(sum(item.fba_sellable for item in all_items), 2),
        "inbound_total": round(sum(item.inbound_total for item in all_items), 2),
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
        notes=[
            f"{SOURCE_TABLE} 作为控制塔主宽表和月度基准快照使用。",
            f"{DAILY_SALES_TABLE} 按 {sales_period['label']} 的 volume 聚合为区间销量，可在前端选择单日或多日。",
            f"{PICI_SALE_TABLE} 的 chazhi 字段作为断货排查关键字段：库存量/预测销量（缺口数量）。",
            "断货等级按 chazhi 最早缺口窗口判断：0-42 天高风险，43-70 天中风险，70 天以后低风险；冗余库存另算。",
            "参考 SOP：冗余风险按可售天数 1-6 和 FBA 库龄判定，淘汰/待淘汰状态需拦截采购/发货。",
            "实时库存变动、采购在途和发货在途应继续接入 DWD/ODS 明细表复核。",
        ],
        kpis=kpis,
        risk_distribution=risk_distribution,
        risk_type_distribution=risk_type_distribution,
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
        items=items,
    )


def get_monthly_forecast_review(
    material_code: str | None = None,
    msku: str | None = None,
    fnsku: str | None = None,
    store_name: str | None = None,
    country_code: str | None = None,
    as_of_date: str | date | None = None,
    month_offset: int = 2,
    connector: StiDatabaseConnector | None = None,
) -> MonthlyForecastReview:
    connector = connector or StiDatabaseConnector()
    if not connector.config.ready:
        raise RuntimeError("数据获取失败：STI 数据库未启用或连接信息不完整。")
    target_start, target_end = _target_month_window(as_of_date=as_of_date, month_offset=month_offset)
    review_start = target_start
    review_end = _as_date(as_of_date) or date.today()
    if review_end < review_start:
        review_end = review_start
    codes = _unique_text([_text(material_code), _text(msku), _text(fnsku)])
    if not codes:
        raise ValueError("material_code、msku、fnsku 至少需要一个。")
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
        estimate_rows = connector.get_monthly_sales_estimate_rows(
            material_codes=codes,
            target_month=target_start.strftime("%Y-%m"),
            target_start_date=review_start.isoformat(),
            target_end_date=review_end.isoformat(),
            store_name=store_name,
            country_code=country_code,
        )
    except Exception as exc:
        raise RuntimeError("数据获取失败：月度销量预估表读取失败。") from exc

    forecast_quantity = sum(_number(row.get("daily_sales_quantity")) for row in estimate_rows)
    matched_actual_rows = _matching_sales_rows(actual_rows, codes)
    actual_sales = sum(_number(row.get("daily_sales_volume")) for row in matched_actual_rows)
    difference = actual_sales - forecast_quantity
    variance_ratio = difference / forecast_quantity if forecast_quantity else None
    snapshot_date = max((_sales_stat_date(row.get("date")) for row in snapshot_rows), default="")
    result_type, result_label = _forecast_review_result(difference, forecast_quantity, actual_sales)

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
        forecast_field="daily_sales_quantity",
        actual_field="volume",
        forecast_quantity=round(forecast_quantity, 2),
        actual_sales=round(actual_sales, 2),
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
            "趋势对比区间从预测版本月月初开始，截止到触发当天。",
            f"{MONTHLY_FORECAST_REVIEW_TABLE} 先取目标月份内全表最大 date，作为该月最后一次库存监控底表备份快照。",
            f"预测口径使用 {MONTHLY_SALES_ESTIMATE_TABLE}.daily_sales_quantity，取 month=预测版本月 且 date 落在趋势对比区间内的预估，并按周聚合。",
            f"实际销量使用 {DAILY_SALES_TABLE}.volume，按趋势对比区间和周聚合。",
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
        weekly_estimates=_weekly_estimates(estimate_rows, matched_actual_rows, review_start, review_end),
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
        _include("msku_sales_property", "销售属性", "筛选维度", "爆/旺/平/滞会影响风险解释和后续补货规则。"),
        _include("seasonality", "季节属性", "筛选维度", "季节款的冗余和补货动作需要单独判断。"),
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
    inbound_total = sum(
        _number(row.get(name))
        for name in (
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
            "overseas_wh_product_onway",
            "local_wh_product_onway",
            "planned_quantity",
        )
    )
    demand_7d = _number(row.get("sale_quantity_7"))
    demand_30d = _number(row.get("future_30d_sales")) or _number(row.get("sale_quantity_30"))
    daily_demand = demand_30d / 30 if demand_30d > 0 else max(demand_7d / 7, 0)
    sellable_days = fba_sellable / daily_demand if daily_demand else None
    lead_time_days = _lead_time_days(row)
    fba_age = _fba_age_breakdown(row)
    long_age_inventory = sum(fba_age.values())
    fba_long_age_ratio = long_age_inventory / fba_inventory if fba_inventory else None
    projected_7d = fba_sellable - demand_7d
    risk_flags = _risk_flags(row)
    pici_summary = _pici_gap_summary(row)
    is_pici_shortage = pici_summary["first_shortage_days"] is not None
    is_stockout = is_pici_shortage
    redundancy_sellable_days = _redundancy_sellable_days(
        daily_demand=daily_demand,
        fba_sellable=fba_sellable,
        overseas_inventory=overseas_inventory,
        local_inventory=local_inventory,
        row=row,
    )
    overstock = _overstock_assessment(redundancy_sellable_days, fba_age)
    is_overstock = overstock["is_overstock"]
    is_anomaly = bool(risk_flags)

    pici_first_shortage_days = pici_summary["first_shortage_days"]
    stockout_risk_level, stockout_risk_score = _stockout_assessment(
        is_stockout=is_stockout,
        pici_first_shortage_days=pici_first_shortage_days,
        sellable_days=sellable_days,
    )
    overstock_risk_level = overstock["risk_level"] if is_overstock else "normal"
    overstock_risk_score = overstock["risk_score"] if is_overstock else 10
    anomaly_score = 65 if is_anomaly else 10
    risk_level = _max_level((stockout_risk_level, overstock_risk_level, "medium" if is_anomaly else "normal"))
    risk_score = max(stockout_risk_score, overstock_risk_score, anomaly_score)
    stockout_warning = _risk_warning("断货", stockout_risk_level)
    overstock_warning = _risk_warning("冗余", overstock_risk_level)

    action_parts = []
    if _is_active_level(stockout_risk_level):
        action_parts.append("断货：优先核查 FBA 可售、chazhi 缺口、在途覆盖和最快补货窗口")
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
        sales_property=_text(row.get("msku_sales_property")),
        seasonality=_text(row.get("seasonality")),
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
        evidence={
            "risk_flags": risk_flags,
            "stockout_rule": "temp_lingxing_pici_sale chazhi_0_N gap < 0",
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
    "sellable_1": {"label": "可售天数1", "threshold": 90, "level": "low", "action": "重点监控运营清货进度"},
    "sellable_2": {"label": "可售天数2", "threshold": 120, "level": "medium", "action": "禁止向FBA补货"},
    "sellable_3": {"label": "可售天数3", "threshold": 120, "level": "medium", "action": "禁止向海外仓补货；禁止向FBA补货"},
    "sellable_4": {"label": "可售天数4", "threshold": 120, "level": "medium", "action": "禁止向海外仓补货；禁止向FBA补货"},
    "sellable_5": {"label": "可售天数5", "threshold": 180, "level": "high", "action": "禁止向海外仓补货；禁止向FBA补货；禁止本地仓补货"},
    "sellable_6": {
        "label": "可售天数6",
        "threshold": 180,
        "level": "high",
        "action": "禁止向海外仓补货；禁止向FBA补货；禁止本地仓补货；停止下采购单",
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
    if daily_demand <= 0:
        return {key: None for key in SELLABLE_DAY_RULES}
    fba_inbound = sum(
        _number(row.get(name))
        for name in (
            "afn_inbound_receiving_quantity",
            "afn_inbound_working_quantity",
            "oversease_afn_inbound_shipped_quantity",
            "local_afn_inbound_shipped_quantity",
        )
    )
    overseas_inbound = _number(row.get("overseas_wh_product_onway"))
    local_inbound = _number(row.get("local_wh_product_onway"))
    planned_quantity = _number(row.get("planned_quantity"))
    return {
        "sellable_1": fba_sellable / daily_demand,
        "sellable_2": (fba_sellable + fba_inbound) / daily_demand,
        "sellable_3": overseas_inventory / daily_demand,
        "sellable_4": (overseas_inventory + overseas_inbound + fba_inbound) / daily_demand,
        "sellable_5": local_inventory / daily_demand,
        "sellable_6": (
            fba_sellable
            + fba_inbound
            + overseas_inventory
            + overseas_inbound
            + local_inventory
            + local_inbound
            + planned_quantity
        )
        / daily_demand,
    }


def _overstock_assessment(redundancy_sellable_days: dict[str, float | None], fba_age: dict[str, float]) -> dict[str, Any]:
    sellable_hits = [
        {**rule, "key": key, "days": value}
        for key, value in redundancy_sellable_days.items()
        for rule in (SELLABLE_DAY_RULES[key],)
        if value is not None and value > rule["threshold"]
    ]
    age_hit = next((rule for rule in FBA_AGE_RULES if fba_age.get(rule["key"], 0) > 0), None)
    if not sellable_hits and not age_hit:
        return {
            "is_overstock": False,
            "risk_level": "normal",
            "risk_score": 10,
            "warning_type": "正常",
            "suggested_action": "继续例行监控。",
            "reason": "",
            "rule": "SOP: 可售天数1-6超过冗余阈值或 FBA库龄进入预警/清货区间。",
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
    reason_parts = [f'{hit["label"]} {hit["days"]:.1f}天 > {hit["threshold"]}天' for hit in sellable_hits]
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
        "rule": "SOP: 可售天数1>90、2/3/4>120、5/6>180；FBA库龄61-180预警、181-270重点清货、271+批量清货。",
    }


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


def _pici_stockout_level(first_shortage_days: int) -> tuple[str, int]:
    if first_shortage_days <= 42:
        return "high", 86
    if first_shortage_days <= 70:
        return "medium", 65
    return "low", 38


def _stockout_assessment(
    is_stockout: bool,
    pici_first_shortage_days: int | None,
    sellable_days: float | None,
) -> tuple[str, int]:
    if pici_first_shortage_days is not None:
        return _pici_stockout_level(pici_first_shortage_days)
    if not is_stockout:
        return "normal", 10
    if (sellable_days or 0) <= 7:
        return "high", 86
    if (sellable_days or 0) <= 42:
        return "medium", 65
    return "low", 38


def _risk_warning(prefix: str, level: str) -> str:
    labels = {"high": "高风险", "medium": "中风险", "low": "低风险", "normal": "正常"}
    if level == "normal":
        return f"无{prefix}风险"
    return f"{prefix}{labels.get(level, level)}"


def _is_active_level(level: str | None) -> bool:
    return level in {"critical", "high", "medium", "low"}


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
    parsed: list[tuple[int, float, str]] = []
    for horizon in PICI_HORIZONS:
        key = f"0_{horizon}"
        value = _text(row.get(f"_chazhi_0_{horizon}"))
        if not value:
            continue
        values[key] = value
        gap = _parse_chazhi_gap(value)
        if gap is not None:
            parsed.append((horizon, gap, value))
    shortage = [(horizon, gap, value) for horizon, gap, value in parsed if gap < 0]
    first_shortage = min(shortage, key=lambda item: item[0]) if shortage else None
    min_gap = min((gap for _, gap, _ in parsed), default=None)
    key_gap = first_shortage[2] if first_shortage else (parsed[-1][2] if parsed else "")
    return {
        "values": values,
        "first_shortage_days": first_shortage[0] if first_shortage else None,
        "min_gap_quantity": round(min_gap, 2) if min_gap is not None else None,
        "key_gap": key_gap,
    }


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
        }
        if code_set.intersection(row_codes):
            matched.append(row)
    return matched


def _weekly_estimates(
    estimate_rows: list[dict[str, Any]],
    actual_rows: list[dict[str, Any]],
    review_start: date,
    review_end: date,
) -> list[MonthlyForecastReviewWeeklyEstimate]:
    grouped: dict[str, dict[str, Any]] = {}

    for row in estimate_rows:
        row_date = _as_date(row.get("date"))
        if not row_date:
            continue
        bucket = _weekly_bucket(grouped, row_date, review_start, review_end)
        bucket["forecast_quantity"] += _number(row.get("daily_sales_quantity"))

    for row in actual_rows:
        row_date = _as_date(row.get("date"))
        if not row_date:
            continue
        bucket = _weekly_bucket(grouped, row_date, review_start, review_end)
        bucket["actual_sales"] += _number(row.get("daily_sales_volume"))

    estimates: list[MonthlyForecastReviewWeeklyEstimate] = []
    for values in sorted(grouped.values(), key=lambda item: item["week_start"]):
        forecast_quantity = values["forecast_quantity"]
        actual_sales = values["actual_sales"]
        difference = actual_sales - forecast_quantity
        variance_ratio = difference / forecast_quantity if forecast_quantity else None
        estimates.append(
            MonthlyForecastReviewWeeklyEstimate(
                week=values["week"],
                week_start_date=values["display_start"].isoformat(),
                week_end_date=values["display_end"].isoformat(),
                forecast_quantity=round(forecast_quantity, 2),
                actual_sales=round(actual_sales, 2),
                difference=round(difference, 2),
                variance_ratio=round(variance_ratio, 4) if variance_ratio is not None else None,
                variance_percent=round(variance_ratio * 100, 2) if variance_ratio is not None else None,
                day_count=max((values["display_end"] - values["display_start"]).days + 1, 0),
            )
        )
    return estimates


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
    return grouped.setdefault(
        week,
        {
            "week": week,
            "week_start": week_start,
            "display_start": max(week_start, review_start),
            "display_end": min(week_end, review_end),
            "forecast_quantity": 0.0,
            "actual_sales": 0.0,
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
    if not value:
        return None
    if isinstance(value, (list, tuple, set)):
        value = next(iter(value), "")
    text = str(value).strip().upper()
    return text or None


def _selected_store(filters: dict[str, Any] | None) -> str | None:
    if not filters:
        return None
    value = filters.get("store_name")
    if not value:
        return None
    if isinstance(value, (list, tuple, set)):
        value = next(iter(value), "")
    text = str(value).strip()
    return text or None


def _selected_risk_type(filters: dict[str, Any] | None) -> str | None:
    if not filters:
        return None
    value = _text(filters.get("risk_type")).strip().lower()
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
    return aliases.get(value)


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
        if value and value.strip().lower() not in SAFE_RISK_VALUES:
            flags.append(
                {
                    "field": field,
                    "label": f"断货风险 {index}",
                    "value": value,
                    "reason": f"{field} 底表风险标记为 {value}",
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
