from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.base import ConnectorLogMixin
from pmc_agent.domain import InventorySnapshot, Material
from pmc_agent.env import load_env_file
from pmc_agent.query_spec import QuerySpec
from pmc_agent.schema_catalog import ALL_WAREHOUSE_CATALOG, FieldPack, normalize_field_pack


logger = get_logger(__name__)


def _number(value: Any) -> float:
    if value is None:
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _alias_queries(material_code: str) -> list[tuple[str, tuple[Any, ...]]]:
    return [
        (
            """
            SELECT sku, msku, asin, new_asin, NULL AS fnsku
            FROM leang_lst_asin_mapping
            WHERE UPPER(msku) = UPPER(%s)
               OR UPPER(asin) = UPPER(%s)
               OR UPPER(new_asin) = UPPER(%s)
               OR UPPER(sku) = UPPER(%s)
            LIMIT 50
            """,
            (material_code, material_code, material_code, material_code),
        ),
        (
            """
            SELECT sku, msku, asin, new_asin, NULL AS fnsku
            FROM dim_msku_dimension_detailed
            WHERE UPPER(msku) = UPPER(%s)
               OR UPPER(asin) = UPPER(%s)
               OR UPPER(new_asin) = UPPER(%s)
               OR UPPER(sku) = UPPER(%s)
            LIMIT 50
            """,
            (material_code, material_code, material_code, material_code),
        ),
        (
            """
            SELECT sku, NULL AS msku, asin, NULL AS new_asin, fnsku
            FROM temp_lingxing_sku_quantity
            WHERE UPPER(sku) = UPPER(%s)
               OR UPPER(fnsku) = UPPER(%s)
               OR UPPER(asin) = UPPER(%s)
            LIMIT 50
            """,
            (material_code, material_code, material_code),
        ),
    ]


@dataclass(frozen=True)
class StiDatabaseConfig:
    host: str
    port: int
    user: str
    password: str
    database: str
    charset: str = "utf8mb4"
    connect_timeout: int = 10
    read_timeout: int = 30
    enabled: bool = False

    @classmethod
    def from_env(cls) -> "StiDatabaseConfig":
        load_env_file(override=False)
        return cls(
            host=os.getenv("STI_DB_HOST", ""),
            port=int(os.getenv("STI_DB_PORT", "9030")),
            user=os.getenv("STI_DB_USER", ""),
            password=os.getenv("STI_DB_PASSWORD", ""),
            database=os.getenv("STI_DB_NAME", "dw_leang"),
            charset=os.getenv("STI_DB_CHARSET", "utf8mb4"),
            enabled=os.getenv("STI_DB_ENABLED", "").lower() in {"1", "true", "yes", "on"},
        )

    @property
    def ready(self) -> bool:
        return bool(self.enabled and self.host and self.user and self.password and self.database)


class StiDatabaseConnector(ConnectorLogMixin):
    """只读连接 STI / dw_leang 数据库。

    当前首期只实现库存快照读取，主表为 ads_lingxing_all_warehouse_new_v1。
    """

    connector_name = "sti_database"

    def __init__(self, config: StiDatabaseConfig | None = None) -> None:
        self.config = config or StiDatabaseConfig.from_env()
        self.last_resolved_aliases: list[str] = []

    def get_material(self, material_code: str) -> Material | None:
        snapshots = self.get_inventory_snapshot(material_code)
        if not snapshots:
            return None
        return Material(code=snapshots[0].material_code, name=snapshots[0].material_code)

    def get_inventory_snapshot(
        self,
        material_code: str | None = None,
        field_pack: FieldPack | str | None = None,
        query_spec: QuerySpec | None = None,
    ) -> list[InventorySnapshot]:
        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        spec = query_spec or QuerySpec.inventory(material_code=material_code, field_pack=field_pack)
        self.log_query_started("get_inventory_snapshot", material_code)
        try:
            rows = self._query_inventory_rows(spec)
        except Exception as exc:
            self.log_query_failed("get_inventory_snapshot")
            raise RuntimeError("STI database inventory snapshot query failed.") from exc
        snapshots = [self._row_to_snapshot(row) for row in rows]
        if not snapshots:
            self.log_empty_result("get_inventory_snapshot")
            query_scope = f"material_code={spec.material_code}" if spec.material_code else "portfolio query"
            raise LookupError(f"No inventory snapshot found in STI database for {query_scope}.")
        self.log_query_completed("get_inventory_snapshot", len(snapshots))
        return snapshots

    def record_control_advice(self, material_code: str, advice: list[str]) -> str:
        logger.warning(
            "database connector is read only",
            extra=log_extra("database_connector_read_only", material_code=material_code),
        )
        return "read_only_not_recorded"

    def _connect(self):
        try:
            import pymysql
        except ImportError as exc:  # pragma: no cover - dependency guard
            raise RuntimeError("pymysql is required for StiDatabaseConnector.") from exc
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset=self.config.charset,
            connect_timeout=self.config.connect_timeout,
            read_timeout=self.config.read_timeout,
            write_timeout=30,
            cursorclass=pymysql.cursors.DictCursor,
        )

    def _query_inventory_rows(self, spec: QuerySpec) -> list[dict[str, Any]]:
        self.last_resolved_aliases = []
        material_code = spec.material_code
        if material_code:
            with self._connect() as conn:
                rows = self._query_inventory_rows_by_codes(conn, [material_code], spec)
                if rows:
                    self.last_resolved_aliases = [material_code]
                    return rows
                aliases = self._resolve_inventory_aliases(conn, material_code)
                if aliases:
                    self.last_resolved_aliases = aliases
                    return self._query_inventory_rows_by_codes(conn, aliases, spec)
                return []

        filter_sql, params = _filter_sql(spec)
        order_sql = _order_sql(spec)
        select_sql = f"""
            SELECT
                {_select_fields(spec)}
            FROM {ALL_WAREHOUSE_CATALOG.table_name}
            {filter_sql}
            {order_sql}
            LIMIT {_bounded_limit(spec.limit)}
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(select_sql, params)
                return list(cursor.fetchall())

    def _query_inventory_rows_by_codes(self, conn: Any, codes: list[str], spec: QuerySpec) -> list[dict[str, Any]]:
        normalized = list(dict.fromkeys(code.strip() for code in codes if code and code.strip()))
        if not normalized:
            return []
        placeholders = ", ".join(["%s"] * len(normalized))
        filter_sql, filter_params = _filter_sql(spec, prefix="AND")
        order_sql = _order_sql(spec)
        select_sql = f"""
            SELECT
                {_select_fields(spec)}
            FROM {ALL_WAREHOUSE_CATALOG.table_name}
            WHERE (
                UPPER(msku) IN ({placeholders})
                OR UPPER(sku) IN ({placeholders})
                OR UPPER(fnsku) IN ({placeholders})
            )
            {filter_sql}
            {order_sql}
            LIMIT {_bounded_limit(spec.limit)}
        """
        upper_codes = [code.upper() for code in normalized]
        params = [*upper_codes, *upper_codes, *upper_codes, *filter_params]
        with conn.cursor() as cursor:
            cursor.execute(select_sql, params)
            return list(cursor.fetchall())

    def _resolve_inventory_aliases(self, conn: Any, material_code: str) -> list[str]:
        aliases: list[str] = [material_code]
        with conn.cursor() as cursor:
            for sql, params in _alias_queries(material_code):
                cursor.execute(sql, params)
                for row in cursor.fetchall():
                    for key in ("sku", "msku", "fnsku", "asin", "new_asin"):
                        value = row.get(key)
                        if value:
                            aliases.append(str(value))
        return list(dict.fromkeys(item.strip() for item in aliases if item and item.strip()))

    def _row_to_snapshot(self, row: dict[str, Any]) -> InventorySnapshot:
        material_code = str(row.get("sku") or row.get("fnsku") or row.get("msku") or "UNKNOWN")
        fba_stock = _number(row.get("fba_warehouse_quantity")) or _number(row.get("afn_fulfillable_quantity"))
        overseas_stock = _number(row.get("overseas_warehouse_quantity"))
        local_stock = _number(row.get("local_warehouse_quantity"))
        on_hand = fba_stock + overseas_stock + local_stock

        inbound = sum(
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
        demand_next_7d = _number(row.get("sale_quantity_7"))
        demand_next_30d = _number(row.get("future_30d_sales")) or _number(row.get("sale_quantity_30"))

        return InventorySnapshot(
            material_code=material_code,
            on_hand=on_hand,
            allocated=0,
            inbound=inbound,
            demand_next_7d=demand_next_7d,
            demand_next_30d=demand_next_30d,
            metadata={
                "source_table": ALL_WAREHOUSE_CATALOG.table_name,
                "field_pack": normalize_field_pack(row.get("_field_pack")).value if row.get("_field_pack") else None,
                "store_name": row.get("store_name"),
                "country_code": row.get("country_code"),
                "shipments_country": row.get("shipments_country"),
                "sku_name": row.get("sku_name"),
                "msku": row.get("msku"),
                "sku": row.get("sku"),
                "fnsku": row.get("fnsku"),
                "raw_evidence": {key: value for key, value in row.items() if not key.startswith("_")},
            },
        )


def _select_fields(spec: QuerySpec) -> str:
    fields = list(ALL_WAREHOUSE_CATALOG.fields_for(spec.field_pack))
    # Carry the selected pack through the row mapping without trusting the DB for this value.
    fields_sql = ",\n                ".join(fields)
    pack = normalize_field_pack(spec.field_pack).value.replace("'", "")
    return f"{fields_sql},\n                '{pack}' AS _field_pack"


def _filter_sql(spec: QuerySpec, prefix: str = "WHERE") -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    filters = spec.filters or {}

    sales_property = filters.get("sales_property") or filters.get("msku_sales_property")
    values = _as_list(sales_property)
    if values:
        placeholders = ", ".join(["%s"] * len(values))
        clauses.append(f"msku_sales_property IN ({placeholders})")
        params.extend(values)

    if filters.get("risk_only"):
        risk_fields = [f"fnsku_out_of_stock_risk_{index}" for index in range(1, 7)]
        clauses.append(
            "("
            + " OR ".join(f"COALESCE({field}, '') NOT IN ('', '安全', '数据缺失')" for field in risk_fields)
            + ")"
        )

    if filters.get("positive_demand"):
        clauses.append("COALESCE(future_30d_sales, sale_quantity_30, sale_quantity_7, 0) > 0")

    if not clauses:
        return "", []
    return f"{prefix} " + "\n              AND ".join(clauses), params


def _order_sql(spec: QuerySpec) -> str:
    order_by = str((spec.filters or {}).get("order_by") or "").strip().lower()
    if order_by in {"demand_desc", "risk_then_demand"}:
        return "ORDER BY COALESCE(future_30d_sales, sale_quantity_30, sale_quantity_7, 0) DESC"
    return ""


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value]
    else:
        values = [str(value)]
    allowed = {"爆", "旺", "平", "滞"}
    return [item.strip() for item in values if item and item.strip() in allowed]


def _bounded_limit(limit: int) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = ALL_WAREHOUSE_CATALOG.default_limit
    return max(1, min(value, 500))
