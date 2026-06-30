from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime
import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
SRC_ROOT = REPO_ROOT / "src"


def _bootstrap() -> None:
    import sys

    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))
    from pmc_agent.env import load_env_file

    load_env_file(override=False)


@dataclass
class CapitalRow:
    date: str
    warehouse: str
    type: str
    country: str
    sku: str
    fnsku: str
    status: str
    qty: float
    unitCost: float
    amount: float
    ageDays: float
    storageNext30: float


@dataclass
class LossRow:
    date: str
    warehouse: str
    type: str
    country: str
    sku: str
    fnsku: str
    kind: str
    qty: float
    unitCost: float
    stockLoss: float
    handlingFee: float
    recovery: float
    action: str


def _number(value: Any) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _date_text(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    return _text(value)[:10]


def _unit_cost(row: dict[str, Any]) -> float:
    for key in ("stock_price", "stock_cost", "purchase_price"):
        value = _number(row.get(key))
        if value:
            return value
    total = _number(row.get("product_total"))
    amount = _number(row.get("stock_cost_total"))
    return amount / total if total else 0.0


def _warehouse_type(value: Any) -> str:
    code = int(_number(value))
    if code == 1:
        return "本地仓"
    if code == 3:
        return "海外仓"
    if code == 4:
        return "FBA"
    if code == 6:
        return "AWD"
    return "其他"


def _country_from_name(name: str) -> str:
    upper = (name or "").upper()
    for code in ("US", "CA", "MX", "BR", "UK", "GB", "DE", "FR", "IT", "ES", "JP", "AU", "CN"):
        if f"-{code}" in upper or upper.endswith(code):
            return "UK" if code == "GB" else code
    if "美国" in name:
        return "US"
    if "英国" in name:
        return "UK"
    if "日本" in name:
        return "JP"
    if "加拿大" in name:
        return "CA"
    if "德国" in name:
        return "DE"
    return ""


def _fba_age_days(row: dict[str, Any]) -> float:
    buckets = [
        ("inv_age_0_to_30_days", 15),
        ("inv_age_31_to_60_days", 45),
        ("inv_age_61_to_90_days", 75),
        ("inv_age_91_to_180_days", 135),
        ("inv_age_181_to_270_days", 225),
        ("inv_age_271_to_330_days", 300),
        ("inv_age_331_to_365_days", 348),
        ("inv_age_365_plus_days", 390),
    ]
    total_qty = 0.0
    weighted = 0.0
    for key, midpoint in buckets:
        qty = _number(row.get(key))
        total_qty += qty
        weighted += qty * midpoint
    return round(weighted / total_qty, 1) if total_qty else 0.0


def _connect():
    import pymysql

    return pymysql.connect(
        host=os.getenv("STI_DB_HOST"),
        port=int(os.getenv("STI_DB_PORT", "9030")),
        user=os.getenv("STI_DB_USER"),
        password=os.getenv("STI_DB_PASSWORD"),
        database=os.getenv("STI_DB_NAME", "dw_leang"),
        charset=os.getenv("STI_DB_CHARSET", "utf8mb4"),
        connect_timeout=10,
        read_timeout=45,
        write_timeout=30,
        cursorclass=pymysql.cursors.DictCursor,
    )


def load_funds(limit: int = 320) -> dict[str, Any]:
    _bootstrap()
    limit = max(20, min(int(limit or 320), 1000))
    per_source = max(30, min(limit // 2, 500))

    with _connect() as conn:
        inventory_rows, fba_rows, ledger_rows, metadata = _query_source_rows(conn, per_source)

    capital_rows = _build_inventory_capital(inventory_rows)
    capital_rows.extend(_build_fba_capital(fba_rows))
    capital_rows.sort(key=lambda item: item.amount, reverse=True)
    capital_rows = capital_rows[:limit]

    unit_costs = _build_unit_cost_index(capital_rows)
    loss_rows = _build_inventory_losses(inventory_rows)
    loss_rows.extend(_build_fba_losses(fba_rows))
    loss_rows.extend(_build_ledger_losses(ledger_rows, unit_costs))
    loss_rows.sort(key=lambda item: item.stockLoss + item.handlingFee - item.recovery, reverse=True)
    loss_rows = loss_rows[:limit]

    return {
        "ok": True,
        "metadata": metadata,
        "capitalRows": [asdict(item) for item in capital_rows],
        "lossRows": [asdict(item) for item in loss_rows],
    }


def _query_source_rows(conn: Any, limit: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    with conn.cursor() as cursor:
        cursor.execute("SELECT MAX(date) AS value FROM dwd_lingxing_inventory_details")
        inventory_date = cursor.fetchone()["value"]
        cursor.execute("SELECT MAX(date) AS value FROM dwd_lingxing_fba_warehouse_detail")
        fba_date = cursor.fetchone()["value"]
        cursor.execute("SELECT MAX(date) AS value FROM dwd_lingxing_inventory_ledger_summary_incr")
        ledger_date = cursor.fetchone()["value"]

        cursor.execute(
            f"""
            SELECT
                d.date,
                d.wid,
                d.sku,
                d.fnsku,
                d.product_total,
                d.product_valid_num,
                d.product_bad_num,
                d.product_qc_num,
                d.product_lock_num,
                d.good_lock_num,
                d.bad_lock_num,
                d.stock_cost_total,
                d.stock_cost,
                d.product_onway,
                d.transit_head_cost,
                d.average_age,
                d.purchase_price,
                d.price,
                d.head_stock_price,
                d.stock_price,
                w.name AS warehouse_name,
                w.type AS warehouse_type_code,
                w.t_country_area_name,
                w.t_warehouse_code,
                w.t_warehouse_name,
                w.country_code
            FROM dwd_lingxing_inventory_details d
            LEFT JOIN (
                SELECT *
                FROM dwd_lingxing_sc_warehouse
                WHERE date = (SELECT MAX(date) FROM dwd_lingxing_sc_warehouse)
            ) w ON d.wid = w.wid
            WHERE d.date = %s
              AND COALESCE(d.product_total, 0) > 0
            ORDER BY COALESCE(d.stock_cost_total, 0) DESC
            LIMIT {limit}
            """,
            (inventory_date,),
        )
        inventory_rows = list(cursor.fetchall())

        cursor.execute(
            f"""
            SELECT *
            FROM dwd_lingxing_fba_warehouse_detail
            WHERE date = %s
              AND COALESCE(total, 0) > 0
            ORDER BY COALESCE(total_price, 0) DESC
            LIMIT {limit}
            """,
            (fba_date,),
        )
        fba_rows = list(cursor.fetchall())

        cursor.execute(
            f"""
            SELECT
                date,
                seller_id,
                fnsku,
                asin,
                msku,
                lost,
                damaged,
                disposed,
                other_events,
                location
            FROM dwd_lingxing_inventory_ledger_summary_incr
            WHERE date = %s
              AND (
                COALESCE(lost, 0) <> 0
                OR COALESCE(damaged, 0) <> 0
                OR COALESCE(disposed, 0) <> 0
              )
            ORDER BY ABS(COALESCE(lost, 0)) + ABS(COALESCE(damaged, 0)) + ABS(COALESCE(disposed, 0)) DESC
            LIMIT {limit}
            """,
            (ledger_date,),
        )
        ledger_rows = list(cursor.fetchall())

    metadata = {
        "inventoryDate": _date_text(inventory_date),
        "fbaDate": _date_text(fba_date),
        "ledgerDate": _date_text(ledger_date),
        "inventorySourceRows": len(inventory_rows),
        "fbaSourceRows": len(fba_rows),
        "ledgerSourceRows": len(ledger_rows),
    }
    return inventory_rows, fba_rows, ledger_rows, metadata


def _build_inventory_capital(rows: list[dict[str, Any]]) -> list[CapitalRow]:
    result: list[CapitalRow] = []
    statuses = [
        ("可用", "product_valid_num"),
        ("锁定", "product_lock_num"),
        ("次品", "product_bad_num"),
        ("待检", "product_qc_num"),
        ("调拨在途", "product_onway"),
    ]
    for row in rows:
        unit_cost = _unit_cost(row)
        warehouse = _text(row.get("t_warehouse_name") or row.get("t_warehouse_code") or row.get("warehouse_name") or f"WID-{row.get('wid')}")
        warehouse_type = _warehouse_type(row.get("warehouse_type_code"))
        country = _text(row.get("country_code")) or _country_from_name(warehouse)
        storage_next30 = 0.0
        for status, field in statuses:
            qty = abs(_number(row.get(field)))
            if qty <= 0:
                continue
            amount = qty * unit_cost
            result.append(
                CapitalRow(
                    date=_date_text(row.get("date")),
                    warehouse=warehouse,
                    type=warehouse_type,
                    country=country,
                    sku=_text(row.get("sku")),
                    fnsku=_text(row.get("fnsku")),
                    status=status,
                    qty=round(qty, 2),
                    unitCost=round(unit_cost, 4),
                    amount=round(amount, 2),
                    ageDays=round(_number(row.get("average_age")), 1),
                    storageNext30=storage_next30,
                )
            )
    return result


def _build_fba_capital(rows: list[dict[str, Any]]) -> list[CapitalRow]:
    result: list[CapitalRow] = []
    statuses = [
        ("FBA可售", "afn_fulfillable_quantity", "afn_fulfillable_quantity_price"),
        ("待调仓", "reserved_fc_transfers", "reserved_fc_transfers_price"),
        ("调仓中", "reserved_fc_processing", "reserved_fc_processing_price"),
        ("待发货", "reserved_customerorders", "reserved_customerorders_price"),
        ("FBM可售", "quantity", "quantity_price"),
        ("FBA不可售", "afn_unsellable_quantity", "afn_unsellable_quantity_price"),
        ("计划入库", "afn_inbound_working_quantity", "afn_inbound_working_quantity_price"),
        ("在途", "afn_inbound_shipped_quantity", "afn_inbound_shipped_quantity_price"),
        ("入库中", "afn_inbound_receiving_quantity", "afn_inbound_receiving_quantity_price"),
        ("调查中", "afn_researching_quantity", "afn_researching_quantity_price"),
    ]
    for row in rows:
        warehouse = _text(row.get("name") or "FBA")
        country = _country_from_name(warehouse)
        age_days = _fba_age_days(row)
        total_price = _number(row.get("total_price"))
        estimated_storage = _number(row.get("estimated_storage_cost_next_month"))
        for status, qty_field, amount_field in statuses:
            qty = abs(_number(row.get(qty_field)))
            amount = abs(_number(row.get(amount_field)))
            if qty <= 0 and amount <= 0:
                continue
            unit_cost = amount / qty if qty else 0.0
            storage_next30 = estimated_storage * (amount / total_price) if total_price else 0.0
            result.append(
                CapitalRow(
                    date=_date_text(row.get("date")),
                    warehouse=warehouse,
                    type="FBA",
                    country=country,
                    sku=_text(row.get("sku") or row.get("seller_sku")),
                    fnsku=_text(row.get("fnsku")),
                    status=status,
                    qty=round(qty, 2),
                    unitCost=round(unit_cost, 4),
                    amount=round(amount, 2),
                    ageDays=age_days,
                    storageNext30=round(storage_next30, 2),
                )
            )
    return result


def _build_inventory_losses(rows: list[dict[str, Any]]) -> list[LossRow]:
    losses: list[LossRow] = []
    for row in rows:
        qty = abs(_number(row.get("product_bad_num")))
        if qty <= 0:
            continue
        unit_cost = _unit_cost(row)
        warehouse = _text(row.get("t_warehouse_name") or row.get("t_warehouse_code") or row.get("warehouse_name") or f"WID-{row.get('wid')}")
        losses.append(
            LossRow(
                date=_date_text(row.get("date")),
                warehouse=warehouse,
                type=_warehouse_type(row.get("warehouse_type_code")),
                country=_text(row.get("country_code")) or _country_from_name(warehouse),
                sku=_text(row.get("sku")),
                fnsku=_text(row.get("fnsku")),
                kind="次品",
                qty=round(qty, 2),
                unitCost=round(unit_cost, 4),
                stockLoss=round(qty * unit_cost, 2),
                handlingFee=0.0,
                recovery=0.0,
                action="降本复核",
            )
        )
    return losses


def _build_fba_losses(rows: list[dict[str, Any]]) -> list[LossRow]:
    losses: list[LossRow] = []
    for row in rows:
        qty = abs(_number(row.get("afn_unsellable_quantity")))
        amount = abs(_number(row.get("afn_unsellable_quantity_price")))
        if qty <= 0 and amount <= 0:
            continue
        unit_cost = amount / qty if qty else 0.0
        warehouse = _text(row.get("name") or "FBA")
        losses.append(
            LossRow(
                date=_date_text(row.get("date")),
                warehouse=warehouse,
                type="FBA",
                country=_country_from_name(warehouse),
                sku=_text(row.get("sku") or row.get("seller_sku")),
                fnsku=_text(row.get("fnsku")),
                kind="不可售",
                qty=round(qty, 2),
                unitCost=round(unit_cost, 4),
                stockLoss=round(amount, 2),
                handlingFee=0.0,
                recovery=0.0,
                action="移除测算",
            )
        )
    return losses


def _build_ledger_losses(rows: list[dict[str, Any]], unit_costs: dict[str, float]) -> list[LossRow]:
    result: list[LossRow] = []
    kinds = [("丢失", "lost"), ("损毁", "damaged"), ("弃置", "disposed")]
    for row in rows:
        sku = _text(row.get("msku") or row.get("fnsku") or row.get("asin"))
        fnsku = _text(row.get("fnsku"))
        unit_cost = _lookup_unit_cost(unit_costs, sku, fnsku)
        for kind, field in kinds:
            qty = abs(_number(row.get(field)))
            if qty <= 0:
                continue
            result.append(
                LossRow(
                    date=_date_text(row.get("date")),
                    warehouse=_text(row.get("location") or "FBA台账"),
                    type="FBA",
                    country=_text(row.get("location")),
                    sku=sku,
                    fnsku=fnsku,
                    kind=kind,
                    qty=round(qty, 2),
                    unitCost=round(unit_cost, 4),
                    stockLoss=round(qty * unit_cost, 2),
                    handlingFee=0.0,
                    recovery=0.0,
                    action="索赔核对" if kind in {"丢失", "损毁"} else "移除复核",
                )
            )
    return result


def _build_unit_cost_index(rows: list[CapitalRow]) -> dict[str, float]:
    index: dict[str, float] = {}
    for row in rows:
        if row.unitCost <= 0:
            continue
        for key in (row.sku, row.fnsku):
            if key and key not in index:
                index[key.upper()] = row.unitCost
    return index


def _lookup_unit_cost(index: dict[str, float], sku: str, fnsku: str) -> float:
    for key in (sku, fnsku):
        value = index.get((key or "").upper())
        if value:
            return value
    return 0.0


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - stdlib API
        parsed = urlparse(self.path)
        if parsed.path == "/api/funds":
            self._handle_funds(parsed.query)
            return
        self._serve_static(parsed.path)

    def _handle_funds(self, query: str) -> None:
        try:
            params = parse_qs(query)
            limit = int(params.get("limit", ["320"])[0])
            payload = load_funds(limit=limit)
            self._send_json(payload)
        except Exception as exc:  # pragma: no cover - visible in browser response.
            self._send_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, status=500)

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in {"", "/"} else path.lstrip("/")
        target = (ROOT / relative).resolve()
        if ROOT not in target.parents and target != ROOT:
            self.send_error(403)
            return
        if not target.exists() or not target.is_file():
            self.send_error(404)
            return
        content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        return


def main() -> None:
    port = int(os.getenv("WAREHOUSE_FUNDS_PORT", "8792"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Warehouse funds control tower: http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
