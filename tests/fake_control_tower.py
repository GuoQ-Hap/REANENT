from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pmc_agent.domain import InventorySnapshot


@dataclass(frozen=True)
class ReadyConfig:
    ready: bool = True


class FakeMainRuleConnector:
    config = ReadyConfig()

    def get_inventory_rows(self, query_spec):
        rows = [_stockout_row(), _overstock_row()]
        code = (query_spec.material_code or "").upper()
        if code == "B0BXD4MCCK":
            code = "A100"
        if code:
            rows = [row for row in rows if code in {row["sku"], row["msku"], row["fnsku"]}]
        return rows

    def get_daily_sales_rows(
        self,
        sales_start_date: str,
        sales_end_date: str | None = None,
        country_code: str | None = None,
        store_name: str | None = None,
    ):
        sales_end_date = sales_end_date or sales_start_date
        day_count = _day_count(sales_start_date, sales_end_date)
        rows = [
            {"sku": "A100", "seller_sku": "A100-US-BLK", "store_name": "Amazon US", "country_code": "US", "daily_sales_volume": 12 * day_count},
            {"sku": "B200", "seller_sku": "B200-US-RED", "store_name": "Amazon US", "country_code": "US", "daily_sales_volume": 2 * day_count},
        ]
        if country_code:
            rows = [row for row in rows if row["country_code"] == country_code]
        if store_name:
            rows = [row for row in rows if row["store_name"] == store_name]
        return rows

    def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
        rows = [
            _pici_row("X001A100", "Amazon US", "40/80(-40)"),
            _pici_row("X001B200", "Amazon US", "1200/20(1180)"),
        ]
        if store_name:
            rows = [row for row in rows if row["store_name"] == store_name]
        return rows

    def get_warehouse_inventory_rows(self, country_code: str | None = None, limit: int = 80):
        rows = [
            {
                "country_code": "US",
                "warehouse_code": "WPPA2",
                "warehouse_name": "WPPA2",
                "warehouse_display_name": "西邮智仓 WPPA2",
                "sku_count": 2,
                "product_total": 1000,
                "product_valid_num": 980,
                "product_lock_num": 20,
                "product_onway": 100,
            }
        ]
        if country_code:
            rows = [row for row in rows if row["country_code"] == country_code]
        return rows[:limit]

    def get_inventory_snapshot(self, material_code=None, field_pack=None, query_spec=None):
        rows = self.get_inventory_rows(query_spec or _Query(material_code))
        return [
            InventorySnapshot(
                material_code=row["sku"],
                on_hand=float(row["fba_warehouse_quantity"] + row["overseas_warehouse_quantity"] + row["local_warehouse_quantity"]),
                allocated=0,
                inbound=float(row.get("planned_quantity", 0) + row.get("afn_inbound_working_quantity", 0) + row.get("afn_inbound_receiving_quantity", 0)),
                demand_next_7d=float(row["sale_quantity_7"]),
                demand_next_30d=float(row["future_30d_sales"]),
            )
            for row in rows
        ]


@dataclass(frozen=True)
class _Query:
    material_code: str | None = None


def _stockout_row() -> dict[str, Any]:
    return {
        "sku": "A100",
        "msku": "A100-US-BLK",
        "fnsku": "X001A100",
        "asin": "B0A1000001",
        "sku_name": "Main board",
        "store_name": "Amazon US",
        "country_code": "US",
        "shipments_country": "US",
        "msku_sales_property": "旺",
        "seasonality": "常规",
        "afn_fulfillable_quantity": 32,
        "fba_warehouse_quantity": 40,
        "overseas_warehouse_quantity": 12,
        "local_warehouse_quantity": 80,
        "afn_inbound_receiving_quantity": 6,
        "afn_inbound_working_quantity": 8,
        "planned_quantity": 20,
        "sale_quantity_7": 110,
        "sale_quantity_30": 360,
        "future_30d_sales": 420,
        "order_duration": 5,
        "production_duration": 8,
        "local_to_FBA_time": 12,
    }


def _overstock_row() -> dict[str, Any]:
    return {
        "sku": "B200",
        "msku": "B200-US-RED",
        "fnsku": "X001B200",
        "asin": "B0B2000002",
        "sku_name": "Battery pack",
        "store_name": "Amazon US",
        "country_code": "US",
        "shipments_country": "US",
        "msku_sales_property": "滞",
        "seasonality": "常规",
        "afn_fulfillable_quantity": 520,
        "fba_warehouse_quantity": 560,
        "overseas_warehouse_quantity": 340,
        "local_warehouse_quantity": 260,
        "sale_quantity_7": 18,
        "sale_quantity_30": 80,
        "future_30d_sales": 70,
        "inv_age_181_to_270_days": 130,
        "inv_age_271_to_330_days": 80,
        "inv_age_365_plus_days": 50,
    }


def _pici_row(fnsku: str, store_name: str, value: str) -> dict[str, Any]:
    row = {"fnsku": fnsku, "store_name": store_name, "fnsku_inventory_1": 40}
    for horizon in (7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84, 98):
        row[f"chazhi_0_{horizon}"] = value
    return row


def _day_count(start: str, end: str) -> int:
    start_date = datetime.strptime(start, "%Y-%m-%d").date()
    end_date = datetime.strptime(end, "%Y-%m-%d").date()
    return (end_date - start_date).days + 1
