import unittest

from pmc_agent.control_tower import control_tower_field_decisions, get_control_tower_summary, get_monthly_forecast_review
from pmc_agent.connectors.database import StiDatabaseConfig, StiDatabaseConnector
from pmc_agent.schema_catalog import ALL_WAREHOUSE_CATALOG, FieldPack, field_pack_for_task
from pmc_agent.domain import TaskType
from tests.fake_control_tower import FakeMainRuleConnector


class ControlTowerTests(unittest.TestCase):
    def test_control_tower_field_pack_contains_risk_and_age_fields(self):
        fields = ALL_WAREHOUSE_CATALOG.fields_for(FieldPack.CONTROL_TOWER)

        self.assertIn("afn_fulfillable_quantity", fields)
        self.assertIn("future_30d_sales", fields)
        self.assertIn("fnsku_out_of_stock_risk_1", fields)
        self.assertIn("inv_age_61_to_90_days", fields)
        self.assertIn("inv_age_91_to_180_days", fields)
        self.assertIn("inv_age_365_plus_days", fields)
        self.assertEqual(field_pack_for_task(TaskType.CONTROL_TOWER), FieldPack.CONTROL_TOWER)

    def test_control_tower_fails_when_database_is_not_ready(self):
        connector = StiDatabaseConnector(StiDatabaseConfig(host="", port=9030, user="", password="", database="dw_leang", enabled=False))

        with self.assertRaisesRegex(RuntimeError, "数据获取失败"):
            get_control_tower_summary(connector=connector)

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

        self.assertGreater(stockout.pagination["total_count"], 0)
        self.assertGreater(overstock.pagination["total_count"], 0)
        self.assertTrue(all(item.stockout_risk_level != "normal" for item in stockout.items))
        self.assertTrue(all(item.overstock_risk_level != "normal" for item in overstock.items))

    def test_monthly_forecast_review_compares_weekly_forecast_to_sales_since_target_month(self):
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
        self.assertEqual(review.comparison_start_date, "2026-04-01")
        self.assertEqual(review.comparison_end_date, "2026-06-10")
        self.assertEqual(review.review_start_date, "2026-04-01")
        self.assertEqual(review.review_end_date, "2026-06-10")
        self.assertEqual(review.forecast_source, "dim_lingxing_sales_estimates_monthly_v1")
        self.assertEqual(review.forecast_field, "daily_sales_quantity")
        self.assertEqual(review.forecast_quantity, 700)
        self.assertEqual(review.actual_sales, 840)
        self.assertEqual(review.difference, 140)
        self.assertEqual(review.variance_percent, 20)
        self.assertEqual(review.result_type, "over_sold")
        self.assertEqual(review.result_label, "超额")
        self.assertEqual(review.forecast_row_count, 11)
        self.assertEqual(review.actual_row_count, 11)
        self.assertEqual(len(review.weekly_estimates), 11)
        first_week = review.weekly_estimates[0]
        self.assertEqual(first_week.week, "2026W14")
        self.assertEqual(first_week.week_start_date, "2026-04-01")
        self.assertEqual(first_week.week_end_date, "2026-04-05")
        self.assertEqual(first_week.forecast_quantity, 28)
        self.assertEqual(first_week.actual_sales, 33.6)
        self.assertEqual(first_week.difference, 5.6)
        self.assertEqual(first_week.variance_percent, 20)

    def test_field_decisions_include_and_exclude_groups(self):
        decisions = control_tower_field_decisions()

        self.assertTrue(any(item.name == "future_30d_sales" and item.included for item in decisions))
        self.assertTrue(any(item.name == "jypurchase_quantity" and not item.included for item in decisions))


if __name__ == "__main__":
    unittest.main()
