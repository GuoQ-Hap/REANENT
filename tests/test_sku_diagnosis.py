from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict, replace
from datetime import date, timedelta
import io
import unittest

from pmc_agent.capabilities.external_actions import run_external_action_skill
from pmc_agent.control_tower import ControlTowerItem
from pmc_agent.sku_diagnosis import build_sku_diagnosis, diagnose_sku_payload_with_ai, estimate_sku_shipping_cost


class FakePayloadDiagnosisClient:
    def __init__(self) -> None:
        self.seen_payload = None
        self.seen_question = None

    def generate_from_sku_data(self, item_payload, user_question="生成 SKU 全链路诊断"):
        self.seen_payload = item_payload
        self.seen_question = user_question
        return {
            "reply": "模型已基于前端明细数据输出诊断。",
            "model": "fake-model",
            "record_path": "logs/model_interactions/conversations/fake.txt",
            "input": {"model": "fake-model", "input": [{"role": "user", "content": "payload"}]},
            "output": {"output_text": "模型已基于前端明细数据输出诊断。"},
        }

    def generate_reply(self, diagnosis, user_question="生成 SKU 全链路诊断"):
        raise AssertionError("payload diagnosis should not use pre-built diagnosis explanation")


class FakeProductWeightConnector:
    def __init__(self) -> None:
        self.calls = []

    def get_product_weight_rows(self, material_codes, store_name=None, country_code=None, limit=50):
        self.calls.append(
            {
                "material_codes": material_codes,
                "store_name": store_name,
                "country_code": country_code,
                "limit": limit,
            }
        )
        return [
            {
                "sku": "SKU-1",
                "msku": "MSKU-1",
                "fnsku": "FNSKU-1",
                "asin": "B012345678",
                "sku_name": "测试 SKU",
                "store_name": "US",
                "country_code": "US",
                "weight_gram": 750,
                "size_length_cm": 10,
                "size_width_cm": 8,
                "size_height_cm": 6,
            }
        ]


class SkuDiagnosisTests(unittest.TestCase):
    def test_builds_full_chain_diagnosis_for_stockout_and_overstock(self) -> None:
        item = _sample_control_tower_item()

        diagnosis = build_sku_diagnosis(item).to_dict()

        self.assertEqual(diagnosis["overall_status"], "断货风险 / 冗余风险 / 库存异常")
        self.assertEqual(diagnosis["suggested_action"], "断货：核查在途；冗余：冻结SKU。")
        self.assertIn("并存归因", " ".join(diagnosis["attribution"]))
        self.assertTrue(any(action["owner"] == "采购" for action in diagnosis["remedies"]))
        self.assertTrue(any(action["owner"] == "销售" for action in diagnosis["remedies"]))
        channels = {item["channel"] for item in diagnosis["logistics_plan"]}
        self.assertIn("sales_control", channels)
        self.assertIn("urgent_air", channels)
        self.assertIn("standard_air", channels)
        self.assertIn("fast_ship", channels)
        self.assertIn("slow_ship", channels)
        by_channel = {item["channel"]: item for item in diagnosis["logistics_plan"]}
        self.assertEqual(by_channel["slow_ship"]["arrival_day"], 60)
        self.assertIn("第60天以后", by_channel["slow_ship"]["window"])
        self.assertEqual(len(diagnosis["replenishment_countdowns"]), 6)
        self.assertEqual(diagnosis["replenishment_countdowns"][0]["action"], "催FBA在途")
        self.assertEqual(diagnosis["replenishment_countdowns"][0]["formula"], "可售天数1-FBA安全天数-FBA交付天数")
        self.assertTrue(diagnosis["replenishment_countdowns"][0]["should_act"])
        self.assertIn("控销方面", diagnosis["replenishment_recommendation"]["sales_control"])
        self.assertEqual(diagnosis["replenishment_recommendation"]["total_replenishment_quantity"], 352)
        self.assertEqual(diagnosis["replenishment_recommendation"]["purchase"]["suggested_purchase_quantity"], 352)
        cause_types = {item["type"] for item in diagnosis["root_cause_analysis"]}
        self.assertEqual(cause_types, {"planning_anomaly"})
        self.assertEqual(diagnosis["potential_analysis"]["label"], "中等潜力，稳态补货")
        skill_names = {item["name"] for item in diagnosis["external_action_skills"]}
        self.assertIn("purchase_order_placeholder", skill_names)
        self.assertEqual(set(diagnosis["direction_recommendations"]), {"sales", "logistics", "plan"})
        sales_direction = diagnosis["direction_recommendations"]["sales"]
        self.assertEqual(sales_direction["stockout_and_sales_control"]["strategy_label"], "当前45天控销口径")
        self.assertEqual(sales_direction["stockout_and_sales_control"]["control_quantity"], 21)
        self.assertEqual(sales_direction["stockout_and_sales_control"]["control_days"], 7)
        self.assertIn("第1-7天 控60%", sales_direction["stockout_and_sales_control"]["control_segments"])
        self.assertIn("旺款命中断货风险", sales_direction["stockout_and_sales_control"]["reminder"])
        self.assertIn("控销量：合计控 21 件", sales_direction["stockout_and_sales_control"]["reminder"])
        self.assertIn("控销天数 7 天", sales_direction["stockout_and_sales_control"]["reminder"])
        self.assertIn("销售预测", sales_direction["forecast_accuracy"]["recommendation"])
        logistics_direction = diagnosis["direction_recommendations"]["logistics"]
        self.assertTrue(logistics_direction["detected_anomalies"])
        self.assertIn("物流方向", logistics_direction["summary"])
        self.assertEqual(diagnosis["computed_strategy_recommendation"]["strategy_label"], "当前45天控销口径")
        plan_direction = diagnosis["direction_recommendations"]["plan"]
        self.assertEqual(plan_direction["inventory_replenishment"]["strategy_label"], "当前45天控销口径")
        self.assertEqual(plan_direction["inventory_replenishment"]["total_replenishment_quantity"], 0)
        self.assertEqual(plan_direction["inventory_replenishment"]["methods"], [])
        self.assertIn("程序策略未给出新增补货量", plan_direction["summary"])
        self.assertIn("purchase_order_placeholder", {item["name"] for item in plan_direction["skill_placeholders"]})

    def test_flat_or_stagnant_sku_uses_flat_control_strategy_not_air_window(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            sales_property="平",
            pici_key_gap="36/44(-8)",
            pici_gap_values={
                "0_7": "36/44(-8)",
                "0_14": "36/125(-89)",
                "0_21": "36/161(-125)",
                "0_28": "81/161(-80)",
                "0_35": "171/169(2)",
                "0_42": "171/226(-55)",
                "0_49": "171/285(-114)",
                "0_56": "171/347(-176)",
                "0_63": "171/409(-238)",
                "0_70": "171/471(-300)",
            },
        )

        diagnosis = build_sku_diagnosis(item).to_dict()

        control = diagnosis["direction_recommendations"]["sales"]["stockout_and_sales_control"]
        self.assertEqual(control["strategy_label"], "当前平滞控销口径")
        self.assertEqual(control["control_quantity"], 185.2)
        self.assertEqual(control["control_days"], 60)
        self.assertIn("第1-21天 控60%", control["control_segments"])
        self.assertIn("第22-60天 控40%", control["control_segments"])
        self.assertIn("不把空运作为控销依据", control["recommendation"])
        plan = diagnosis["direction_recommendations"]["plan"]
        methods = {item["channel"]: item for item in plan["inventory_replenishment"]["methods"]}
        self.assertEqual(set(methods), {"slow_ship"})
        self.assertEqual(methods["slow_ship"]["suggested_quantity"], 87)
        self.assertEqual(methods["slow_ship"]["window"], "第60天到，覆盖61-75天窗口")
        self.assertEqual(plan["inventory_replenishment"]["total_replenishment_quantity"], 87)
        self.assertEqual(plan["computed_strategy"]["urgent_air_quantity"], 0)
        self.assertEqual(plan["computed_strategy"]["standard_air_quantity"], 0)
        self.assertEqual(plan["computed_strategy"]["fast_quantity"], 0)
        self.assertEqual(plan["computed_strategy"]["slow_quantity"], 87)
        self.assertIn("覆盖61-75天", plan["computed_strategy"]["replenishment_text"])
        self.assertIn("慢船87件", plan["summary"])

    def test_sales_direction_uses_weekly_sales_ad_ratio_and_forecast_variance(self) -> None:
        item = _sample_control_tower_item()
        source_payload = asdict(item)
        source_payload["weekly_sales_and_price"] = {
            "ok": True,
            "forecast_quantity": 100,
            "actual_sales": 130,
            "ad_spend": 260,
            "ad_order_quantity": 39,
            "variance_percent": 30,
            "result_label": "超额",
            "weekly_estimates": [
                {"week": "2026W01", "actual_sales": 20, "forecast_quantity": 18, "ad_spend": 60, "ad_order_quantity": 6},
                {"week": "2026W02", "actual_sales": 40, "forecast_quantity": 32, "ad_spend": 80, "ad_order_quantity": 12},
                {"week": "2026W03", "actual_sales": 70, "forecast_quantity": 50, "ad_spend": 120, "ad_order_quantity": 21},
            ],
        }

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()

        sales = diagnosis["direction_recommendations"]["sales"]
        self.assertEqual(sales["sales_potential"]["weekly_sales_ad_ratio"], 0.5)
        self.assertEqual(sales["sales_potential"]["ad_order_share"], 0.3)
        self.assertIn("上升", sales["sales_potential"]["sales_curve"])
        self.assertTrue(sales["forecast_accuracy"]["needs_raise_forecast"])
        self.assertEqual(sales["forecast_accuracy"]["suggested_increase_quantity"], 30)

    def test_sales_direction_marks_zero_forecast_rows_as_missing_input(self) -> None:
        item = _sample_control_tower_item()
        source_payload = asdict(item)
        source_payload["weekly_sales_and_price"] = {
            "ok": True,
            "target_month": "2026-04",
            "forecast_quantity": None,
            "raw_forecast_quantity": 0,
            "actual_sales": 84,
            "ad_spend": 24.23,
            "ad_order_quantity": 7,
            "forecast_row_count": 0,
            "forecast_data_status": "missing",
            "forecast_missing_reason": "预测表未匹配到 2026-04 的销售预测行；raw_forecast_quantity=0 代表缺数据。",
            "weekly_estimates": [
                {"week": "2026W21", "actual_sales": 18, "forecast_quantity": 0, "ad_spend": 8.74, "ad_order_quantity": 1},
                {"week": "2026W22", "actual_sales": 33, "forecast_quantity": 0, "ad_spend": 5.48, "ad_order_quantity": 1},
                {"week": "2026W23", "actual_sales": 24, "forecast_quantity": 0, "ad_spend": 9.49, "ad_order_quantity": 5},
                {"week": "2026W24", "actual_sales": 9, "forecast_quantity": 0, "ad_spend": 0.52, "ad_order_quantity": 0},
            ],
        }

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()

        sales = diagnosis["direction_recommendations"]["sales"]
        self.assertIsNone(sales["forecast_accuracy"]["needs_raise_forecast"])
        self.assertEqual(sales["forecast_accuracy"]["suggested_forecast_quantity"], 84)
        self.assertIn("不能把 raw_forecast_quantity=0 当成真实预测", sales["forecast_accuracy"]["recommendation"])
        self.assertIn("预测输入缺失", diagnosis["potential_analysis"]["basis"][2])
        self.assertEqual(sales["sales_performance"]["actual_sales"], 84)
        self.assertEqual(sales["sales_performance"]["demand_reference"]["demand_30d"], item.demand_30d)
        self.assertIn("回落", sales["sales_performance"]["sales_curve"])
        self.assertNotIn("首周 0，末周 9，变化 100.0%", sales["sales_performance"]["sales_curve"])

    def test_stockout_root_cause_uses_monthly_oversell_and_supply_delay_rules(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            overstock_risk_level="normal",
            overstock_warning="无冗余风险",
            risk_type="stockout",
        )
        source_payload = asdict(item)
        source_payload["monthly_forecast_review"] = {
            "detail_monthly_totals": [
                {
                    "month": "2026-06",
                    "forecast_quantity": 100,
                    "actual_sales": 65,
                    "actual_sales_projected": 130,
                    "actual_covered_days": 15,
                    "month_day_count": 30,
                    "selected_variance_percent": 30,
                    "forecast_version_totals": [
                        {"forecast_month_offset": 2, "forecast_quantity": 100, "forecast_label": "2个月之前的预估线"}
                    ],
                }
            ]
        }
        plan_delivery = date.today() + timedelta(days=2)
        estimated_delivery = plan_delivery + timedelta(days=8)
        source_payload["first_leg_shipments"] = [
            {
                "ship_id": "SHIP-1",
                "plan_delivery_time": plan_delivery.isoformat(),
                "estimated_delivery_time": estimated_delivery.isoformat(),
                "estimated_departure_time": "2026-06-01",
                "logistics_pickup_time": "2026-06-09",
                "delay_remark": "目的港查验，仍未签收",
            }
        ]

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        causes = {cause["type"]: cause for cause in diagnosis["root_cause_analysis"]}

        self.assertIn("oversell", causes)
        self.assertIn("超卖导致断货", causes["oversell"]["cause"])
        self.assertIn("物流延期", causes["logistics_delay"]["cause"])
        self.assertIn("目的港查验", causes["logistics_delay"]["evidence"])
        self.assertIn("采购延期", causes["procurement_delay"]["cause"])

    def test_future_pending_delay_in_stockout_window_is_marked(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            overstock_risk_level="normal",
            overstock_warning="无冗余风险",
            risk_type="stockout",
        )
        source_payload = asdict(item)
        plan_delivery = date.today() + timedelta(days=2)
        estimated_delivery = plan_delivery + timedelta(days=7)
        plan_ship = date.today() - timedelta(days=8)
        pickup = plan_ship + timedelta(days=7)
        source_payload["first_leg_shipments"] = [
            {
                "ship_id": "SHIP-7D",
                "plan_delivery_time": plan_delivery.isoformat(),
                "estimated_delivery_time": estimated_delivery.isoformat(),
                "actual_arrival_time": date.today().isoformat(),
                "estimated_departure_time": plan_ship.isoformat(),
                "logistics_pickup_time": pickup.isoformat(),
                "logistics_delay_remark": "海外清关排队",
                "current_shipping_status": "国外查验",
                "remarks": "已标记发货",
            }
        ]

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        causes = {cause["type"]: cause for cause in diagnosis["root_cause_analysis"]}

        self.assertIn("logistics_delay", causes)
        self.assertIn("断货窗口", causes["logistics_delay"]["evidence"])
        self.assertIn("海外清关排队", causes["logistics_delay"]["evidence"])
        self.assertIn("国外查验", causes["logistics_delay"]["evidence"])
        self.assertNotIn("已标记发货", causes["logistics_delay"]["evidence"])
        self.assertIn("procurement_delay", causes)

    def test_signed_late_shipment_is_not_marked_as_logistics_delay(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            overstock_risk_level="normal",
            overstock_warning="无冗余风险",
            risk_type="stockout",
        )
        source_payload = asdict(item)
        plan_delivery = date.today() + timedelta(days=2)
        estimated_delivery = plan_delivery + timedelta(days=8)
        source_payload["first_leg_shipments"] = [
            {
                "ship_id": "SHIP-SIGNED",
                "ship_num": 30,
                "quantity_received": 30,
                "plan_delivery_time": plan_delivery.isoformat(),
                "estimated_delivery_time": estimated_delivery.isoformat(),
                "actual_delivery_time": estimated_delivery.isoformat(),
            }
        ]

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        cause_types = {cause["type"] for cause in diagnosis["root_cause_analysis"]}

        self.assertNotIn("logistics_delay", cause_types)

    def test_pending_abnormal_shipment_status_is_marked_as_logistics_exception(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            overstock_risk_level="normal",
            overstock_warning="无冗余风险",
            risk_type="stockout",
        )
        source_payload = asdict(item)
        source_payload["sales_end_date"] = date.today().isoformat()
        plan_delivery = date.today() + timedelta(days=20)
        estimated_delivery = plan_delivery + timedelta(days=21)
        source_payload["first_leg_shipments"] = [
            {
                "batch_num": "SP260516302",
                "package_id": "FBA19DDX54Q8",
                "plan_delivery_time": plan_delivery.isoformat(),
                "estimated_delivery_time": estimated_delivery.isoformat(),
                "actual_arrival_time": date.today().isoformat(),
                "actual_delivery_time": "",
                "quantity_received": 0,
                "current_shipping_status": "国外查验",
                "detail_status": "SHIPPED",
                "remarks": "已标记发货",
            }
        ]

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        causes = {cause["type"]: cause for cause in diagnosis["root_cause_analysis"]}

        self.assertIn("logistics", causes)
        self.assertIn("物流异常", causes["logistics"]["cause"])
        self.assertIn("国外查验", causes["logistics"]["evidence"])
        self.assertIn("预计较计划延后 21 天", causes["logistics"]["evidence"])
        self.assertNotIn("SHIPPED", causes["logistics"]["evidence"])
        self.assertNotIn("已标记发货", causes["logistics"]["evidence"])
        self.assertNotIn("logistics_delay", causes)

    def test_past_estimated_late_shipment_is_not_marked_as_logistics_delay(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            overstock_risk_level="normal",
            overstock_warning="无冗余风险",
            risk_type="stockout",
        )
        source_payload = asdict(item)
        source_payload["sales_end_date"] = (date.today() - timedelta(days=12)).isoformat()
        plan_delivery = date.today() - timedelta(days=10)
        estimated_delivery = date.today() - timedelta(days=2)
        source_payload["first_leg_shipments"] = [
            {
                "ship_id": "SHIP-PAST",
                "plan_delivery_time": plan_delivery.isoformat(),
                "estimated_delivery_time": estimated_delivery.isoformat(),
            }
        ]

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        cause_types = {cause["type"] for cause in diagnosis["root_cause_analysis"]}

        self.assertNotIn("logistics_delay", cause_types)

    def test_stockout_root_cause_does_not_emit_backend_only_shortage_segments(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            stockout_risk_level="high",
            overstock_risk_level="normal",
            risk_type="stockout",
            fba_sellable=0,
            sellable_days=0,
            pici_gap_values={
                "chazhi_0_7": "0/70(-70)",
                "chazhi_0_14": "70/140(-70)",
                "chazhi_0_21": "70/210(-140)",
            },
            pici_first_shortage_days=1,
            pici_min_gap_quantity=-70,
            pici_key_gap="0/70(-70)",
        )
        source_payload = asdict(item)
        source_payload["sales_end_date"] = "2026-06-01"
        source_payload["first_leg_shipments"] = [
            {
                "ship_id": "SHIP-A",
                "ship_num": 70,
                "quantity_received": 0,
                "plan_delivery_time": "2026-06-04",
                "estimated_delivery_time": "2026-06-10",
            }
        ]

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        segments = [cause for cause in diagnosis["root_cause_analysis"] if cause["type"] == "stockout_segment"]

        self.assertEqual(segments, [])
        self.assertTrue(any(cause["type"] == "planning_anomaly" for cause in diagnosis["root_cause_analysis"]))

    def test_overstock_root_cause_uses_monthly_low_sell_rule(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            stockout_risk_level="normal",
            stockout_warning="无断货风险",
            risk_type="overstock",
            pici_first_shortage_days=None,
            pici_min_gap_quantity=None,
            pici_key_gap="",
            pici_gap_values={},
        )
        source_payload = asdict(item)
        source_payload["monthly_forecast_review"] = {
            "detail_monthly_totals": [
                {
                    "month": "2026-05",
                    "forecast_quantity": 200,
                    "actual_sales": 150,
                    "actual_sales_projected": 150,
                    "actual_covered_days": 31,
                    "month_day_count": 31,
                    "selected_variance_percent": -25,
                    "forecast_version_totals": [
                        {"forecast_month_offset": 2, "forecast_quantity": 200, "forecast_label": "2个月之前的预估线"}
                    ],
                }
            ]
        }

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        causes = {cause["type"]: cause for cause in diagnosis["root_cause_analysis"]}

        self.assertIn("low_sell", causes)
        self.assertIn("低卖", causes["low_sell"]["cause"])

    def test_overstock_warning_monitor_does_not_calculate_overstock_root_cause(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            stockout_risk_level="normal",
            stockout_warning="无断货风险",
            overstock_risk_level="low",
            overstock_warning="冗余低风险",
            warning_type="SOP 冗余-预警监控",
            suggested_action="冗余：按 SOP 冗余处理：重点监控运营清货进度。",
            risk_type="overstock",
            pici_first_shortage_days=None,
            pici_min_gap_quantity=None,
            pici_key_gap="",
            pici_gap_values={},
            evidence={
                "overstock_reason": "FBA库龄61-90天 库存 13，动作：预警监控",
                "pici_gap_missing": False,
            },
        )
        source_payload = asdict(item)
        source_payload["monthly_forecast_review"] = {
            "detail_monthly_totals": [
                {
                    "month": "2026-05",
                    "forecast_quantity": 200,
                    "actual_sales": 100,
                    "actual_sales_projected": 100,
                    "actual_covered_days": 31,
                    "month_day_count": 31,
                    "selected_variance_percent": -50,
                    "forecast_version_totals": [
                        {"forecast_month_offset": 2, "forecast_quantity": 200, "forecast_label": "2个月之前的预估线"}
                    ],
                }
            ]
        }

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        cause_types = {cause["type"] for cause in diagnosis["root_cause_analysis"]}

        self.assertEqual(cause_types, set())
        self.assertNotIn("冗余归因", "\n".join(diagnosis["attribution"]))
        self.assertIn("FBA库龄61-90天", "；".join(diagnosis["overstock"]["findings"]))

    def test_overstock_root_cause_within_threshold_is_planning_anomaly(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            stockout_risk_level="normal",
            stockout_warning="无断货风险",
            risk_type="overstock",
            pici_first_shortage_days=None,
            pici_min_gap_quantity=None,
            pici_key_gap="",
            pici_gap_values={},
        )
        source_payload = asdict(item)
        source_payload["monthly_forecast_review"] = {
            "detail_monthly_totals": [
                {
                    "month": "2026-05",
                    "forecast_quantity": 200,
                    "actual_sales": 190,
                    "actual_sales_projected": 190,
                    "actual_covered_days": 31,
                    "month_day_count": 31,
                    "selected_variance_percent": -5,
                    "forecast_version_totals": [
                        {"forecast_month_offset": 2, "forecast_quantity": 200, "forecast_label": "2个月之前的预估线"}
                    ],
                }
            ]
        }

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        causes = {cause["type"]: cause for cause in diagnosis["root_cause_analysis"]}

        self.assertIn("planning_anomaly", causes)
        self.assertIn("计划原因", causes["planning_anomaly"]["cause"])
        self.assertNotIn("low_sell", causes)

    def test_overstock_root_cause_marks_supply_when_actual_is_not_below_forecast(self) -> None:
        item = replace(
            _sample_control_tower_item(),
            stockout_risk_level="normal",
            stockout_warning="无断货风险",
            risk_type="overstock",
            pici_first_shortage_days=None,
            pici_min_gap_quantity=None,
            pici_key_gap="",
            pici_gap_values={},
        )
        source_payload = asdict(item)
        source_payload["monthly_forecast_review"] = {
            "detail_monthly_totals": [
                {
                    "month": "2026-05",
                    "forecast_quantity": 100,
                    "actual_sales": 140,
                    "actual_sales_projected": 140,
                    "actual_covered_days": 31,
                    "month_day_count": 31,
                    "selected_variance_percent": 40,
                    "forecast_version_totals": [
                        {"forecast_month_offset": 2, "forecast_quantity": 100, "forecast_label": "2个月之前的预估线"}
                    ],
                }
            ]
        }

        diagnosis = build_sku_diagnosis(item, source_payload=source_payload).to_dict()
        cause_types = {cause["type"] for cause in diagnosis["root_cause_analysis"]}

        self.assertIn("supply_anomaly", cause_types)
        self.assertNotIn("overstock", cause_types)

    def test_payload_diagnosis_uses_frontend_data_as_model_input(self) -> None:
        item_payload = asdict(_sample_control_tower_item())
        client = FakePayloadDiagnosisClient()

        result = diagnose_sku_payload_with_ai(item_payload, question="根据当前行数据诊断", ai_client=client)

        self.assertEqual(client.seen_payload["material_code"], item_payload["material_code"])
        self.assertEqual(client.seen_question, "根据当前行数据诊断")
        self.assertEqual(result["diagnosis_mode"], "model_from_frontend_data")
        self.assertEqual(result["ai_reply"], "模型已基于前端明细数据输出诊断。")
        self.assertEqual(result["ai_model"], "fake-model")
        self.assertEqual(result["source_item"]["identity"]["material_code"], "SKU-1")
        self.assertFalse(result["shipping_cost_estimate"]["ok"])
        self.assertEqual(result["ai_review"]["input"]["model"], "fake-model")
        self.assertEqual(result["ai_review"]["output"]["output_text"], "模型已基于前端明细数据输出诊断。")
        self.assertEqual(result["ai_review"]["extracted_reply"], "模型已基于前端明细数据输出诊断。")
        self.assertIn("computed_diagnosis", client.seen_payload)
        self.assertEqual(client.seen_payload["computed_diagnosis"]["material_code"], "SKU-1")
        self.assertEqual(len(client.seen_payload["replenishment_countdowns"]), 6)
        self.assertIn("控销方面", client.seen_payload["replenishment_recommendation"]["sales_control"])
        self.assertEqual(set(client.seen_payload["direction_recommendations"]), {"sales", "logistics", "plan"})
        self.assertIn("computed_strategy_recommendation", client.seen_payload)
        self.assertFalse(client.seen_payload["weekly_sales_and_price"]["ok"])

    def test_payload_diagnosis_passes_monthly_review_as_primary_model_input(self) -> None:
        item_payload = asdict(_sample_control_tower_item())
        item_payload["forecast_review"] = {
            "target_month": "2026-04",
            "review_start_date": "2026-05-11",
            "review_end_date": "2026-06-15",
            "forecast_quantity": 0,
            "actual_sales": 84,
            "ad_spend": 24.23,
            "ad_order_quantity": 7,
            "forecast_row_count": 0,
            "actual_row_count": 30,
            "notes": ["预测表未匹配到复盘月份。"],
            "weekly_estimates": [
                {"week": "2026W21", "actual_sales": 18, "forecast_quantity": 0, "ad_spend": 8.74, "ad_order_quantity": 1},
                {"week": "2026W22", "actual_sales": 33, "forecast_quantity": 0, "ad_spend": 5.48, "ad_order_quantity": 1},
            ],
            "daily_price_points": [
                {"date": "2026-05-11", "price": 16, "listing_price": 16.5, "currency_code": "USD"},
                {"date": "2026-06-15", "price": 15.5, "listing_price": 16, "currency_code": "USD"},
            ],
        }
        client = FakePayloadDiagnosisClient()

        result = diagnose_sku_payload_with_ai(item_payload, question="根据复盘诊断", ai_client=client)

        review = client.seen_payload["monthly_forecast_review"]
        self.assertTrue(review["ok"])
        self.assertEqual(review["forecast_data_status"], "missing")
        self.assertEqual(review["actual_sales"], 84)
        self.assertEqual(len(review["weekly_estimates"]), 2)
        self.assertEqual(len(review["daily_price_points"]), 2)
        self.assertEqual(result["source_item"]["monthly_forecast_review"]["actual_sales"], 84)

    def test_shipping_cost_estimate_uses_payload_weight(self) -> None:
        item_payload = asdict(_sample_control_tower_item())
        item_payload["weight_gram"] = 500
        client = FakePayloadDiagnosisClient()

        result = diagnose_sku_payload_with_ai(item_payload, question="根据当前行数据诊断", ai_client=client)

        estimate = client.seen_payload["shipping_cost_estimate"]
        self.assertTrue(estimate["ok"])
        self.assertEqual(estimate["weight"]["weight_gram"], 500)
        by_channel = {item["channel"]: item for item in estimate["estimates"]}
        self.assertEqual(by_channel["urgent_air"]["unit_shipping_cost_cny"], 42.5)
        self.assertEqual(by_channel["standard_air"]["unit_shipping_cost_cny"], 30)
        self.assertEqual(by_channel["fast_ship"]["unit_shipping_cost_cny"], 5.75)
        self.assertEqual(by_channel["slow_ship"]["unit_shipping_cost_cny"], 4.5)
        self.assertEqual(by_channel["urgent_air"]["suggested_quantity"], 40)
        self.assertEqual(by_channel["urgent_air"]["estimated_cost_cny"], 1700)
        self.assertEqual(by_channel["standard_air"]["suggested_quantity"], 100)
        self.assertEqual(by_channel["standard_air"]["estimated_cost_cny"], 3000)
        self.assertEqual(by_channel["fast_ship"]["suggested_quantity"], 60)
        self.assertEqual(by_channel["fast_ship"]["estimated_cost_cny"], 345)
        self.assertEqual(estimate["cost_comparison"]["lowest_total_cost_channel"]["channel"], "fast_ship")
        self.assertEqual(result["source_item"]["shipping_cost_estimate"]["formula"], "unit_shipping_cost_cny = unit_weight_kg * rate_cny_per_kg")

    def test_shipping_cost_estimate_can_lookup_product_info_weight(self) -> None:
        item_payload = asdict(_sample_control_tower_item())
        client = FakePayloadDiagnosisClient()
        connector = FakeProductWeightConnector()

        result = diagnose_sku_payload_with_ai(item_payload, question="根据当前行数据诊断", connector=connector, ai_client=client)

        self.assertEqual(connector.calls[0]["material_codes"][:4], ["SKU-1", "MSKU-1", "FNSKU-1", "B012345678"])
        estimate = result["shipping_cost_estimate"]
        self.assertTrue(estimate["ok"])
        self.assertEqual(estimate["weight"]["source_table"], "dim_lingxing_product_info")
        self.assertEqual(estimate["weight"]["weight_gram"], 750)
        by_channel = {item["channel"]: item for item in estimate["estimates"]}
        self.assertEqual(by_channel["urgent_air"]["unit_shipping_cost_cny"], 63.75)
        self.assertEqual(by_channel["standard_air"]["unit_shipping_cost_cny"], 45)
        self.assertEqual(by_channel["urgent_air"]["estimated_cost_cny"], 2550)
        self.assertEqual(result["replenishment_cost_comparison"]["rows"][0]["channel"], "urgent_air")
        self.assertEqual(client.seen_payload["product_weight"]["dimensions_cm"]["size_length_cm"], 10)

    def test_estimate_sku_shipping_cost_returns_replenishment_cost_only(self) -> None:
        item_payload = asdict(_sample_control_tower_item())
        item_payload["weight_gram"] = 500

        result = estimate_sku_shipping_cost(item_payload)

        self.assertEqual(result["material_code"], "SKU-1")
        estimate = result["shipping_cost_estimate"]
        self.assertTrue(estimate["ok"])
        by_channel = {item["channel"]: item for item in estimate["estimates"]}
        self.assertEqual(by_channel["urgent_air"]["unit_shipping_cost_cny"], 42.5)
        self.assertEqual(by_channel["standard_air"]["unit_shipping_cost_cny"], 30)
        self.assertEqual(by_channel["urgent_air"]["suggested_quantity"], 40)
        self.assertEqual(by_channel["urgent_air"]["estimated_cost_cny"], 1700)
        self.assertEqual(result["replenishment_cost_comparison"]["lowest_total_cost_channel"]["channel"], "fast_ship")

    def test_external_action_skill_is_placeholder_and_prints_action(self) -> None:
        diagnosis = build_sku_diagnosis(_sample_control_tower_item()).to_dict()
        skill = next(item for item in diagnosis["external_action_skills"] if item["name"] == "purchase_order_placeholder")
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            result = run_external_action_skill(skill, {"suggested_purchase_quantity": 352})

        self.assertTrue(result["ok"])
        self.assertFalse(result["implemented"])
        self.assertEqual(result["status"], "printed_placeholder_action")
        self.assertIn("purchase_order_placeholder", buffer.getvalue())
        self.assertIn("suggested_purchase_quantity", buffer.getvalue())


def _sample_control_tower_item() -> ControlTowerItem:
    return ControlTowerItem(
        material_code="SKU-1",
        msku="MSKU-1",
        fnsku="FNSKU-1",
        asin="B012345678",
        sku_name="测试 SKU",
        store_name="US",
        country_code="US",
        shipments_country="US",
        sales_department="North America",
        salesman="Alice",
        product_manager="PM Chen",
        seller_id="SELLER-US-01",
        sales_property="旺",
        product_property="standard",
        seasonality="常规",
        msku_status="active",
        msku_life_process="成熟期",
        risk_type="stockout",
        risk_level="high",
        warning_type="断货高风险 / SOP 冗余-重点清货",
        suggested_action="断货：核查在途；冗余：冻结SKU。",
        risk_score=88,
        stockout_risk_level="high",
        stockout_warning="断货高风险",
        overstock_risk_level="medium",
        overstock_warning="冗余中风险",
        total_inventory=300,
        fba_sellable=10,
        fba_inventory=80,
        overseas_inventory=160,
        local_inventory=60,
        inbound_total=40,
        daily_sales_volume=12,
        pici_first_shortage_days=7,
        pici_min_gap_quantity=-25,
        pici_key_gap="10/35(-25)",
        pici_gap_values={"chazhi_0_7": "10/35(-25)", "chazhi_0_14": "25/35(-10)"},
        demand_7d=35,
        demand_30d=120,
        daily_demand=4,
        last_30_order_price=19.99,
        last_30_order_us_price=2.75,
        last_90_gross_margin=0.32,
        sellable_days=2.5,
        projected_7d=-25,
        lead_time_days=25,
        long_age_inventory=90,
        fba_age_61_to_90=30,
        fba_age_91_to_180=60,
        fba_age_181_to_270=0,
        fba_age_271_to_330=0,
        fba_age_331_to_365=0,
        fba_age_365_plus=0,
        fba_long_age_ratio=0.75,
        redundancy_sellable_days={"sellable_1": 2.5, "sellable_4": 50},
        evidence={
            "risk_flags": [{"reason": "历史断货风险仍未关闭"}],
            "overstock_reason": "FBA 91-180 天库龄库存 60，动作：重点清货",
            "pici_gap_missing": False,
        },
    )


if __name__ == "__main__":
    unittest.main()
