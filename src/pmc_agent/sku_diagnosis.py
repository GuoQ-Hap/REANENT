from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta
import json
import os
import re
from typing import Any
import urllib.error
import urllib.request

from pmc_agent.capabilities.external_actions import build_sku_external_action_skills
from pmc_agent.control_tower import ControlTowerItem, get_control_tower_summary, get_monthly_forecast_review
from pmc_agent.control_tower_recommendations import (
    _build_strategy_recommendation as _build_control_strategy_recommendation,
    _is_flat_or_stagnant as _is_flat_or_stagnant_sales_property,
)
from pmc_agent.env import load_env_file
from pmc_agent.model import _extract_response_text
from pmc_agent.model_io import generate_time_id, record_model_interaction
from pmc_agent.model_router import ModelAction, ModelRouteRequest, ModelRouter


ACTIVE_RISK_LEVELS = {"low", "medium", "high", "critical"}
MONTHLY_FORECAST_CHANGE_ANOMALY_PERCENT = 30
WEEKLY_SALES_DEVIATION_ANOMALY_PERCENT = 20
LOGISTICS_RECEIPT_DELAY_MARK_DAYS = 7
PROCUREMENT_PICKUP_DELAY_MARK_DAYS = 4
ROOT_CAUSE_LOOKBACK_COUNT = 3
NUMERIC_ITEM_FIELDS = {
    "risk_score",
    "total_inventory",
    "fba_sellable",
    "fba_inventory",
    "overseas_inventory",
    "local_inventory",
    "inbound_total",
    "daily_sales_volume",
    "demand_7d",
    "demand_30d",
    "daily_demand",
    "projected_7d",
    "lead_time_days",
    "long_age_inventory",
    "fba_age_61_to_90",
    "fba_age_91_to_180",
    "fba_age_181_to_270",
    "fba_age_271_to_330",
    "fba_age_331_to_365",
    "fba_age_365_plus",
}
RISK_LABELS = {
    "critical": "紧急",
    "high": "高",
    "medium": "中",
    "low": "低",
    "normal": "正常",
}
SHIPPING_COST_RATES_CNY_PER_KG = {
    "urgent_air": 85.0,
    "standard_air": 60.0,
    "fast_ship": 11.5,
    "slow_ship": 9.0,
}
SHIPPING_COST_CHANNEL_LABELS = {
    "urgent_air": "加急空运",
    "standard_air": "普通空运",
    "fast_ship": "快船",
    "slow_ship": "慢船",
}
URGENT_AIR_ARRIVAL_DAY = 10
STANDARD_AIR_ARRIVAL_DAY = 20
FAST_SHIP_ARRIVAL_DAY = 45
SLOW_SHIP_ARRIVAL_DAY = 60
SLOW_SHIP_REPLENISHMENT_START_DAY = 61
FLAT_STAGNANT_SHIPPING_CUTOFF_DAY = 75
DEFAULT_REPLENISHMENT_RULES = {
    "fba_safety_days": 7.0,
    "overseas_safety_days": 14.0,
    "local_safety_days": 21.0,
    "fba_delivery_days": 7.0,
    "overseas_delivery_days": 21.0,
    "local_delivery_days": 30.0,
    "purchase_frequency_days": 30.0,
    "oversell_rate": 0.0,
}


@dataclass(frozen=True)
class DiagnosisSection:
    status: str
    metrics: dict[str, Any]
    findings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SkuDiagnosis:
    material_code: str
    title: str
    overall_status: str
    risk_level: str
    inventory: DiagnosisSection
    sales: DiagnosisSection
    stockout: DiagnosisSection
    overstock: DiagnosisSection
    attribution: list[str]
    root_cause_analysis: list[dict[str, Any]]
    handling_logic: list[str]
    logistics_plan: list[dict[str, Any]]
    replenishment_countdowns: list[dict[str, Any]]
    replenishment_recommendation: dict[str, Any]
    replenishment_cost_comparison: dict[str, Any]
    sales_recommendation: dict[str, Any]
    potential_analysis: dict[str, Any]
    computed_strategy_recommendation: dict[str, Any]
    direction_recommendations: dict[str, Any]
    external_action_skills: list[dict[str, Any]]
    remedies: list[dict[str, str]]
    calculation_logic: list[str]
    suggested_action: str
    source_item: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class OpenAISkuDiagnosisClient:
    def __init__(
        self,
        model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        model_router: ModelRouter | None = None,
    ) -> None:
        load_env_file(override=False)
        self.model = model
        self.model_router = model_router or ModelRouter()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout or float(os.getenv("PMC_AGENT_HTTP_TIMEOUT", "30"))
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAISkuDiagnosisClient.")

    def generate_reply(self, diagnosis: SkuDiagnosis, user_question: str = "生成 SKU 全链路诊断") -> dict[str, Any]:
        compact = _compact_diagnosis_payload(diagnosis)
        route = self.model_router.route(
            ModelRouteRequest(
                action=ModelAction.BUSINESS_EXPLANATION,
                content=json.dumps(compact, ensure_ascii=False),
                metadata={"sku_full_chain_diagnosis": True, "material_code": diagnosis.material_code},
            )
        )
        selected_model = self.model or route.model
        interaction_id = generate_time_id()
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 库存控制塔的 SKU 全链路诊断模型。"
                        "必须只基于用户提供的诊断 JSON 回答，不得编造库存、销量、缺口、库龄或在途数字。"
                        "最终输出只允许三个一级方向：销售、物流、计划；不要再拆成库存情况、补货倒计时、溯源、潜力分析等额外一级标题。"
                        "diagnosis.logistics_plan 只是系统根据提前期和缺口窗口给出的候选窗口，不是固定结论。"
                        "必须优先使用 diagnosis.direction_recommendations；其他字段只作为补充证据。"
                        "计划方向必须优先使用 diagnosis.computed_strategy_recommendation 和 diagnosis.direction_recommendations.plan.computed_strategy，"
                        "补货方式、补货数量、采购建议以程序已算好的策略行为准，不得用 logistics_plan 重新发明口径。"
                        "销售方向必须包含三件事：1）根据上几周销量、广告投入比例、销量曲线判断销售潜力；2）判断是否断货、断货从什么时候开始、预计断几天、控销控多少和控几天；3）判断销售预测是否准确、是否需要提高销售预测量。"
                        "销售方向里的售卖表现必须使用 direction_recommendations.sales.sales_performance 的实际销量复盘；demand_7d、demand_30d、daily_demand 只能作为需求/预测参考，不能当作实际销量。"
                        "销售方向的控销必须使用 direction_recommendations.sales.stockout_and_sales_control 中的平滞/爆旺控销口径；严禁用加急空运、普通空运、快船或慢船到货日来推控销天数。"
                        "物流方向只写物流/在途/上架/调拨异常和要检查的动作，例如 FBA 接收、海外仓在途、本地仓在途、到货是否晚于缺口。"
                        "计划方向只写库存补货、采购、补货方式、补货数量、补货成本对比、补货倒计时等计划侧建议。"
                        "你必须像业务决策者一样基于库存、销量、断货窗口、冗余和候选窗口自行判断模型动作："
                        "哪段时间控销、是否需要加急空运/普通空运/紧急调拨、快船补哪段需求、慢船补哪段需求、哪些补货要因冗余被拦截或削减。"
                        "如果某个候选动作不应该执行，要明确说不执行及原因。"
                        "外部动作Skill只能作为三个方向里的草稿说明，不得单独成段；不得声称已经写入采购、发货、控销或飞书系统。"
                        "缺少销售计划、周度价格曲线、广告花费、历史销量或 product info.weight_gram 时，写到对应方向的待补数据里。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "user_question": user_question,
                            "diagnosis": compact,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        }
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
            reply = _extract_response_text(raw).strip()
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error = f"HTTPError {exc.code}: {error_body[:1000]}"
            record_model_interaction("sku_full_chain_diagnosis_ai", interaction_id, payload, output=raw, error=error)
            raise RuntimeError(error) from exc
        except Exception as exc:
            record_model_interaction("sku_full_chain_diagnosis_ai", interaction_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            raise

        record_model_interaction("sku_full_chain_diagnosis_ai", interaction_id, payload, output=raw)
        return {
            "reply": reply,
            "model": selected_model,
            "record_path": f"logs/model_interactions/conversations/{interaction_id}.txt",
            "input": payload,
            "output": raw,
        }

    def generate_from_sku_data(self, item_payload: dict[str, Any], user_question: str = "生成 SKU 全链路诊断") -> dict[str, Any]:
        """Let the model diagnose directly from the current frontend SKU row."""

        sku_data = _compact_frontend_sku_payload(item_payload)
        content = json.dumps({"user_question": user_question, "sku_data": sku_data}, ensure_ascii=False)
        route = self.model_router.route(
            ModelRouteRequest(
                action=ModelAction.BUSINESS_EXPLANATION,
                content=content,
                metadata={
                    "sku_full_chain_diagnosis": True,
                    "frontend_payload_diagnosis": True,
                    "material_code": sku_data.get("identity", {}).get("material_code"),
                },
            )
        )
        selected_model = self.model or route.model
        interaction_id = generate_time_id()
        payload = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": (
                        "你是 PMC 库存控制塔的 SKU 全链路诊断模型。"
                        "用户已经从前端传入当前 SKU 明细数据，sku_data 是唯一事实来源。"
                        "你必须直接根据这些字段判断库存情况、售卖情况、断货风险、冗余风险、归因、"
                        "发货/控销节奏、补货数量、补货方式、采购逻辑、销售建议和 SKU 潜力。"
                        "不得编造库存、销量、缺口、库龄、在途、日期或金额；字段缺失时必须说明缺失。"
                        "必须优先使用 sku_data.direction_recommendations；computed_diagnosis、replenishment_countdowns、replenishment_recommendation、"
                        "replenishment_cost_comparison、weekly_sales_and_price、monthly_forecast_review、external_action_skills 只作为补充证据。"
                        "计划方向必须优先使用 sku_data.computed_strategy_recommendation 和 sku_data.direction_recommendations.plan.computed_strategy；"
                        "补货方式、补货数量、采购建议以程序已算好的策略行为准，不得用 logistics_plan 或旧窗口测算重写口径。"
                        "月度复盘必须使用 sku_data.monthly_forecast_review 的 weekly_estimates、daily_price_points、广告投入、预测/实际行数和 notes，不能只看一个汇总值。"
                        "可以使用字段中的风险等级、warning、evidence、chazhi 缺口、可售天数、库龄、销售计划/周度价格曲线/广告花费和需求数据进行业务判断。"
                        "如果 sku_data.shipping_cost_estimate.ok 为 true，必须把加急空运、普通空运、快船、慢船的单件运费作为成本参考，"
                        "公式为 unit_weight_kg * rate_cny_per_kg；若有 suggested_quantity，则总补货成本按 suggested_quantity * unit_shipping_cost_cny 粗估。"
                        "最终输出只允许三个一级方向：销售、物流、计划；不要输出额外一级标题。"
                        "销售方向必须包含：销售潜力、断货风险/控销数量/控销天数/断货开始与持续天数、销售预测准确性和是否要提高预测量。"
                        "销售方向里的售卖表现必须使用 sku_data.direction_recommendations.sales.sales_performance 的实际销量复盘；不要把 demand_30d 或 daily_demand 写成近30天实际销量。"
                        "销售方向的控销必须使用 sku_data.direction_recommendations.sales.stockout_and_sales_control 中的平滞/爆旺控销策略；不要用空运或海运到货日作为控销依据。"
                        "物流方向必须包含：检测到的物流异常、在途/接收/上架/调拨检查项。"
                        "计划方向必须包含：库存补货建议、补货方式、补货数量、成本对比和采购建议。"
                        "涉及动作时必须保持草稿性质，采购、发货、控销、促销清货和关闭异常都需要人工确认，外部动作Skill只能打印草稿并归入对应方向。"
                    ),
                },
                {"role": "user", "content": content},
            ],
        }
        raw = self._post_diagnosis_request(payload, interaction_id)
        reply = _extract_response_text(raw).strip()
        return {
            "reply": reply,
            "model": selected_model,
            "record_path": f"logs/model_interactions/conversations/{interaction_id}.txt",
            "input": payload,
            "output": raw,
        }

    def _post_diagnosis_request(self, payload: dict[str, Any], interaction_id: str) -> dict[str, Any]:
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        http_request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=request_body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        raw: dict[str, Any] | None = None
        try:
            with urllib.request.urlopen(http_request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            error = f"HTTPError {exc.code}: {error_body[:1000]}"
            record_model_interaction("sku_full_chain_diagnosis_ai", interaction_id, payload, output=raw, error=error)
            raise RuntimeError(error) from exc
        except Exception as exc:
            record_model_interaction("sku_full_chain_diagnosis_ai", interaction_id, payload, output=raw, error=f"{type(exc).__name__}: {exc}")
            raise

        record_model_interaction("sku_full_chain_diagnosis_ai", interaction_id, payload, output=raw)
        return raw


def diagnose_sku_full_chain(
    material_code: str | None,
    *,
    store_name: str | None = None,
    country_code: str | None = None,
    shipments_country: str | None = None,
    connector: Any | None = None,
) -> SkuDiagnosis:
    filters = {
        "store_name": store_name,
        "country_code": country_code,
        "shipments_country": shipments_country,
        "order_by": "risk_then_demand",
    }
    filters = {key: value for key, value in filters.items() if value not in {None, ""}}
    summary = get_control_tower_summary(material_code=material_code, filters=filters, connector=connector, page_size=50)
    if not summary.items:
        raise LookupError(f"未找到 SKU 全链路诊断数据：{material_code or '-'}")
    item = _choose_best_item(summary.items, material_code, store_name, country_code)
    return build_sku_diagnosis(item)


def diagnose_sku_full_chain_with_ai(
    material_code: str | None,
    *,
    store_name: str | None = None,
    country_code: str | None = None,
    shipments_country: str | None = None,
    question: str = "生成 SKU 全链路诊断",
    connector: Any | None = None,
    ai_client: OpenAISkuDiagnosisClient | None = None,
) -> dict[str, Any]:
    diagnosis = diagnose_sku_full_chain(
        material_code,
        store_name=store_name,
        country_code=country_code,
        shipments_country=shipments_country,
        connector=connector,
    )
    enriched_source_item, enriched_diagnosis = _prepare_diagnosis_payload(diagnosis.source_item, connector=connector)
    fallback_result = {
        **enriched_diagnosis,
        "diagnosis_mode": "model_from_control_tower_data",
        "source_item": _compact_frontend_sku_payload(enriched_source_item),
        "shipping_cost_estimate": _json_safe(enriched_source_item.get("shipping_cost_estimate")),
    }
    try:
        ai_result = (ai_client or OpenAISkuDiagnosisClient()).generate_from_sku_data(enriched_source_item, user_question=question)
    except Exception as exc:
        return {
            **fallback_result,
            "diagnosis_mode": "rules_from_control_tower_data",
            "ai_error": str(exc),
        }
    return {
        **fallback_result,
        "ai_reply": ai_result["reply"],
        "ai_model": ai_result["model"],
        "ai_record_path": ai_result["record_path"],
        "ai_review": _build_ai_review(ai_result),
    }


def diagnose_sku_payload_with_ai(
    item_payload: dict[str, Any],
    *,
    question: str = "生成 SKU 全链路诊断",
    connector: Any | None = None,
    ai_client: OpenAISkuDiagnosisClient | None = None,
) -> dict[str, Any]:
    enriched_payload, fallback = _prepare_diagnosis_payload(item_payload, connector=connector)
    source_item = _compact_frontend_sku_payload(enriched_payload)
    fallback_result = {
        **fallback,
        "diagnosis_mode": "model_from_frontend_data",
        "source_item": source_item,
        "shipping_cost_estimate": _json_safe(enriched_payload.get("shipping_cost_estimate")),
    }
    try:
        ai_result = (ai_client or OpenAISkuDiagnosisClient()).generate_from_sku_data(enriched_payload, user_question=question)
    except Exception as exc:
        return {
            **fallback_result,
            "diagnosis_mode": "rules_from_frontend_data",
            "ai_error": str(exc),
        }
    return {
        **fallback_result,
        "ai_reply": ai_result["reply"],
        "ai_model": ai_result["model"],
        "ai_record_path": ai_result["record_path"],
        "ai_review": _build_ai_review(ai_result),
    }


def estimate_sku_shipping_cost(
    item_payload: dict[str, Any],
    *,
    connector: Any | None = None,
) -> dict[str, Any]:
    enriched_payload = _enrich_payload_with_shipping_cost(item_payload, connector=connector)
    return {
        "material_code": enriched_payload.get("material_code") or enriched_payload.get("sku") or enriched_payload.get("msku") or "",
        "product_weight": _json_safe(enriched_payload.get("product_weight")),
        "shipping_cost_estimate": _json_safe(enriched_payload.get("shipping_cost_estimate")),
        "replenishment_cost_comparison": _json_safe(enriched_payload.get("replenishment_cost_comparison")),
        "source_item": _compact_frontend_sku_payload(enriched_payload),
    }


def control_tower_item_from_payload(payload: dict[str, Any]) -> ControlTowerItem:
    values = {}
    for definition in fields(ControlTowerItem):
        if definition.name in payload:
            raw_value = payload[definition.name]
            if definition.name in NUMERIC_ITEM_FIELDS:
                values[definition.name] = _number(raw_value) or 0
            elif definition.name == "pici_first_shortage_days":
                parsed = _number(raw_value)
                values[definition.name] = int(parsed) if parsed is not None else None
            elif definition.name in {"pici_min_gap_quantity", "sellable_days", "fba_long_age_ratio"}:
                values[definition.name] = _number(raw_value)
            elif definition.name in {"pici_gap_values", "redundancy_sellable_days", "evidence"}:
                values[definition.name] = raw_value if isinstance(raw_value, dict) else {}
            else:
                values[definition.name] = str(raw_value or "")
        elif definition.name == "evidence":
            values[definition.name] = {}
        elif definition.name in {"pici_first_shortage_days", "pici_min_gap_quantity", "sellable_days", "fba_long_age_ratio"}:
            values[definition.name] = None
        elif definition.name == "pici_gap_values":
            values[definition.name] = {}
        elif definition.name == "redundancy_sellable_days":
            values[definition.name] = {}
        elif definition.name in NUMERIC_ITEM_FIELDS:
            values[definition.name] = 0
        else:
            values[definition.name] = ""
    return ControlTowerItem(**values)


def build_sku_diagnosis(item: ControlTowerItem, source_payload: dict[str, Any] | None = None) -> SkuDiagnosis:
    stockout_active = _active(item.stockout_risk_level)
    overstock_active = _active(item.overstock_risk_level)
    anomaly_active = bool(item.evidence.get("risk_flags"))
    title = item.sku_name or item.msku or item.fnsku or item.material_code
    source_item = {**asdict(item), **(source_payload if isinstance(source_payload, dict) else {})}
    overstock_attribution_active = _real_overstock_requires_attribution(item, source_item)
    logistics_plan = _build_logistics_plan(item, stockout_active, overstock_active)
    replenishment_countdowns = _build_replenishment_countdowns(item, source_item)
    replenishment_recommendation = _build_replenishment_recommendation(item, stockout_active, overstock_active, logistics_plan, replenishment_countdowns)
    replenishment_cost_comparison = _build_replenishment_cost_comparison(logistics_plan, None)
    root_cause_analysis = _build_root_cause_analysis(item, stockout_active, overstock_attribution_active, anomaly_active, source_item)
    sales_recommendation = _build_sales_recommendation(item, stockout_active, overstock_active, replenishment_recommendation, source_item)
    potential_analysis = _build_potential_analysis(item, stockout_active, overstock_active, source_item)
    strategy_recommendation = _sales_property_control_strategy(item)
    external_action_skills = [
        skill.to_dict()
        for skill in build_sku_external_action_skills(
            item.material_code,
            sales_control_summary=str(strategy_recommendation.get("sales_recommendation") or sales_recommendation.get("sales_control") or ""),
            replenishment_summary=str(strategy_recommendation.get("pmc_recommendation") or strategy_recommendation.get("replenishment_text") or ""),
            purchase_summary=str(
                strategy_recommendation.get("procurement_recommendation")
                or strategy_recommendation.get("pmc_recommendation")
                or strategy_recommendation.get("replenishment_text")
                or ""
            ),
        )
    ]
    direction_recommendations = _build_direction_recommendations(
        item,
        stockout_active,
        overstock_active,
        logistics_plan,
        replenishment_countdowns,
        replenishment_recommendation,
        replenishment_cost_comparison,
        root_cause_analysis,
        sales_recommendation,
        potential_analysis,
        external_action_skills,
        source_item,
        strategy_recommendation,
    )
    attribution = _build_attribution(item, stockout_active, overstock_attribution_active, anomaly_active)
    remedies = _build_remedies(item, stockout_active, overstock_active, anomaly_active)
    return SkuDiagnosis(
        material_code=item.material_code,
        title=title,
        overall_status=_overall_status(item, stockout_active, overstock_active, anomaly_active),
        risk_level=item.risk_level,
        inventory=_inventory_section(item),
        sales=_sales_section(item),
        stockout=_stockout_section(item, stockout_active),
        overstock=_overstock_section(item, overstock_active),
        attribution=attribution,
        root_cause_analysis=root_cause_analysis,
        handling_logic=_handling_logic(item, stockout_active, overstock_active, anomaly_active),
        logistics_plan=logistics_plan,
        replenishment_countdowns=replenishment_countdowns,
        replenishment_recommendation=replenishment_recommendation,
        replenishment_cost_comparison=replenishment_cost_comparison,
        sales_recommendation=sales_recommendation,
        potential_analysis=potential_analysis,
        computed_strategy_recommendation=strategy_recommendation,
        direction_recommendations=direction_recommendations,
        external_action_skills=external_action_skills,
        remedies=remedies,
        calculation_logic=[
            "库存结构 = FBA库存 + 海外仓库存 + 本地仓库存 + 备货库存；在途含 FBA接收/处理中、海外/本地发 FBA 在途、仓库在途和计划量。",
            "售卖情况优先看区间销量、近7天需求、未来/近30天需求和日均需求；可售天数 = FBA可售 / 日均需求。",
            "断货风险按 temp_lingxing_pici_sale 的 chazhi_0_N 缺口窗口判断，最早缺口越近风险越高。",
            "补货倒计时按 6 个动作节点计算：可售天数N - FBA/海外仓/本地仓安全天数 - 对应交付天数；倒计时 <= 0 表示已到催货、发货或下采购单动作点。",
            "建议补货数量按渠道到货窗口覆盖对应缺口：加急空运约第10天到，普通空运约第20天到，快船约第45天到，慢船约第60天到；总补货成本 = 建议数量 * 单件运费。",
            "计划方向必须优先采用 control_tower_recommendations._build_strategy_recommendation 已计算的控销/补货策略行；旧窗口补货测算只作为辅助证据，不得覆盖程序策略。",
            "冗余风险按 SOP 可售天数1-6阈值判断：爆旺用1>90、2/3/4>120、5/6>180；平滞用1>60、2/3/4>105、5/6>150；再叠加 FBA库龄区间动作。",
            "断货/冗余溯源按销量需求、广告/促销信号、物流在途、库存位置、库龄和预测偏差分层判断；缺少广告或周度价格数据时必须标记待补数据。",
            "断货和冗余同时存在时，优先按库存结构错配处理：FBA前端短缺、海外/本地/长库龄或在途库存无法及时转化为可售。",
            "最终输出按销售、物流、计划三个方向汇总：销售看潜力/控销/预测，物流看异常检查，计划看库存补货/采购/成本。",
        ],
        suggested_action=item.suggested_action,
        source_item=source_item,
    )


def _real_overstock_requires_attribution(item: ControlTowerItem, source: dict[str, Any]) -> bool:
    if not _active(item.overstock_risk_level):
        return False
    if item.overstock_risk_level in {"medium", "high", "critical"}:
        return True
    if item.overstock_risk_level == "low":
        return False
    evidence = item.evidence if isinstance(item.evidence, dict) else {}
    source_evidence = source.get("evidence") if isinstance(source.get("evidence"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            item.warning_type,
            item.suggested_action,
            item.overstock_warning,
            evidence.get("overstock_reason"),
            source.get("warning_type"),
            source.get("suggested_action"),
            source_evidence.get("overstock_reason"),
        )
    )
    warning_markers = ("预警监控", "SOP 冗余-预警", "重点监控")
    if any(marker in text for marker in warning_markers):
        return False
    return True


def _compact_diagnosis_payload(diagnosis: SkuDiagnosis) -> dict[str, Any]:
    return {
        "material_code": diagnosis.material_code,
        "title": diagnosis.title,
        "overall_status": diagnosis.overall_status,
        "risk_level": diagnosis.risk_level,
        "inventory": asdict(diagnosis.inventory),
        "sales": asdict(diagnosis.sales),
        "stockout": asdict(diagnosis.stockout),
        "overstock": asdict(diagnosis.overstock),
        "attribution": diagnosis.attribution,
        "root_cause_analysis": diagnosis.root_cause_analysis,
        "handling_logic": diagnosis.handling_logic,
        "logistics_plan": diagnosis.logistics_plan,
        "replenishment_countdowns": diagnosis.replenishment_countdowns,
        "replenishment_recommendation": diagnosis.replenishment_recommendation,
        "replenishment_cost_comparison": diagnosis.replenishment_cost_comparison,
        "sales_recommendation": diagnosis.sales_recommendation,
        "potential_analysis": diagnosis.potential_analysis,
        "computed_strategy_recommendation": diagnosis.computed_strategy_recommendation,
        "direction_recommendations": diagnosis.direction_recommendations,
        "external_action_skills": diagnosis.external_action_skills,
        "remedies": diagnosis.remedies,
        "calculation_logic": diagnosis.calculation_logic,
        "suggested_action": diagnosis.suggested_action,
        "identity": {
            "msku": diagnosis.source_item.get("msku"),
            "fnsku": diagnosis.source_item.get("fnsku"),
            "asin": diagnosis.source_item.get("asin"),
            "store_name": diagnosis.source_item.get("store_name"),
            "country_code": diagnosis.source_item.get("country_code"),
            "shipments_country": diagnosis.source_item.get("shipments_country"),
            "sales_property": diagnosis.source_item.get("sales_property"),
        },
    }


def _build_ai_review(ai_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": ai_result.get("model"),
        "record_path": ai_result.get("record_path"),
        "input": _json_safe(ai_result.get("input")),
        "output": _json_safe(ai_result.get("output")),
        "extracted_reply": ai_result.get("reply"),
    }


def _compact_frontend_sku_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Group the frontend row data so the model sees data, not a pre-made diagnosis."""

    source = payload if isinstance(payload, dict) else {}
    return {
        "identity": _pick_fields(
            source,
            [
                "material_code",
                "msku",
                "fnsku",
                "asin",
                "sku_name",
                "store_name",
                "country_code",
                "shipments_country",
                "sales_property",
                "seasonality",
                "msku_life_process",
            ],
        ),
        "risk_signals": _pick_fields(
            source,
            [
                "risk_type",
                "risk_level",
                "warning_type",
                "suggested_action",
                "risk_score",
                "stockout_risk_level",
                "stockout_warning",
                "overstock_risk_level",
                "overstock_warning",
            ],
        ),
        "inventory": _pick_fields(
            source,
            [
                "total_inventory",
                "fba_sellable",
                "fba_inventory",
                "overseas_inventory",
                "local_inventory",
                "inbound_total",
                "projected_7d",
                "lead_time_days",
            ],
        ),
        "sales_and_demand": _pick_fields(
            source,
            [
                "daily_sales_volume",
                "demand_7d",
                "demand_30d",
                "daily_demand",
                "sellable_days",
            ],
        ),
        "stockout": _pick_fields(
            source,
            [
                "pici_first_shortage_days",
                "pici_min_gap_quantity",
                "pici_key_gap",
                "pici_gap_values",
            ],
        ),
        "overstock": _pick_fields(
            source,
            [
                "long_age_inventory",
                "fba_age_61_to_90",
                "fba_age_91_to_180",
                "fba_age_181_to_270",
                "fba_age_271_to_330",
                "fba_age_331_to_365",
                "fba_age_365_plus",
                "fba_long_age_ratio",
                "redundancy_sellable_days",
            ],
        ),
        "product_weight": _json_safe(source.get("product_weight", {})),
        "shipping_cost_estimate": _json_safe(source.get("shipping_cost_estimate", {})),
        "computed_diagnosis": _json_safe(source.get("computed_diagnosis", {})),
        "replenishment_countdowns": _json_safe(source.get("replenishment_countdowns", [])),
        "replenishment_recommendation": _json_safe(source.get("replenishment_recommendation", {})),
        "replenishment_cost_comparison": _json_safe(source.get("replenishment_cost_comparison", {})),
        "root_cause_analysis": _json_safe(source.get("root_cause_analysis", [])),
        "sales_recommendation": _json_safe(source.get("sales_recommendation", {})),
        "potential_analysis": _json_safe(source.get("potential_analysis", {})),
        "computed_strategy_recommendation": _json_safe(source.get("computed_strategy_recommendation", {})),
        "direction_recommendations": _json_safe(source.get("direction_recommendations", {})),
        "monthly_forecast_review": _compact_monthly_forecast_review(source.get("monthly_forecast_review") or source.get("forecast_review")),
        "weekly_sales_and_price": _json_safe(source.get("weekly_sales_and_price", {})),
        "first_leg_shipments": _json_safe(_shipment_rows_from_source(source)[:20], max_items=20),
        "external_action_skills": _json_safe(source.get("external_action_skills", [])),
        "evidence": _json_safe(source.get("evidence", {})),
        "field_notes": {
            "pici_gap_values": "chazhi_0_N 缺口窗口；负数表示对应窗口可能缺口。",
            "projected_7d": "预计 7 天后 FBA 可售余额，负数表示短期覆盖不足。",
            "sales_and_demand": "daily_sales_volume 是当前页面选择销售区间的实际销量；demand_7d、demand_30d、daily_demand 是需求/预测参考，不等于近30天实际销量。",
            "sellable_days": "FBA 可售天数；redundancy_sellable_days 是不同库存范围折算的可售天数。",
            "risk_levels": "risk_level/stockout_risk_level/overstock_risk_level 是前端当前行已有风险信号，模型可复核但不要盲目照抄。",
            "replenishment_countdowns": "补货倒计时按图中 6 个动作节点计算；倒计时 <= 0 表示已到动作点。",
            "shipping_cost_estimate": "单件运费 = product info.weight_gram / 1000 * 渠道元/kg；总补货成本 = 建议补货数量 * 单件运费；加急空运85、普通空运60、快船11.5、慢船9。",
            "computed_strategy_recommendation": "来自 control_tower_recommendations._build_strategy_recommendation 的程序策略行；计划方向补货/采购/控销口径优先使用它。",
            "monthly_forecast_review": "月度复盘完整结构，含周度预测/实际销量、广告投入、广告订单、价格点、行数和复盘 notes；AI 诊断销售潜力和预测准确性必须优先使用它。",
            "direction_recommendations": "最终 AI 输出只按销售、物流、计划三个方向组织；销售看潜力/控销/预测，物流看异常检查，计划看补货/采购/成本。",
            "external_action_skills": "外部写动作当前都是 placeholder skill，只能打印动作草稿，不能直接写采购、发货、飞书或控销系统。",
        },
        "raw_fields": {str(key): _json_safe(value) for key, value in source.items()},
    }


def prepare_sku_diagnosis_payload(payload: dict[str, Any], connector: Any | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    return _prepare_diagnosis_payload(payload, connector=connector)


def _prepare_diagnosis_payload(payload: dict[str, Any], connector: Any | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched = _enrich_payload_with_shipping_cost(payload, connector=connector)
    enriched = _enrich_payload_with_market_review(enriched, connector=connector)
    enriched = _enrich_payload_with_first_leg_shipments(enriched, connector=connector)
    diagnosis = build_sku_diagnosis(control_tower_item_from_payload(enriched), source_payload=enriched).to_dict()
    enriched["computed_diagnosis"] = _compact_diagnosis_dict(diagnosis)
    for key in (
        "replenishment_countdowns",
        "replenishment_recommendation",
        "replenishment_cost_comparison",
        "root_cause_analysis",
        "sales_recommendation",
        "potential_analysis",
        "computed_strategy_recommendation",
        "direction_recommendations",
        "external_action_skills",
    ):
        enriched[key] = diagnosis.get(key)
    enriched["monthly_forecast_review"] = _compact_monthly_forecast_review(enriched.get("forecast_review") or enriched.get("monthly_forecast_review"))
    enriched["shipping_cost_estimate"] = _merge_shipping_cost_comparison(
        enriched.get("shipping_cost_estimate"),
        diagnosis.get("replenishment_cost_comparison"),
    )
    diagnosis["replenishment_cost_comparison"] = _json_safe(enriched.get("shipping_cost_estimate", {}).get("cost_comparison") or diagnosis.get("replenishment_cost_comparison"))
    diagnosis["direction_recommendations"] = _build_direction_recommendations(
        control_tower_item_from_payload(enriched),
        _active(str(enriched.get("stockout_risk_level") or "")),
        _active(str(enriched.get("overstock_risk_level") or "")),
        diagnosis.get("logistics_plan") if isinstance(diagnosis.get("logistics_plan"), list) else [],
        diagnosis.get("replenishment_countdowns") if isinstance(diagnosis.get("replenishment_countdowns"), list) else [],
        diagnosis.get("replenishment_recommendation") if isinstance(diagnosis.get("replenishment_recommendation"), dict) else {},
        diagnosis.get("replenishment_cost_comparison") if isinstance(diagnosis.get("replenishment_cost_comparison"), dict) else {},
        diagnosis.get("root_cause_analysis") if isinstance(diagnosis.get("root_cause_analysis"), list) else [],
        diagnosis.get("sales_recommendation") if isinstance(diagnosis.get("sales_recommendation"), dict) else {},
        diagnosis.get("potential_analysis") if isinstance(diagnosis.get("potential_analysis"), dict) else {},
        diagnosis.get("external_action_skills") if isinstance(diagnosis.get("external_action_skills"), list) else [],
        enriched,
        diagnosis.get("computed_strategy_recommendation") if isinstance(diagnosis.get("computed_strategy_recommendation"), dict) else None,
    )
    enriched["direction_recommendations"] = diagnosis["direction_recommendations"]
    return enriched, diagnosis


def _enrich_payload_with_first_leg_shipments(payload: dict[str, Any], connector: Any | None = None) -> dict[str, Any]:
    enriched = dict(payload if isinstance(payload, dict) else {})
    if _shipment_rows_from_source(enriched):
        return enriched
    if connector is None or not getattr(getattr(connector, "config", None), "ready", False):
        return enriched
    if not hasattr(connector, "get_first_leg_shipment_rows"):
        return enriched
    codes = _material_codes_from_payload(enriched)
    if not codes:
        return enriched
    try:
        rows = connector.get_first_leg_shipment_rows(
            material_codes=codes,
            latest_only=True,
            limit=200,
        )
    except Exception as exc:  # pragma: no cover - defensive guard around external DB calls
        enriched["first_leg_error"] = f"{type(exc).__name__}: {exc}"
        return enriched
    if rows:
        enriched["first_leg_shipments"] = rows
        enriched["shipments"] = rows
    return enriched


def _compact_diagnosis_dict(diagnosis: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_safe(diagnosis.get(key))
        for key in (
            "material_code",
            "overall_status",
            "risk_level",
            "inventory",
            "sales",
            "stockout",
            "overstock",
            "root_cause_analysis",
            "replenishment_countdowns",
            "replenishment_recommendation",
            "replenishment_cost_comparison",
            "sales_recommendation",
            "potential_analysis",
            "computed_strategy_recommendation",
            "direction_recommendations",
            "external_action_skills",
            "suggested_action",
            "calculation_logic",
        )
    }


def _enrich_payload_with_market_review(payload: dict[str, Any], connector: Any | None = None) -> dict[str, Any]:
    enriched = dict(payload if isinstance(payload, dict) else {})
    if enriched.get("weekly_sales_and_price"):
        return enriched
    forecast_review = enriched.get("forecast_review") or enriched.get("monthly_forecast_review")
    if isinstance(forecast_review, dict):
        enriched["weekly_sales_and_price"] = _weekly_sales_and_price_from_review(forecast_review)
        return enriched
    if connector is None or not getattr(getattr(connector, "config", None), "ready", False):
        enriched["weekly_sales_and_price"] = {
            "ok": False,
            "reason": "未接入月度预测复盘/周度价格曲线，潜力分析只使用当前行库存、销量和属性。",
        }
        return enriched
    try:
        review = get_monthly_forecast_review(
            material_code=str(enriched.get("material_code") or enriched.get("sku") or ""),
            msku=str(enriched.get("msku") or ""),
            fnsku=str(enriched.get("fnsku") or ""),
            asin=str(enriched.get("asin") or ""),
            store_name=str(enriched.get("store_name") or ""),
            country_code=str(enriched.get("country_code") or ""),
            connector=connector,
        ).to_dict()
    except Exception as exc:
        enriched["weekly_sales_and_price"] = {
            "ok": False,
            "reason": f"月度预测复盘/周度价格曲线暂不可用：{type(exc).__name__}: {exc}",
        }
        return enriched
    enriched["forecast_review"] = review
    enriched["weekly_sales_and_price"] = _weekly_sales_and_price_from_review(review)
    return enriched


def _weekly_sales_and_price_from_review(review: dict[str, Any]) -> dict[str, Any]:
    weekly = review.get("weekly_estimates") if isinstance(review.get("weekly_estimates"), list) else []
    prices = review.get("daily_price_points") if isinstance(review.get("daily_price_points"), list) else []
    forecast_row_count = int(_number(review.get("forecast_row_count")) or 0)
    forecast_missing = forecast_row_count == 0
    raw_forecast_quantity = review.get("forecast_quantity")
    return {
        "ok": True,
        "target_month": review.get("target_month"),
        "review_start_date": review.get("review_start_date") or review.get("comparison_start_date"),
        "review_end_date": review.get("review_end_date") or review.get("comparison_end_date"),
        "forecast_quantity": None if forecast_missing else raw_forecast_quantity,
        "raw_forecast_quantity": raw_forecast_quantity,
        "actual_sales": review.get("actual_sales"),
        "last_year_same_week_sales": review.get("last_year_same_week_sales"),
        "ad_spend": review.get("ad_spend"),
        "ad_sales_amount": review.get("ad_sales_amount"),
        "ad_order_quantity": review.get("ad_order_quantity"),
        "organic_sales": review.get("organic_sales"),
        "ad_acos": review.get("ad_acos"),
        "variance_percent": review.get("variance_percent"),
        "result_label": review.get("result_label"),
        "snapshot_row_count": review.get("snapshot_row_count"),
        "forecast_row_count": forecast_row_count,
        "actual_row_count": review.get("actual_row_count"),
        "forecast_data_status": "missing" if forecast_missing else "matched",
        "forecast_missing_reason": (
            f"预测表未匹配到 {review.get('target_month') or '-'} 的销售预测行；当前 raw_forecast_quantity=0 代表缺数据，不代表真实预测为0。"
            if forecast_missing
            else ""
        ),
        "weekly_estimates": _json_safe(weekly[:12]),
        "daily_price_points": _json_safe(prices[:80]),
        "forecast_anomalies": _json_safe(review.get("forecast_anomalies") or []),
        "sales_anomalies": _json_safe(review.get("sales_anomalies") or []),
        "detail_monthly_totals": _json_safe(review.get("detail_monthly_totals") or [], max_items=12),
    }


def _compact_monthly_forecast_review(review: Any) -> dict[str, Any]:
    if not isinstance(review, dict) or not review:
        return {
            "ok": False,
            "reason": "未拿到月度复盘明细。",
        }
    forecast_row_count = int(_number(review.get("forecast_row_count")) or 0)
    forecast_missing = forecast_row_count == 0
    weekly = review.get("weekly_estimates") if isinstance(review.get("weekly_estimates"), list) else []
    forecast_versions = review.get("forecast_versions") if isinstance(review.get("forecast_versions"), list) else []
    prices = review.get("daily_price_points") if isinstance(review.get("daily_price_points"), list) else []
    snapshots = review.get("snapshot_rows") if isinstance(review.get("snapshot_rows"), list) else []
    compact = _pick_fields(
        review,
        [
            "data_source",
            "sales_source",
            "forecast_source",
            "target_month",
            "target_start_date",
            "target_end_date",
            "comparison_month",
            "comparison_start_date",
            "comparison_end_date",
            "review_start_date",
            "review_end_date",
            "month_offset",
            "snapshot_date",
            "forecast_field",
            "actual_field",
            "forecast_quantity",
            "actual_sales",
            "ad_spend",
            "ad_sales_amount",
            "ad_order_quantity",
            "organic_sales",
            "ad_acos",
            "difference",
            "variance_ratio",
            "variance_percent",
            "result_type",
            "result_label",
            "snapshot_row_count",
            "forecast_row_count",
            "actual_row_count",
            "notes",
        ],
    )
    compact["ok"] = True
    compact["forecast_data_status"] = "missing" if forecast_missing else "matched"
    compact["forecast_missing_reason"] = (
        f"预测表未匹配到 {review.get('target_month') or '-'} 的销售预测行；forecast_quantity=0 代表缺数据，不代表真实预测为0。"
        if forecast_missing
        else ""
    )
    compact["weekly_estimates"] = _json_safe(weekly[:20], max_items=20)
    compact["forecast_versions"] = _json_safe(forecast_versions[:6], max_items=6)
    compact["daily_price_points"] = _json_safe(prices[:120], max_items=120)
    compact["snapshot_rows"] = _json_safe(snapshots[:20], max_items=20)
    compact["detail_monthly_totals"] = _json_safe(review.get("detail_monthly_totals") or [], max_items=12)
    compact["forecast_anomalies"] = _json_safe(review.get("forecast_anomalies") or [], max_items=12)
    compact["sales_anomalies"] = _json_safe(review.get("sales_anomalies") or [], max_items=12)
    compact["coverage"] = {
        "weekly_estimate_count": len(weekly),
        "forecast_version_count": len(forecast_versions),
        "daily_price_point_count": len(prices),
        "snapshot_row_count": len(snapshots),
    }
    return compact


def _enrich_payload_with_shipping_cost(payload: dict[str, Any], connector: Any | None = None) -> dict[str, Any]:
    source = payload if isinstance(payload, dict) else {}
    enriched = dict(source)
    weight_info = _product_weight_from_payload(enriched)
    lookup_error = None

    if weight_info is None and connector is not None and hasattr(connector, "get_product_weight_rows"):
        try:
            rows = connector.get_product_weight_rows(
                _material_codes_from_payload(enriched),
                store_name=str(enriched.get("store_name") or ""),
                country_code=str(enriched.get("country_code") or ""),
                limit=20,
            )
        except Exception as exc:  # pragma: no cover - defensive guard around external DB calls
            rows = []
            lookup_error = f"{type(exc).__name__}: {exc}"
        if rows:
            weight_info = _product_weight_from_product_info_row(rows[0])

    if weight_info is not None:
        enriched["product_weight"] = weight_info
    current_month_profit_summary = _current_month_profit_summary_from_payload(enriched, connector=connector)
    if current_month_profit_summary is not None:
        enriched["current_month_profit_summary"] = current_month_profit_summary
    enriched["shipping_cost_estimate"] = _shipping_cost_estimate_from_payload(
        enriched,
        weight_info,
        current_month_profit_summary=current_month_profit_summary,
        lookup_error=lookup_error,
    )
    enriched["replenishment_cost_comparison"] = _json_safe(enriched["shipping_cost_estimate"].get("cost_comparison"))
    return enriched


def _material_codes_from_payload(source: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for key in ("material_code", "sku", "msku", "fnsku", "asin", "new_sku", "new_asin"):
        value = source.get(key)
        if value is not None and str(value).strip():
            codes.append(str(value).strip())
    return list(dict.fromkeys(codes))


def _current_month_profit_summary_from_payload(source: dict[str, Any], connector: Any | None = None) -> dict[str, Any] | None:
    existing = source.get("current_month_profit_summary")
    if isinstance(existing, dict) and existing:
        return _json_safe(existing)
    if connector is None or not hasattr(connector, "get_current_month_profit_summary"):
        return None
    try:
        return _json_safe(
            connector.get_current_month_profit_summary(
                _material_codes_from_payload(source),
                store_name=str(source.get("store_name") or ""),
                country_code=str(source.get("country_code") or ""),
            )
        )
    except Exception as exc:  # pragma: no cover - defensive guard around external DB calls
        return {
            "ok": False,
            "reason": f"查询本月利润失败，暂不能使用本月毛利率估算：{type(exc).__name__}: {exc}",
        }


def _product_weight_from_payload(source: dict[str, Any]) -> dict[str, Any] | None:
    nested = source.get("product_weight") if isinstance(source.get("product_weight"), dict) else {}
    for field_name in ("weight_gram", "unit_weight_gram", "sku_weight_gram", "product_weight_gram"):
        if field_name in nested:
            weight = _normalize_product_weight(nested.get(field_name), "payload", f"product_weight.{field_name}", nested)
            if weight is not None:
                return weight
        if field_name in source:
            weight = _normalize_product_weight(source.get(field_name), "payload", field_name, source)
            if weight is not None:
                return weight

    for field_name in ("weight_kg", "unit_weight_kg", "sku_weight_kg", "product_weight_kg"):
        if field_name in nested:
            weight_kg = _number(nested.get(field_name))
            weight = _normalize_product_weight(weight_kg * 1000 if weight_kg is not None else None, "payload", f"product_weight.{field_name}", nested)
            if weight is not None:
                return weight
        if field_name in source:
            weight_kg = _number(source.get(field_name))
            weight = _normalize_product_weight(weight_kg * 1000 if weight_kg is not None else None, "payload", field_name, source)
            if weight is not None:
                return weight
    return None


def _product_weight_from_product_info_row(row: dict[str, Any]) -> dict[str, Any] | None:
    return _normalize_product_weight(row.get("weight_gram"), "dim_lingxing_product_info", "weight_gram", row)


def _normalize_product_weight(
    weight_gram: Any,
    source_table: str,
    source_field: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    parsed = _number(weight_gram)
    if parsed is None or parsed <= 0:
        return None
    source = metadata if isinstance(metadata, dict) else {}
    result: dict[str, Any] = {
        "source_table": source_table,
        "source_field": source_field,
        "weight_gram": round(parsed, 3),
        "weight_kg": round(parsed / 1000, 6),
    }
    for key in ("sku", "material_code", "msku", "fnsku", "asin", "sku_name", "store_name", "country_code"):
        value = source.get(key)
        if value is not None and value != "":
            result[key] = _json_safe(value)
    dimensions = {}
    for key in ("size_length_cm", "size_width_cm", "size_height_cm"):
        value = source.get(key)
        if value is None or value == "":
            continue
        parsed_dimension = _number(value)
        if parsed_dimension is not None:
            dimensions[key] = parsed_dimension
    if dimensions:
        result["dimensions_cm"] = {key: round(value, 3) for key, value in dimensions.items() if value is not None}
    if source.get("size"):
        result["size"] = _json_safe(source.get("size"))
    return result


def _shipping_cost_estimate_from_payload(
    source: dict[str, Any],
    weight_info: dict[str, Any] | None,
    *,
    current_month_profit_summary: dict[str, Any] | None = None,
    lookup_error: str | None = None,
) -> dict[str, Any]:
    formula = "unit_shipping_cost_cny = unit_weight_kg * rate_cny_per_kg"
    base = {
        "formula": formula,
        "currency": "CNY",
        "rates_cny_per_kg": _shipping_rate_payload(),
        "material_codes": _material_codes_from_payload(source),
        "current_month_profit_summary": _json_safe(current_month_profit_summary or {}),
    }
    if weight_info is None:
        reason = "未拿到 product info.weight_gram，暂不能估算发货成本。"
        if lookup_error:
            reason = f"查询 product info.weight_gram 失败，暂不能估算发货成本：{lookup_error}"
        item = control_tower_item_from_payload(source)
        logistics_plan = _build_logistics_plan(item, _active(item.stockout_risk_level), _active(item.overstock_risk_level))
        cost_comparison = _build_replenishment_cost_comparison(logistics_plan, None)
        return {
            **base,
            "ok": False,
            "reason": reason,
            "weight": None,
            "estimates": [],
            "cost_comparison": cost_comparison,
        }

    item = control_tower_item_from_payload(source)
    stockout_active = _active(item.stockout_risk_level)
    overstock_active = _active(item.overstock_risk_level)
    logistics_plan = _build_logistics_plan(item, stockout_active, overstock_active)
    unit_weight_kg = _number(weight_info.get("weight_kg")) or 0
    estimates = []
    for plan in logistics_plan:
        channel = str(plan.get("channel") or "")
        rate = SHIPPING_COST_RATES_CNY_PER_KG.get(channel)
        if rate is None:
            continue
        unit_shipping_cost_cny = unit_weight_kg * rate
        estimates.append(
            {
                "channel": channel,
                "channel_label": SHIPPING_COST_CHANNEL_LABELS.get(channel, channel),
                "window": plan.get("window"),
                "arrival_day": plan.get("arrival_day"),
                "unit_weight_kg": round(unit_weight_kg, 6),
                "rate_cny_per_kg": rate,
                "unit_shipping_cost_cny": round(unit_shipping_cost_cny, 2),
                "suggested_quantity": int(plan.get("suggested_quantity") or 0),
                "estimated_cost_cny": round(unit_shipping_cost_cny * max(float(plan.get("suggested_quantity") or 0), 0), 2),
                "formula": f"{unit_weight_kg:g}kg * {rate:g}元/kg",
                "total_cost_formula": f"{int(plan.get('suggested_quantity') or 0)}件 * {unit_shipping_cost_cny:.2f}元/件",
                "basis": plan.get("summary"),
            }
        )
    cost_comparison = _build_replenishment_cost_comparison(logistics_plan, estimates)
    return {
        **base,
        "ok": True,
        "reason": "使用 product info.weight_gram 按发货渠道粗估单件运费。",
        "weight": _json_safe(weight_info),
        "estimates": estimates,
        "cost_comparison": cost_comparison,
        "notes": [
            "该成本只按重量和渠道单价粗估，不含抛重、箱规、头程附加费、关税、仓储及平台费用。",
            "建议补货数量来自 SKU 全链路诊断的到货窗口覆盖测算；执行前仍需人工确认 MOQ、箱规、供应商和实际渠道价格。",
        ],
    }


def _shipping_rate_payload() -> dict[str, dict[str, Any]]:
    return {
        channel: {
            "label": SHIPPING_COST_CHANNEL_LABELS.get(channel, channel),
            "rate_cny_per_kg": rate,
        }
        for channel, rate in SHIPPING_COST_RATES_CNY_PER_KG.items()
    }


def _pick_fields(source: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: _json_safe(source.get(key)) for key in keys if key in source}


def _json_safe(value: Any, *, max_string: int = 2000, max_items: int = 80) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:max_string]
    if isinstance(value, dict):
        return {str(key)[:120]: _json_safe(item, max_string=max_string, max_items=max_items) for key, item in list(value.items())[:max_items]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item, max_string=max_string, max_items=max_items) for item in list(value)[:max_items]]
    return str(value)[:max_string]


def _choose_best_item(
    items: list[ControlTowerItem],
    material_code: str | None,
    store_name: str | None,
    country_code: str | None,
) -> ControlTowerItem:
    normalized_code = _norm(material_code)
    normalized_store = _norm(store_name)
    normalized_country = _norm(country_code)

    def score(item: ControlTowerItem) -> tuple[int, int, int, int]:
        identity_hit = int(normalized_code in {_norm(item.material_code), _norm(item.msku), _norm(item.fnsku), _norm(item.asin)})
        store_hit = int(not normalized_store or normalized_store == _norm(item.store_name))
        country_hit = int(not normalized_country or normalized_country in {_norm(item.country_code), _norm(item.shipments_country)})
        return (identity_hit, store_hit, country_hit, item.risk_score)

    return max(items, key=score)


def _inventory_section(item: ControlTowerItem) -> DiagnosisSection:
    findings = [
        f"总库存 {item.total_inventory:g}，其中 FBA可售 {item.fba_sellable:g}，海外仓 {item.overseas_inventory:g}，本地仓 {item.local_inventory:g}，在途/计划 {item.inbound_total:g}。",
    ]
    if item.sellable_days is None:
        findings.append("日均需求为 0 或缺失，FBA可售天数无法稳定计算。")
    else:
        findings.append(f"按当前日均需求 {item.daily_demand:g} 计算，FBA可售约 {item.sellable_days:g} 天。")
    if item.projected_7d < 0:
        findings.append(f"预计7天后 FBA 可售余额为 {item.projected_7d:g}，短期覆盖不足。")
    elif item.projected_7d == 0:
        findings.append("预计7天后 FBA 可售刚好打平，需要持续观察销量波动。")
    else:
        findings.append(f"预计7天后 FBA 可售余额为 {item.projected_7d:g}。")
    if item.long_age_inventory > 0:
        findings.append(f"FBA 61天以上库龄库存 {item.long_age_inventory:g}，长库龄占比 {_ratio_text(item.fba_long_age_ratio)}。")
    return DiagnosisSection(
        status="库存异常" if item.projected_7d < 0 or item.long_age_inventory > 0 else "库存正常",
        metrics={
            "total_inventory": item.total_inventory,
            "fba_sellable": item.fba_sellable,
            "fba_inventory": item.fba_inventory,
            "overseas_inventory": item.overseas_inventory,
            "local_inventory": item.local_inventory,
            "inbound_total": item.inbound_total,
            "sellable_days": item.sellable_days,
            "projected_7d": item.projected_7d,
            "long_age_inventory": item.long_age_inventory,
            "fba_long_age_ratio": item.fba_long_age_ratio,
        },
        findings=findings,
    )


def _sales_section(item: ControlTowerItem) -> DiagnosisSection:
    findings = [
        f"销售属性为 {item.sales_property or '未标记'}，区间销量 {item.daily_sales_volume:g}。",
        f"近/未来7天需求 {item.demand_7d:g}，未来/近30天需求 {item.demand_30d:g}，日均需求 {item.daily_demand:g}。",
    ]
    if item.daily_demand <= 0:
        findings.append("当前需求口径偏低或缺失，补救动作应先复核预测和近销。")
    elif item.sales_property in {"爆", "旺"} and item.projected_7d <= 0:
        findings.append("爆/旺款短期余额不充足，应优先保障 FBA 可售和补货时效。")
    elif item.sales_property == "滞":
        findings.append("滞销属性下需谨慎新增采购和发货，优先清理可售与库龄。")
    return DiagnosisSection(
        status="有销量/需求" if item.daily_demand > 0 or item.daily_sales_volume > 0 else "低销量或无需求",
        metrics={
            "sales_property": item.sales_property,
            "daily_sales_volume": item.daily_sales_volume,
            "demand_7d": item.demand_7d,
            "demand_30d": item.demand_30d,
            "daily_demand": item.daily_demand,
        },
        findings=findings,
    )


def _stockout_section(item: ControlTowerItem, active: bool) -> DiagnosisSection:
    shortage_days = _shortage_days(item)
    findings = []
    if active:
        first_day = item.pici_first_shortage_days
        first_text = "今天起" if first_day is not None and first_day <= 0 else f"第 {first_day} 天" if first_day is not None else "未知窗口"
        findings.append(f"命中{item.stockout_warning}，最早缺口出现在 {first_text}。")
        findings.append(f"chazhi 最大缺口 {item.pici_min_gap_quantity if item.pici_min_gap_quantity is not None else '-'}，关键缺口 {item.pici_key_gap or '-'}。")
        if shortage_days:
            findings.append(f"缺口窗口合计约 {shortage_days} 天。")
        if item.inbound_total > 0:
            findings.append(f"存在在途/计划 {item.inbound_total:g}，需要核查是否能赶在最早缺口日前转为 FBA 可售。")
    else:
        findings.append("当前未命中 chazhi 断货窗口。")
    if item.evidence.get("pici_gap_missing"):
        findings.append("批次 chazhi 数据缺失，断货判断可信度需人工复核。")
    return DiagnosisSection(
        status="存在断货风险" if active else "暂无断货风险",
        metrics={
            "risk_level": item.stockout_risk_level,
            "first_shortage_days": item.pici_first_shortage_days,
            "shortage_days": shortage_days,
            "min_gap_quantity": item.pici_min_gap_quantity,
            "key_gap": item.pici_key_gap,
            "gap_values": item.pici_gap_values,
        },
        findings=findings,
    )


def _overstock_section(item: ControlTowerItem, active: bool) -> DiagnosisSection:
    findings = []
    if active:
        findings.append(f"命中{item.overstock_warning}。")
        if item.evidence.get("overstock_reason"):
            findings.append(str(item.evidence["overstock_reason"]))
        if item.long_age_inventory > 0:
            findings.append(f"FBA 61天以上库龄库存 {item.long_age_inventory:g}，需进入清货/拦截视角。")
    else:
        findings.append("当前未命中 SOP 冗余阈值。")
    return DiagnosisSection(
        status="存在冗余风险" if active else "暂无冗余风险",
        metrics={
            "risk_level": item.overstock_risk_level,
            "redundancy_sellable_days": item.redundancy_sellable_days,
            "long_age_inventory": item.long_age_inventory,
            "fba_age_61_to_90": item.fba_age_61_to_90,
            "fba_age_91_to_180": item.fba_age_91_to_180,
            "fba_age_181_to_270": item.fba_age_181_to_270,
            "fba_age_271_to_330": item.fba_age_271_to_330,
            "fba_age_331_to_365": item.fba_age_331_to_365,
            "fba_age_365_plus": item.fba_age_365_plus,
        },
        findings=findings,
    )


def _build_attribution(item: ControlTowerItem, stockout: bool, overstock: bool, anomaly: bool) -> list[str]:
    reasons: list[str] = []
    if stockout:
        reasons.append(f"断货归因：chazhi 缺口窗口命中，{item.pici_key_gap or '关键缺口未返回'}，FBA可售 {item.fba_sellable:g} 对近7天需求 {item.demand_7d:g} 的覆盖不足。")
        if item.inbound_total > 0:
            reasons.append("在途归因：虽有在途/计划量，但需要确认到仓、上架、转 FBA 可售的时间是否早于最早断货日。")
    if overstock:
        reasons.append(f"冗余归因：{item.evidence.get('overstock_reason') or '可售天数或 FBA库龄命中 SOP 冗余阈值'}。")
    if stockout and overstock:
        reasons.append("并存归因：前端 FBA 可售短缺与后端/长库龄库存积压同时存在，重点不是简单总量不足，而是库存位置、库龄和补货节奏错配。")
    if anomaly:
        flags = "；".join(str(flag.get("reason") or flag.get("value") or flag) for flag in item.evidence.get("risk_flags", []))
        reasons.append(f"异常归因：底表风险标记命中：{flags}。")
    if not reasons:
        reasons.append("当前未识别到明确断货、冗余或底表异常，保持例行监控。")
    return reasons


def _handling_logic(item: ControlTowerItem, stockout: bool, overstock: bool, anomaly: bool) -> list[str]:
    logic = []
    if stockout:
        logic.append("先保供：核查最早缺口日、FBA 可售、在途到货和最快补货方式，优先让可售覆盖缺口窗口。")
    if overstock:
        logic.append("再控冗：冻结非必要采购和发货，复核长库龄、可售天数和清货节奏，避免继续把库存推向高库龄。")
    if stockout and overstock:
        logic.append("并存时按“调结构”处理：优先转移可转化库存、调整仓位/渠道，再判断是否需要新增采购。")
    if anomaly:
        logic.append("异常字段必须先复核来源表和口径，确认不是数据延迟、映射错位或历史风险标记未关闭。")
    if not logic:
        logic.append("当前风险可控，按日监控销量、预测和在途变化即可。")
    return logic


def _build_remedies(item: ControlTowerItem, stockout: bool, overstock: bool, anomaly: bool) -> list[dict[str, str]]:
    remedies: list[dict[str, str]] = []
    if stockout:
        remedies.extend(
            [
                {"owner": "PMC", "action": "确认 chazhi 最早缺口窗口和缺口数量，锁定需要补救的 FNSKU/店铺/国家。", "priority": "P0"},
                {"owner": "物流/仓库", "action": "核查在途与海外/本地库存是否能加急转 FBA，可覆盖则优先调拨或催上架。", "priority": "P0"},
                {"owner": "采购", "action": "若现有库存和在途无法覆盖缺口，复核 MOQ/箱规/交期后生成采购补救草稿。", "priority": "P1"},
            ]
        )
    if overstock:
        remedies.extend(
            [
                {"owner": "PMC", "action": "冻结非必要补货和未下单采购，避免冗余继续扩大。", "priority": "P0"},
                {"owner": "销售", "action": "结合库龄和可售天数制定控价、促销、清货或停售节奏。", "priority": "P1"},
                {"owner": "物流", "action": "暂停非必要发货计划，避免把后端冗余继续推入 FBA。", "priority": "P1"},
            ]
        )
    if anomaly:
        remedies.append({"owner": "数据/PMC", "action": "复核底表风险标记、SKU/FNSKU/MSKU 映射和销量预测口径，确认后再关闭异常。", "priority": "P1"})
    if not remedies:
        remedies.append({"owner": "PMC", "action": "保持日监控；若销量或预测突变，再重新触发全链路诊断。", "priority": "P2"})
    return _unique_remedies(remedies)


def _build_logistics_plan(item: ControlTowerItem, stockout: bool, overstock: bool) -> list[dict[str, Any]]:
    first_shortage_day = item.pici_first_shortage_days
    shortage_points = _shortage_points(item)
    min_gap_quantity = abs(item.pici_min_gap_quantity or 0)
    daily_demand = item.daily_demand or max(item.demand_7d / 7 if item.demand_7d else 0, item.daily_sales_volume or 0)
    plans: list[dict[str, Any]] = []

    if not stockout:
        plans.append(
            {
                "channel": "monitor",
                "window": "当前至下一次滚动复盘",
                "arrival_day": None,
                "suggested_quantity": 0,
                "summary": "当前未命中断货窗口，保持日监控，不建议新增快船或慢船补货。",
                "reason": "chazhi 未返回负缺口或断货风险为正常。",
            }
        )
        if overstock:
            plans.append(
                {
                    "channel": "sales_clearance",
                    "window": "当前至冗余解除",
                    "arrival_day": None,
                    "suggested_quantity": 0,
                    "summary": "存在冗余风险时暂停非必要发货和采购，优先销售清货。",
                    "reason": item.evidence.get("overstock_reason") or "命中冗余阈值。",
                }
            )
        return plans

    if first_shortage_day is not None and first_shortage_day < 45:
        control_qty = _quantity_for_window(daily_demand, max(45 - max(first_shortage_day, 0), 0), min_gap_quantity)
        plans.append(
            {
                "channel": "sales_control",
                "window": f"当前至第45天快船到货前，重点关注第{first_shortage_day}天起缺口",
                "arrival_day": None,
                "suggested_quantity": control_qty,
                "summary": f"第{first_shortage_day}天已出现缺口，海运到货前需要控销/限促/调拨，避免 FBA 可售提前断档。",
                "reason": f"最早断货日 {first_shortage_day} 小于快船45天提前期。",
            }
        )

    if first_shortage_day is not None and first_shortage_day < URGENT_AIR_ARRIVAL_DAY:
        plans.append(
            {
                "channel": "urgent_air",
                "window": f"当前至第{URGENT_AIR_ARRIVAL_DAY}天",
                "arrival_day": URGENT_AIR_ARRIVAL_DAY,
                "suggested_quantity": _quantity_for_window(daily_demand, URGENT_AIR_ARRIVAL_DAY, min_gap_quantity),
                "summary": "若业务必须不断货，需评估加急空运或海外/本地紧急调拨覆盖10天内缺口。",
                "reason": "最早缺口早于加急空运10天节点，普通空运和海运都无法覆盖。",
            }
        )

    standard_air_gap = _max_gap_between(shortage_points, STANDARD_AIR_ARRIVAL_DAY, FAST_SHIP_ARRIVAL_DAY)
    if first_shortage_day is not None and first_shortage_day <= FAST_SHIP_ARRIVAL_DAY:
        plans.append(
            {
                "channel": "standard_air",
                "window": f"第{STANDARD_AIR_ARRIVAL_DAY}天至第{FAST_SHIP_ARRIVAL_DAY}天",
                "arrival_day": STANDARD_AIR_ARRIVAL_DAY,
                "suggested_quantity": _quantity_for_window(
                    daily_demand,
                    FAST_SHIP_ARRIVAL_DAY - STANDARD_AIR_ARRIVAL_DAY,
                    standard_air_gap or min_gap_quantity,
                ),
                "summary": f"普通空运用于补第{STANDARD_AIR_ARRIVAL_DAY}-{FAST_SHIP_ARRIVAL_DAY}天的短期缺口，成本低于加急空运。",
                "reason": f"普通空运{STANDARD_AIR_ARRIVAL_DAY}天到货，可覆盖快船{FAST_SHIP_ARRIVAL_DAY}天前的缺口窗口。",
            }
        )

    fast_gap = _max_gap_between(shortage_points, FAST_SHIP_ARRIVAL_DAY, SLOW_SHIP_ARRIVAL_DAY)
    if first_shortage_day is not None and first_shortage_day <= SLOW_SHIP_ARRIVAL_DAY:
        plans.append(
            {
                "channel": "fast_ship",
                "window": f"第{FAST_SHIP_ARRIVAL_DAY}天至第{SLOW_SHIP_ARRIVAL_DAY}天",
                "arrival_day": FAST_SHIP_ARRIVAL_DAY,
                "suggested_quantity": _quantity_for_window(
                    daily_demand,
                    SLOW_SHIP_ARRIVAL_DAY - FAST_SHIP_ARRIVAL_DAY,
                    fast_gap or min_gap_quantity,
                ),
                "summary": f"快船用于补第{FAST_SHIP_ARRIVAL_DAY}-{SLOW_SHIP_ARRIVAL_DAY}天的中短期缺口，并衔接慢船到货前的需求。",
                "reason": f"快船{FAST_SHIP_ARRIVAL_DAY}天到货，能覆盖慢船{SLOW_SHIP_ARRIVAL_DAY}天前后的缺口窗口。",
            }
        )

    long_gap = _max_gap_between(shortage_points, SLOW_SHIP_ARRIVAL_DAY, 98)
    if long_gap or item.demand_30d > 0:
        plans.append(
            {
                "channel": "slow_ship",
                "window": f"第{SLOW_SHIP_ARRIVAL_DAY}天以后",
                "arrival_day": SLOW_SHIP_ARRIVAL_DAY,
                "suggested_quantity": _quantity_for_window(daily_demand, max(98 - SLOW_SHIP_ARRIVAL_DAY, 0), long_gap),
                "summary": f"慢船用于补第{SLOW_SHIP_ARRIVAL_DAY}天后的持续需求，不建议用来解决45天内的断货。",
                "reason": f"慢船{SLOW_SHIP_ARRIVAL_DAY}天到货，只适合覆盖中长期需求和慢变量补仓。",
            }
        )

    if overstock:
        plans.append(
            {
                "channel": "overstock_guardrail",
                "window": "所有补货决策前",
                "arrival_day": None,
                "suggested_quantity": 0,
                "summary": "命中冗余时，快船/慢船数量必须先扣减可转化库存和长库龄清货目标，避免一边断货一边继续制造冗余。",
                "reason": item.evidence.get("overstock_reason") or "命中冗余阈值。",
            }
        )

    return plans


def _build_replenishment_countdowns(item: ControlTowerItem, source: dict[str, Any]) -> list[dict[str, Any]]:
    rules = _replenishment_rule_values(item, source)
    definitions = [
        (1, "催FBA在途", "sellable_1", ["fba_safety_days", "fba_delivery_days"], "可售天数1-FBA安全天数-FBA交付天数"),
        (2, "发FBA", "sellable_2", ["fba_safety_days", "fba_delivery_days"], "可售天数2-FBA安全天数-FBA交付天数"),
        (3, "催海外仓在途", "sellable_3", ["fba_safety_days", "overseas_safety_days", "overseas_delivery_days", "fba_delivery_days"], "可售天数3-FBA安全天数-海外仓安全天数-海外仓交付天数-FBA交付天数"),
        (4, "发海外仓", "sellable_4", ["fba_safety_days", "overseas_safety_days", "overseas_delivery_days", "fba_delivery_days"], "可售天数4-FBA安全天数-海外仓安全天数-海外仓交付天数-FBA交付天数"),
        (5, "催本地仓在途", "sellable_5", ["fba_safety_days", "overseas_safety_days", "local_safety_days", "local_delivery_days", "overseas_delivery_days", "fba_delivery_days"], "可售天数5-FBA安全天数-海外仓安全天数-本地仓安全库存天数-本地仓交付天数-海外仓交付天数-FBA交付天数"),
        (6, "下采购单", "sellable_6", ["fba_safety_days", "overseas_safety_days", "local_safety_days", "local_delivery_days", "overseas_delivery_days", "fba_delivery_days"], "可售天数6-FBA安全天数-海外仓安全天数-本地仓安全库存天数-本地仓交付天数-海外仓交付天数-FBA交付天数"),
    ]
    rows: list[dict[str, Any]] = []
    for index, action, available_key, component_keys, formula in definitions:
        available_days = item.redundancy_sellable_days.get(available_key)
        if available_days is None and available_key == "sellable_1":
            available_days = item.sellable_days
        components = {key: rules[key]["value"] for key in component_keys}
        subtract_days = sum(float(value or 0) for value in components.values())
        countdown = None if available_days is None else round(float(available_days) - subtract_days, 1)
        rows.append(
            {
                "index": index,
                "name": f"补货倒计时{index}",
                "action": action,
                "available_days_key": available_key,
                "available_days": available_days,
                "components": components,
                "component_sources": {key: rules[key]["source"] for key in component_keys},
                "formula": formula,
                "countdown_days": countdown,
                "status": "缺少可售天数，需补数据" if countdown is None else "已到动作点" if countdown <= 0 else f"{countdown:g}天后触发",
                "should_act": bool(countdown is not None and countdown <= 0),
            }
        )
    return rows


def _replenishment_rule_values(item: ControlTowerItem, source: dict[str, Any]) -> dict[str, dict[str, Any]]:
    order_duration = _first_number(source, ["order_duration", "采购交付时长", "采购下单时长"]) or 0
    production_duration = _first_number(source, ["production_duration", "生产时长"]) or 0
    fallback_local_delivery = item.lead_time_days or order_duration + production_duration or DEFAULT_REPLENISHMENT_RULES["local_delivery_days"]
    aliases = {
        "fba_safety_days": ["fba_safety_days_fn", "FBA安全天数_fnsku", "FBA安全天数", "safety_stock_days_sales"],
        "overseas_safety_days": ["overseas_warehouse_safety_days", "海外仓安全天数_fnsku", "海外仓安全天数"],
        "local_safety_days": ["local_warehouse_safety_days", "本地仓安全天数_fnsku", "本地仓安全库存天数"],
        "fba_delivery_days": ["FBA_delivery_time_fn", "fba_delivery_time_fn", "overseas_to_FBA_time", "local_to_FBA_time", "FBA交付时长_fnsku"],
        "overseas_delivery_days": ["overseas_warehouse_delivery_time_fn", "local_to_overseas_warehouse_time", "海外仓交付时长_fnsku"],
        "local_delivery_days": ["local_warehouse_delivery_time_fn", "本地仓交付时长_fnsku"],
        "purchase_frequency_days": ["restocking_frequency", "补货频率", "purchase_frequency_days"],
        "oversell_rate": ["oversell_rate", "可超卖比例"],
    }
    values: dict[str, dict[str, Any]] = {}
    for key, names in aliases.items():
        found = _first_number(source, names)
        default = fallback_local_delivery if key == "local_delivery_days" else DEFAULT_REPLENISHMENT_RULES[key]
        values[key] = {
            "value": round(found if found is not None else default, 3),
            "source": "field" if found is not None else "default",
        }
    return values


def _first_number(source: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key in source:
            value = _number(source.get(key))
            if value is not None:
                return value
        evidence = source.get("evidence")
        if isinstance(evidence, dict) and key in evidence:
            value = _number(evidence.get(key))
            if value is not None:
                return value
    return None


def _build_replenishment_recommendation(
    item: ControlTowerItem,
    stockout: bool,
    overstock: bool,
    logistics_plan: list[dict[str, Any]],
    countdowns: list[dict[str, Any]],
) -> dict[str, Any]:
    channel_plans = [plan for plan in logistics_plan if plan.get("channel") in SHIPPING_COST_RATES_CNY_PER_KG]
    methods = [
        {
            "channel": plan.get("channel"),
            "channel_label": SHIPPING_COST_CHANNEL_LABELS.get(str(plan.get("channel")), str(plan.get("channel"))),
            "arrival_day": plan.get("arrival_day"),
            "window": plan.get("window"),
            "suggested_quantity": int(plan.get("suggested_quantity") or 0),
            "basis": plan.get("reason") or plan.get("summary"),
        }
        for plan in channel_plans
        if int(plan.get("suggested_quantity") or 0) > 0
    ]
    total_quantity = sum(item["suggested_quantity"] for item in methods)
    first_shortage = item.pici_first_shortage_days
    sales_control_plan = next((plan for plan in logistics_plan if plan.get("channel") == "sales_control"), None)
    if not stockout:
        sales_control = "控销方面：当前未命中断货窗口，无需控销；保持销量、广告和价格曲线监控。"
    elif sales_control_plan:
        sales_control = f"控销方面：预计第{first_shortage}天起有断货风险，快船到货前需要控销/限促/广告降档；若不控销，{sales_control_plan.get('summary')}"
    else:
        sales_control = f"控销方面：当前可覆盖主要短期窗口，{FAST_SHIP_ARRIVAL_DAY}天前无需硬控销，但要监控销量突增。"

    purchase_countdown = next((row for row in countdowns if row.get("index") == 6), {})
    needs_purchase = bool(purchase_countdown.get("should_act") or (stockout and total_quantity > 0))
    purchase_quantity = _purchase_suggested_quantity(item, methods, needs_purchase)
    purchase = {
        "needs_purchase": needs_purchase,
        "suggested_purchase_quantity": purchase_quantity,
        "summary": (
            f"采购逻辑：补货倒计时6={purchase_countdown.get('countdown_days')}，已到下采购单判断点；建议采购草稿量 {purchase_quantity}，需复核 MOQ/箱规/供应商/交期。"
            if needs_purchase
            else f"采购逻辑：补货倒计时6={purchase_countdown.get('countdown_days')}，暂不直接新增采购，先消化在途和可转化库存。"
        ),
        "formula": "建议采购草稿量 = max(渠道窗口建议量合计, 未来30天需求 - FBA可售 - 在途, 0)，最终受 MOQ/箱规/可拼采购约束。",
        "draft_only": True,
    }
    if overstock:
        purchase["guardrail"] = "命中冗余时，采购草稿量必须先扣减可转化库存和清货目标，禁止自动下单。"

    return {
        "summary": _replenishment_summary(stockout, methods, total_quantity),
        "sales_control": sales_control,
        "methods": methods,
        "total_replenishment_quantity": total_quantity,
        "purchase": purchase,
        "draft_only": True,
        "human_confirmation_required": True,
    }


def _purchase_suggested_quantity(item: ControlTowerItem, methods: list[dict[str, Any]], needs_purchase: bool) -> int:
    if not needs_purchase:
        return 0
    channel_quantity = sum(int(method.get("suggested_quantity") or 0) for method in methods)
    demand_gap = max(float(item.demand_30d or 0) - float(item.fba_sellable or 0) - float(item.inbound_total or 0), 0)
    return int(round(max(channel_quantity, demand_gap)))


def _replenishment_summary(stockout: bool, methods: list[dict[str, Any]], total_quantity: int) -> str:
    if not stockout:
        return "补货方面：当前不建议新增补货，重点观察销量、价格、广告和库存消化。"
    if not methods:
        return "补货方面：已命中断货风险，但缺少可执行补货窗口，需人工补充到货时效或 chazhi 明细。"
    parts = [f"{method['channel_label']} {method['suggested_quantity']}件" for method in methods]
    return f"补货方面：建议按窗口组合补货，{'，'.join(parts)}，合计 {total_quantity}件；执行前需人工确认渠道、MOQ 和成本。"


def _build_replenishment_cost_comparison(logistics_plan: list[dict[str, Any]], estimates: list[dict[str, Any]] | None) -> dict[str, Any]:
    plan_by_channel = {str(plan.get("channel")): plan for plan in logistics_plan}
    estimate_by_channel = {str(item.get("channel")): item for item in estimates or []}
    rows = []
    for channel in ("urgent_air", "standard_air", "fast_ship", "slow_ship"):
        plan = plan_by_channel.get(channel, {})
        estimate = estimate_by_channel.get(channel, {})
        suggested_quantity = int(estimate.get("suggested_quantity") or plan.get("suggested_quantity") or 0)
        rows.append(
            {
                "channel": channel,
                "channel_label": SHIPPING_COST_CHANNEL_LABELS.get(channel, channel),
                "arrival_day": estimate.get("arrival_day", plan.get("arrival_day")),
                "window": estimate.get("window", plan.get("window")),
                "suggested_quantity": suggested_quantity,
                "unit_shipping_cost_cny": estimate.get("unit_shipping_cost_cny"),
                "estimated_cost_cny": estimate.get("estimated_cost_cny"),
                "basis": estimate.get("basis") or plan.get("summary"),
            }
        )
    priced = [row for row in rows if row["suggested_quantity"] > 0 and row.get("estimated_cost_cny") is not None]
    lowest_total = min(priced, key=lambda row: float(row["estimated_cost_cny"])) if priced else None
    lowest_unit = min((row for row in rows if row.get("unit_shipping_cost_cny") is not None), key=lambda row: float(row["unit_shipping_cost_cny"])) if any(row.get("unit_shipping_cost_cny") is not None for row in rows) else None
    return {
        "ok": bool(priced),
        "currency": "CNY",
        "rows": rows,
        "lowest_total_cost_channel": lowest_total,
        "lowest_unit_cost_channel": lowest_unit,
        "recommendation": _cost_recommendation_text(rows, lowest_total),
        "formula": "estimated_cost_cny = suggested_quantity * unit_shipping_cost_cny",
        "draft_only": True,
    }


def _merge_shipping_cost_comparison(estimate: Any, fallback_comparison: Any) -> dict[str, Any]:
    if not isinstance(estimate, dict):
        return {"cost_comparison": fallback_comparison}
    if not estimate.get("cost_comparison") and fallback_comparison:
        estimate = {**estimate, "cost_comparison": fallback_comparison}
    return estimate


def _cost_recommendation_text(rows: list[dict[str, Any]], lowest_total: dict[str, Any] | None) -> str:
    active = [row for row in rows if row["suggested_quantity"] > 0]
    if not active:
        return "暂无建议补货数量，无法比较总成本。"
    if lowest_total:
        return f"按当前建议量粗估，{lowest_total['channel_label']}总成本最低；但是否采用仍取决于断货窗口和到货时效。"
    return "缺少 product info.weight_gram 或渠道单价，当前只能比较建议数量，不能比较总成本。"


def _build_root_cause_analysis(
    item: ControlTowerItem,
    stockout: bool,
    overstock: bool,
    anomaly: bool,
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    causes = _rule_based_risk_causes(item, stockout=stockout, overstock=overstock, source=source)
    if causes:
        return causes
    if anomaly and not (stockout or overstock):
        flags = "；".join(str(flag.get("reason") or flag.get("value") or flag) for flag in item.evidence.get("risk_flags", []))
        return [
            {
                "cause": "数据或历史异常标记",
                "type": "data_quality",
                "evidence": flags,
                "recommendation": "复核源表、SKU/FNSKU/MSKU 映射和异常关闭状态。",
                "confidence": 0.58,
            }
        ]
    return []


def _rule_based_risk_causes(
    item: ControlTowerItem,
    *,
    stockout: bool,
    overstock: bool,
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    if not stockout and not overstock:
        return []
    causes: list[dict[str, Any]] = []
    delay_causes = _supply_delay_causes(item, source)
    forecast_change_cause = _forecast_change_cause(source)

    if stockout:
        oversell_cause = _sales_gap_root_cause(item, source, direction="oversell")
        if oversell_cause:
            causes.append(oversell_cause)
        causes.extend(delay_causes)
        if forecast_change_cause:
            causes.append(forecast_change_cause)
        if not causes:
            causes.append(_plan_root_cause(item, risk_type="stockout"))

    if overstock:
        low_sell_cause = _sales_gap_root_cause(item, source, direction="low_sell")
        if low_sell_cause:
            causes.append(low_sell_cause)
        else:
            supply_cause = _overstock_supply_root_cause(source)
            if supply_cause:
                causes.append(supply_cause)
        causes.extend(delay_causes)
        if forecast_change_cause:
            causes.append(forecast_change_cause)
        if not causes:
            causes.append(_plan_root_cause(item, risk_type="overstock"))

    return _dedupe_root_causes(causes)


def _sales_gap_root_cause(item: ControlTowerItem, source: dict[str, Any], *, direction: str) -> dict[str, Any] | None:
    threshold = _sales_gap_threshold_percent(item)
    if threshold is None:
        return None
    signals = _recent_sales_gap_signals(source, direction=direction, threshold_percent=threshold)
    if not signals:
        return None
    if direction == "oversell":
        return {
            "cause": "超卖导致断货",
            "type": "oversell",
            "evidence": _sales_gap_evidence_text(item, signals, threshold, direction="oversell"),
            "recommendation": "",
            "confidence": 0.82,
        }
    return {
        "cause": "低卖导致冗余",
        "type": "low_sell",
        "evidence": _sales_gap_evidence_text(item, signals, threshold, direction="low_sell"),
        "recommendation": "",
        "confidence": 0.8,
    }


def _sales_gap_threshold_percent(item: ControlTowerItem) -> float | None:
    property_text = str(item.sales_property or "").strip()
    if property_text in {"爆", "旺"}:
        return 20.0
    if property_text in {"平", "滞"}:
        return 10.0
    return None


def _sales_gap_evidence_text(
    item: ControlTowerItem,
    signals: list[str],
    threshold_percent: float,
    *,
    direction: str,
) -> str:
    property_text = str(item.sales_property or "").strip() or "未填写"
    hit_label = "超卖" if direction == "oversell" else "低卖"
    conclusion = (
        "销量超过原预估，库存被提前消耗，所以判定为超卖导致断货"
        if direction == "oversell"
        else "销量低于原预估，库存消化不掉，所以判定为低卖导致冗余"
    )
    shown = signals[:2]
    more_count = max(len(signals) - len(shown), 0)
    more_text = f"；另有 {more_count} 个区间也命中" if more_count else ""
    detail_text = "；".join(shown)
    return (
        f"基准：按2个月前预测值对比；当前销售属性 {property_text}，判断阈值 {threshold_percent:g}%。\n"
        f"命中：{len(signals)} 个{hit_label}区间，{detail_text}{more_text}。\n"
        f"结论：{conclusion}。"
    )


def _recent_sales_gap_signals(source: dict[str, Any], *, direction: str, threshold_percent: float) -> list[str]:
    signals: list[str] = []
    monthly_rows = _recent_monthly_rows(source, ROOT_CAUSE_LOOKBACK_COUNT)
    for row in monthly_rows:
        forecast = _two_month_forecast_from_monthly_row(row)
        actual = _actual_reference_from_monthly_row(row)
        if forecast is None or actual is None:
            continue
        gap = actual - forecast
        variance = _variance_percent(actual, forecast)
        if _sales_gap_direction_matches(direction, variance, threshold_percent):
            signals.append(_format_monthly_gap_signal(row, forecast, actual, gap, variance))

    for row, forecast in _recent_two_month_weekly_pairs(source, ROOT_CAUSE_LOOKBACK_COUNT):
        actual = _number(row.get("actual_sales"))
        if forecast is None or actual is None:
            continue
        gap = actual - forecast
        variance = _variance_percent(actual, forecast)
        if _sales_gap_direction_matches(direction, variance, threshold_percent):
            signals.append(_format_weekly_gap_signal(row, forecast, actual, gap, variance))
    return signals


def _sales_gap_direction_matches(direction: str, variance_percent: float | None, threshold_percent: float) -> bool:
    if variance_percent is None:
        return False
    if direction == "oversell":
        return variance_percent > threshold_percent
    if direction == "low_sell":
        return variance_percent < -threshold_percent
    return False


def _variance_percent(actual: float, forecast: float) -> float | None:
    if forecast <= 0:
        return None
    return round((actual - forecast) / forecast * 100, 2)


def _two_month_forecast_from_monthly_row(row: dict[str, Any]) -> float | None:
    versions = row.get("forecast_version_totals")
    if isinstance(versions, list):
        for version in versions:
            if not isinstance(version, dict):
                continue
            if _number(version.get("forecast_month_offset")) == 2:
                return _number(version.get("forecast_quantity"))
    if _number(row.get("forecast_month_offset")) == 2:
        return _number(row.get("forecast_quantity"))
    label = str(row.get("forecast_label") or "")
    if "2个月之前" in label:
        return _number(row.get("forecast_quantity"))
    return None


def _recent_two_month_weekly_pairs(source: dict[str, Any], count: int) -> list[tuple[dict[str, Any], float | None]]:
    review = _review_from_source(source)
    if not isinstance(review, dict):
        return []
    actual_rows = _recent_weekly_rows(source, count)
    version_rows = _two_month_forecast_weekly_rows(review)
    forecast_by_key: dict[str, float] = {}
    for row in version_rows:
        key = _weekly_compare_key(row)
        if not key:
            continue
        forecast = _number(row.get("forecast_quantity"))
        if forecast is not None:
            forecast_by_key[key] = forecast
    pairs = []
    fallback_to_weekly = _number(review.get("month_offset")) == 2
    for row in actual_rows:
        forecast = forecast_by_key.get(_weekly_compare_key(row))
        if forecast is None and fallback_to_weekly:
            forecast = _number(row.get("forecast_quantity"))
        pairs.append((row, forecast))
    return pairs


def _two_month_forecast_weekly_rows(review: dict[str, Any]) -> list[dict[str, Any]]:
    versions = review.get("forecast_versions")
    if not isinstance(versions, list):
        versions = review.get("detail_forecast_versions") if isinstance(review.get("detail_forecast_versions"), list) else []
    for version in versions:
        if not isinstance(version, dict):
            continue
        if _number(version.get("month_offset")) != 2:
            continue
        rows = version.get("weekly_estimates")
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    return []


def _weekly_compare_key(row: dict[str, Any]) -> str:
    start = str(row.get("week_start_date") or "").strip()
    end = str(row.get("week_end_date") or "").strip()
    if start or end:
        return f"{start}|{end}"
    return str(row.get("week") or "").strip()


def _format_monthly_gap_signal(row: dict[str, Any], forecast: float, actual: float, gap: float, variance: float | None) -> str:
    month = str(row.get("month") or "月份")
    variance_text = _format_variance_with_sign(variance)
    return f"{month}：原预估 {forecast:g}，实际/折算 {actual:g}，{_format_gap_delta(gap)}{variance_text}"


def _format_weekly_gap_signal(row: dict[str, Any], forecast: float, actual: float, gap: float, variance: float | None) -> str:
    label = _date_range_label(row.get("week_start_date"), row.get("week_end_date")) or str(row.get("week") or "周度")
    variance_text = _format_variance_with_sign(variance)
    return f"{label}：原预估 {forecast:g}，实际 {actual:g}，{_format_gap_delta(gap)}{variance_text}"


def _format_gap_delta(gap: float) -> str:
    direction = "多" if gap >= 0 else "少"
    return f"{direction} {abs(gap):g}"


def _format_variance_with_sign(variance: float | None) -> str:
    if variance is None:
        return ""
    sign = "+" if variance > 0 else ""
    return f"（{sign}{variance:g}%）"


def _forecast_change_cause(source: dict[str, Any]) -> dict[str, Any] | None:
    reasons = _forecast_change_reasons(source)
    if not reasons:
        return None
    return {
        "cause": "销量预测异常",
        "type": "forecast",
        "evidence": "；".join(reasons[:4]),
        "recommendation": "",
        "confidence": 0.78,
    }


def _forecast_change_reasons(source: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    review = _review_from_source(source)
    if isinstance(review, dict):
        for item in review.get("forecast_anomalies") or []:
            if not isinstance(item, dict):
                continue
            item_reasons = item.get("anomaly_reasons") or item.get("reasons") or []
            if isinstance(item_reasons, list):
                reasons.extend(str(reason) for reason in item_reasons if reason)
            elif item.get("reason"):
                reasons.append(str(item["reason"]))
        for row in review.get("detail_monthly_totals") or []:
            if not isinstance(row, dict) or not row.get("forecast_anomaly"):
                continue
            row_reasons = row.get("forecast_anomaly_reasons") or []
            if isinstance(row_reasons, list):
                reasons.extend(str(reason) for reason in row_reasons if reason)
            for check in row.get("forecast_variance_checks") or []:
                if not isinstance(check, dict) or not check.get("is_anomaly"):
                    continue
                label = check.get("label") or "预估版本差异"
                variance = _number(check.get("variance_percent"))
                if variance is not None and abs(variance) >= MONTHLY_FORECAST_CHANGE_ANOMALY_PERCENT:
                    reasons.append(f"{label} 差异率 {variance:g}%，达到{MONTHLY_FORECAST_CHANGE_ANOMALY_PERCENT}%阈值")
    return list(dict.fromkeys(reasons))


def _overstock_supply_root_cause(source: dict[str, Any]) -> dict[str, Any] | None:
    signals = []
    for row in _recent_monthly_rows(source, ROOT_CAUSE_LOOKBACK_COUNT):
        forecast = _two_month_forecast_from_monthly_row(row)
        actual = _actual_reference_from_monthly_row(row)
        if forecast is None or actual is None:
            continue
        if actual >= forecast:
            signals.append(_format_monthly_gap_signal(row, forecast, actual, actual - forecast, _variance_percent(actual, forecast)))
    if not signals:
        return None
    return {
        "cause": "供应异常导致冗余",
        "type": "supply_anomaly",
        "evidence": f"销售未低于预估但仍出现冗余：{'；'.join(signals[:3])}。",
        "recommendation": "",
        "confidence": 0.7,
    }


def _plan_root_cause(item: ControlTowerItem, *, risk_type: str) -> dict[str, Any]:
    if risk_type == "stockout":
        return {
            "cause": "计划原因导致断货",
            "type": "planning_anomaly",
            "evidence": "未命中近3个月/近3周超卖、供应延期或销量预测异常，按规则归因为计划原因。",
            "recommendation": "",
            "confidence": 0.66,
        }
    return {
        "cause": "计划原因导致冗余",
        "type": "planning_anomaly",
        "evidence": "未命中低卖、供应异常或销量预测异常，按规则归因为计划原因。",
        "recommendation": "",
        "confidence": 0.66,
    }


def _dedupe_root_causes(causes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for cause in causes:
        key = (str(cause.get("type") or ""), str(cause.get("evidence") or cause.get("cause") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(cause)
    return result


def _monthly_risk_causes(source: dict[str, Any], *, stockout: bool, overstock: bool) -> list[dict[str, Any]]:
    monthly_totals = _monthly_totals_from_source(source)
    if not monthly_totals:
        return []
    latest_month = max((str(row.get("month") or "") for row in monthly_totals), default="")
    causes: list[dict[str, Any]] = []
    latest_rows = [row for row in monthly_totals if str(row.get("month") or "") == latest_month]
    for row in latest_rows[-1:]:
        variance = _number(row.get("selected_variance_percent"))
        if variance is None:
            continue
        month = str(row.get("month") or "")
        forecast_quantity = _number(row.get("forecast_quantity")) or 0
        actual_reference = _number(row.get("actual_sales_projected")) or _number(row.get("actual_sales")) or 0
        month_label = _month_issue_label(row, latest_month)
        evidence_month = month or "本月"
        evidence = (
            f"{evidence_month} 图表同口径预估 {forecast_quantity:g}，实际/折算销量 {actual_reference:g}，"
            f"实际较预估 {variance:g}%。"
        )
        if stockout:
            if variance > 10:
                causes.append(
                    {
                        "cause": f"{month_label}超卖",
                        "type": "oversell",
                        "evidence": evidence + " 销售预估低于实际销量超过10%，且当前命中断货。",
                        "recommendation": "按实际销量修正销售预测和控销节奏，复核后续补货是否覆盖超卖缺口。",
                        "confidence": 0.78,
                    }
                )
            elif variance < -10:
                causes.append(
                    {
                        "cause": f"{month_label}供应异常",
                        "type": "supply_anomaly",
                        "evidence": evidence + " 销售预估高于实际销量超过10%，但仍发生断货，更偏向供应侧未按计划转化。",
                        "recommendation": "追查在途、签收、提货、上架和采购交付节点，确认是否物流或采购延期。",
                        "confidence": 0.74,
                    }
                )
            else:
                causes.append(
                    {
                        "cause": f"{month_label}计划异常",
                        "type": "planning_anomaly",
                        "evidence": evidence + " 实际与预估偏差未超过10%，但当前命中断货。",
                        "recommendation": "复核计划安全库存、补货触发点、发货节奏和仓位转化口径。",
                        "confidence": 0.68,
                    }
                )
        if overstock:
            if abs(variance) <= 10:
                causes.append(
                    {
                        "cause": f"{month_label}计划异常",
                        "type": "planning_anomaly",
                        "evidence": evidence + " 实际与预估偏差未超过10%，但当前命中冗余。",
                        "recommendation": "复核计划安全库存、补货触发点、发货节奏和仓位转化口径。",
                        "confidence": 0.68,
                    }
                )
            elif variance < -10:
                causes.append(
                    {
                        "cause": f"{month_label}低卖",
                        "type": "low_sell",
                        "evidence": evidence + " 销售预估高于实际销量，且当前命中冗余。",
                        "recommendation": "复核价格、广告、转化和清货计划，降低后续预测或暂停新增补货。",
                        "confidence": 0.76,
                    }
                )
    return causes[:8]


def _monthly_totals_from_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    review = _review_from_source(source)
    if not isinstance(review, dict):
        return []
    rows = review.get("detail_monthly_totals")
    if not isinstance(rows, list):
        return []
    comparable = [
        row
        for row in rows
        if isinstance(row, dict)
        and (_number(row.get("actual_covered_days")) or 0) > 0
        and _actual_reference_from_monthly_row(row) is not None
        and _two_month_forecast_from_monthly_row(row) is not None
    ]
    return comparable[-6:]


def _review_from_source(source: dict[str, Any]) -> dict[str, Any] | None:
    review = source.get("monthly_forecast_review") if isinstance(source.get("monthly_forecast_review"), dict) else None
    if review is None:
        review = source.get("forecast_review") if isinstance(source.get("forecast_review"), dict) else None
    if review is None:
        weekly = source.get("weekly_sales_and_price") if isinstance(source.get("weekly_sales_and_price"), dict) else {}
        review = weekly if weekly else None
    return review if isinstance(review, dict) else None


def _recent_monthly_rows(source: dict[str, Any], count: int) -> list[dict[str, Any]]:
    rows = _monthly_totals_from_source(source)
    return rows[-count:]


def _recent_weekly_rows(source: dict[str, Any], count: int) -> list[dict[str, Any]]:
    review = _review_from_source(source)
    if not isinstance(review, dict):
        return []
    rows = review.get("weekly_estimates")
    if not isinstance(rows, list):
        return []
    comparable = [
        row
        for row in rows
        if isinstance(row, dict)
        and _number(row.get("forecast_quantity")) is not None
        and _number(row.get("actual_sales")) is not None
    ]
    return comparable[-count:]


def _actual_reference_from_monthly_row(row: dict[str, Any]) -> float | None:
    projected = _number(row.get("actual_sales_projected"))
    if projected is not None:
        return projected
    return _number(row.get("actual_sales"))


def _date_range_label(start: Any, end: Any) -> str:
    start_text = str(start or "").strip()
    end_text = str(end or "").strip()
    if start_text and end_text and start_text != end_text:
        return f"{start_text}到{end_text}"
    return start_text or end_text


def _month_issue_label(row: dict[str, Any], latest_month: str) -> str:
    month = str(row.get("month") or "")
    covered_days = int(_number(row.get("actual_covered_days")) or 0)
    month_days = int(_number(row.get("month_day_count")) or 0)
    if month and month == latest_month and month_days and covered_days < month_days:
        return "本月可能"
    return f"{month} " if month else ""


def _supply_delay_causes(item: ControlTowerItem, source: dict[str, Any]) -> list[dict[str, Any]]:
    causes: list[dict[str, Any]] = []
    stockout_windows = _stockout_date_windows(item, source)
    for row in _shipment_rows_from_source(source):
        label = _shipment_label(row)
        plan_sign_date = _row_date(row, ("plan_delivery_time", "planned_delivery_time", "计划签收时间"))
        estimated_sign_date = _row_date(
            row,
            (
                "estimated_delivery_time",
                "estimated_arrival_time",
                "estimated_sign_time",
                "estimated_signed_time",
                "预计签收时间",
                "预计到达时间",
            ),
        )
        stockout_window = _stockout_window_for_date(plan_sign_date, stockout_windows)
        row_has_logistics_delay = False
        if (
            plan_sign_date
            and estimated_sign_date
            and stockout_window
            and _is_current_pending_logistics_delay(row, estimated_sign_date)
        ):
            delay_days = (estimated_sign_date - plan_sign_date).days
            if delay_days >= LOGISTICS_RECEIPT_DELAY_MARK_DAYS:
                note_text = _shipment_delay_note_text(row)
                causes.append(
                    {
                        "cause": "物流延期",
                        "type": "logistics_delay",
                        "evidence": (
                            f"{label}计划签收 {plan_sign_date.isoformat()} 落在断货窗口"
                            f"{_format_stockout_window(stockout_window)}，预计签收 {estimated_sign_date.isoformat()}，"
                            f"延期 {delay_days} 天，达到{LOGISTICS_RECEIPT_DELAY_MARK_DAYS}天阈值{note_text}。"
                        ),
                        "recommendation": "",
                        "confidence": 0.82,
                    }
                )
                row_has_logistics_delay = True
        logistics_exception = _shipment_logistics_exception_cause(
            row,
            label=label,
            plan_sign_date=plan_sign_date,
            estimated_sign_date=estimated_sign_date,
        )
        if logistics_exception and not row_has_logistics_delay:
            causes.append(logistics_exception)
        pickup_date = _row_date(row, ("logistics_pickup_time", "actual_pickup_time", "物流商实际提货时间"))
        plan_ship_date = _row_date(
            row,
            (
                "plan_shipment_time",
                "planned_shipment_time",
                "计划发货时间",
                "estimated_departure_time",
                "shipment_time",
                "supplier_ready_time",
            ),
        )
        if (
            pickup_date
            and plan_ship_date
            and stockout_window
            and estimated_sign_date
            and _is_current_pending_logistics_delay(row, estimated_sign_date)
        ):
            delay_days = (pickup_date - plan_ship_date).days
            if delay_days >= PROCUREMENT_PICKUP_DELAY_MARK_DAYS:
                note_text = _shipment_delay_note_text(row)
                causes.append(
                    {
                        "cause": "采购延期",
                        "type": "procurement_delay",
                        "evidence": (
                            f"{label}物流商实际提货 {pickup_date.isoformat()}，计划发货 {plan_ship_date.isoformat()}，"
                            f"延期 {delay_days} 天，且计划签收落在断货窗口"
                            f"{_format_stockout_window(stockout_window)}，达到{PROCUREMENT_PICKUP_DELAY_MARK_DAYS}天阈值{note_text}。"
                        ),
                        "recommendation": "",
                        "confidence": 0.72,
                    }
                )
    return causes[:6]


def _shipment_rows_from_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = []
    for key in ("first_leg_shipments", "shipments", "shipment_rows"):
        value = source.get(key)
        if isinstance(value, list):
            candidates.extend(value)
        elif isinstance(value, dict) and isinstance(value.get("shipments"), list):
            candidates.extend(value["shipments"])
    first_leg = source.get("first_leg") if isinstance(source.get("first_leg"), dict) else {}
    if isinstance(first_leg.get("shipments"), list):
        candidates.extend(first_leg["shipments"])
    return [row for row in candidates if isinstance(row, dict)]


def _stockout_date_windows(item: ControlTowerItem, source: dict[str, Any]) -> list[dict[str, Any]]:
    base_date = _parse_date(source.get("sales_end_date")) or date.today()
    windows: list[dict[str, Any]] = []
    for start_day, end_day in _stockout_day_ranges(item, source):
        start_date = base_date + timedelta(days=max(start_day - 1, 0))
        end_date = base_date + timedelta(days=max(end_day - 1, 0))
        windows.append(
            {
                "start_day": start_day,
                "end_day": end_day,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return windows


def _stockout_day_ranges(item: ControlTowerItem, source: dict[str, Any]) -> list[tuple[int, int]]:
    values = source.get("pici_gap_values") if isinstance(source.get("pici_gap_values"), dict) else item.pici_gap_values
    entries = []
    for key, raw_value in (values or {}).items():
        horizon = _horizon(key)
        parsed = _parse_pici_gap_value(raw_value)
        if horizon and parsed:
            entries.append({"horizon": horizon, **parsed})
    entries.sort(key=lambda entry: entry["horizon"])

    ranges: list[tuple[int, int]] = []
    previous_horizon = 0
    previous_available = 0.0
    previous_forecast = 0.0
    base_pool = 0.0
    active_start: int | None = None

    for entry in entries:
        horizon = int(entry["horizon"])
        interval_days = max(horizon - previous_horizon, 0)
        if interval_days <= 0:
            previous_horizon = horizon
            previous_available = float(entry["available"])
            previous_forecast = float(entry["forecast"])
            continue

        interval_forecast = max(float(entry["forecast"]) - previous_forecast, 0.0)
        interval_supply = max(float(entry["available"]) - previous_available, 0.0)
        daily_forecast = interval_forecast / interval_days if interval_days else 0.0
        base_pool += interval_supply

        for day in range(previous_horizon + 1, horizon + 1):
            used_quantity = min(base_pool, daily_forecast)
            base_pool -= used_quantity
            remaining_demand = max(daily_forecast - used_quantity, 0.0)
            is_shortage = daily_forecast > 0 and remaining_demand > 0.000001
            if is_shortage:
                if active_start is None:
                    active_start = day
            elif active_start is not None:
                ranges.append((active_start, day - 1))
                active_start = None

        previous_horizon = horizon
        previous_available = float(entry["available"])
        previous_forecast = float(entry["forecast"])

    if active_start is not None:
        end_day = int(entries[-1]["horizon"]) if entries else active_start
        ranges.append((active_start, end_day))

    return ranges


def _parse_pici_gap_value(value: Any) -> dict[str, float] | None:
    text = str(value or "").strip()
    match = re.match(r"^\s*([\d,]+(?:\.\d+)?)\s*/\s*([\d,]+(?:\.\d+)?)\s*\((-?[\d,]+(?:\.\d+)?)\)", text)
    if not match:
        return None
    return {
        "available": float(match.group(1).replace(",", "")),
        "forecast": float(match.group(2).replace(",", "")),
        "gap": float(match.group(3).replace(",", "")),
    }


def _stockout_window_for_date(target_date: date | None, windows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not target_date:
        return None
    for window in windows:
        start_date = window.get("start_date")
        end_date = window.get("end_date")
        if isinstance(start_date, date) and isinstance(end_date, date) and start_date <= target_date <= end_date:
            return window
    return None


def _format_stockout_window(window: dict[str, Any]) -> str:
    start_day = int(window.get("start_day") or 0)
    end_day = int(window.get("end_day") or start_day)
    start_date = window.get("start_date")
    end_date = window.get("end_date")
    day_text = f"第{start_day}-{end_day}天" if start_day != end_day else f"第{start_day}天"
    if isinstance(start_date, date) and isinstance(end_date, date):
        return f"{day_text}（{start_date.isoformat()}至{end_date.isoformat()}）"
    return day_text


def _shipment_delay_note_text(row: dict[str, Any], *, include_status: bool = True) -> str:
    note_keys = {
        "logistics_delay_remark",
        "delay_remark",
        "delay_reason",
        "exception",
        "exception_remark",
        "abnormal_remark",
        "logistics_exception",
        "remark",
        "remarks",
        "note",
        "notes",
        "memo",
        "comment",
        "备注",
        "延误备注",
        "异常备注",
        "物流异常备注",
        "跟进备注",
    }
    notes: list[str] = []
    for key, value in row.items():
        key_text = str(key or "").strip()
        normalized_key = key_text.lower()
        should_include = (
            key_text in note_keys
            or normalized_key in note_keys
            or any(token in key_text for token in ("备注", "异常", "延误"))
        )
        if not should_include:
            continue
        text = str(value or "").strip()
        if not _is_meaningful_delay_note(text):
            continue
        notes.append(text)
    if include_status:
        status_note = _shipment_abnormal_status_note(row)
        if status_note:
            notes.insert(0, status_note)
    deduped = list(dict.fromkeys(notes))
    if not deduped:
        return ""
    return f"；备注：{'；'.join(deduped[:3])}"


def _shipment_logistics_exception_cause(
    row: dict[str, Any],
    *,
    label: str,
    plan_sign_date: date | None,
    estimated_sign_date: date | None,
) -> dict[str, Any] | None:
    status_note = _shipment_abnormal_status_note(row)
    if not status_note or not _is_current_pending_logistics_delay(row, estimated_sign_date):
        return None
    date_parts = []
    if plan_sign_date:
        date_parts.append(f"计划签收 {plan_sign_date.isoformat()}")
    if estimated_sign_date:
        date_parts.append(f"预计签收 {estimated_sign_date.isoformat()}")
    delay_text = ""
    if plan_sign_date and estimated_sign_date:
        delay_days = (estimated_sign_date - plan_sign_date).days
        if delay_days > 0:
            delay_text = f"，预计较计划延后 {delay_days} 天"
    note_text = _shipment_delay_note_text(row, include_status=False)
    return {
        "cause": "物流异常",
        "type": "logistics",
        "evidence": f"{label}{'，'.join(date_parts)}{delay_text}，当前{status_note}{note_text}。",
        "recommendation": "",
        "confidence": 0.76,
    }


def _is_meaningful_delay_note(text: str) -> bool:
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    generic_notes = {"-", "无", "暂无", "已标记发货", "标记发货", "已发货"}
    return cleaned not in generic_notes


def _shipment_abnormal_status_note(row: dict[str, Any]) -> str:
    abnormal_markers = (
        "查验",
        "海关",
        "异常",
        "延误",
        "滞留",
        "扣关",
        "查柜",
        "inspection",
        "customs",
        "hold",
        "delay",
        "delayed",
    )
    status_values = [
        str(row.get(key) or "").strip()
        for key in ("current_shipping_status", "detail_status", "status", "shipping_status")
        if str(row.get(key) or "").strip()
    ]
    abnormal_values = [
        value
        for value in status_values
        if any(marker in value.lower() for marker in abnormal_markers)
    ]
    if abnormal_values:
        return f"状态：{'；'.join(dict.fromkeys(abnormal_values))}"
    return ""


def _shipment_label(row: dict[str, Any]) -> str:
    for key in ("batch_num", "ship_id", "package_id", "refer_id", "warehouse_inbound_number", "logistics_tracking_number"):
        value = str(row.get(key) or "").strip()
        if value:
            return f"批次{value}"
    return "头程批次"


def _shipment_has_arrived(row: dict[str, Any]) -> bool:
    if _row_date(
        row,
        (
            "actual_delivery_time",
            "actual_sign_time",
            "actual_signed_time",
            "received_time",
            "receipt_time",
            "signed_time",
            "实际签收时间",
            "实际交付时间",
        ),
    ):
        return True
    shipped = _number(row.get("ship_num"))
    received = _number(row.get("quantity_received"))
    if shipped and shipped > 0 and received is not None and received >= shipped:
        return True
    status_text = " ".join(
        str(row.get(key) or "")
        for key in ("current_shipping_status", "detail_status", "status", "shipping_status")
    ).lower()
    arrived_markers = ("已签收", "已到货", "已入库", "已完成", "delivered", "received", "closed", "done")
    return any(marker in status_text for marker in arrived_markers)


def _is_current_pending_logistics_delay(row: dict[str, Any], estimated_sign_date: date | None) -> bool:
    if not estimated_sign_date or _shipment_has_arrived(row):
        return False
    return estimated_sign_date >= date.today()


def _row_date(row: dict[str, Any], keys: tuple[str, ...]) -> date | None:
    for key in keys:
        parsed = _parse_date(row.get(key))
        if parsed:
            return parsed
    return None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("/", "-")
    try:
        return datetime.fromisoformat(text[:19]).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _build_sales_recommendation(
    item: ControlTowerItem,
    stockout: bool,
    overstock: bool,
    replenishment: dict[str, Any],
    source: dict[str, Any],
) -> dict[str, Any]:
    projection = _stockout_projection_text(item)
    actions: list[str] = []
    if stockout:
        actions.append("控销/限促/广告降档，优先让库存撑到最快可落地补货方式到货。")
        if item.sales_property in {"爆", "旺"}:
            actions.append("爆旺款不建议直接停推，应以轻控销+加快补货保住排名和销售连续性。")
    if overstock:
        actions.append("对冗余或长库龄部分做促销、价格测试、捆绑或清货，避免继续堆高库龄。")
    if not actions:
        actions.append("无需控销，维持当前销售节奏并监控价格、广告和销量波动。")
    market = _market_signal_summary(source)
    return {
        "sales_control": replenishment.get("sales_control") or ("控销方面：" + actions[0]),
        "stockout_projection": projection,
        "actions": actions,
        "ad_and_price_review": market["summary"],
        "sales_plan_note": "销售计划、周度价格曲线、广告花费和历史销量已接入时用于校正；缺失时该建议只基于当前行数据。",
    }


def _build_potential_analysis(
    item: ControlTowerItem,
    stockout: bool,
    overstock: bool,
    source: dict[str, Any],
) -> dict[str, Any]:
    score = 50
    if item.sales_property == "爆":
        score += 25
    elif item.sales_property == "旺":
        score += 15
    elif item.sales_property == "平":
        score += 5
    elif item.sales_property == "滞":
        score -= 15
    if item.seasonality and any(term in item.seasonality for term in ("旺季", "节日", "季节")):
        score += 8
    if stockout and item.sales_property in {"爆", "旺"}:
        score += 5
    if overstock:
        score -= 12
    market = _market_signal_summary(source)
    if market.get("forecast_overrun"):
        score += 8
    if market.get("price_decline"):
        score -= 6
    score = max(0, min(100, score))
    if score >= 75:
        label = "高潜力，优先保供"
    elif score >= 55:
        label = "中等潜力，稳态补货"
    else:
        label = "谨慎销售，优先控库存"
    return {
        "score": score,
        "label": label,
        "basis": [
            f"销售属性 {item.sales_property or '-'}，产品属性 {item.product_property or '-'}，季节属性 {item.seasonality or '-'}。",
            f"未来/近30天需求 {item.demand_30d:g}，日均需求 {item.daily_demand:g}，FBA可售天数 {item.sellable_days if item.sellable_days is not None else '-'}。",
            market["summary"],
        ],
        "best_for_sales": _best_sales_strategy(label, stockout, overstock),
        "missing_data": market["missing_data"],
    }


def _build_direction_recommendations(
    item: ControlTowerItem,
    stockout: bool,
    overstock: bool,
    logistics_plan: list[dict[str, Any]],
    countdowns: list[dict[str, Any]],
    replenishment: dict[str, Any],
    cost_comparison: dict[str, Any],
    root_causes: list[dict[str, Any]],
    sales_recommendation: dict[str, Any],
    potential: dict[str, Any],
    external_action_skills: list[dict[str, Any]],
    source: dict[str, Any],
    strategy_recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    market = _market_signal_metrics(source)
    strategy = strategy_recommendation if isinstance(strategy_recommendation, dict) and strategy_recommendation else _sales_property_control_strategy(item)
    control = _sales_control_measure(item, stockout, logistics_plan, strategy)
    logistics_anomalies = _logistics_anomalies(item, stockout, countdowns, root_causes)
    strategy_cost_comparison = _strategy_cost_comparison(strategy, cost_comparison)
    plan_actions = _plan_actions_from_strategy(strategy, strategy_cost_comparison, countdowns, overstock)
    plan_methods = _strategy_replenishment_methods(strategy, cost_comparison)
    total_strategy_quantity = int(sum(_number(method.get("suggested_quantity")) or 0 for method in plan_methods))
    plan_purchase = _strategy_purchase_advice(strategy, total_strategy_quantity, countdowns, overstock)
    return {
        "sales": {
            "owner": "销售",
            "summary": _sales_direction_summary(potential, control, market),
            "sales_potential": {
                "score": potential.get("score"),
                "label": potential.get("label"),
                "basis": potential.get("basis", []),
                "weekly_sales_ad_ratio": market.get("sales_per_ad_yuan"),
                "ad_order_share": market.get("ad_order_share"),
                "sales_curve": market.get("sales_curve"),
                "sales_anomalies": market.get("sales_anomalies", []),
                "ad_spend": market.get("ad_spend"),
                "actual_sales": market.get("actual_sales"),
                "missing_data": market.get("missing_data", []),
            },
            "sales_performance": {
                "selected_period_sales": item.daily_sales_volume,
                "selected_period_note": "daily_sales_volume 是当前页面选择销售区间的实际销量，不一定是30天销量。",
                "actual_sales": market.get("actual_sales"),
                "review_start_date": market.get("review_start_date"),
                "review_end_date": market.get("review_end_date"),
                "weekly_actual_sales": market.get("weekly_actual_sales", []),
                "sales_curve": market.get("sales_curve"),
                "sales_anomalies": market.get("sales_anomalies", []),
                "ad_spend": market.get("ad_spend"),
                "ad_order_quantity": market.get("ad_order_quantity"),
                "ad_order_share": market.get("ad_order_share"),
                "sales_per_ad_yuan": market.get("sales_per_ad_yuan"),
                "demand_reference": {
                    "demand_7d": item.demand_7d,
                    "demand_30d": item.demand_30d,
                    "daily_demand": item.daily_demand,
                    "note": "这些是需求/预测参考，不是实际售卖表现。",
                },
            },
            "stockout_and_sales_control": {
                "has_stockout_risk": stockout,
                "strategy_key": control.get("strategy_key"),
                "strategy_label": control.get("strategy_label"),
                "sales_property": item.sales_property,
                "stockout_start_day": item.pici_first_shortage_days,
                "estimated_stockout_days": control["stockout_days"],
                "stockout_window": control["stockout_window"],
                "control_required": control["control_required"],
                "control_quantity": control["control_quantity"],
                "control_days": control["control_days"],
                "daily_control_quantity": control["daily_control_quantity"],
                "control_segments": control.get("control_segments"),
                "max_control_ratio": control.get("max_control_ratio"),
                "residual_shortage_quantity": control.get("residual_shortage_quantity"),
                "unresolved_segments": control.get("unresolved_segments"),
                "target_limit_day": control.get("target_limit_day"),
                "recommendation": control["recommendation"],
                "reminder": control.get("reminder", ""),
            },
            "forecast_accuracy": {
                "forecast_quantity": market.get("forecast_quantity"),
                "actual_sales": market.get("actual_sales"),
                "variance_percent": market.get("variance_percent"),
                "result_label": market.get("result_label"),
                "forecast_anomalies": market.get("forecast_anomalies", []),
                "detail_monthly_totals": market.get("detail_monthly_totals", []),
                "is_accurate": market.get("forecast_is_accurate"),
                "needs_raise_forecast": market.get("needs_raise_forecast"),
                "suggested_forecast_quantity": market.get("suggested_forecast_quantity"),
                "suggested_increase_quantity": market.get("suggested_forecast_increase_quantity"),
                "recommendation": market.get("forecast_recommendation"),
            },
            "actions": sales_recommendation.get("actions", []),
            "skill_placeholders": _skill_placeholders(external_action_skills, {"sales_control", "promotion_clearance"}),
        },
        "logistics": {
            "owner": "物流",
            "summary": _logistics_direction_summary(logistics_anomalies),
            "detected_anomalies": logistics_anomalies,
            "checks": _logistics_checks(item, stockout, countdowns),
            "skill_placeholders": _skill_placeholders(external_action_skills, {"logistics_replenishment"}),
        },
        "plan": {
            "owner": "计划",
            "summary": _plan_direction_summary(strategy, total_strategy_quantity),
            "computed_strategy": _json_safe(strategy),
            "inventory_replenishment": {
                "source": "control_tower_recommendations._build_strategy_recommendation",
                "strategy_key": strategy.get("strategy_key"),
                "strategy_label": strategy.get("strategy_label"),
                "methods": plan_methods,
                "total_replenishment_quantity": total_strategy_quantity,
                "purchase": plan_purchase,
                "replenishment_text": strategy.get("replenishment_text") or "",
                "pmc_recommendation": strategy.get("pmc_recommendation") or "",
                "procurement_recommendation": strategy.get("procurement_recommendation") or "",
                "legacy_window_replenishment": _json_safe(replenishment),
                "countdowns": countdowns,
            },
            "cost_comparison": strategy_cost_comparison,
            "actions": plan_actions,
            "skill_placeholders": _skill_placeholders(external_action_skills, {"purchase_order_draft"}),
        },
    }


def _sales_direction_summary(potential: dict[str, Any], control: dict[str, Any], market: dict[str, Any]) -> str:
    potential_text = potential.get("label") or "潜力待判断"
    control_text = control.get("recommendation") or "控销建议待判断。"
    forecast_text = market.get("forecast_recommendation") or "销售预测准确性待补数据。"
    return f"销售方向：{potential_text}；{control_text}；{forecast_text}"


def _sales_control_measure(
    item: ControlTowerItem,
    stockout: bool,
    logistics_plan: list[dict[str, Any]],
    strategy_recommendation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    first_day = item.pici_first_shortage_days
    shortage_days = _shortage_days(item)
    if not stockout or first_day is None:
        return {
            "strategy_key": None,
            "strategy_label": "无需控销",
            "control_required": False,
            "control_quantity": 0,
            "control_days": 0,
            "daily_control_quantity": 0,
            "control_segments": "",
            "max_control_ratio": 0,
            "residual_shortage_quantity": 0,
            "unresolved_segments": "",
            "target_limit_day": None,
            "stockout_days": shortage_days,
            "stockout_window": _stockout_window_text(item, shortage_days),
            "recommendation": "控销方面：当前未命中断货窗口，无需控销。",
            "reminder": "",
        }

    strategy = strategy_recommendation if isinstance(strategy_recommendation, dict) and strategy_recommendation else _sales_property_control_strategy(item)
    control_quantity = round(_number(strategy.get("control_saved_quantity")) or 0, 1)
    control_days = int(_number(strategy.get("control_days")) or 0)
    daily_control_quantity = round(control_quantity / control_days, 1) if control_days else 0
    stockout_days = int(_number(strategy.get("original_shortage_days")) or shortage_days or 0)
    strategy_label = str(strategy.get("strategy_label") or "")
    control_segments = str(strategy.get("control_segments") or "")
    residual_shortage = round(_number(strategy.get("residual_shortage_quantity")) or 0, 1)
    unresolved_segments = str(strategy.get("unresolved_segments") or "")
    property_note = (
        "平滞款按平滞控销口径：目标看至第60天，不把空运作为控销依据；只用慢船/自然恢复补61-75天后段，不覆盖75天后不建议发货区。"
        if _is_flat_or_stagnant_property_value(item.sales_property)
        else "爆旺款按45天控销口径：优先保排名和销售连续性，控销用于覆盖45天内缺口，补货另走计划/物流判断。"
    )
    if control_days or control_quantity:
        recommendation = (
            f"控销方面：销售属性{item.sales_property or '-'}，使用{strategy_label}。{property_note}"
            f"建议控销段 {control_segments or '-'}，合计控 {control_quantity:g} 件、控 {control_days} 天，"
            f"约每天少卖/少推 {daily_control_quantity:g} 件；控销后剩余缺口 {residual_shortage:g}。"
        )
    else:
        recommendation = (
            f"控销方面：销售属性{item.sales_property or '-'}，使用{strategy_label or '当前控销口径'}。"
            f"{property_note}当前控销算法未给出必须控销段，重点复核断货段和补货计划。"
        )
    if unresolved_segments:
        recommendation += f" 无法仅靠控销覆盖的断货段：{unresolved_segments}。"
    reminder = _sales_control_reminder_text(
        item=item,
        strategy=strategy,
        stockout_window=_stockout_window_text(item, stockout_days),
        strategy_label=strategy_label,
        control_segments=control_segments,
        control_quantity=control_quantity,
        control_days=control_days,
        daily_control_quantity=daily_control_quantity,
        residual_shortage=residual_shortage,
        unresolved_segments=unresolved_segments,
    )
    return {
        "strategy_key": strategy.get("strategy_key"),
        "strategy_label": strategy_label,
        "control_required": True,
        "control_quantity": control_quantity,
        "control_days": control_days,
        "daily_control_quantity": daily_control_quantity,
        "control_segments": control_segments,
        "max_control_ratio": strategy.get("max_control_ratio"),
        "residual_shortage_quantity": residual_shortage,
        "unresolved_segments": unresolved_segments,
        "target_limit_day": strategy.get("target_limit_day"),
        "stockout_days": stockout_days,
        "stockout_window": _stockout_window_text(item, stockout_days),
        "recommendation": recommendation,
        "reminder": reminder,
    }


def _sales_control_reminder_text(
    *,
    item: ControlTowerItem,
    strategy: dict[str, Any],
    stockout_window: str,
    strategy_label: str,
    control_segments: str,
    control_quantity: float,
    control_days: int,
    daily_control_quantity: float,
    residual_shortage: float,
    unresolved_segments: str,
) -> str:
    strategy_key = str(strategy.get("strategy_key") or "")
    target_limit_day = int(_number(strategy.get("target_limit_day")) or 0)
    is_boom_or_wang = item.sales_property in {"爆", "旺"} or strategy_key == "standard_45" or target_limit_day == 45
    if not is_boom_or_wang or (control_quantity <= 0 and control_days <= 0 and not control_segments):
        return ""
    clean_stockout_window = str(stockout_window or "").strip(" 。")
    parts = [
        f"{item.sales_property or '爆旺'}款命中断货风险，按{strategy_label or '当前45天控销口径'}触发控销提醒",
        f"断货窗口：{clean_stockout_window}",
        f"控销时间：{control_segments or f'控 {control_days:g} 天'}",
        f"控销量：合计控 {control_quantity:g} 件",
    ]
    if control_days:
        parts.append(f"控销天数 {control_days:g} 天")
    if daily_control_quantity:
        parts.append(f"约每天少卖/少推 {daily_control_quantity:g} 件")
    if residual_shortage:
        parts.append(f"控销后仍缺 {residual_shortage:g} 件，需补货覆盖")
    return "；".join(parts) + "。"


def _sales_property_control_strategy(item: ControlTowerItem) -> dict[str, Any]:
    if _is_flat_or_stagnant_property_value(item.sales_property):
        strategy = _build_control_strategy_recommendation(
            item,
            strategy_key="flat_slow_60",
            strategy_label="当前平滞控销口径",
            target_limit_day=60,
            replenishment_mode="slow_ship_only",
            control_mode="recovery_segmented",
        )
        strategy["target_limit_day"] = 60
        strategy["replenishment_mode"] = "slow_ship_only"
        strategy["control_mode"] = "recovery_segmented"
        strategy["source_logic"] = "control_tower_recommendations._build_strategy_recommendation"
        return strategy
    strategy = _build_control_strategy_recommendation(
        item,
        strategy_key="standard_45",
        strategy_label="当前45天控销口径",
        target_limit_day=45,
    )
    strategy["target_limit_day"] = 45
    strategy["replenishment_mode"] = "standard"
    strategy["control_mode"] = "auto"
    strategy["source_logic"] = "control_tower_recommendations._build_strategy_recommendation"
    return strategy


def _is_flat_or_stagnant_property_value(value: Any) -> bool:
    if _is_flat_or_stagnant_sales_property(str(value or "")):
        return True
    try:
        repaired = str(value or "").encode("latin1").decode("utf-8")
    except UnicodeError:
        repaired = ""
    return _is_flat_or_stagnant_sales_property(repaired)


def _stockout_window_text(item: ControlTowerItem, stockout_days: int) -> str:
    if item.pici_first_shortage_days is None:
        return "当前缺少最早断货日，无法判断断货窗口。"
    if stockout_days:
        end_day = item.pici_first_shortage_days + max(stockout_days - 1, 0)
        return f"预计第 {item.pici_first_shortage_days} 天开始，当前 chazhi 窗口约持续 {stockout_days} 天，约到第 {end_day} 天。"
    return f"预计第 {item.pici_first_shortage_days} 天开始出现断货窗口，持续天数需补 chazhi 明细。"


def _market_signal_metrics(source: dict[str, Any]) -> dict[str, Any]:
    weekly = source.get("weekly_sales_and_price") if isinstance(source.get("weekly_sales_and_price"), dict) else {}
    if not weekly or not weekly.get("ok"):
        reason = weekly.get("reason") if weekly else "缺少销售计划、历史销量、广告花费和周度价格曲线。"
        return {
            "ok": False,
            "summary": reason,
            "forecast_quantity": None,
            "actual_sales": None,
            "ad_spend": None,
            "sales_per_ad_yuan": None,
            "ad_order_share": None,
            "sales_curve": "缺少周度销量曲线。",
            "variance_percent": None,
            "result_label": None,
            "forecast_is_accurate": None,
            "needs_raise_forecast": None,
            "suggested_forecast_quantity": None,
            "suggested_forecast_increase_quantity": None,
            "forecast_recommendation": f"销售预测：{reason}",
            "forecast_anomalies": [],
            "sales_anomalies": [],
            "detail_monthly_totals": [],
            "missing_data": ["sales_plan", "weekly_price_curve", "ad_spend", "historical_sales"],
        }

    weekly_rows = weekly.get("weekly_estimates") if isinstance(weekly.get("weekly_estimates"), list) else []
    forecast_anomalies = weekly.get("forecast_anomalies") if isinstance(weekly.get("forecast_anomalies"), list) else []
    sales_anomalies = weekly.get("sales_anomalies") if isinstance(weekly.get("sales_anomalies"), list) else []
    detail_monthly_totals = (
        weekly.get("detail_monthly_totals")
        if isinstance(weekly.get("detail_monthly_totals"), list)
        else []
    )
    forecast_row_count = _number(weekly.get("forecast_row_count"))
    forecast_missing = weekly.get("forecast_data_status") == "missing" or (forecast_row_count is not None and int(forecast_row_count) == 0)
    forecast_quantity = _number(weekly.get("forecast_quantity"))
    actual_sales = _number(weekly.get("actual_sales"))
    ad_spend = _number(weekly.get("ad_spend"))
    ad_orders = _number(weekly.get("ad_order_quantity"))
    if forecast_quantity is None and not forecast_missing:
        forecast_quantity = _sum_weekly_metric(weekly_rows, "forecast_quantity")
    if actual_sales is None:
        actual_sales = _sum_weekly_metric(weekly_rows, "actual_sales")
    if ad_spend is None:
        ad_spend = _sum_weekly_metric(weekly_rows, "ad_spend")
    if ad_orders is None:
        ad_orders = _sum_weekly_metric(weekly_rows, "ad_order_quantity")

    variance = _number(weekly.get("variance_percent"))
    if variance is None and forecast_quantity:
        variance = ((actual_sales or 0) - forecast_quantity) / forecast_quantity * 100
    sales_per_ad_yuan = round((actual_sales or 0) / ad_spend, 4) if ad_spend else None
    ad_order_share = round((ad_orders or 0) / actual_sales, 4) if actual_sales else None
    curve = _weekly_sales_curve(weekly_rows)
    if forecast_missing:
        needs_raise = None
        forecast_is_accurate = None
        suggested_forecast_quantity = round(actual_sales, 2) if actual_sales is not None else None
        suggested_increase = round(actual_sales, 2) if actual_sales is not None else None
        forecast_recommendation = (
            "销售预测：预测表未匹配到有效预测行，不能把 raw_forecast_quantity=0 当成真实预测；"
            f"需先补/修正销售计划匹配口径。若用本轮实际销量作临时下限，建议至少补到 {suggested_forecast_quantity:g} 件。"
            if suggested_forecast_quantity is not None
            else "销售预测：预测表未匹配到有效预测行，需先补/修正销售计划匹配口径。"
        )
    elif variance is None:
        needs_raise = None
        forecast_is_accurate = None
        suggested_forecast_quantity = forecast_quantity
        suggested_increase = None
        forecast_recommendation = "销售预测：缺少预测与实际销量差异，需补销售计划或历史销量。"
    else:
        needs_raise = variance >= 15
        forecast_is_accurate = abs(variance) <= 15
        suggested_forecast_quantity = round(max(actual_sales or 0, forecast_quantity or 0), 2) if needs_raise else forecast_quantity
        suggested_increase = round(max((actual_sales or 0) - (forecast_quantity or 0), 0), 2) if needs_raise else 0
        if needs_raise:
            forecast_recommendation = f"销售预测：实际销量高于预测 {variance:g}%，建议把后续预测至少提高 {suggested_increase:g} 件或按实际销量重算。"
        elif variance <= -15:
            forecast_recommendation = f"销售预测：实际销量低于预测 {abs(variance):g}%，暂不建议提高预测，先复核价格、广告和转化。"
        else:
            forecast_recommendation = f"销售预测：实际与预测偏差 {variance:g}%，当前预测基本可用。"
    return {
        "ok": True,
        "summary": (
            f"周度销量/广告：实际销量 {actual_sales or 0:g}，广告花费 {ad_spend or 0:g}，"
            f"销量/广告费 {sales_per_ad_yuan if sales_per_ad_yuan is not None else '-'} 件/元；{curve}"
        ),
        "review_start_date": weekly.get("review_start_date"),
        "review_end_date": weekly.get("review_end_date"),
        "forecast_quantity": forecast_quantity,
        "actual_sales": actual_sales,
        "ad_spend": ad_spend,
        "ad_order_quantity": ad_orders,
        "sales_per_ad_yuan": sales_per_ad_yuan,
        "ad_order_share": ad_order_share,
        "sales_curve": curve,
        "weekly_actual_sales": _weekly_actual_sales_points(weekly_rows),
        "variance_percent": round(variance, 2) if variance is not None else None,
        "result_label": weekly.get("result_label"),
        "forecast_is_accurate": forecast_is_accurate,
        "needs_raise_forecast": needs_raise,
        "suggested_forecast_quantity": suggested_forecast_quantity,
        "suggested_forecast_increase_quantity": suggested_increase,
        "forecast_recommendation": forecast_recommendation,
        "forecast_anomalies": forecast_anomalies,
        "sales_anomalies": sales_anomalies,
        "detail_monthly_totals": detail_monthly_totals,
        "missing_data": ["sales_plan"] if forecast_missing else [],
    }


def _sum_weekly_metric(rows: list[Any], key: str) -> float:
    return round(sum(_number(row.get(key)) or 0 for row in rows if isinstance(row, dict)), 2)


def _weekly_sales_curve(rows: list[Any]) -> str:
    points = [
        {
            "week": str(row.get("week") or ""),
            "actual_sales": _number(row.get("actual_sales")) or 0,
        }
        for row in rows
        if isinstance(row, dict)
    ]
    if len(points) < 2:
        return "周度销量曲线不足，无法判断趋势。"
    nonzero = [point for point in points if point["actual_sales"] > 0]
    if not nonzero:
        return "周度实际销量均为0，暂无有效售卖趋势。"
    if len(nonzero) == 1:
        point = nonzero[0]
        return f"仅 {point['week'] or '1个周'} 有实际销量 {point['actual_sales']:g}，趋势样本不足。"
    first = float(nonzero[0]["actual_sales"])
    last = float(nonzero[-1]["actual_sales"])
    peak_point = max(nonzero, key=lambda point: float(point["actual_sales"]))
    peak = float(peak_point["actual_sales"])
    if first:
        change = (last - first) / first * 100
    else:
        change = 100 if last > 0 else 0
    if peak > 0 and last < peak * 0.8:
        trend = "回落"
    elif change >= 10:
        trend = "上升"
    elif change <= -10:
        trend = "下降"
    else:
        trend = "平稳"
    peak_change = (last - peak) / peak * 100 if peak else 0
    sequence = " -> ".join(f"{point['week'] or '-'}:{point['actual_sales']:g}" for point in nonzero[-6:])
    return (
        f"周度实际销量曲线{trend}，有销量周序列 {sequence}；"
        f"首个有销量周 {first:g}，最近一周 {last:g}，较首个有销量周变化 {change:.1f}%；"
        f"峰值 {peak:g}({peak_point['week'] or '-'})，最近较峰值变化 {peak_change:.1f}%。"
    )


def _weekly_actual_sales_points(rows: list[Any]) -> list[dict[str, Any]]:
    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        points.append(
            {
                "week": row.get("week"),
                "week_start_date": row.get("week_start_date"),
                "week_end_date": row.get("week_end_date"),
                "actual_sales": _number(row.get("actual_sales")) or 0,
                "forecast_quantity": _number(row.get("forecast_quantity")) or 0,
                "ad_spend": _number(row.get("ad_spend")) or 0,
                "ad_order_quantity": _number(row.get("ad_order_quantity")) or 0,
            }
        )
    return points[-12:]


def _logistics_anomalies(
    item: ControlTowerItem,
    stockout: bool,
    countdowns: list[dict[str, Any]],
    root_causes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    anomalies = [
        {
            "type": cause.get("type"),
            "cause": cause.get("cause"),
            "evidence": cause.get("evidence"),
            "recommendation": cause.get("recommendation"),
        }
        for cause in root_causes
        if isinstance(cause, dict) and cause.get("type") in {"logistics", "logistics_delay", "procurement_delay"}
    ]
    for row in countdowns:
        if not isinstance(row, dict) or not row.get("should_act"):
            continue
        action = str(row.get("action") or "")
        if "催" in action or "FBA" in action or "海外仓" in action or "本地仓" in action:
            anomalies.append(
                {
                    "type": "replenishment_countdown",
                    "cause": action,
                    "evidence": f"{row.get('name')}={row.get('countdown_days')}天，{row.get('status')}",
                    "recommendation": f"检查{action}对应的在途、接收、上架或调拨状态。",
                }
            )
    return anomalies


def _logistics_direction_summary(anomalies: list[dict[str, Any]]) -> str:
    active = [item for item in anomalies if item.get("type") != "monitor"]
    if not active:
        return "物流方向：未检测到明确物流异常，保持 ETA、接收和上架监控。"
    causes = "；".join(str(item.get("cause") or "-") for item in active[:3])
    return f"物流方向：检测到 {len(active)} 项需要检查的物流/在途异常：{causes}。"


def _logistics_checks(item: ControlTowerItem, stockout: bool, countdowns: list[dict[str, Any]]) -> list[str]:
    checks = []
    if stockout:
        checks.append("检查 FBA 接收中/处理中库存能否早于最早断货日转可售。")
    if item.inbound_total > 0:
        checks.append(f"核对在途/计划 {item.inbound_total:g} 件的 ETA、承运渠道、清关、入仓和上架状态。")
    for row in countdowns:
        if isinstance(row, dict) and row.get("should_act") and "催" in str(row.get("action") or ""):
            checks.append(f"{row.get('action')}：{row.get('formula')}={row.get('countdown_days')}天，需当天检查。")
    if not checks:
        checks.append("暂无强物流检查项，维持日常 ETA 与上架监控。")
    return checks


STRATEGY_REPLENISHMENT_CHANNELS = (
    ("urgent_air", "urgent_air_quantity", "加急空运", URGENT_AIR_ARRIVAL_DAY, "第10天到，覆盖10-19天窗口"),
    ("standard_air", "standard_air_quantity", "普通空运", STANDARD_AIR_ARRIVAL_DAY, "第20天到，覆盖20-45天窗口"),
    ("fast_ship", "fast_quantity", "快船", FAST_SHIP_ARRIVAL_DAY, "第45天到，覆盖46-60天窗口"),
    ("slow_ship", "slow_quantity", "慢船", SLOW_SHIP_ARRIVAL_DAY, "第60天到，覆盖61天后窗口"),
)


def _strategy_replenishment_methods(
    strategy: dict[str, Any],
    cost_comparison: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cost_rows = {
        str(row.get("channel")): row
        for row in (cost_comparison or {}).get("rows", [])
        if isinstance(row, dict) and row.get("channel")
    }
    methods: list[dict[str, Any]] = []
    basis = strategy.get("replenishment_text") or strategy.get("pmc_recommendation") or "程序策略行未给出补货说明。"
    for channel, quantity_field, label, arrival_day, window in STRATEGY_REPLENISHMENT_CHANNELS:
        quantity = int(round(_number(strategy.get(quantity_field)) or 0))
        if quantity <= 0:
            continue
        method_window = (
            f"第{SLOW_SHIP_ARRIVAL_DAY}天到，覆盖{SLOW_SHIP_REPLENISHMENT_START_DAY}-{FLAT_STAGNANT_SHIPPING_CUTOFF_DAY}天窗口"
            if channel == "slow_ship" and strategy.get("replenishment_mode") == "slow_ship_only"
            else window
        )
        cost_row = cost_rows.get(channel, {})
        unit_cost = _number(cost_row.get("unit_shipping_cost_cny"))
        method = {
            "channel": channel,
            "channel_label": label,
            "arrival_day": arrival_day,
            "window": method_window,
            "suggested_quantity": quantity,
            "basis": basis,
            "source_quantity_field": quantity_field,
        }
        if unit_cost is not None:
            method["unit_shipping_cost_cny"] = round(unit_cost, 2)
            method["estimated_cost_cny"] = round(unit_cost * quantity, 2)
        methods.append(method)
    return methods


def _strategy_cost_comparison(strategy: dict[str, Any], cost_comparison: dict[str, Any]) -> dict[str, Any]:
    methods = _strategy_replenishment_methods(strategy, cost_comparison)
    rows = [
        {
            "channel": method.get("channel"),
            "channel_label": method.get("channel_label"),
            "arrival_day": method.get("arrival_day"),
            "window": method.get("window"),
            "suggested_quantity": method.get("suggested_quantity"),
            "unit_shipping_cost_cny": method.get("unit_shipping_cost_cny"),
            "estimated_cost_cny": method.get("estimated_cost_cny"),
            "basis": method.get("basis"),
        }
        for method in methods
    ]
    rows_with_total_cost = [row for row in rows if _number(row.get("estimated_cost_cny")) is not None]
    if not methods:
        recommendation = "程序策略未给出新增补货量，当前计划方向无需做补货成本对比。"
    elif rows_with_total_cost:
        lowest_total = min(rows_with_total_cost, key=lambda row: _number(row.get("estimated_cost_cny")) or 0)
        recommendation = (
            f"按程序策略补货量测算，当前最低总成本渠道为 {lowest_total.get('channel_label')}，"
            f"预计 {lowest_total.get('estimated_cost_cny')} 元；执行前仍需复核箱规、抛重和实际报价。"
        )
    else:
        recommendation = "已有程序策略补货量，但缺少 product info.weight_gram 或渠道单价，暂不能比较补货总成本。"
    return {
        "ok": bool(rows_with_total_cost),
        "currency": "CNY",
        "source": "computed_strategy_recommendation",
        "rows": rows,
        "lowest_total_cost_channel": min(rows_with_total_cost, key=lambda row: _number(row.get("estimated_cost_cny")) or 0) if rows_with_total_cost else None,
        "lowest_unit_cost_channel": min(rows_with_total_cost, key=lambda row: _number(row.get("unit_shipping_cost_cny")) or 0) if rows_with_total_cost else None,
        "recommendation": recommendation,
        "formula": "estimated_cost_cny = computed_strategy_quantity * unit_shipping_cost_cny",
        "draft_only": True,
    }


def _strategy_purchase_advice(
    strategy: dict[str, Any],
    total_quantity: int,
    countdowns: list[dict[str, Any]],
    overstock: bool,
) -> dict[str, Any]:
    existing = str(strategy.get("procurement_recommendation") or "").strip()
    if existing:
        summary = existing
    elif total_quantity:
        summary = (
            f"采购逻辑：按{strategy.get('strategy_label') or '程序策略'}，补货草稿量 {total_quantity} 件；"
            "需复核 MOQ、箱规、供应商、交期和库存可转化量。"
        )
    else:
        summary = f"采购逻辑：按{strategy.get('strategy_label') or '程序策略'}，当前程序策略未给出新增采购补货量。"
    if overstock and total_quantity:
        summary += " 命中冗余时，采购草稿需先扣减可转化库存和清货目标，禁止自动下单。"
    triggered = [row for row in countdowns if isinstance(row, dict) and row.get("should_act")]
    return {
        "needs_purchase": total_quantity > 0,
        "suggested_purchase_quantity": total_quantity,
        "summary": summary,
        "formula": "建议采购草稿量 = 程序策略行 urgent_air_quantity + standard_air_quantity + fast_quantity + slow_quantity。",
        "strategy_key": strategy.get("strategy_key"),
        "strategy_label": strategy.get("strategy_label"),
        "triggered_countdowns": _json_safe(triggered),
        "draft_only": True,
    }


def _plan_direction_summary(strategy: dict[str, Any], total_quantity: int) -> str:
    strategy_label = strategy.get("strategy_label") or "程序策略"
    plan_text = strategy.get("pmc_recommendation") or strategy.get("replenishment_text")
    if plan_text:
        return f"计划方向：使用{strategy_label}，程序补货建议为 {plan_text}，合计 {total_quantity} 件。"
    return f"计划方向：使用{strategy_label}，程序策略未给出新增补货量，计划侧不新增空运/海运/采购动作。"


def _plan_actions_from_strategy(
    strategy: dict[str, Any],
    cost_comparison: dict[str, Any],
    countdowns: list[dict[str, Any]],
    overstock: bool,
) -> list[str]:
    actions = []
    strategy_label = strategy.get("strategy_label") or "程序策略"
    plan_text = strategy.get("pmc_recommendation") or strategy.get("replenishment_text")
    if plan_text:
        actions.append(f"{strategy_label}：{plan_text}")
    else:
        actions.append(f"{strategy_label}：程序策略未给出新增补货量，计划侧先不新增发货或采购。")
    procurement_text = strategy.get("procurement_recommendation")
    if procurement_text:
        actions.append(f"采购建议：{procurement_text}")
    if cost_comparison.get("recommendation"):
        actions.append(f"成本对比：{cost_comparison['recommendation']}")
    triggered = [row for row in countdowns if isinstance(row, dict) and row.get("should_act")]
    if triggered:
        actions.append("已触发计划动作：" + "；".join(f"{row.get('action')}({row.get('countdown_days')}天)" for row in triggered))
    if overstock:
        actions.append("命中冗余时，计划侧需冻结非必要补货和未确认采购。")
    return actions


def _plan_actions(
    replenishment: dict[str, Any],
    cost_comparison: dict[str, Any],
    countdowns: list[dict[str, Any]],
    overstock: bool,
) -> list[str]:
    actions = []
    if replenishment.get("summary"):
        actions.append(str(replenishment["summary"]))
    purchase = replenishment.get("purchase") if isinstance(replenishment.get("purchase"), dict) else {}
    if purchase.get("summary"):
        actions.append(str(purchase["summary"]))
    if cost_comparison.get("recommendation"):
        actions.append(f"成本对比：{cost_comparison['recommendation']}")
    triggered = [row for row in countdowns if isinstance(row, dict) and row.get("should_act")]
    if triggered:
        actions.append("已触发计划动作：" + "；".join(f"{row.get('action')}({row.get('countdown_days')}天)" for row in triggered))
    if overstock:
        actions.append("命中冗余时，计划侧需冻结非必要补货和未确认采购。")
    if not actions:
        actions.append("计划方向：暂无新增补货或采购动作，继续滚动复盘。")
    return actions


def _skill_placeholders(skills: list[dict[str, Any]], action_types: set[str]) -> list[dict[str, Any]]:
    return [
        skill
        for skill in skills
        if isinstance(skill, dict) and str(skill.get("action_type") or "") in action_types
    ]


def _market_signal_summary(source: dict[str, Any]) -> dict[str, Any]:
    weekly = source.get("weekly_sales_and_price") if isinstance(source.get("weekly_sales_and_price"), dict) else {}
    if not weekly or not weekly.get("ok"):
        return {
            "summary": weekly.get("reason") if weekly else "缺少销售计划、历史销量、广告花费和周度价格曲线。",
            "forecast_overrun": False,
            "price_decline": False,
            "missing_data": ["sales_plan", "weekly_price_curve", "ad_spend", "historical_sales"],
        }
    forecast_row_count = _number(weekly.get("forecast_row_count"))
    forecast_missing = weekly.get("forecast_data_status") == "missing" or (forecast_row_count is not None and int(forecast_row_count) == 0)
    if forecast_missing:
        ad_spend = _number(weekly.get("ad_spend")) or 0
        ad_orders = _number(weekly.get("ad_order_quantity")) or 0
        actual_sales = _number(weekly.get("actual_sales")) or 0
        return {
            "summary": (
                f"预测输入缺失：{weekly.get('forecast_missing_reason') or '预测表未匹配到销售预测行'} "
                f"实际销量 {actual_sales:g}，广告花费 {ad_spend:g}，广告订单 {ad_orders:g}。"
            ),
            "forecast_overrun": False,
            "price_decline": False,
            "missing_data": ["sales_plan"],
        }
    variance = _number(weekly.get("variance_percent")) or 0
    ad_spend = _number(weekly.get("ad_spend")) or 0
    ad_orders = _number(weekly.get("ad_order_quantity")) or 0
    price_points = weekly.get("daily_price_points") if isinstance(weekly.get("daily_price_points"), list) else []
    first_price = _number(price_points[0].get("price")) if price_points and isinstance(price_points[0], dict) else None
    last_price = _number(price_points[-1].get("price")) if price_points and isinstance(price_points[-1], dict) else None
    price_decline = first_price is not None and last_price is not None and last_price < first_price * 0.95
    parts = [
        f"周度复盘：{weekly.get('result_label') or '-'}，实际/预测差值 {variance:g}%。",
        f"广告花费 {ad_spend:g}，广告订单 {ad_orders:g}。",
    ]
    if first_price is not None and last_price is not None:
        parts.append(f"价格曲线从 {first_price:g} 到 {last_price:g}。")
    return {
        "summary": " ".join(parts),
        "forecast_overrun": variance >= 15 or ad_orders > 0 and ad_spend > 0,
        "price_decline": price_decline,
        "missing_data": [],
    }


def _stockout_projection_text(item: ControlTowerItem) -> str:
    if item.pici_first_shortage_days is not None:
        return f"此 SKU 如果按当前销量/预测节奏，预计第 {item.pici_first_shortage_days} 天出现断货窗口。"
    if item.sellable_days is not None:
        return f"此 SKU 按当前日均需求预计 FBA 可售约 {item.sellable_days:g} 天。"
    return "此 SKU 当前缺少日均需求或可售天数，无法稳定预计断货时间。"


def _best_sales_strategy(label: str, stockout: bool, overstock: bool) -> str:
    if stockout and "高潜力" in label:
        return "保排名优先：轻控销、保广告核心词、同步加快补货。"
    if stockout:
        return "控缺口优先：降低促销强度，限制非必要广告放量，等待补货到货。"
    if overstock:
        return "清库存优先：促销/价格测试/捆绑清货，暂停新增采购和非必要发货。"
    return "稳定销售：维持当前节奏，按周复盘价格、广告和销量偏差。"


def _overall_status(item: ControlTowerItem, stockout: bool, overstock: bool, anomaly: bool) -> str:
    parts = []
    if stockout:
        parts.append("断货风险")
    if overstock:
        parts.append("冗余风险")
    if anomaly:
        parts.append("库存异常")
    return " / ".join(parts) if parts else item.warning_type or "正常"


def _shortage_days(item: ControlTowerItem) -> int:
    total = 0
    previous_horizon = 0
    for key, raw_value in sorted(item.pici_gap_values.items(), key=lambda pair: _horizon(pair[0])):
        horizon = _horizon(key)
        value = _number(raw_value)
        if horizon > previous_horizon and value is not None and value < 0:
            total += horizon - previous_horizon
        previous_horizon = horizon
    return total


def _shortage_points(item: ControlTowerItem) -> list[tuple[int, float]]:
    points = []
    for key, raw_value in item.pici_gap_values.items():
        horizon = _horizon(key)
        value = _number(raw_value)
        if horizon and value is not None and value < 0:
            points.append((horizon, abs(value)))
    return sorted(points)


def _max_gap_between(points: list[tuple[int, float]], start_day: int, end_day: int) -> float:
    return max((gap for horizon, gap in points if start_day < horizon <= end_day), default=0)


def _quantity_for_window(daily_demand: float, days: int | float, min_gap_quantity: float = 0) -> int:
    quantity = max(float(daily_demand or 0) * max(float(days or 0), 0), float(min_gap_quantity or 0))
    return int(round(quantity))


def _active(level: str) -> bool:
    return level in ACTIVE_RISK_LEVELS


def _horizon(key: str) -> int:
    try:
        return int(str(key).split("_")[-1])
    except ValueError:
        return 0


def _number(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        text = str(value).strip()
        if "(" in text and ")" in text:
            text = text.rsplit("(", 1)[-1].split(")", 1)[0].strip()
        return float(text)
    except (TypeError, ValueError):
        return None


def _norm(value: Any) -> str:
    return str(value or "").strip().upper()


def _ratio_text(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"


def _unique_remedies(remedies: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique = []
    for item in remedies:
        key = (item.get("owner", ""), item.get("action", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique
