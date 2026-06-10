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

    当前首期只实现库存快照读取，主表为 ads_lingxing_all_warehouse_new。
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

    def get_inventory_rows(self, query_spec: QuerySpec) -> list[dict[str, Any]]:
        """Return whitelisted raw inventory rows for UI-oriented read models."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        self.log_query_started(query_spec.intent, query_spec.material_code)
        try:
            rows = self._query_inventory_rows(query_spec)
        except Exception as exc:
            self.log_query_failed(query_spec.intent)
            raise RuntimeError("STI database inventory row query failed.") from exc
        self.log_query_completed(query_spec.intent, len(rows))
        return rows

    def get_inventory_export_rows(
        self,
        fields: tuple[str, ...],
        filters: dict[str, Any] | None = None,
        limit: int = 20000,
    ) -> list[dict[str, Any]]:
        """Return raw inventory rows for the controlled Excel export surface."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        safe_fields = [
            field
            for field in dict.fromkeys(fields)
            if field and field.replace("_", "").isalnum() and not field[0].isdigit()
        ]
        if not safe_fields:
            return []
        spec = QuerySpec.inventory(
            intent="inventory_monitoring_export",
            filters={**(filters or {}), "order_by": "risk_then_demand"},
            limit=limit,
        )
        filter_sql, params = _filter_sql(spec)
        fields_sql = ",\n                ".join(safe_fields)
        select_sql = f"""
            SELECT
                {fields_sql}
            FROM {ALL_WAREHOUSE_CATALOG.table_name}
            {filter_sql}
            {_order_sql(spec)}
            LIMIT {_bounded_limit(limit, spec)}
        """
        self.log_query_started("inventory_monitoring_export")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(select_sql, params)
                rows = list(cursor.fetchall())
        self.log_query_completed("inventory_monitoring_export", len(rows))
        return rows

    def get_warehouse_inventory_rows(self, country_code: str | None = None, limit: int = 80) -> list[dict[str, Any]]:
        """Return warehouse-level inventory quantities from domestic/overseas warehouse details."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        sql = f"""
            SELECT
                resolved_country_code AS country_code,
                country_area_name,
                warehouse_code,
                warehouse_name,
                warehouse_display_name,
                SUM(product_total) AS product_total,
                SUM(product_valid_num) AS product_valid_num,
                SUM(product_lock_num) AS product_lock_num,
                SUM(product_onway) AS product_onway,
                COUNT(DISTINCT sku) AS sku_count
            FROM (
                SELECT
                    CASE
                        WHEN COALESCE(w.country_code, '') <> '' THEN UPPER(w.country_code)
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-US%%' OR COALESCE(w.name, '') LIKE '%%美国%%' THEN 'US'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-CA%%' OR COALESCE(w.name, '') LIKE '%%加拿大%%' THEN 'CA'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-MX%%' OR COALESCE(w.name, '') LIKE '%%墨西哥%%' THEN 'MX'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-BR%%' OR COALESCE(w.name, '') LIKE '%%巴西%%' THEN 'BR'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-UK%%' OR COALESCE(w.name, '') LIKE '%%英国%%' THEN 'UK'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-DE%%' OR COALESCE(w.name, '') LIKE '%%德国%%' THEN 'DE'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-JP%%' OR COALESCE(w.name, '') LIKE '%%日本%%' THEN 'JP'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-AU%%' OR COALESCE(w.name, '') LIKE '%%澳%%' THEN 'AU'
                        WHEN UPPER(COALESCE(w.name, '')) LIKE '%%-CN%%' OR COALESCE(w.name, '') LIKE '%%中国%%' OR COALESCE(w.name, '') LIKE '%%深圳%%' OR COALESCE(w.name, '') LIKE '%%义乌%%' THEN 'CN'
                        ELSE ''
                    END AS resolved_country_code,
                    COALESCE(w.t_country_area_name, '') AS country_area_name,
                    COALESCE(w.t_warehouse_code, '') AS warehouse_code,
                    COALESCE(w.t_warehouse_name, '') AS warehouse_name,
                    COALESCE(NULLIF(w.t_warehouse_name, ''), NULLIF(w.name, ''), CONCAT('WID-', CAST(d.wid AS CHAR))) AS warehouse_display_name,
                    d.sku,
                    COALESCE(d.product_total, 0) AS product_total,
                    COALESCE(d.product_valid_num, 0) AS product_valid_num,
                    COALESCE(d.product_lock_num, 0) AS product_lock_num,
                    COALESCE(d.product_onway, 0) AS product_onway
                FROM (
                    SELECT *
                    FROM dwd_lingxing_inventory_details
                    WHERE date = (SELECT MAX(date) FROM dwd_lingxing_inventory_details)
                ) d
                LEFT JOIN (
                    SELECT *
                    FROM dwd_lingxing_sc_warehouse
                    WHERE date = (SELECT MAX(date) FROM dwd_lingxing_sc_warehouse)
                ) w ON d.wid = w.wid
                WHERE COALESCE(d.product_total, 0) + COALESCE(d.product_valid_num, 0) + COALESCE(d.product_onway, 0) > 0
            ) warehouse_rows
            WHERE (%s = '' OR resolved_country_code = UPPER(%s))
            GROUP BY resolved_country_code, country_area_name, warehouse_code, warehouse_name, warehouse_display_name
            ORDER BY product_total DESC
            LIMIT {_bounded_limit(limit)}
        """
        value = (country_code or "").strip().upper()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (value, value))
                return list(cursor.fetchall())

    def get_daily_sales_rows(
        self,
        sales_start_date: str,
        sales_end_date: str | None = None,
        country_code: str | None = None,
        store_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return SKU sales aggregated by store and country for the selected date range."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        sales_end_date = sales_end_date or sales_start_date
        sql = """
            SELECT
                UPPER(COALESCE(sku, '')) AS sku,
                UPPER(COALESCE(price_list_seller_sku, '')) AS seller_sku,
                COALESCE(store_name, '') AS store_name,
                UPPER(COALESCE(country_code, '')) AS country_code,
                UPPER(COALESCE(fnsku, '')) AS fnsku,
                SUM(COALESCE(volume, 0)) AS daily_sales_volume,
                SUM(COALESCE(amount, 0)) AS daily_sales_amount,
                SUM(COALESCE(order_items, 0)) AS daily_order_items
            FROM ads_lingxing_sc_sales_daily_new
            WHERE date BETWEEN %s AND %s
              AND (%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))
              AND (%s = '' OR COALESCE(store_name, '') = %s)
            GROUP BY
                UPPER(COALESCE(sku, '')),
                UPPER(COALESCE(price_list_seller_sku, '')),
                COALESCE(store_name, ''),
                UPPER(COALESCE(country_code, '')),
                UPPER(COALESCE(fnsku, ''))
        """
        country = (country_code or "").strip().upper()
        store = (store_name or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (sales_start_date, sales_end_date, country, country, store, store))
                return list(cursor.fetchall())

    def get_daily_sales_detail_rows(
        self,
        sales_start_date: str,
        sales_end_date: str | None = None,
        country_code: str | None = None,
        store_name: str | None = None,
        material_codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Return daily SKU sales rows for time-series comparisons."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        sales_end_date = sales_end_date or sales_start_date
        codes = [code.strip().upper() for code in (material_codes or []) if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        code_filter = ""
        code_params: list[Any] = []
        if codes:
            placeholders = ", ".join(["%s"] * len(codes))
            code_filter = f"""
              AND (
                UPPER(COALESCE(sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(price_list_seller_sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
              )
            """
            code_params = [*codes, *codes, *codes]
        sql = f"""
            SELECT
                date,
                UPPER(COALESCE(sku, '')) AS sku,
                UPPER(COALESCE(price_list_seller_sku, '')) AS seller_sku,
                COALESCE(store_name, '') AS store_name,
                UPPER(COALESCE(country_code, '')) AS country_code,
                UPPER(COALESCE(fnsku, '')) AS fnsku,
                SUM(COALESCE(volume, 0)) AS daily_sales_volume,
                SUM(COALESCE(spend, 0)) AS ad_spend,
                SUM(COALESCE(real_ad_cost, 0)) AS real_ad_cost,
                SUM(COALESCE(ad_sales_amount, 0)) AS ad_sales_amount,
                SUM(COALESCE(ad_order_quantity, 0)) AS ad_order_quantity,
                SUM(COALESCE(clicks, 0)) AS ad_clicks,
                SUM(COALESCE(impressions, 0)) AS ad_impressions,
                SUM(COALESCE(ads_sp_cost, 0)) AS ads_sp_cost,
                SUM(COALESCE(ads_sd_cost, 0)) AS ads_sd_cost,
                SUM(COALESCE(shared_ads_sb_cost, 0)) AS shared_ads_sb_cost,
                SUM(COALESCE(shared_ads_sbv_cost, 0)) AS shared_ads_sbv_cost
            FROM ads_lingxing_sc_sales_daily_new
            WHERE date BETWEEN %s AND %s
              {code_filter}
              AND (%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))
              AND (%s = '' OR COALESCE(store_name, '') = %s)
            GROUP BY
                date,
                UPPER(COALESCE(sku, '')),
                UPPER(COALESCE(price_list_seller_sku, '')),
                COALESCE(store_name, ''),
                UPPER(COALESCE(country_code, '')),
                UPPER(COALESCE(fnsku, ''))
        """
        country = (country_code or "").strip().upper()
        store = (store_name or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [sales_start_date, sales_end_date, *code_params, country, country, store, store])
                return list(cursor.fetchall())

    def get_monthly_forecast_snapshot_rows(
        self,
        material_codes: list[str],
        target_start_date: str,
        target_end_date: str,
        store_name: str | None = None,
        country_code: str | None = None,
        table_name: str = "ads_lingxing_all_warehouse_new_sh_v1",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return the latest monthly backup rows for a SKU in the target month."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        allowed_tables = {"ads_lingxing_all_warehouse_new_sh_v1"}
        if table_name not in allowed_tables:
            raise ValueError(f"unsupported monthly forecast table: {table_name}")
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        conditions = [
            "date BETWEEN %s AND %s",
            f"""(
                UPPER(COALESCE(sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
            )""",
            "(%s = '' OR COALESCE(store_name, '') = %s)",
            "(%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))",
        ]
        params: list[Any] = [
            target_start_date,
            target_end_date,
            *codes,
            *codes,
            *codes,
            (store_name or "").strip(),
            (store_name or "").strip(),
            (country_code or "").strip().upper(),
            (country_code or "").strip().upper(),
        ]
        where_sql = " AND ".join(conditions)
        sql = f"""
            SELECT
                sku,
                msku,
                fnsku,
                asin,
                store_name,
                country_code,
                shipments_country,
                sku_name,
                COALESCE(future_30d_sales, 0) AS future_30d_sales,
                COALESCE(sale_quantity_30, 0) AS sale_quantity_30,
                date
            FROM {table_name}
            WHERE {where_sql}
              AND date = (
                SELECT MAX(date)
                FROM {table_name}
                WHERE date BETWEEN %s AND %s
              )
            ORDER BY COALESCE(future_30d_sales, 0) DESC
            LIMIT {_bounded_limit(limit)}
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [*params, target_start_date, target_end_date])
                return list(cursor.fetchall())

    def get_monthly_sales_estimate_rows(
        self,
        material_codes: list[str],
        target_month: str,
        target_start_date: str,
        target_end_date: str,
        store_name: str | None = None,
        country_code: str | None = None,
        table_name: str = "dim_lingxing_sales_estimates_monthly_v1",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return monthly sales-estimate rows for the target natural month."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        allowed_tables = {"dim_lingxing_sales_estimates_monthly_v1"}
        if table_name not in allowed_tables:
            raise ValueError(f"unsupported sales estimate table: {table_name}")
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        sql = f"""
            SELECT
                month,
                date,
                week,
                sku,
                msku,
                fnsku,
                asin,
                store_name,
                country_code,
                COALESCE(daily_sales_quantity, 0) AS daily_sales_quantity,
                COALESCE(total, 0) AS total
            FROM {table_name}
            WHERE month = %s
              AND date BETWEEN %s AND %s
              AND (
                UPPER(COALESCE(sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
              )
              AND (%s = '' OR COALESCE(store_name, '') = %s)
              AND (%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))
            ORDER BY date, week
            LIMIT {_bounded_limit(limit)}
        """
        store = (store_name or "").strip()
        country = (country_code or "").strip().upper()
        params: list[Any] = [
            target_month,
            target_start_date,
            target_end_date,
            *codes,
            *codes,
            *codes,
            store,
            store,
            country,
            country,
        ]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = "temp_lingxing_pici_sale") -> list[dict[str, Any]]:
        """Return batch inventory/forecast gap rows used for shortage investigation."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        allowed_tables = {"temp_lingxing_pici_sale"}
        if table_name not in allowed_tables:
            raise ValueError(f"unsupported pici shortage table: {table_name}")
        sql = f"""
            SELECT
                fnsku,
                store_name,
                fnsku_inventory_1,
                chazhi_0_7,
                chazhi_0_14,
                chazhi_0_21,
                chazhi_0_28,
                chazhi_0_35,
                chazhi_0_42,
                chazhi_0_49,
                chazhi_0_56,
                chazhi_0_63,
                chazhi_0_70,
                chazhi_0_77,
                chazhi_0_84,
                chazhi_0_98
            FROM {table_name}
            WHERE (%s = '' OR COALESCE(store_name, '') = %s)
        """
        store = (store_name or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, (store, store))
                return list(cursor.fetchall())

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
        LIMIT {_bounded_limit(spec.limit, spec)}
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
            LIMIT {_bounded_limit(spec.limit, spec)}
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

    for field in ("country_code", "shipments_country", "store_name"):
        values = _safe_filter_values(filters.get(field), max_values=20)
        if values:
            placeholders = ", ".join(["%s"] * len(values))
            clauses.append(f"{field} IN ({placeholders})")
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


def _safe_filter_values(value: Any, max_values: int = 20) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple, set)):
        values = [str(item) for item in value]
    else:
        values = [str(value)]
    clean = []
    for item in values:
        text = item.strip()
        if text and len(text) <= 80:
            clean.append(text)
    return list(dict.fromkeys(clean))[:max_values]


def _bounded_limit(limit: int, spec: QuerySpec | None = None) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = ALL_WAREHOUSE_CATALOG.default_limit
    max_limit = 20000 if spec and spec.intent in {"inventory_control_tower", "inventory_monitoring_export"} else 500
    return max(1, min(value, max_limit))
