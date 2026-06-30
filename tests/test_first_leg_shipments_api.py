from __future__ import annotations

import unittest

from pmc_agent.connectors.database import _dedupe_first_leg_rows

try:
    from fastapi.testclient import TestClient
    import pmc_agent.api as api
except ImportError:  # pragma: no cover - optional api dependency
    TestClient = None
    api = None


class FakeFirstLegConnector:
    def __init__(self) -> None:
        self.calls = []

    def get_first_leg_shipment_rows(self, material_codes, latest_only=True, limit=200):
        self.calls.append(
            {
                "material_codes": material_codes,
                "latest_only": latest_only,
                "limit": limit,
            }
        )
        return [
            {
                "source_relation": "in_transit_package",
                "detail_source_table": "in_transit_shipment_records",
                "sku": "A100",
                "msku": "A100-US-BLK",
                "fnsku": "X001A100",
                "package_id": "FBA123",
                "ship_id": "FBA123",
                "logistics_tracking_number": "TRACK-1",
                "estimated_arrival_time": "2026-06-20",
                "actual_arrival_time": "",
                "plan_delivery_time": "2026-06-23",
                "estimated_delivery_time": "2026-06-24",
                "actual_delivery_time": "",
                "current_shipping_status": "运输中",
                "ship_num": 40,
                "in_transit_qty": 40,
            }
        ]


@unittest.skipIf(TestClient is None or api is None or api.app is None, "FastAPI is not installed")
class FirstLegShipmentsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_connector = api.sku_diagnosis_connector

    def tearDown(self) -> None:
        api.sku_diagnosis_connector = self.original_connector

    def test_first_leg_shipments_queries_identity_codes(self):
        connector = FakeFirstLegConnector()
        api.sku_diagnosis_connector = connector
        client = TestClient(api.app)

        response = client.get(
            "/control-tower/first-leg-shipments",
            params={
                "material_code": "A100, X001A100",
                "fnsku": "X001A100",
                "latest_only": "false",
                "limit": "999",
            },
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(["A100", "X001A100"], payload["query"]["material_codes"])
        self.assertFalse(payload["query"]["latest_only"])
        self.assertEqual(500, payload["query"]["limit"])
        self.assertEqual(1, payload["row_count"])
        self.assertEqual("FBA123", payload["shipments"][0]["ship_id"])
        self.assertEqual("2026-06-23", payload["shipments"][0]["plan_delivery_time"])
        self.assertEqual("运输中", payload["shipments"][0]["current_shipping_status"])
        self.assertIn("feishu_first_leg_shipment_records", payload["source_tables"])
        self.assertEqual(
            {
                "material_codes": ["A100", "X001A100"],
                "latest_only": False,
                "limit": 500,
            },
            connector.calls[0],
        )

    def test_first_leg_shipments_requires_identity_code(self):
        client = TestClient(api.app)

        response = client.get("/control-tower/first-leg-shipments")

        self.assertEqual(400, response.status_code)

    def test_cache_stats_endpoint_reports_cache_metrics(self):
        client = TestClient(api.app)
        api.BOTTOM_TABLE_QUERY_CACHE.clear()
        api.BOTTOM_TABLE_QUERY_CACHE.reset_stats()
        try:
            api.BOTTOM_TABLE_QUERY_CACHE.get_or_load("unit.inventory", {"sku": "A100"}, lambda: [{"sku": "A100"}])
            api.BOTTOM_TABLE_QUERY_CACHE.get_or_load("unit.inventory", {"sku": "A100"}, lambda: [{"sku": "B200"}])

            response = client.get("/control-tower/cache-stats")

            self.assertEqual(200, response.status_code)
            payload = response.json()
            row = next(item for item in payload["namespaces"] if item["namespace"] == "unit.inventory")
            self.assertEqual(1, row["entries"])
            self.assertEqual(1, row["hits"])
            self.assertEqual(1, row["misses"])
        finally:
            api.BOTTOM_TABLE_QUERY_CACHE.clear()
            api.BOTTOM_TABLE_QUERY_CACHE.reset_stats()

class FirstLegShipmentMergeTests(unittest.TestCase):
    def test_dedupe_merges_fba_quantity_into_zero_in_transit_row(self):
        rows = _dedupe_first_leg_rows(
            [
                {
                    "source_relation": "in_transit_package",
                    "detail_source_table": "in_transit_shipment_records",
                    "ship_id": "FBA123",
                    "package_id": "FBA123",
                    "sku": "A100",
                    "msku": "A100-US",
                    "fnsku": "X001A100",
                    "ship_num": 0,
                    "in_transit_qty": 0,
                    "quantity_received": 0,
                    "detail_status": "",
                },
                {
                    "source_relation": "fba_shipment_confirmation",
                    "detail_source_table": "dwd_lingxing_fba_report_shipment_detail_incr",
                    "ship_id": "FBA123",
                    "package_id": "FBA123",
                    "sku": "A100",
                    "msku": "A100-US",
                    "fnsku": "X001A100",
                    "asin": "B000A100",
                    "ship_num": 45,
                    "in_transit_qty": None,
                    "quantity_received": None,
                    "detail_status": "WORKING",
                },
            ]
        )

        self.assertEqual(1, len(rows))
        self.assertEqual(45, rows[0]["ship_num"])
        self.assertEqual(0, rows[0]["in_transit_qty"])
        self.assertEqual("B000A100", rows[0]["asin"])
        self.assertEqual("WORKING", rows[0]["detail_status"])
        self.assertEqual("fba_shipment_confirmation", rows[0]["quantity_source_relation"])


if __name__ == "__main__":
    unittest.main()
