from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from neo4j import GraphDatabase
import pymysql

from pmc_agent.env import load_env_file


FALLBACK_COMMENTS = {
    "msku": "MSKU",
    "sku": "SKU",
    "fnsku": "FNSKU",
    "asin": "ASIN",
    "parent_asin": "父 ASIN",
    "brand": "品牌",
    "store_name": "店铺名称",
    "sid": "店铺 ID",
    "seller_id": "店铺 ID",
    "country": "国家",
    "country_code": "国家代码",
    "channel": "渠道",
    "forecast_date": "预测日期",
    "date": "日期",
    "expected_arrival": "预计到达日期",
    "expected_sales": "预计销量",
    "ending_inventory": "期末库存",
    "starting_inventory": "期初库存",
    "insert_time": "写入时间",
    "update_time": "更新时间",
    "fba_warehouse_quantity": "FBA 仓库存量",
    "overseas_warehouse_quantity": "海外仓库存量",
    "oversease_afn_inbound_shipped_quantity": "海外仓/FBA 在途发货量",
    "local_warehouse_quantity": "国内仓库存量",
    "stock_up_num": "备货数量",
    "afn_fulfillable_quantity": "FBA 可售库存",
    "afn_reserved_quantity": "FBA 预留库存",
    "afn_inbound_working_quantity": "FBA 入库处理中数量",
    "afn_inbound_shipped_quantity": "FBA 已发货在途数量",
    "afn_inbound_receiving_quantity": "FBA 接收中数量",
    "sale_quantity_7": "近 7 天销量",
    "sale_quantity_30": "近 30 天销量",
    "forecast_30d_sales_checked": "近 30 天需求预测校验值",
    "sales_apartment": "销售部门",
    "salesman": "销售员",
    "operator": "运营人员",
    "product_name": "产品名称",
    "sku_name": "SKU 名称",
    "spu": "SPU",
    "spu_name": "SPU 名称/款名",
    "logistics_model": "物流模式",
    "first_leg_logistics_channel": "头程物流渠道",
    "shipments_country": "发货国家",
    "region": "区域",
    "seasonality": "季节属性",
    "msku_status": "MSKU 状态",
    "color": "颜色",
    "planned_quantity": "计划数量",
    "shipment_quantity2": "发货数量",
    "day_num": "天数",
    "local_to_overseas_warehouse_time": "国内仓到海外仓时效",
    "overseas_to_FBA_time": "海外仓到 FBA 时效",
    "overseas_to_fba_time": "海外仓到 FBA 时效",
    "FBA_delivery_time_fn_next": "下一次 FBA 配送时效",
    "fba_delivery_time_fn_next": "下一次 FBA 配送时效",
    "overseas_warehouse_delivery_time_fn_next": "下一次海外仓配送时效",
    "local_warehouse_delivery_time_fn_next": "下一次国内仓配送时效",
    "day_safety_stock_sales_next": "下一次日安全库存销量",
    "next_overseas_warehouse_safety_days": "下一次海外仓安全天数",
    "next_local_warehouse_safety_days": "下一次国内仓安全天数",
    "next_fba_safety_days_fn": "下一次 FBA 安全天数",
    "next_safety_stock_days_sales": "下一次安全库存天数销量",
    "basic_purchase_quantity": "基础采购量",
    "basic_fh_quantity": "基础发货量",
    "start_dates": "采购窗口开始日期",
    "end_dates": "采购窗口结束日期",
    "start_dates0": "发货窗口开始日期",
    "end_dates0": "发货窗口结束日期",
    "start_sales0": "发货窗口销量开始日期",
    "end_sales0": "发货窗口销量结束日期",
    "last_30_order_price": "近 30 天订单价格",
    "last_30_order_us_price": "近 30 天订单美元价格",
    "last_90_gross_margin": "近 90 天毛利率",
    "biaoqian": "标签",
    "xiuzhenliang": "采购修正量",
    "fhxiuzhenliang": "发货修正量",
    "jypurchase_quantity": "建议采购量",
    "jyfahuo_quantity": "建议发货量",
    "total": "总计",
    "t0day": "T0 日期",
    "today": "当前日期",
    "fhtoday": "发货当前日期",
    "start_date_calculated2": "计算后开始日期",
    "start_sales": "销量窗口开始日期",
    "end_sales": "销量窗口结束日期",
    "restocking_frequency": "补货频率",
    "shipments_frequency": "发货频率",
}

CONCEPT_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("FNSKU", ("fnsku",)),
    ("MSKU", ("msku", "seller_sku", "price_list_seller_sku")),
    ("SKU", ("sku",)),
    ("ASIN", ("asin",)),
    ("SPU", ("spu",)),
    ("Store", ("store", "store_name", "seller_id", "sid", "店铺")),
    ("Country", ("country", "国家")),
    ("Warehouse", ("warehouse", "仓库")),
    ("Date", ("date", "日期", "day", "month", "year")),
    ("InventoryQuantity", ("inventory", "quantity", "qty", "num", "stock", "库存")),
    ("Sales", ("sales", "sale", "销量")),
    ("Forecast", ("forecast", "estimate", "predict", "expected", "预测")),
    ("Shipment", ("shipment", "shipping", "fh", "fahuo", "发货")),
    ("Purchase", ("purchase", "caigou", "采购")),
    ("Logistics", ("logistics", "carrier", "channel", "物流")),
    ("Supplier", ("supplier", "vendor", "供应商")),
    ("Rule", ("rule", "frequency", "safety", "oversell", "规则")),
)


def main() -> int:
    load_env_file(override=False)
    graph = GraphDatabase.driver(os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    try:
        with graph.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            v1_tables = [
                record["table"]
                for record in session.run(
                    "MATCH (t:DataTable) WHERE toLower(t.name) CONTAINS 'v1' RETURN t.name AS table ORDER BY table"
                )
            ]
            existing_comments = _load_existing_comment_map(session)

        columns_by_table = _load_mysql_columns(v1_tables)
        updated_comments = 0
        merged_fields = 0
        skipped_tables: list[str] = []
        remaining_updates = 0
        with graph.session(database=os.getenv("NEO4J_DATABASE", "neo4j")) as session:
            for table, columns in columns_by_table.items():
                if not columns:
                    skipped_tables.append(table)
                    continue
                for ordinal, column in enumerate(columns, start=1):
                    comment, source = _best_comment(column["name"], column["comment"], existing_comments)
                    session.execute_write(_merge_field, table, ordinal, column, comment, source)
                    for concept in _detect_concepts(column["name"], comment):
                        session.execute_write(_merge_field_concept, f"{table}.{column['name']}", concept)
                    merged_fields += 1
                    if comment:
                        updated_comments += 1
                session.run(
                    """
                    MATCH (t:DataTable {name: $table})
                    SET t.field_count = $field_count,
                        t.schema_detail_source = 'mysql_show_full_columns'
                    """,
                    table=table,
                    field_count=len(columns),
                ).consume()
            remaining_updates = _fill_remaining_empty_comments(session, existing_comments)

        print(
            f"Synced {len(columns_by_table) - len(skipped_tables)} v1 tables, "
            f"merged {merged_fields} fields, populated {updated_comments} comments, "
            f"filled {remaining_updates} remaining existing comments."
        )
        if skipped_tables:
            print("Skipped tables without live schema:", ", ".join(skipped_tables))
    finally:
        graph.close()
    return 0


def _load_existing_comment_map(session: Any) -> dict[str, str]:
    rows = session.run(
        """
        MATCH (f:DataField)
        WHERE f.comment IS NOT NULL AND trim(f.comment) <> ''
        RETURN toLower(f.name) AS name, collect(DISTINCT f.comment) AS comments
        """
    )
    comments: dict[str, str] = {}
    for row in rows:
        values = [value for value in row["comments"] if value]
        if len(values) == 1:
            comments[row["name"]] = values[0]
    return comments


def _load_mysql_columns(tables: list[str]) -> dict[str, list[dict[str, Any]]]:
    conn = pymysql.connect(
        host=os.getenv("STI_DB_HOST"),
        port=int(os.getenv("STI_DB_PORT", "9030")),
        user=os.getenv("STI_DB_USER"),
        password=os.getenv("STI_DB_PASSWORD"),
        database=os.getenv("STI_DB_NAME"),
        charset=os.getenv("STI_DB_CHARSET", "utf8mb4"),
        connect_timeout=10,
        read_timeout=30,
    )
    try:
        result: dict[str, list[dict[str, Any]]] = {}
        with conn.cursor() as cur:
            for table in tables:
                try:
                    cur.execute(f"SHOW FULL COLUMNS FROM `{table}`")
                except Exception:
                    result[table] = []
                    continue
                result[table] = [
                    {
                        "name": row[0],
                        "type": row[1],
                        "collation": row[2] or "",
                        "nullable": row[3],
                        "key": row[4],
                        "default": "" if row[5] is None else str(row[5]),
                        "extra": row[6],
                        "privileges": row[7],
                        "comment": row[8] or "",
                    }
                    for row in cur.fetchall()
                ]
        return result
    finally:
        conn.close()


def _fill_remaining_empty_comments(session: Any, existing_comments: dict[str, str]) -> int:
    rows = list(
        session.run(
            """
            MATCH (t:DataTable)-[:HAS_FIELD]->(f:DataField)
            WHERE toLower(t.name) CONTAINS 'v1'
              AND (f.comment IS NULL OR trim(f.comment) = '')
            RETURN f.id AS field_id, f.name AS name
            """
        )
    )
    updated = 0
    for row in rows:
        comment, source = _best_comment(row["name"], "", existing_comments)
        if not comment:
            continue
        session.run(
            """
            MATCH (f:DataField {id: $field_id})
            SET f.comment = $comment,
                f.comment_source = $comment_source
            """,
            field_id=row["field_id"],
            comment=comment,
            comment_source=source,
        ).consume()
        for concept in _detect_concepts(row["name"], comment):
            session.execute_write(_merge_field_concept, row["field_id"], concept)
        updated += 1
    return updated


def _best_comment(field_name: str, db_comment: str, existing_comments: dict[str, str]) -> tuple[str, str]:
    if db_comment.strip():
        return db_comment.strip(), "mysql_column_comment"
    key = field_name.lower()
    if key in existing_comments:
        return existing_comments[key], "matched_existing_field_comment"
    if key in FALLBACK_COMMENTS:
        return FALLBACK_COMMENTS[key], "inferred_from_field_name"
    pattern_comment = _pattern_comment(field_name)
    if pattern_comment:
        return pattern_comment, "inferred_from_field_name"
    return "", ""


def _pattern_comment(field_name: str) -> str:
    key = field_name.lower()
    week_match = re.fullmatch(r"\d{4}w\d{2}", key)
    if week_match:
        return f"{field_name} 周度预测值"
    sale_quantity = re.fullmatch(r"sale_quantity_(\d+)", key)
    if sale_quantity:
        return f"近 {sale_quantity.group(1)} 天销量"
    future_sales = re.fullmatch(r"future_(\d+)d_sales", key)
    if future_sales:
        return f"未来 {future_sales.group(1)} 天销量"
    last_year_sales = re.fullmatch(r"last_year_sale_quantity_(\d+)", key)
    if last_year_sales:
        return f"去年同期近 {last_year_sales.group(1)} 天销量"
    inv_age = re.fullmatch(r"inv_age_(\d+)_to_(\d+)_days", key)
    if inv_age:
        return f"库龄 {inv_age.group(1)}-{inv_age.group(2)} 天库存"
    inv_age_plus = re.fullmatch(r"inv_age_(\d+)_plus_days", key)
    if inv_age_plus:
        return f"库龄 {inv_age_plus.group(1)} 天以上库存"
    available_days = re.fullmatch(r"fnsku_available_days_str_(\d+)", key)
    if available_days:
        return f"FNSKU 可售天数展示值 {available_days.group(1)}"
    restocking_countdown = re.fullmatch(r"fnsku_restocking_countdown_str_(\d+)", key)
    if restocking_countdown:
        return f"FNSKU 补货倒计时展示值 {restocking_countdown.group(1)}"
    sale_available = re.fullmatch(r"sale_fnsku_available_(\d+)", key)
    if sale_available:
        return f"销售侧 FNSKU 可售值 {sale_available.group(1)}"
    sale_available_str = re.fullmatch(r"sale_fnsku_available_str_(\d+)", key)
    if sale_available_str:
        return f"销售侧 FNSKU 可售展示值 {sale_available_str.group(1)}"
    sale_countdown = re.fullmatch(r"sale_fnsku_restocking_countdown_(\d+)", key)
    if sale_countdown:
        return f"销售侧 FNSKU 补货倒计时 {sale_countdown.group(1)}"
    sale_countdown_str = re.fullmatch(r"sale_fnsku_restocking_countdown_str_(\d+)", key)
    if sale_countdown_str:
        return f"销售侧 FNSKU 补货倒计时展示值 {sale_countdown_str.group(1)}"
    sale_risk = re.fullmatch(r"sale_fnsku_out_of_stock_risk_(\d+)", key)
    if sale_risk:
        return f"销售侧 FNSKU 断货风险标记 {sale_risk.group(1)}"
    return ""


def _detect_concepts(field_name: str, comment: str) -> list[str]:
    haystack = f"{field_name} {comment}".lower()
    return [concept for concept, patterns in CONCEPT_PATTERNS if any(pattern.lower() in haystack for pattern in patterns)]


def _merge_field(tx: Any, table: str, ordinal: int, column: dict[str, Any], comment: str, source: str) -> None:
    tx.run(
        """
        MERGE (t:DataTable {name: $table})
        MERGE (f:DataField {id: $field_id})
        SET f.name = $name,
            f.ordinal = $ordinal,
            f.type = $type,
            f.nullable = $nullable,
            f.is_key = $is_key,
            f.default = $default,
            f.extra = $extra,
            f.comment = CASE
                WHEN coalesce(trim(f.comment), '') = '' THEN $comment
                ELSE f.comment
            END,
            f.comment_source = CASE
                WHEN coalesce(trim(f.comment), '') = '' AND $comment <> '' THEN $comment_source
                ELSE coalesce(f.comment_source, '')
            END
        MERGE (t)-[rel:HAS_FIELD]->(f)
        SET rel.ordinal = $ordinal
        """,
        table=table,
        field_id=f"{table}.{column['name']}",
        name=column["name"],
        ordinal=ordinal,
        type=column["type"],
        nullable=column["nullable"],
        is_key=str(column["key"]).upper() in {"YES", "PRI", "MUL", "UNI"},
        default=column["default"],
        extra=column["extra"],
        comment=comment,
        comment_source=source,
    ).consume()


def _merge_field_concept(tx: Any, field_id: str, concept: str) -> None:
    tx.run(
        """
        MATCH (f:DataField {id: $field_id})
        MERGE (c:FieldConcept {name: $concept})
        MERGE (f)-[:MEANS]->(c)
        """,
        field_id=field_id,
        concept=concept,
    ).consume()


if __name__ == "__main__":
    raise SystemExit(main())
