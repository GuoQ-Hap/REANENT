import unittest
from types import SimpleNamespace

from pmc_agent.control_tower import (
    _build_risk_dimension_slices,
    control_tower_field_decisions,
    get_control_tower_summary,
    get_monthly_forecast_review,
)
from pmc_agent.connectors.database import StiDatabaseConfig, StiDatabaseConnector, _filter_sql
from pmc_agent.query_spec import QuerySpec
from pmc_agent.schema_catalog import ALL_WAREHOUSE_CATALOG, FieldPack, field_pack_for_task
from pmc_agent.domain import TaskType
from tests.fake_control_tower import FakeMainRuleConnector


class ControlTowerTests(unittest.TestCase):
    def test_control_tower_field_pack_contains_risk_and_age_fields(self):
        fields = ALL_WAREHOUSE_CATALOG.fields_for(FieldPack.CONTROL_TOWER)

        self.assertIn("afn_fulfillable_quantity", fields)
        self.assertIn("future_30d_sales", fields)
        self.assertIn("fnsku_out_of_stock_risk_1", fields)
        self.assertIn("fnsku_inventory_1", fields)
        self.assertIn("fnsku_inventory_6", fields)
        self.assertIn("fnsku_available_days_1", fields)
        self.assertIn("fnsku_available_days_6", fields)
        self.assertIn("inv_age_61_to_90_days", fields)
        self.assertIn("inv_age_91_to_180_days", fields)
        self.assertIn("inv_age_365_plus_days", fields)
        self.assertIn("sales_apartment", fields)
        self.assertIn("salesman", fields)
        self.assertIn("seasonality", fields)
        self.assertIn("msku_life_process", fields)
        self.assertIn("msku_product_property", fields)
        self.assertEqual(field_pack_for_task(TaskType.CONTROL_TOWER), FieldPack.CONTROL_TOWER)

    def test_control_tower_fails_when_database_is_not_ready(self):
        connector = StiDatabaseConnector(StiDatabaseConfig(host="", port=9030, user="", password="", database="dw_leang", enabled=False))

        with self.assertRaisesRegex(RuntimeError, "数据获取失败"):
            get_control_tower_summary(connector=connector)

    def test_control_tower_summary_returns_empty_result_when_filters_match_no_rows(self):
        class EmptyConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                return []

        summary = get_control_tower_summary(filters={"country_code": "CN"}, connector=EmptyConnector())

        self.assertEqual(summary.pagination["total_count"], 0)
        self.assertEqual(summary.pagination["returned_count"], 0)
        self.assertEqual(summary.kpis["sku_count"], 0)
        self.assertEqual(summary.items, [])
        self.assertEqual(summary.map_nodes, [])
        self.assertEqual(summary.warehouse_inventory, [])
        self.assertEqual(summary.filter_options["sales_department"], [])
        self.assertEqual(summary.filter_options["salesman"], [])
        self.assertEqual(summary.filter_options["seasonality"], [])
        self.assertEqual(summary.filter_options["msku_life_process"], [])

    def test_control_tower_summary_classifies_main_rule_stockout_and_overstock(self):
        connector = FakeMainRuleConnector()

        summary = get_control_tower_summary(page=1, page_size=20, sales_date="2026-06-03", connector=connector)

        self.assertEqual(summary.data_source, ALL_WAREHOUSE_CATALOG.table_name)
        self.assertEqual(summary.sales_stat_date, "2026-06-03")
        self.assertEqual(summary.sales_start_date, "2026-06-03")
        self.assertEqual(summary.sales_end_date, "2026-06-03")
        self.assertEqual(summary.sales_day_count, 1)
        self.assertGreaterEqual(summary.kpis["stockout_count"], 1)
        self.assertGreater(summary.kpis["daily_sales_volume"], 0)
        self.assertGreaterEqual(summary.kpis["overstock_count"], 1)
        self.assertEqual(summary.kpis["local_inventory"], 340)
        self.assertEqual(summary.kpis["overseas_inventory"], 352)
        self.assertEqual(summary.kpis["domestic_supply_inventory"], 340)
        self.assertEqual(summary.kpis["overseas_sellable_inventory"], 904)
        self.assertIn("high", summary.risk_distribution)
        self.assertTrue(summary.items[0].risk_score >= summary.items[-1].risk_score)
        self.assertEqual(summary.pagination["total_count"], 2)
        self.assertTrue(all(item.daily_sales_volume >= 0 for item in summary.items))
        self.assertTrue(any(item.pici_key_gap for item in summary.items))
        self.assertTrue(any(item.pici_first_shortage_days is not None for item in summary.items))
        self.assertTrue(any(item.fba_age_365_plus > 0 for item in summary.items))
        self.assertTrue(any(item.redundancy_sellable_days.get("sellable_6") for item in summary.items))
        self.assertTrue(any(item.stockout_risk_level in {"high", "medium", "low"} for item in summary.items))
        self.assertTrue(any(item.overstock_risk_level in {"high", "medium", "low"} for item in summary.items))
        self.assertTrue(any("冻结SKU" in item.suggested_action for item in summary.items if item.overstock_risk_level != "normal"))
        self.assertTrue(any(node.country_code == "US" for node in summary.map_nodes))
        stockout_item = next(item for item in summary.items if item.material_code == "A100")
        self.assertEqual(stockout_item.projected_7d, -78)
        self.assertEqual(stockout_item.sales_department, "North America")
        self.assertEqual(stockout_item.salesman, "Alice")
        self.assertEqual(stockout_item.product_property, "standard")
        self.assertEqual(stockout_item.msku_life_process, "新品期")
        self.assertEqual(summary.filter_options["sales_department"], ["Clearance", "North America"])
        self.assertEqual(summary.filter_options["salesman"], ["Alice", "Bob"])
        self.assertEqual(summary.filter_options["store_name"], ["Amazon US"])
        self.assertEqual(summary.filter_options["product_manager"], ["PM Chen", "PM Li"])
        self.assertEqual(summary.filter_options["product_property"], ["seasonal", "standard"])
        self.assertEqual(summary.filter_options["country_code"], ["US"])
        self.assertEqual(summary.filter_options["shipments_country"], ["US"])
        self.assertEqual(summary.filter_options["seasonality"], ["常规"])
        self.assertEqual(summary.filter_options["msku_status"], ["active"])
        self.assertEqual(summary.filter_options["msku_life_process"], ["新品期", "非新品期"])
        country_risks = {item.key: item for item in summary.risk_dimensions["country_code"]}
        store_risks = {item.key: item for item in summary.risk_dimensions["store_name"]}
        department_risks = {item.key: item for item in summary.risk_dimensions["sales_department"]}
        salesman_risks = {item.key: item for item in summary.risk_dimensions["salesman"]}
        sales_property_risks = {item.key: item for item in summary.risk_dimensions["sales_property"]}
        seasonality_risks = {item.key: item for item in summary.risk_dimensions["seasonality"]}
        self.assertEqual(country_risks["US"].risk_count, 2)
        self.assertEqual(country_risks["US"].stockout_count, 1)
        self.assertEqual(country_risks["US"].overstock_count, 1)
        self.assertEqual(store_risks["Amazon US"].risk_count, 2)
        self.assertEqual(store_risks["Amazon US"].stockout_count, 1)
        self.assertEqual(store_risks["Amazon US"].overstock_count, 1)
        self.assertEqual(department_risks["North America"].risk_count, 1)
        self.assertEqual(department_risks["North America"].stockout_count, 1)
        self.assertEqual(department_risks["Clearance"].overstock_count, 1)
        self.assertEqual(salesman_risks["Alice"].stockout_count, 1)
        self.assertEqual(salesman_risks["Bob"].overstock_count, 1)
        self.assertEqual(sales_property_risks["旺"].stockout_count, 1)
        self.assertEqual(sales_property_risks["滞"].overstock_count, 1)
        self.assertEqual(seasonality_risks["常规"].risk_count, 2)

    def test_product_property_options_include_inventory_candidates(self):
        class ProductPropertyOptionConnector(FakeMainRuleConnector):
            def get_inventory_filter_option_values(self, fields, limit=200):
                self.option_fields = fields
                return {"msku_product_property": ["fragile", "seasonal", "standard"]}

        connector = ProductPropertyOptionConnector()
        summary = get_control_tower_summary(connector=connector)

        self.assertEqual(("msku_product_property",), connector.option_fields)
        self.assertEqual(summary.filter_options["product_property"], ["fragile", "seasonal", "standard"])

    def test_risk_dimension_rate_uses_real_risk_only(self):
        def item(level: str):
            return SimpleNamespace(
                country_code="US",
                risk_level=level,
                risk_type="healthy" if level == "normal" else "stockout",
                risk_score={"high": 86, "medium": 65, "normal": 10}[level],
                stockout_risk_level=level if level != "normal" else "normal",
                overstock_risk_level="normal",
                evidence={},
                total_inventory=10,
                demand_30d=5,
                daily_sales_volume=1,
            )

        slices = _build_risk_dimension_slices([item("high"), item("medium"), item("normal")], "country_code")

        self.assertEqual(slices[0].risk_count, 2)
        self.assertEqual(slices[0].risk_rate, 0.3333)

    def test_control_tower_uses_table_sellable_days_when_present(self):
        class TableSellableConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                row = super().get_inventory_rows(query_spec)[0].copy()
                row.update(
                    {
                        "fnsku_available_days_1": 27,
                        "fnsku_available_days_2": 62,
                        "fnsku_available_days_3": 62,
                        "fnsku_available_days_4": 62,
                        "fnsku_available_days_5": 62,
                        "fnsku_available_days_6": 83,
                        "fnsku_inventory_1": 2092,
                        "fnsku_inventory_2": 4673,
                        "fnsku_inventory_3": 4673,
                        "fnsku_inventory_4": 4673,
                        "fnsku_inventory_5": 4673,
                        "fnsku_inventory_6": 6401,
                    }
                )
                return [row]

        summary = get_control_tower_summary(connector=TableSellableConnector())
        item = summary.items[0]

        self.assertEqual(item.sellable_days, 27)
        self.assertEqual(
            item.redundancy_sellable_days,
            {
                "sellable_1": 27,
                "sellable_2": 62,
                "sellable_3": 62,
                "sellable_4": 62,
                "sellable_5": 62,
                "sellable_6": 83,
            },
        )

    def test_flat_or_stagnant_overstock_uses_lower_sellable_day_thresholds(self):
        class FlatSellableConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                row = super().get_inventory_rows(query_spec)[0].copy()
                row.update(
                    {
                        "msku_sales_property": "平",
                        "fnsku_available_days_1": 61,
                        "fnsku_available_days_2": 0,
                        "fnsku_available_days_3": 0,
                        "fnsku_available_days_4": 0,
                        "fnsku_available_days_5": 0,
                        "fnsku_available_days_6": 0,
                        "fnsku_out_of_stock_risk_1": "正常",
                        "fnsku_out_of_stock_risk_2": "正常",
                        "fnsku_out_of_stock_risk_3": "正常",
                        "fnsku_out_of_stock_risk_4": "正常",
                        "fnsku_out_of_stock_risk_5": "正常",
                        "fnsku_out_of_stock_risk_6": "正常",
                    }
                )
                return [row]

            def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
                return []

        summary = get_control_tower_summary(connector=FlatSellableConnector())
        item = summary.items[0]

        self.assertEqual(item.overstock_risk_level, "low")
        self.assertEqual(item.risk_type, "overstock")
        self.assertIn("可售天数1(平滞) 61.0天 > 60天", item.evidence["overstock_reason"])
        self.assertIn("重点监控运营清货进度", item.suggested_action)

    def test_boom_or_wang_overstock_keeps_higher_sellable_day_thresholds(self):
        class BoomSellableConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                row = super().get_inventory_rows(query_spec)[0].copy()
                row.update(
                    {
                        "msku_sales_property": "旺",
                        "fnsku_available_days_1": 61,
                        "fnsku_available_days_2": 0,
                        "fnsku_available_days_3": 0,
                        "fnsku_available_days_4": 0,
                        "fnsku_available_days_5": 0,
                        "fnsku_available_days_6": 0,
                        "fnsku_out_of_stock_risk_1": "正常",
                        "fnsku_out_of_stock_risk_2": "正常",
                        "fnsku_out_of_stock_risk_3": "正常",
                        "fnsku_out_of_stock_risk_4": "正常",
                        "fnsku_out_of_stock_risk_5": "正常",
                        "fnsku_out_of_stock_risk_6": "正常",
                    }
                )
                return [row]

            def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
                return []

        summary = get_control_tower_summary(connector=BoomSellableConnector())
        item = summary.items[0]

        self.assertEqual(item.overstock_risk_level, "normal")

    def test_stockout_risk_uses_0_to_45_day_shortage_days(self):
        class PiciWindowConnector(FakeMainRuleConnector):
            def __init__(self, recover_horizon: int):
                self.recover_horizon = recover_horizon

            def get_inventory_rows(self, query_spec):
                row = super().get_inventory_rows(query_spec)[0].copy()
                row.update({f"fnsku_out_of_stock_risk_{index}": "正常" for index in range(1, 7)})
                return [row]

            def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
                row = {"fnsku": "X001A100", "store_name": "Amazon US", "fnsku_inventory_1": 0}
                for horizon in (7, 14, 21, 28, 35, 42, 49, 56, 63, 70, 77, 84, 98):
                    if horizon <= self.recover_horizon:
                        row[f"chazhi_0_{horizon}"] = f"0/{horizon}(-{horizon})"
                    else:
                        row[f"chazhi_0_{horizon}"] = f"{self.recover_horizon}/{self.recover_horizon}(0)"
                return [row]

        cases = [
            (7, "medium", "断货中等风险", 7),
            (14, "high", "断货高风险", 14),
            (21, "critical", "严重断货风险", 21),
        ]
        for recover_horizon, expected_level, expected_warning, expected_days in cases:
            with self.subTest(recover_horizon=recover_horizon):
                summary = get_control_tower_summary(connector=PiciWindowConnector(recover_horizon))
                item = summary.items[0]

                self.assertEqual(item.stockout_risk_level, expected_level)
                self.assertEqual(item.stockout_warning, expected_warning)
                self.assertEqual(item.evidence["stockout_shortage_days_0_45"], expected_days)

    def test_stockout_after_45_days_only_marks_replenishment_hint(self):
        class FuturePiciConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                row = super().get_inventory_rows(query_spec)[0].copy()
                row.update({f"fnsku_out_of_stock_risk_{index}": "正常" for index in range(1, 7)})
                return [row]

            def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
                row = {"fnsku": "X001A100", "store_name": "Amazon US", "fnsku_inventory_1": 0}
                for horizon in (7, 14, 21, 28, 35, 42):
                    row[f"chazhi_0_{horizon}"] = "200/1(199)"
                for horizon in (49, 56, 63, 70, 77, 84, 98):
                    row[f"chazhi_0_{horizon}"] = "0/300(-300)"
                return [row]

        summary = get_control_tower_summary(connector=FuturePiciConnector())
        item = summary.items[0]

        self.assertEqual(item.stockout_risk_level, "normal")
        self.assertEqual(item.risk_type, "healthy")
        self.assertEqual(item.evidence["stockout_shortage_days_0_45"], 0)
        self.assertEqual(item.evidence["stockout_future_replenishment_hint_days"], 49)
        self.assertIn("补货提示", item.stockout_warning)
        self.assertIn("提前排补货", item.suggested_action)

    def test_control_tower_summary_aggregates_daily_sales_by_date_range(self):
        connector = FakeMainRuleConnector()

        single_day = get_control_tower_summary(sales_start_date="2026-06-01", sales_end_date="2026-06-01", connector=connector)
        three_days = get_control_tower_summary(sales_start_date="2026-06-01", sales_end_date="2026-06-03", connector=connector)

        self.assertEqual(three_days.sales_stat_date, "2026-06-01 至 2026-06-03")
        self.assertEqual(three_days.sales_day_count, 3)
        self.assertEqual(three_days.kpis["daily_sales_volume"], single_day.kpis["daily_sales_volume"] * 3)
        self.assertEqual(
            sum(item.daily_sales_volume for item in three_days.items),
            sum(item.daily_sales_volume for item in single_day.items) * 3,
        )

    def test_control_tower_notes_use_non_v1_pici_table(self):
        connector = FakeMainRuleConnector()

        summary = get_control_tower_summary(connector=connector)
        notes = "\n".join(summary.notes)

        self.assertIn("temp_lingxing_pici_sale 的 chazhi 字段", notes)
        self.assertNotIn("temp_lingxing_pici_sale_v1", notes)

    def test_control_tower_keeps_rows_when_pici_gap_is_missing(self):
        class MissingPiciConnector(FakeMainRuleConnector):
            def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
                return super().get_pici_shortage_rows(store_name=store_name, table_name=table_name)[:1]

        summary = get_control_tower_summary(connector=MissingPiciConnector())

        self.assertEqual(summary.pagination["total_count"], 2)
        missing = [item for item in summary.items if not item.pici_gap_values]
        self.assertEqual(len(missing), 1)
        self.assertTrue(missing[0].evidence["pici_gap_missing"])

    def test_control_tower_can_filter_by_computed_risk_type(self):
        connector = FakeMainRuleConnector()

        stockout = get_control_tower_summary(filters={"risk_type": "stockout"}, connector=connector)
        overstock = get_control_tower_summary(filters={"risk_type": "overstock"}, connector=connector)
        combined = get_control_tower_summary(filters={"risk_type": ["stockout", "overstock"]}, connector=connector)

        self.assertGreater(stockout.pagination["total_count"], 0)
        self.assertGreater(overstock.pagination["total_count"], 0)
        self.assertEqual(combined.pagination["total_count"], 2)
        self.assertTrue(all(item.stockout_risk_level != "normal" for item in stockout.items))
        self.assertTrue(all(item.overstock_risk_level != "normal" for item in overstock.items))

    def test_control_tower_risk_only_uses_computed_risk_after_row_build(self):
        class MixedRiskConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                stockout, healthy = [row.copy() for row in super().get_inventory_rows(query_spec)]
                for row in (stockout, healthy):
                    for index in range(1, 7):
                        row[f"fnsku_out_of_stock_risk_{index}"] = "正常"
                healthy.update(
                    {
                        "sku": "H300",
                        "msku": "H300-US-GRN",
                        "fnsku": "X001H300",
                        "asin": "B0H3000003",
                        "sku_name": "Healthy item",
                        "msku_sales_property": "旺",
                        "afn_fulfillable_quantity": 30,
                        "fba_warehouse_quantity": 30,
                        "overseas_warehouse_quantity": 0,
                        "local_warehouse_quantity": 0,
                        "afn_inbound_receiving_quantity": 0,
                        "afn_inbound_working_quantity": 0,
                        "planned_quantity": 0,
                        "sale_quantity_7": 28,
                        "sale_quantity_30": 120,
                        "future_30d_sales": 120,
                        "inv_age_181_to_270_days": 0,
                        "inv_age_271_to_330_days": 0,
                        "inv_age_365_plus_days": 0,
                    }
                )
                return [stockout, healthy]

        summary = get_control_tower_summary(filters={"risk_only": True}, connector=MixedRiskConnector())

        self.assertEqual([item.material_code for item in summary.items], ["A100"])
        self.assertEqual(summary.risk_type_distribution, {"stockout": 1})
        self.assertEqual(summary.kpis["stockout_count"], 1)

    def test_database_risk_only_does_not_filter_raw_marker_columns(self):
        spec = QuerySpec.inventory(field_pack=FieldPack.CONTROL_TOWER, filters={"msku_status": "在售", "risk_only": True})

        sql, params = _filter_sql(spec)

        self.assertIn("msku_status IN", sql)
        self.assertNotIn("fnsku_out_of_stock_risk", sql)
        self.assertEqual(params, ["在售"])

    def test_control_tower_flags_only_missing_risk_marker_values_as_anomaly(self):
        def row(material_code: str, markers: dict[str, str | None]) -> dict[str, object]:
            payload: dict[str, object] = {
                "sku": material_code,
                "msku": f"{material_code}-US",
                "fnsku": f"X-{material_code}",
                "asin": f"B0{material_code}",
                "sku_name": material_code,
                "store_name": "Amazon US",
                "country_code": "US",
                "shipments_country": "US",
                "afn_fulfillable_quantity": 100,
                "fba_warehouse_quantity": 100,
                "sale_quantity_7": 70,
                "sale_quantity_30": 300,
                "future_30d_sales": 300,
            }
            payload.update(markers)
            return payload

        class RiskMarkerConnector(FakeMainRuleConnector):
            def get_inventory_rows(self, query_spec):
                return [
                    row(
                        "C300",
                        {
                            "fnsku_out_of_stock_risk_1": "安全",
                            "fnsku_out_of_stock_risk_2": "正常",
                            "fnsku_out_of_stock_risk_3": "safe",
                            "fnsku_out_of_stock_risk_4": "高风险",
                            "fnsku_out_of_stock_risk_5": "0",
                            "fnsku_out_of_stock_risk_6": "已处理",
                        },
                    ),
                    row(
                        "D400",
                        {
                            "fnsku_out_of_stock_risk_1": "",
                            "fnsku_out_of_stock_risk_2": "数据缺失",
                            "fnsku_out_of_stock_risk_3": "none",
                            "fnsku_out_of_stock_risk_4": "null",
                            "fnsku_out_of_stock_risk_5": "安全",
                            "fnsku_out_of_stock_risk_6": "正常",
                        },
                    ),
                ]

            def get_pici_shortage_rows(self, store_name: str | None = None, table_name: str = ""):
                return []

            def get_warehouse_inventory_rows(self, country_code: str | None = None, limit: int = 80):
                return []

        summary = get_control_tower_summary(connector=RiskMarkerConnector())
        items = {item.material_code: item for item in summary.items}

        self.assertEqual(items["C300"].risk_type, "healthy")
        self.assertEqual(items["C300"].risk_level, "normal")
        self.assertEqual(items["C300"].evidence["risk_flags"], [])
        self.assertEqual(items["D400"].risk_type, "anomaly")
        self.assertEqual(items["D400"].risk_level, "medium")
        self.assertEqual(items["D400"].risk_score, 65)
        self.assertEqual([flag["value"] for flag in items["D400"].evidence["risk_flags"]], ["空", "数据缺失", "none", "null"])

    def test_control_tower_can_filter_by_main_table_business_dimensions(self):
        connector = FakeMainRuleConnector()

        by_department = get_control_tower_summary(filters={"sales_apartment": "North America"}, connector=connector)
        by_salesman = get_control_tower_summary(filters={"salesman": "Bob"}, connector=connector)
        by_product_property = get_control_tower_summary(filters={"msku_product_property": "seasonal"}, connector=connector)
        by_life_process = get_control_tower_summary(filters={"msku_life_process": "新品期"}, connector=connector)
        by_non_new_life_process = get_control_tower_summary(filters={"msku_life_process": "非新品期"}, connector=connector)
        by_multi_department = get_control_tower_summary(filters={"sales_apartment": ["North America", "Clearance"]}, connector=connector)
        by_multi_sales_property = get_control_tower_summary(filters={"sales_property": ["旺", "滞"]}, connector=connector)

        self.assertEqual([item.material_code for item in by_department.items], ["A100"])
        self.assertEqual([item.material_code for item in by_salesman.items], ["B200"])
        self.assertEqual([item.material_code for item in by_product_property.items], ["B200"])
        self.assertEqual([item.material_code for item in by_life_process.items], ["A100"])
        self.assertEqual([item.material_code for item in by_non_new_life_process.items], ["B200"])
        self.assertEqual({item.material_code for item in by_multi_department.items}, {"A100", "B200"})
        self.assertEqual({item.material_code for item in by_multi_sales_property.items}, {"A100", "B200"})

    def test_monthly_forecast_review_compares_complete_weeks_after_snapshot(self):
        connector = FakeMainRuleConnector()

        review = get_monthly_forecast_review(
            material_code="A100",
            msku="A100-US-BLK",
            store_name="Amazon US",
            country_code="US",
            as_of_date="2026-06-10",
            connector=connector,
        )

        self.assertEqual(review.target_month, "2026-04")
        self.assertEqual(review.target_start_date, "2026-04-01")
        self.assertEqual(review.target_end_date, "2026-04-30")
        self.assertEqual(review.comparison_month, "2026-04 至 2026-06")
        self.assertEqual(review.comparison_start_date, "2026-04-13")
        self.assertEqual(review.comparison_end_date, "2026-06-07")
        self.assertEqual(review.review_start_date, "2026-04-13")
        self.assertEqual(review.review_end_date, "2026-06-07")
        self.assertEqual(review.snapshot_date, "2026-04-11")
        self.assertEqual(review.forecast_source, "ods_lingxing_sales_estimates_monthly_v1")
        self.assertEqual(review.forecast_field, "value")
        self.assertEqual(review.forecast_quantity, 532)
        self.assertEqual(review.actual_sales, 638.4)
        self.assertEqual(review.ad_spend, 1276.8)
        self.assertEqual(review.ad_sales_amount, 6384)
        self.assertEqual(review.ad_order_quantity, 63.84)
        self.assertEqual(review.organic_sales, 574.56)
        self.assertEqual(review.ad_acos, 0.2)
        self.assertEqual(review.difference, 106.4)
        self.assertEqual(review.variance_percent, 20)
        self.assertEqual(review.result_type, "over_sold")
        self.assertEqual(review.result_label, "超额")
        self.assertEqual(review.forecast_row_count, 8)
        self.assertEqual(review.actual_row_count, 8)
        self.assertEqual(len(review.weekly_estimates), 8)
        self.assertEqual(len(review.daily_price_points), 56)
        self.assertEqual(review.daily_price_points[0].date, "2026-04-13")
        self.assertEqual(review.daily_price_points[0].price, 19.99)
        self.assertEqual([item.month_offset for item in review.forecast_versions[:4]], [3, 2, 1, 0])
        self.assertEqual([item.target_month for item in review.forecast_versions[:4]], ["2026-03", "2026-04", "2026-05", "2026-06"])
        two_month_version = review.forecast_versions[1]
        self.assertEqual(two_month_version.label, "2个月之前的预估线")
        self.assertEqual(two_month_version.forecast_quantity, 532)
        self.assertEqual(two_month_version.weekly_estimates[0].forecast_quantity, 42)
        self.assertEqual([item.month_offset for item in review.detail_forecast_versions[:4]], [3, 2, 1, 0])
        self.assertEqual(review.detail_forecast_versions[0].target_start_date, "2026-03-01")
        self.assertEqual(review.detail_forecast_versions[0].target_end_date, "2026-08-28")
        self.assertEqual(review.detail_forecast_versions[-1].target_start_date, "2026-06-01")
        self.assertEqual(review.detail_forecast_versions[-1].target_end_date, "2026-11-28")
        self.assertEqual(review.detail_forecast_versions[-1].forecast_quantity, 3150)
        self.assertEqual(review.detail_forecast_versions[-1].forecast_row_count, 25)
        self.assertEqual(review.detail_forecast_versions[-1].weekly_estimates[0].week_start_date, "2026-06-01")
        self.assertEqual(review.detail_forecast_versions[-1].weekly_estimates[0].forecast_quantity, 42)
        self.assertEqual(review.detail_actual_sales[0].week_start_date, "2026-03-02")
        self.assertEqual(review.detail_actual_sales[-1].week_end_date, "2026-06-07")
        monthly_totals = {item.month: item for item in review.detail_monthly_totals}
        self.assertEqual(monthly_totals["2026-03"].forecast_quantity, 198)
        self.assertEqual(monthly_totals["2026-03"].forecast_month, "2026-03")
        self.assertEqual(monthly_totals["2026-03"].forecast_month_offset, 3)
        self.assertEqual(monthly_totals["2026-03"].forecast_label, "3个月之前的预估线")
        self.assertEqual(monthly_totals["2026-04"].forecast_quantity, 362)
        self.assertEqual(monthly_totals["2026-04"].actual_sales, 264)
        self.assertEqual(monthly_totals["2026-04"].actual_sales_projected, 264)
        self.assertEqual(monthly_totals["2026-04"].actual_sales_virtual, 0)
        self.assertEqual(monthly_totals["2026-04"].forecast_month, "2026-03")
        self.assertEqual(monthly_totals["2026-04"].forecast_month_offset, 3)
        self.assertEqual(monthly_totals["2026-04"].forecast_label, "3个月之前的预估线")
        self.assertEqual(monthly_totals["2026-05"].forecast_quantity, 509)
        self.assertEqual(monthly_totals["2026-05"].actual_sales, 352.8)
        self.assertEqual(monthly_totals["2026-05"].forecast_month, "2026-03")
        self.assertEqual(monthly_totals["2026-05"].forecast_month_offset, 3)
        self.assertEqual(monthly_totals["2026-05"].forecast_label, "3个月之前的预估线")
        self.assertEqual(monthly_totals["2026-06"].forecast_quantity, 490)
        self.assertEqual(monthly_totals["2026-06"].actual_sales, 109.2)
        self.assertEqual(monthly_totals["2026-06"].actual_sales_projected, 468)
        self.assertEqual(monthly_totals["2026-06"].actual_sales_virtual, 358.8)
        self.assertEqual(monthly_totals["2026-06"].actual_covered_days, 7)
        self.assertEqual(monthly_totals["2026-06"].month_day_count, 30)
        self.assertEqual(monthly_totals["2026-06"].forecast_month, "2026-04")
        self.assertEqual(monthly_totals["2026-06"].forecast_month_offset, 2)
        self.assertEqual(monthly_totals["2026-06"].forecast_label, "2个月之前的预估线")
        self.assertEqual(
            [item["forecast_month_offset"] for item in monthly_totals["2026-06"].forecast_version_totals],
            [3, 2, 1, 0],
        )
        self.assertEqual(
            [item["forecast_month"] for item in monthly_totals["2026-06"].forecast_version_totals],
            ["2026-03", "2026-04", "2026-05", "2026-06"],
        )
        self.assertEqual(monthly_totals["2026-06"].selected_variance_percent, -4.49)
        self.assertEqual(monthly_totals["2026-06"].sales_gap_direction, "within_10_percent")
        self.assertTrue(monthly_totals["2026-06"].forecast_anomaly)
        self.assertEqual(
            [check["forecast_month_offset"] for check in monthly_totals["2026-06"].forecast_variance_checks],
            [2, 1, 0],
        )
        self.assertEqual(monthly_totals["2026-06"].forecast_variance_checks[-1]["forecast_label"], "当前月的预估线")
        self.assertEqual(monthly_totals["2026-06"].forecast_variance_checks[1]["previous_variance_percent"], -26.12)
        self.assertEqual(monthly_totals["2026-06"].forecast_variance_checks[2]["previous_variance_percent"], -36.46)
        self.assertEqual(monthly_totals["2026-06"].forecast_variance_checks[2]["first_variance_percent"], -53.06)
        for check in monthly_totals["2026-06"].forecast_variance_checks:
            self.assertEqual(check["comparison_basis"], "forecast_version_quantity")
            self.assertNotIn("actual_reference", check)
            self.assertNotIn("实际/折算销量", check["reason"])
        self.assertEqual(len(review.forecast_anomalies), 1)
        self.assertEqual(review.forecast_anomalies[0]["month"], "2026-06")
        self.assertEqual(len(review.forecast_anomalies[0]["reasons"]), 1)
        self.assertNotIn("未命中预估异常", "\n".join(review.forecast_anomalies[0]["reasons"]))
        self.assertIn("命中预估异常", review.forecast_anomalies[0]["reasons"][0])
        self.assertEqual([check["forecast_month_offset"] for check in review.forecast_anomalies[0]["checks"]], [2, 1, 0])
        self.assertTrue(any(item["type"] == "sales_continuous_increase" for item in review.sales_anomalies))
        for anomaly in review.sales_anomalies:
            self.assertNotIn("2026W", anomaly["reason"])
            self.assertIn("月", anomaly["reason"])
            self.assertIn("日", anomaly["reason"])
        first_week = review.weekly_estimates[0]
        self.assertEqual(first_week.week, "2026W16")
        self.assertEqual(first_week.week_start_date, "2026-04-13")
        self.assertEqual(first_week.week_end_date, "2026-04-19")
        self.assertEqual(first_week.forecast_quantity, 42)
        self.assertEqual(first_week.actual_sales, 50.4)
        self.assertEqual(first_week.ad_spend, 100.8)
        self.assertEqual(first_week.ad_sales_amount, 504)
        self.assertEqual(first_week.ad_order_quantity, 5.04)
        self.assertEqual(first_week.organic_sales, 45.36)
        self.assertEqual(first_week.ad_acos, 0.2)
        self.assertEqual(first_week.difference, 8.4)
        self.assertEqual(first_week.variance_percent, 20)

    def test_field_decisions_include_and_exclude_groups(self):
        decisions = control_tower_field_decisions()

        self.assertTrue(any(item.name == "future_30d_sales" and item.included for item in decisions))
        self.assertTrue(any(item.name == "jypurchase_quantity" and not item.included for item in decisions))


if __name__ == "__main__":
    unittest.main()
