from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.base import ConnectorLogMixin
from pmc_agent.domain import InventorySnapshot, Material
from pmc_agent.env import load_env_file


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

    def get_inventory_snapshot(self, material_code: str | None = None) -> list[InventorySnapshot]:
        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        self.log_query_started("get_inventory_snapshot", material_code)
        try:
            rows = self._query_inventory_rows(material_code)
        except Exception as exc:
            self.log_query_failed("get_inventory_snapshot")
            raise RuntimeError("STI database inventory snapshot query failed.") from exc
        snapshots = [self._row_to_snapshot(row) for row in rows]
        if not snapshots:
            self.log_empty_result("get_inventory_snapshot")
            query_scope = f"material_code={material_code}" if material_code else "portfolio query"
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

    def _query_inventory_rows(self, material_code: str | None) -> list[dict[str, Any]]:
        self.last_resolved_aliases = []
        if material_code:
            with self._connect() as conn:
                rows = self._query_inventory_rows_by_codes(conn, [material_code])
                if rows:
                    self.last_resolved_aliases = [material_code]
                    return rows
                aliases = self._resolve_inventory_aliases(conn, material_code)
                if aliases:
                    self.last_resolved_aliases = aliases
                    return self._query_inventory_rows_by_codes(conn, aliases)
                return []

        select_sql = """
            SELECT
                msku,
                sku,
                fnsku,
                store_name,
                country_code,
                shipments_country,
                sku_name,
                afn_fulfillable_quantity,
                fba_warehouse_quantity,
                overseas_warehouse_quantity,
                local_warehouse_quantity,
                afn_inbound_receiving_quantity,
                afn_inbound_working_quantity,
                oversease_afn_inbound_shipped_quantity,
                local_afn_inbound_shipped_quantity,
                overseas_wh_product_onway,
                local_wh_product_onway,
                planned_quantity,
                sale_quantity_7,
                sale_quantity_30,
                future_30d_sales,
                safety_stock_sales
            FROM ads_lingxing_all_warehouse_new_v1
        """
        select_sql += " LIMIT 50"
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(select_sql)
                return list(cursor.fetchall())

    def _query_inventory_rows_by_codes(self, conn: Any, codes: list[str]) -> list[dict[str, Any]]:
        normalized = list(dict.fromkeys(code.strip() for code in codes if code and code.strip()))
        if not normalized:
            return []
        placeholders = ", ".join(["%s"] * len(normalized))
        select_sql = f"""
            SELECT
                msku,
                sku,
                fnsku,
                store_name,
                country_code,
                shipments_country,
                sku_name,
                afn_fulfillable_quantity,
                fba_warehouse_quantity,
                overseas_warehouse_quantity,
                local_warehouse_quantity,
                afn_inbound_receiving_quantity,
                afn_inbound_working_quantity,
                oversease_afn_inbound_shipped_quantity,
                local_afn_inbound_shipped_quantity,
                overseas_wh_product_onway,
                local_wh_product_onway,
                planned_quantity,
                sale_quantity_7,
                sale_quantity_30,
                future_30d_sales,
                safety_stock_sales
            FROM ads_lingxing_all_warehouse_new_v1
            WHERE UPPER(msku) IN ({placeholders})
               OR UPPER(sku) IN ({placeholders})
               OR UPPER(fnsku) IN ({placeholders})
            LIMIT 50
        """
        upper_codes = [code.upper() for code in normalized]
        params = [*upper_codes, *upper_codes, *upper_codes]
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
                "store_name": row.get("store_name"),
                "country_code": row.get("country_code"),
                "shipments_country": row.get("shipments_country"),
                "sku_name": row.get("sku_name"),
                "msku": row.get("msku"),
                "sku": row.get("sku"),
                "fnsku": row.get("fnsku"),
            },
        )
