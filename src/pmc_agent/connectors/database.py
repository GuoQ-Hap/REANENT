from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from functools import wraps
import inspect
import os
from typing import Any, Callable, TypeVar

from pmc_agent.app_logging import get_logger, log_extra
from pmc_agent.connectors.base import ConnectorLogMixin
from pmc_agent.domain import InventorySnapshot, Material
from pmc_agent.env import load_env_file
from pmc_agent.query_cache import BOTTOM_TABLE_QUERY_CACHE, bottom_table_force_refresh
from pmc_agent.query_spec import QuerySpec
from pmc_agent.schema_catalog import ALL_WAREHOUSE_CATALOG, FieldPack, normalize_field_pack


logger = get_logger(__name__)
T = TypeVar("T")


def _number(value: Any) -> float:
    if value is None:
        return 0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0


def _marketplace_values(country_code: str | None) -> list[str]:
    code = (country_code or "").strip().upper()
    if not code:
        return []
    mapping = {
        "US": ["美国", "US", "United States", "USA"],
        "CA": ["加拿大", "CA", "Canada"],
        "MX": ["墨西哥", "MX", "Mexico"],
        "BR": ["巴西", "BR", "Brazil"],
        "GB": ["英国", "UK", "GB", "United Kingdom"],
        "DE": ["德国", "DE", "Germany"],
        "FR": ["法国", "FR", "France"],
        "IT": ["意大利", "IT", "Italy"],
        "ES": ["西班牙", "ES", "Spain"],
        "JP": ["日本", "JP", "Japan"],
    }
    return mapping.get(code, [code])


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


def _cacheable_bottom_table(method: Callable[..., T]) -> Callable[..., T]:
    signature = inspect.signature(method)

    @wraps(method)
    def wrapper(self: "StiDatabaseConnector", *args: Any, **kwargs: Any) -> T:
        if not self.config.ready:
            return method(self, *args, **kwargs)
        bound = signature.bind(self, *args, **kwargs)
        bound.apply_defaults()
        params = {key: value for key, value in bound.arguments.items() if key != "self"}
        return self._cached_bottom_table_value(method.__name__, params, lambda: method(self, *args, **kwargs))

    return wrapper


class StiDatabaseConnector(ConnectorLogMixin):
    """只读连接 STI / dw_leang 数据库。

    当前首期只实现库存快照读取，主表为 ads_lingxing_all_warehouse_new。
    """

    connector_name = "sti_database"

    def __init__(self, config: StiDatabaseConfig | None = None) -> None:
        self.config = config or StiDatabaseConfig.from_env()
        self.last_resolved_aliases: list[str] = []

    def force_refreshing(self, enabled: bool = True):
        return bottom_table_force_refresh(enabled)

    def _cached_bottom_table_value(self, namespace: str, params: Any, loader: Callable[[], T]) -> T:
        return BOTTOM_TABLE_QUERY_CACHE.get_or_load(
            f"{self.connector_name}.{namespace}",
            {
                "database": {
                    "host": self.config.host,
                    "port": self.config.port,
                    "database": self.config.database,
                    "user": self.config.user,
                },
                "params": params,
            },
            loader,
        )

    def get_material(self, material_code: str) -> Material | None:
        snapshots = self.get_inventory_snapshot(material_code)
        if not snapshots:
            return None
        return Material(code=snapshots[0].material_code, name=snapshots[0].material_code)

    @_cacheable_bottom_table
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

    @_cacheable_bottom_table
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

    @_cacheable_bottom_table
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

    @_cacheable_bottom_table
    def get_inventory_filter_option_values(self, fields: tuple[str, ...], limit: int = 200) -> dict[str, list[str]]:
        """Return distinct non-empty option values for controlled inventory filters."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return {}
        allowed_fields = set(ALL_WAREHOUSE_CATALOG.identity_fields)
        safe_fields = [field for field in dict.fromkeys(fields) if field in allowed_fields]
        if not safe_fields:
            return {}
        bounded_limit = _bounded_limit(limit)
        result: dict[str, list[str]] = {}
        with self._connect() as conn:
            with conn.cursor() as cursor:
                for field in safe_fields:
                    cursor.execute(
                        f"""
                        SELECT DISTINCT {field} AS value
                        FROM {ALL_WAREHOUSE_CATALOG.table_name}
                        WHERE COALESCE({field}, '') <> ''
                        ORDER BY {field}
                        LIMIT {bounded_limit}
                        """
                    )
                    result[field] = [str(row.get("value") or "").strip() for row in cursor.fetchall() if row.get("value")]
        return result

    @_cacheable_bottom_table
    def get_product_weight_rows(
        self,
        material_codes: list[str],
        store_name: str | None = None,
        country_code: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return SKU unit weight from dim_lingxing_product_info.weight_gram."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        store = (store_name or "").strip()
        country = (country_code or "").strip().upper()
        sql = f"""
            SELECT
                sku,
                msku,
                fnsku,
                asin,
                sku_name,
                store_name,
                country_code,
                weight_gram,
                size_length_cm,
                size_width_cm,
                size_height_cm
            FROM dim_lingxing_product_info
            WHERE COALESCE(weight_gram, 0) > 0
              AND (
                UPPER(COALESCE(sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
              )
            ORDER BY
                CASE WHEN %s <> '' AND COALESCE(store_name, '') = %s THEN 0 ELSE 1 END,
                CASE WHEN %s <> '' AND UPPER(COALESCE(country_code, '')) = UPPER(%s) THEN 0 ELSE 1 END,
                weight_gram DESC
            LIMIT {_bounded_limit(limit)}
        """
        params: list[Any] = [
            *codes,
            *codes,
            *codes,
            *codes,
            store,
            store,
            country,
            country,
        ]
        self.log_query_started("product_weight_lookup")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = list(cursor.fetchall())
        self.log_query_completed("product_weight_lookup", len(rows))
        return rows

    @_cacheable_bottom_table
    def get_current_month_profit_summary(
        self,
        material_codes: list[str],
        store_name: str | None = None,
        country_code: str | None = None,
        report_month: str | None = None,
    ) -> dict[str, Any]:
        """Return current-month MSKU profit summary converted to CNY when rates are available."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return {"ok": False, "reason": "STI 数据库未启用，无法读取本月利润。"}
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return {"ok": False, "reason": "缺少 SKU/MSKU/FNSKU/ASIN，无法读取本月利润。"}
        month = (report_month or date.today().strftime("%Y-%m")).strip()[:7]
        today_month = date.today().strftime("%Y-%m")
        end_date_limit = date.today().isoformat() if month == today_month else ""
        placeholders = ", ".join(["%s"] * len(codes))
        store = (store_name or "").strip()
        country = (country_code or "").strip().upper()
        sql = f"""
            SELECT
                report_date_month,
                currency_code,
                MIN(`date`) AS start_date,
                MAX(`date`) AS end_date,
                MAX(msku) AS msku,
                MAX(local_sku) AS local_sku,
                MAX(asin) AS asin,
                GROUP_CONCAT(DISTINCT store_name) AS store_names,
                GROUP_CONCAT(DISTINCT country_code) AS country_codes,
                SUM(COALESCE(total_sales_quantity, 0)) AS total_sales_quantity,
                SUM(COALESCE(total_sales_amount, 0)) AS total_sales_amount,
                SUM(COALESCE(gross_profit_income, 0)) AS gross_profit_income,
                SUM(COALESCE(gross_profit, 0)) AS gross_profit
            FROM dwd_lingxing_sc_profit_report_msku_incr
            WHERE report_date_month = %s
              AND (%s = '' OR `date` <= %s)
              AND (
                UPPER(COALESCE(msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(local_sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
              )
              AND (%s = '' OR COALESCE(store_name, '') = %s)
              AND (%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))
            GROUP BY report_date_month, currency_code
        """
        params: list[Any] = [month, end_date_limit, end_date_limit, *codes, *codes, *codes, store, store, country, country]
        self.log_query_started("current_month_profit_summary")
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = list(cursor.fetchall())
                rates = self._currency_rates_for_month(cursor, month, [str(row.get("currency_code") or "") for row in rows])
        if not rows:
            self.log_query_completed("current_month_profit_summary", 0)
            return {
                "ok": False,
                "report_month": month,
                "reason": "本月利润表暂无该 SKU/MSKU/FNSKU/ASIN 的记录。",
                "source_table": "dwd_lingxing_sc_profit_report_msku_incr",
            }
        summary = _build_current_month_profit_summary(rows, rates, month)
        self.log_query_completed("current_month_profit_summary", len(rows))
        return summary

    def _currency_rates_for_month(self, cursor: Any, report_month: str, currency_codes: list[str]) -> dict[str, float]:
        codes = [code.strip().upper() for code in currency_codes if code and code.strip()]
        codes = list(dict.fromkeys(code for code in codes if code not in {"CNY", "RMB"}))
        rates: dict[str, float] = {"CNY": 1.0, "RMB": 1.0}
        if not codes:
            return rates
        placeholders = ", ".join(["%s"] * len(codes))
        cursor.execute(
            f"""
            SELECT code, my_rate, rate_org
            FROM dwd_lingxing_sc_rate
            WHERE `date` = %s
              AND UPPER(code) IN ({placeholders})
            """,
            [f"{report_month}-01", *codes],
        )
        for row in cursor.fetchall():
            code = str(row.get("code") or "").strip().upper()
            rate = _number(row.get("my_rate")) or _number(row.get("rate_org"))
            if code and rate:
                rates[code] = rate
        return rates

    @_cacheable_bottom_table
    def get_first_leg_shipment_rows(
        self,
        material_codes: list[str],
        latest_only: bool = True,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return first-leg shipment records joined back to SKU/MSKU/FNSKU identities."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        bounded_limit = _bounded_limit(limit)
        rows: list[dict[str, Any]] = []
        with self._connect() as conn:
            rows.extend(self._get_first_leg_rows_from_in_transit(conn, codes, latest_only, bounded_limit))
            rows.extend(
                self._get_first_leg_rows_from_fba_detail(
                    conn,
                    codes,
                    latest_only,
                    bounded_limit,
                )
            )
        return _dedupe_first_leg_rows(rows)[:bounded_limit]

    def _get_first_leg_rows_from_in_transit(
        self,
        conn: Any,
        codes: list[str],
        latest_only: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not codes or limit <= 0:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        latest_filter = "AND f.date = (SELECT MAX(date) FROM feishu_first_leg_shipment_records)" if latest_only else ""
        sql = f"""
            SELECT DISTINCT
                'in_transit_package' AS source_relation,
                'in_transit_shipment_records' AS detail_source_table,
                r.sku,
                r.msku,
                r.fnsku,
                '' AS asin,
                r.batch_num,
                r.package_id,
                r.shipment_time,
                COALESCE(r.ship_num, 0) AS ship_num,
                COALESCE(r.in_transit_qty, 0) AS in_transit_qty,
                COALESCE(r.quantity_received, 0) AS quantity_received,
                r.logistics_provider AS detail_logistics_provider,
                '' AS detail_status,
                f.date AS first_leg_snapshot_date,
                f.logistics_tracking_number,
                f.warehouse_inbound_number,
                f.account_or_shipping_round,
                f.ship_id,
                f.refer_id,
                f.purchase_order_number,
                f.supplier_ready_time,
                f.logistics_pickup_time,
                f.origin_location,
                f.destination_country,
                f.logistics_provider,
                f.shipping_method,
                f.port_of_loading,
                f.port_of_discharge,
                f.destination_warehouse_type,
                f.destination_warehouse,
                f.package_count,
                f.total_item_count,
                f.packing_list_actual_weight,
                f.packing_list_volumetric_weight_or_cubic_meters,
                f.chargeable_weight_kg_or_cbm,
                f.unit_price,
                f.total_shipping_cost,
                f.cost_per_item_rmb,
                f.estimated_departure_time,
                f.actual_departure_date,
                f.estimated_arrival_time,
                f.actual_arrival_time,
                f.plan_delivery_time,
                f.estimated_delivery_time,
                f.actual_delivery_time,
                f.delivery_timeliness,
                f.current_shipping_status,
                f.exception,
                f.putaway_warehouse,
                f.house_bill_of_lading_number,
                f.container_number,
                f.shipping_cycle,
                f.postal_code,
                f.remarks
            FROM in_transit_shipment_records r
            JOIN feishu_first_leg_shipment_records f
              ON UPPER(TRIM(r.package_id)) = UPPER(TRIM(f.ship_id))
            WHERE (
                UPPER(COALESCE(r.sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(r.msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(r.fnsku, '')) IN ({placeholders})
            )
              AND COALESCE(TRIM(r.package_id), '') <> ''
              AND COALESCE(TRIM(f.ship_id), '') <> ''
              {latest_filter}
            ORDER BY
                first_leg_snapshot_date DESC,
                COALESCE(actual_delivery_time, plan_delivery_time, actual_arrival_time, estimated_delivery_time, estimated_arrival_time) DESC
            LIMIT {_bounded_limit(limit)}
        """
        params = [*codes, *codes, *codes]
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    def _get_first_leg_rows_from_fba_detail(
        self,
        conn: Any,
        codes: list[str],
        latest_only: bool,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not codes or limit <= 0:
            return []
        rows: list[dict[str, Any]] = []
        join_paths = (
            ("fba_shipment_confirmation", "UPPER(TRIM(d.shipment_confirmation_id)) = UPPER(TRIM(f.ship_id))"),
            ("fba_reference", "UPPER(TRIM(d.amazon_reference_id)) = UPPER(TRIM(f.refer_id))"),
        )
        for relation, join_condition in join_paths:
            remaining = limit - len(rows)
            if remaining <= 0:
                break
            rows.extend(
                self._get_first_leg_rows_from_fba_detail_path(
                    conn,
                    codes,
                    latest_only,
                    remaining,
                    relation,
                    join_condition,
                )
            )
        return rows

    def _get_first_leg_rows_from_fba_detail_path(
        self,
        conn: Any,
        codes: list[str],
        latest_only: bool,
        limit: int,
        source_relation: str,
        join_condition: str,
    ) -> list[dict[str, Any]]:
        placeholders = ", ".join(["%s"] * len(codes))
        latest_filter = "AND f.date = (SELECT MAX(date) FROM feishu_first_leg_shipment_records)" if latest_only else ""
        sql = f"""
            SELECT DISTINCT
                '{source_relation}' AS source_relation,
                'dwd_lingxing_fba_report_shipment_detail_incr' AS detail_source_table,
                d.sku,
                d.msku,
                d.fnsku,
                d.asin,
                '' AS batch_num,
                d.shipment_confirmation_id AS package_id,
                d.shiping_time AS shipment_time,
                COALESCE(d.quantity, 0) AS ship_num,
                NULL AS in_transit_qty,
                NULL AS quantity_received,
                '' AS detail_logistics_provider,
                d.status AS detail_status,
                f.date AS first_leg_snapshot_date,
                f.logistics_tracking_number,
                f.warehouse_inbound_number,
                f.account_or_shipping_round,
                f.ship_id,
                f.refer_id,
                f.purchase_order_number,
                f.supplier_ready_time,
                f.logistics_pickup_time,
                f.origin_location,
                f.destination_country,
                f.logistics_provider,
                f.shipping_method,
                f.port_of_loading,
                f.port_of_discharge,
                f.destination_warehouse_type,
                f.destination_warehouse,
                f.package_count,
                f.total_item_count,
                f.packing_list_actual_weight,
                f.packing_list_volumetric_weight_or_cubic_meters,
                f.chargeable_weight_kg_or_cbm,
                f.unit_price,
                f.total_shipping_cost,
                f.cost_per_item_rmb,
                f.estimated_departure_time,
                f.actual_departure_date,
                f.estimated_arrival_time,
                f.actual_arrival_time,
                f.plan_delivery_time,
                f.estimated_delivery_time,
                f.actual_delivery_time,
                f.delivery_timeliness,
                f.current_shipping_status,
                f.exception,
                f.putaway_warehouse,
                f.house_bill_of_lading_number,
                f.container_number,
                f.shipping_cycle,
                f.postal_code,
                f.remarks
            FROM dwd_lingxing_fba_report_shipment_detail_incr d
            JOIN feishu_first_leg_shipment_records f
              ON {join_condition}
            WHERE (
                UPPER(COALESCE(d.sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(d.msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(d.fnsku, '')) IN ({placeholders})
                OR UPPER(COALESCE(d.asin, '')) IN ({placeholders})
            )
              {latest_filter}
            ORDER BY
                first_leg_snapshot_date DESC,
                COALESCE(actual_delivery_time, plan_delivery_time, actual_arrival_time, estimated_delivery_time, estimated_arrival_time) DESC
            LIMIT {_bounded_limit(limit)}
        """
        params = [*codes, *codes, *codes, *codes]
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            return list(cursor.fetchall())

    @_cacheable_bottom_table
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

    @_cacheable_bottom_table
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

    @_cacheable_bottom_table
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
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
              )
            """
            code_params = [*codes, *codes, *codes, *codes]
        sql = f"""
            SELECT
                date,
                UPPER(COALESCE(sku, '')) AS sku,
                UPPER(COALESCE(price_list_seller_sku, '')) AS seller_sku,
                COALESCE(store_name, '') AS store_name,
                UPPER(COALESCE(country_code, '')) AS country_code,
                UPPER(COALESCE(fnsku, '')) AS fnsku,
                UPPER(COALESCE(asin, '')) AS asin,
                SUM(COALESCE(volume, 0)) AS daily_sales_volume,
                SUM(COALESCE(amount, 0)) AS daily_sales_amount,
                SUM(COALESCE(net_amount, 0)) AS daily_net_amount,
                AVG(NULLIF(selling_price_plan, 0)) AS selling_price_plan,
                MIN(COALESCE(currency_code, '')) AS currency_code,
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
                UPPER(COALESCE(fnsku, '')),
                UPPER(COALESCE(asin, ''))
        """
        country = (country_code or "").strip().upper()
        store = (store_name or "").strip()
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [sales_start_date, sales_end_date, *code_params, country, country, store, store])
                return list(cursor.fetchall())

    @_cacheable_bottom_table
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
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
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
                WHERE {where_sql}
              )
            ORDER BY COALESCE(future_30d_sales, 0) DESC
            LIMIT {_bounded_limit(limit)}
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [*params, *params])
                return list(cursor.fetchall())

    @_cacheable_bottom_table
    def get_current_sales_forecast_rows(
        self,
        material_codes: list[str],
        snapshot_start_date: str,
        snapshot_end_date: str,
        store_name: str | None = None,
        country_code: str | None = None,
        table_name: str = "ads_lingxing_all_warehouse_new_sh_v1",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return current forecast horizons from the latest available inventory snapshot."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        allowed_tables = {"ads_lingxing_all_warehouse_new_sh_v1"}
        if table_name not in allowed_tables:
            raise ValueError(f"unsupported current forecast table: {table_name}")
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
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
            )""",
            "(%s = '' OR COALESCE(store_name, '') = %s)",
            "(%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))",
        ]
        params: list[Any] = [
            snapshot_start_date,
            snapshot_end_date,
            *codes,
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
                COALESCE(future_30d_sales, 0) AS future_30d_sales,
                COALESCE(future_60d_sales, 0) AS future_60d_sales,
                COALESCE(future_90d_sales, 0) AS future_90d_sales,
                date
            FROM {table_name}
            WHERE {where_sql}
              AND date = (
                SELECT MAX(date)
                FROM {table_name}
                WHERE {where_sql}
              )
            ORDER BY COALESCE(future_90d_sales, future_60d_sales, future_30d_sales, 0) DESC
            LIMIT {_bounded_limit(limit)}
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [*params, *params])
                rows = list(cursor.fetchall())
                if rows:
                    return rows
        return self._get_current_forecast_from_main_rows(
            material_codes=codes,
            store_name=store_name,
            country_code=country_code,
            limit=limit,
        )

    @_cacheable_bottom_table
    def get_weekly_sales_estimate_rows(
        self,
        material_codes: list[str],
        version_start_date: str,
        version_end_date: str,
        target_start_date: str,
        target_end_date: str,
        store_name: str | None = None,
        country_code: str | None = None,
        table_name: str = "ods_lingxing_sales_estimates_monthly_v1",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return weekly forecast rows from the latest snapshot in a version month."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        allowed_tables = {"ods_lingxing_sales_estimates_monthly_v1", "ods_lingxing_sales_estimates_monthly"}
        if table_name not in allowed_tables:
            raise ValueError(f"unsupported weekly sales estimate table: {table_name}")
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
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
            )""",
            "(%s = '' OR COALESCE(store_name, '') = %s)",
            """(
                %s = ''
                OR UPPER(COALESCE(country_code, '')) = UPPER(%s)
                OR UPPER(COALESCE(channel, '')) = UPPER(%s)
            )""",
        ]
        country = (country_code or "").strip().upper()
        params: list[Any] = [
            version_start_date,
            version_end_date,
            *codes,
            *codes,
            *codes,
            *codes,
            (store_name or "").strip(),
            (store_name or "").strip(),
            country,
            country,
            country,
        ]
        where_sql = " AND ".join(conditions)
        sql = f"""
            SELECT
                date AS snapshot_date,
                year,
                month,
                start_date,
                end_date,
                sku,
                msku,
                fnsku,
                asin,
                store_name,
                country_code,
                channel,
                COALESCE(value, 0) AS value,
                COALESCE(value, 0) AS forecast_quantity
            FROM {table_name}
            WHERE {where_sql}
              AND date = (
                SELECT MAX(date)
                FROM {table_name}
                WHERE {where_sql}
              )
              AND start_date <= %s
              AND end_date >= %s
            ORDER BY start_date, end_date
            LIMIT {_bounded_limit(limit)}
        """
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, [*params, *params, target_end_date, target_start_date])
                return list(cursor.fetchall())

    def _get_current_forecast_from_main_rows(
        self,
        material_codes: list[str],
        store_name: str | None = None,
        country_code: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        sql = f"""
            SELECT
                sku,
                msku,
                fnsku,
                asin,
                store_name,
                country_code,
                COALESCE(future_30d_sales, 0) AS future_30d_sales,
                COALESCE(future_60d_sales, 0) AS future_60d_sales,
                COALESCE(future_90d_sales, 0) AS future_90d_sales,
                '' AS date
            FROM {ALL_WAREHOUSE_CATALOG.table_name}
            WHERE (
                UPPER(COALESCE(sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(msku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
            )
              AND (%s = '' OR COALESCE(store_name, '') = %s)
              AND (%s = '' OR UPPER(COALESCE(country_code, '')) = UPPER(%s))
            ORDER BY COALESCE(future_90d_sales, future_60d_sales, future_30d_sales, 0) DESC
            LIMIT {_bounded_limit(limit)}
        """
        params: list[Any] = [
            *codes,
            *codes,
            *codes,
            *codes,
            (store_name or "").strip(),
            (store_name or "").strip(),
            (country_code or "").strip().upper(),
            (country_code or "").strip().upper(),
        ]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    @_cacheable_bottom_table
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
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
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

    @_cacheable_bottom_table
    def get_daily_listing_price_rows(
        self,
        material_codes: list[str],
        start_date: str,
        end_date: str,
        store_name: str | None = None,
        country_code: str | None = None,
        table_name: str = "ods_lingxing_sc_listing",
        limit: int = 1200,
    ) -> list[dict[str, Any]]:
        """Return daily Listing price snapshots for a SKU/date range."""

        if not self.config.ready:
            logger.info("database connector disabled", extra=log_extra("database_connector_disabled"))
            return []
        allowed_tables = {"ods_lingxing_sc_listing"}
        if table_name not in allowed_tables:
            raise ValueError(f"unsupported listing price table: {table_name}")
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        marketplace_values = _marketplace_values(country_code)
        marketplace_filter = ""
        marketplace_params: list[Any] = []
        if marketplace_values:
            marketplace_placeholders = ", ".join(["%s"] * len(marketplace_values))
            marketplace_filter = f"AND COALESCE(marketplace, '') IN ({marketplace_placeholders})"
            marketplace_params = marketplace_values
        sql = f"""
            SELECT
                date,
                COALESCE(AVG(NULLIF(price, 0)), AVG(NULLIF(listing_price, 0)), AVG(NULLIF(landed_price, 0))) AS price,
                AVG(NULLIF(listing_price, 0)) AS listing_price,
                AVG(NULLIF(landed_price, 0)) AS landed_price,
                MIN(COALESCE(currency_code, '')) AS currency_code,
                COUNT(*) AS source_row_count
            FROM {table_name}
            WHERE date BETWEEN %s AND %s
              AND (
                UPPER(COALESCE(seller_sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(local_sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
                OR UPPER(COALESCE(asin, '')) IN ({placeholders})
              )
              {marketplace_filter}
            GROUP BY date
            ORDER BY date
            LIMIT {_bounded_limit(limit)}
        """
        params: list[Any] = [
            start_date,
            end_date,
            *codes,
            *codes,
            *codes,
            *codes,
            *marketplace_params,
        ]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                rows = list(cursor.fetchall())
                if rows:
                    return rows
        return self._get_daily_price_band_rows(
            material_codes=codes,
            start_date=start_date,
            end_date=end_date,
            store_name=store_name,
            limit=limit,
        )

    def _get_daily_price_band_rows(
        self,
        material_codes: list[str],
        start_date: str,
        end_date: str,
        store_name: str | None = None,
        limit: int = 1200,
    ) -> list[dict[str, Any]]:
        codes = [code.strip().upper() for code in material_codes if code and code.strip()]
        codes = list(dict.fromkeys(codes))
        if not codes:
            return []
        placeholders = ", ".join(["%s"] * len(codes))
        store = (store_name or "").strip()
        sql = f"""
            SELECT
                date,
                AVG(NULLIF(current_price, 0)) AS price,
                AVG(NULLIF(current_price, 0)) AS listing_price,
                NULL AS landed_price,
                '' AS currency_code,
                COUNT(*) AS source_row_count
            FROM tmp_price_band_tag
            WHERE date BETWEEN %s AND %s
              AND (
                UPPER(COALESCE(price_list_seller_sku, '')) IN ({placeholders})
                OR UPPER(COALESCE(fnsku, '')) IN ({placeholders})
                OR UPPER(COALESCE(asins_asin, '')) IN ({placeholders})
              )
              AND (%s = '' OR COALESCE(store_name, '') = %s)
            GROUP BY date
            ORDER BY date
            LIMIT {_bounded_limit(limit)}
        """
        params: list[Any] = [start_date, end_date, *codes, *codes, *codes, store, store]
        with self._connect() as conn:
            with conn.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())

    @_cacheable_bottom_table
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


def _dedupe_first_leg_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for row in rows:
        shipment_key = _norm_text(
            row.get("ship_id")
            or row.get("package_id")
            or row.get("warehouse_inbound_number")
            or row.get("refer_id")
            or row.get("logistics_tracking_number")
        )
        identity_values = tuple(
            value
            for value in (
                _norm_text(row.get("sku")),
                _norm_text(row.get("msku")),
                _norm_text(row.get("fnsku")),
            )
            if value
        )
        if not identity_values:
            identity_values = tuple(value for value in (_norm_text(row.get("asin")),) if value)
        key = (shipment_key, identity_values)
        existing = seen.get(key)
        if existing is not None:
            _merge_first_leg_duplicate(existing, row)
            continue
        seen[key] = row
        deduped.append(row)
    return deduped


def _merge_first_leg_duplicate(target: dict[str, Any], source: dict[str, Any]) -> None:
    source_ship_num = _number(source.get("ship_num"))
    if _number(target.get("ship_num")) <= 0 < source_ship_num:
        target["ship_num"] = source.get("ship_num")
        target["quantity_source_relation"] = source.get("source_relation")
        target["quantity_source_table"] = source.get("detail_source_table")
    if _number(target.get("in_transit_qty")) <= 0 and _number(target.get("quantity_received")) <= 0:
        source_status = _norm_text(source.get("detail_status"))
        if source_status == "SHIPPED" and source_ship_num > 0:
            target["in_transit_qty"] = source.get("ship_num")
    for field in ("asin", "detail_status", "shipment_time"):
        if not target.get(field) and source.get(field):
            target[field] = source.get(field)


def _build_current_month_profit_summary(rows: list[dict[str, Any]], rates: dict[str, float], report_month: str) -> dict[str, Any]:
    total_quantity = 0.0
    total_amount = 0.0
    gross_profit_income = 0.0
    gross_profit = 0.0
    gross_profit_income_cny = 0.0
    gross_profit_cny = 0.0
    currencies: list[str] = []
    missing_rate_codes: list[str] = []
    start_dates: list[Any] = []
    end_dates: list[Any] = []
    store_names: list[str] = []
    country_codes: list[str] = []

    for row in rows:
        currency_code = str(row.get("currency_code") or "").strip().upper() or "UNKNOWN"
        if currency_code not in currencies:
            currencies.append(currency_code)
        if row.get("start_date"):
            start_dates.append(row.get("start_date"))
        if row.get("end_date"):
            end_dates.append(row.get("end_date"))
        store_names.extend(_split_concat_values(row.get("store_names")))
        country_codes.extend(_split_concat_values(row.get("country_codes")))

        quantity = _number(row.get("total_sales_quantity"))
        income = _number(row.get("gross_profit_income"))
        profit = _number(row.get("gross_profit"))
        amount = _number(row.get("total_sales_amount"))
        total_quantity += quantity
        total_amount += amount
        gross_profit_income += income
        gross_profit += profit

        rate = rates.get(currency_code)
        if rate is None:
            missing_rate_codes.append(currency_code)
            continue
        gross_profit_income_cny += income * rate
        gross_profit_cny += profit * rate

    gross_profit_cost = gross_profit_income - gross_profit
    gross_profit_cost_cny = gross_profit_income_cny - gross_profit_cny
    gross_rate = gross_profit / gross_profit_income if gross_profit_income else None
    gross_rate_cny = gross_profit_cny / gross_profit_income_cny if gross_profit_income_cny else None
    profit_rate_on_cost = gross_profit / gross_profit_cost if gross_profit_cost else None
    profit_rate_on_cost_cny = gross_profit_cny / gross_profit_cost_cny if gross_profit_cost_cny else None
    average_unit_revenue_cny = gross_profit_income_cny / total_quantity if total_quantity else None
    rate_payload = {code: round(value, 6) for code, value in rates.items() if code in currencies}
    missing_rate_codes = list(dict.fromkeys(code for code in missing_rate_codes if code not in {"UNKNOWN"}))
    start_date = min(start_dates).isoformat() if start_dates else None
    end_date = max(end_dates).isoformat() if end_dates else None
    month_days, elapsed_days, projection_factor = _current_month_projection_window(report_month, end_date)

    return {
        "ok": True,
        "report_month": report_month,
        "start_date": start_date,
        "end_date": end_date,
        "month_days": month_days,
        "elapsed_days": elapsed_days,
        "month_projection_factor": round(projection_factor, 6),
        "source_table": "dwd_lingxing_sc_profit_report_msku_incr",
        "rate_table": "dwd_lingxing_sc_rate",
        "currency_codes": currencies,
        "store_names": list(dict.fromkeys(store_names)),
        "country_codes": list(dict.fromkeys(country_codes)),
        "total_sales_quantity": round(total_quantity, 2),
        "total_sales_amount": round(total_amount, 2),
        "gross_profit_income": round(gross_profit_income, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_profit_cost": round(gross_profit_cost, 2),
        "gross_rate": round(gross_rate, 4) if gross_rate is not None else None,
        "profit_rate_on_cost": round(profit_rate_on_cost, 4) if profit_rate_on_cost is not None else None,
        "gross_profit_income_cny": round(gross_profit_income_cny, 2),
        "gross_profit_cny": round(gross_profit_cny, 2),
        "gross_profit_cost_cny": round(gross_profit_cost_cny, 2),
        "gross_rate_cny": round(gross_rate_cny, 4) if gross_rate_cny is not None else None,
        "profit_rate_on_cost_cny": round(profit_rate_on_cost_cny, 4) if profit_rate_on_cost_cny is not None else None,
        "projected_gross_profit_cny": round(gross_profit_cny * projection_factor, 2),
        "projected_gross_profit_cost_cny": round(gross_profit_cost_cny * projection_factor, 2),
        "average_unit_revenue_cny": round(average_unit_revenue_cny, 2) if average_unit_revenue_cny is not None else None,
        "rates_to_cny": rate_payload,
        "missing_rate_codes": missing_rate_codes,
        "formula": "profit_rate_on_cost = SUM(gross_profit * rate_to_cny) / (SUM(gross_profit_income * rate_to_cny) - SUM(gross_profit * rate_to_cny)); current month projected by month_days / elapsed_days",
    }


def _current_month_projection_window(report_month: str, end_date: str | None) -> tuple[int, int, float]:
    try:
        year, month = [int(part) for part in report_month.split("-", 1)]
        month_days = monthrange(year, month)[1]
    except (TypeError, ValueError):
        return 0, 0, 1.0
    if report_month != date.today().strftime("%Y-%m"):
        return month_days, month_days, 1.0
    end_day = 0
    if end_date:
        try:
            end_day = int(str(end_date)[:10].split("-")[2])
        except (IndexError, ValueError):
            end_day = 0
    if end_day <= 0:
        end_day = date.today().day
    elapsed_days = max(1, min(end_day, month_days))
    return month_days, elapsed_days, month_days / elapsed_days


def _split_concat_values(value: Any) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item and item.strip()]


def _norm_text(value: Any) -> str:
    return str(value or "").strip().upper()


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

    filter_fields = {
        "country_code": ("country_code",),
        "shipments_country": ("shipments_country",),
        "store_name": ("store_name",),
        "seasonality": ("seasonality",),
        "sales_apartment": ("sales_apartment", "sales_department"),
        "salesman": ("salesman", "sales_person"),
        "product_manager": ("product_manager",),
        "seller_id": ("seller_id",),
        "msku_product_property": ("msku_product_property", "product_property"),
        "msku_status": ("msku_status",),
    }
    for field, aliases in filter_fields.items():
        raw_value = next((filters.get(alias) for alias in aliases if not _is_blank_filter_value(filters.get(alias))), None)
        values = _safe_filter_values(raw_value, max_values=20)
        if values:
            placeholders = ", ".join(["%s"] * len(values))
            clauses.append(f"{field} IN ({placeholders})")
            params.extend(values)

    life_values = _safe_filter_values(filters.get("msku_life_process"), max_values=20)
    if life_values:
        life_clauses: list[str] = []
        explicit_values = [value for value in life_values if value != "非新品期"]
        if explicit_values:
            placeholders = ", ".join(["%s"] * len(explicit_values))
            life_clauses.append(f"msku_life_process IN ({placeholders})")
            params.extend(explicit_values)
        if "非新品期" in life_values:
            life_clauses.append("COALESCE(msku_life_process, '') <> %s")
            params.append("新品期")
        if life_clauses:
            clauses.append("(" + " OR ".join(life_clauses) + ")")

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


def _is_blank_filter_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value == ""
    if isinstance(value, (list, tuple, set)):
        return not any(str(item).strip() for item in value)
    return False


def _bounded_limit(limit: int, spec: QuerySpec | None = None) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = ALL_WAREHOUSE_CATALOG.default_limit
    max_limit = 20000 if spec and spec.intent in {"inventory_control_tower", "inventory_monitoring_export"} else 500
    return max(1, min(value, max_limit))
