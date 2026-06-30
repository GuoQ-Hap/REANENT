import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import * as d3 from "d3";
import {
  AlertTriangle,
  BarChart3,
  Boxes,
  CalendarDays,
  CheckCircle2,
  Database,
  Download,
  Filter,
  Gauge,
  Layers3,
  LogIn,
  LogOut,
  Moon,
  Plane,
  RefreshCw,
  ShieldAlert,
  Ship,
  Sun,
  UserRound,
  Warehouse,
  X,
} from "lucide-react";
import "./styles.css";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const THEME_STORAGE_KEY = "pmc-control-tower-theme";

function apiFetch(url, options = {}) {
  return fetch(url, { ...options, credentials: "include" });
}

function initialTheme() {
  if (typeof window === "undefined") return "dark";
  const savedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  return savedTheme === "light" ? "light" : "dark";
}

const riskLabels = {
  critical: "严重",
  high: "高",
  medium: "中等",
  low: "提示",
  normal: "正常",
};

const stockoutRiskBadgeLabels = {
  critical: "严重断货风险",
  high: "高断货风险",
  medium: "中等断货风险",
  low: "低断货风险",
  normal: "暂无断货风险",
};

const overstockRiskBadgeLabels = {
  critical: "紧急冗余风险",
  high: "高冗余风险",
  medium: "中等冗余风险",
  low: "低冗余风险",
  normal: "暂无冗余风险",
};

function riskBadgeLabel(labels, level) {
  return labels[level] || labels.normal;
}

const riskTypeLabels = {
  stockout: "断货",
  overstock: "冗余",
  anomaly: "异常",
  healthy: "正常",
};

const salesPropertyLabels = {
  "爆": "爆款",
  "旺": "旺款",
  "平": "平款",
  "滞": "滞销",
  __blank__: "未维护",
};

const chartColorMap = {
  critical: "#ff5b64",
  high: "#ff8c4a",
  medium: "#ffc961",
  low: "#b6c95d",
  normal: "#22f0c4",
  stockout: "#ff5b64",
  overstock: "#ffc961",
  anomaly: "#ff8c4a",
  healthy: "#22f0c4",
  "爆": "#ff5b64",
  "旺": "#ffc961",
  "平": "#64e7ff",
  "滞": "#b6c95d",
  __blank__: "#6f9da6",
};

const chartPalette = ["#23e8ff", "#ffc961", "#ff8c4a", "#b6c95d", "#c7a7ff", "#ff7fc4", "#7ee28b", "#64e7ff"];

const rootCauseTypeLabels = {
  oversell: "超卖",
  supply_anomaly: "供应异常",
  planning_anomaly: "计划异常",
  low_sell: "低卖",
  logistics_delay: "物流延期",
  procurement_delay: "采购延期",
  inventory_position: "库存位置",
  forecast_ad: "预估/广告",
  logistics: "物流异常",
  sales: "销售异常",
  forecast: "预估异常",
  plan: "计划异常",
  inventory: "库存明细",
  overstock: "冗余库存",
  data_quality: "数据异常",
  monitor: "监控",
};

const rootCauseSectionDefinitions = [
  {
    key: "sales",
    title: "销售方向",
    description: "看超卖、低卖、销售预估与广告/价格拉动。",
    types: ["oversell", "low_sell", "sales", "forecast", "forecast_ad"],
  },
  {
    key: "supply",
    title: "供应方向",
    description: "看预测高于实际但仍断货/冗余的供应转化异常，以及采购、在途、签收、接收和上架节点。",
    types: ["supply_anomaly", "logistics_delay", "procurement_delay", "logistics", "planning_anomaly", "plan"],
  },
  {
    key: "inventory",
    title: "库存明细",
    description: "看 FBA 前端可售、库存位置、缺口和库龄结构。",
    types: ["inventory_position", "inventory", "stockout", "overstock", "data_quality"],
  },
];

const COMMON_COUNTRY_OPTIONS = ["US", "JP", "CA", "UK", "DE", "MX", "CN", "FR", "IT", "ES", "AU", "NL", "PL", "SE", "AE", "SA", "BR"];
const MSKU_STATUS_OPTIONS = ["在售", "待售", "共享", "停售", "待淘汰", "淘汰"];
const SALES_PROPERTY_OPTIONS = ["爆", "旺", "平", "滞"];
const RISK_TYPE_OPTIONS = [
  { value: "stockout", label: "断货预警" },
  { value: "overstock", label: "冗余库存" },
  { value: "anomaly", label: "库存异常" },
  { value: "healthy", label: "正常 SKU" },
];
const OVERSTOCK_RULE_HINTS = {
  boom_wang: {
    label: "爆旺",
    lines: [
      "可售天数1超过90天：重点监控清货",
      "可售天数2或3超过120天：停止向FBA补货",
      "可售天数4超过120天：停止向海外仓和FBA补货",
      "可售天数5超过180天：停止本地仓补货",
      "可售天数6超过180天：停止本地仓补货，并停止下采购单",
    ],
    sellable: {
      sellable_1: "爆旺：FBA当前库存可售天数超过90天命中冗余，合理线45天，动作：重点监控清货。",
      sellable_2: "爆旺：FBA+FBA在途可售天数超过120天命中冗余，合理线90天，动作：停止向FBA补货。",
      sellable_3: "爆旺：海外仓库存可售天数超过120天命中冗余，合理线90天，动作：停止向FBA补货。",
      sellable_4: "爆旺：海外仓+全链路在途可售天数超过120天命中冗余，合理线90天，动作：停止向海外仓和FBA补货。",
      sellable_5: "爆旺：本地仓库存可售天数超过180天命中高冗余，合理线120天，动作：停止本地仓补货。",
      sellable_6: "爆旺：本地仓+全链路可售天数超过180天命中高冗余，合理线120天，动作：停止本地仓补货，并停止下采购单。",
    },
  },
  flat_stagnant: {
    label: "平滞",
    lines: [
      "可售天数1超过60天：重点监控清货",
      "可售天数2或3超过105天：停止向FBA补货",
      "可售天数4超过105天：停止向海外仓和FBA补货",
      "可售天数5超过150天：停止本地仓补货",
      "可售天数6超过150天：停止本地仓补货，并停止下采购单",
    ],
    sellable: {
      sellable_1: "平滞：FBA当前库存可售天数超过60天命中冗余，合理线30天，动作：重点监控清货。",
      sellable_2: "平滞：FBA+FBA在途可售天数超过105天命中冗余，合理线75天，动作：停止向FBA补货。",
      sellable_3: "平滞：海外仓库存可售天数超过105天命中冗余，合理线75天，动作：停止向FBA补货。",
      sellable_4: "平滞：海外仓+全链路在途可售天数超过105天命中冗余，合理线75天，动作：停止向海外仓和FBA补货。",
      sellable_5: "平滞：本地仓库存可售天数超过150天命中高冗余，合理线120天，动作：停止本地仓补货。",
      sellable_6: "平滞：本地仓+全链路可售天数超过150天命中高冗余，合理线120天，动作：停止本地仓补货，并停止下采购单。",
    },
  },
};
const STOCKOUT_RULE_TOOLTIP = [
  "断货判断：只看0-45天内 chazhi 是否为负。",
  "0天：无断货；1-7天：中等；8-14天：高；15天以上：严重。",
  "45天后才首次为负时不计入当前断货，只作为补货提示。",
].join("\n");
const RISK_LEVEL_RULE_TOOLTIP = [
  "处理等级按实际命中的业务部分展示。",
  "断货、冗余、异常分别使用各自口径；详情里分别查看断货明细、冗余依据、库存异常。",
  "同一SKU命中多类时，页面展示当前最需要先处理的业务风险。",
].join("\n");
const RISK_LEVEL_ENTRY_TOOLTIPS = {
  critical: [
    "严重：来自断货部分。",
    "口径：0-45天内 chazhi 为负的天数累计15天以上。",
    "处理重点：先复核 FBA 可售、头程在途、最快可补货窗口和控销方案。",
  ].join("\n"),
  high: [
    "高：可能来自断货或冗余部分。",
    "断货口径：0-45天内 chazhi 为负的天数累计8-14天。",
    "冗余口径：可售天数命中停止补货/拦截补货动作，或FBA库龄271天以上需要批量清货。",
  ].join("\n"),
  medium: [
    "中等：可能来自断货、冗余或异常部分。",
    "断货口径：0-45天内 chazhi 为负的天数累计1-7天。",
    "冗余口径：FBA库龄181-270天需要重点清货；异常口径：关键风险标记缺失或异常。",
  ].join("\n"),
  low: [
    "提示：主要来自冗余预警或未来补货提示。",
    "冗余口径：FBA库龄61-180天进入预警监控。",
    "补货提示：45天后才首次出现 chazhi 负数时，只提示提前排补货，不计入当前断货。",
  ].join("\n"),
  normal: [
    "正常：当前筛选口径下未命中断货、冗余或库存异常。",
    "仍需结合销量变化、补货计划和头程在途做日常复核。",
  ].join("\n"),
};
const RISK_TYPE_RULE_TOOLTIP = [
  "风险类型按业务部分拆开展示：断货、冗余、异常、正常。",
  "每一类都有独立判断口径，悬浮到具体分类可看细则。",
  "同一SKU多类同时命中时，详情里仍分别保留各部分依据。",
].join("\n");
const RISK_TYPE_ENTRY_TOOLTIPS = {
  stockout: [
    "断货预警：看 temp_lingxing_pici_sale 的 chazhi_0_N。",
    "0-45天内 chazhi 为负才计入当前断货；1-7天中等、8-14天高、15天以上严重。",
    "45天后才为负时只作为补货提示，需结合 FBA 可售、头程在途和补货窗口复核。",
  ].join("\n"),
  overstock: [
    "冗余库存：按销售属性区分爆旺和平滞。",
    "看可售天数1-6是否超过对应冗余阈值，并给出停止FBA补货、停止海外仓补货、停止本地仓补货或停止下采购单动作。",
    "同时叠加FBA库龄：61-180天预警、181-270天重点清货、271天以上批量清货。",
  ].join("\n"),
  anomaly: [
    "库存异常：看 fnsku_out_of_stock_risk_1 至 6。",
    "字段为空、数据缺失、none 或 null 时，说明底表风险标记不完整，需要复核库存明细和风险字段来源。",
  ].join("\n"),
  healthy: [
    "正常SKU：当前筛选口径下未命中断货、冗余或库存异常。",
    "仍会保留库存、销量、在途和头程信息，供日常监控使用。",
  ].join("\n"),
};
const DIMENSION_RISK_RULE_TOOLTIP = [
  "维度风险：按当前筛选后的风险SKU聚合。",
  "构成会拆成断货、冗余、异常，便于定位是哪个业务部分拉高风险。",
  "真实风险率用于维度对比：已进入实质处理状态的风险SKU / 维度总SKU。",
  "点击条目只加入筛选，不跳转SKU明细。",
].join("\n");
const ANOMALY_RULE_TOOLTIP = "库存异常判断：fnsku_out_of_stock_risk_1至6中出现空值、数据缺失、none或null时，需要复核底表风险标记、销量波动和库存明细差异。";
const AGE_RULE_TOOLTIP = [
  "库龄冗余：61-90天、91-180天为低风险预警监控。",
  "181-270天为中风险重点清货。",
  "271天以上为高风险批量清货。",
].join("\n");
const FORECAST_RULE_TOOLTIP = [
  "预测复盘：差值 = 实际销量 - 预测销量，差值比例 = 差值 / 预测销量。",
  "月度预测变化异常阈值30%，周销量偏差异常阈值20%。",
  "爆/旺销售偏差阈值20%，平/滞销售偏差阈值10%。",
].join("\n");
const SUPPLY_CONTROL_RULE_TOOLTIP = [
  "供货/控销：控销比例最高60%。",
  "加急空运第10天到，标准空运第20天到，快船第45天到，慢船第60天到。",
  "平滞口径从第61天后看慢船，截止第75天；爆旺前端模拟截止第90天。",
].join("\n");
const INVENTORY_STRUCTURE_RULE_TOOLTIP = "库存结构：总库存=FBA+海外仓+本地仓+备货；在途合计包含FBA接收/工作、海外/本地在途、仓库在途和计划量。";
const WARNING_TYPE_RULE_TOOLTIP = "提示字段会把命中的断货、冗余、异常预警拼接展示，未命中的无风险项不会写入。";
const AGE_ROW_RULE_TOOLTIPS = {
  "61-90天": "库龄61-90天且有库存时：低风险，预警监控。",
  "91-180天": "库龄91-180天且有库存时：低风险，预警监控。",
  "181-270天": "库龄181-270天且有库存时：中风险，重点清货。",
  "271-330天": "库龄271-330天且有库存时：高风险，批量清货。",
  "331-365天": "库龄331-365天且有库存时：高风险，批量清货。",
  "365天+": "库龄365天以上且有库存时：高风险，批量清货。",
};

function hasFeature(auth, feature) {
  const features = auth?.permissions?.features || [];
  return features.includes("*") || features.includes(feature);
}

function authDisplayName(auth) {
  return auth?.user?.name || auth?.user?.enterprise_email || auth?.user?.email || "飞书用户";
}
const KPI_RULE_TOOLTIPS = {
  "SKU 数": "当前筛选条件下的SKU总数。",
  "总库存": "总库存=FBA库存+海外仓库存+本地仓库存+备货。",
  "FBA 可售": "FBA前端可售库存，用于断货和覆盖天数判断。",
  "区间销量": "按当前销量开始/结束日期统计的销量。",
  "断货风险": STOCKOUT_RULE_TOOLTIP,
  "冗余风险": "冗余风险：命中可售天数冗余或库龄冗余规则的SKU数量。",
  "库销比": "库销比=总库存/30天需求，表示当前库存约等于多少个30天需求周期。",
};
const SEASONALITY_OPTIONS = [
  "四季款",
  "四季款（2-4月高峰期）",
  "四季款（7-8月高峰期）",
  "四季款（8月-9月）",
  "四季款（10-12月高峰期）",
  "季节性产品（3-9月）",
  "季节性产品（6月-8月）",
  "季节性产品（8月-10月）",
  "季节性产品（10月-2月）",
  "季节性产品（11月-2月）",
  "季节款（7-8月高峰期）",
  "季节款（独立日）",
  "节日款（万圣）",
  "节日款（圣诞）",
];
const MSKU_LIFE_PROCESS_OPTIONS = ["新品期", "非新品期"];
const OMITTED_FILTER_KEYS = new Set(["seller_id"]);
const FILTER_SUMMARY_ARRAY_FIELDS = [
  { key: "country_code", label: "国家" },
  { key: "shipments_country", label: "发货国家" },
  { key: "store_name", label: "店铺" },
  { key: "seasonality", label: "季节属性" },
  { key: "sales_department", label: "销售部门" },
  { key: "salesman", label: "销售员" },
  { key: "product_manager", label: "产品经理" },
  { key: "sales_property", label: "销售属性" },
  { key: "product_property", label: "产品属性" },
  { key: "msku_status", label: "MSKU状态" },
  { key: "msku_life_process", label: "生命周期" },
  { key: "risk_type", label: "风险类型" },
];
const FILTER_SUMMARY_TOGGLE_FIELDS = [
  { key: "risk_only", label: "只看风险" },
  { key: "positive_demand", label: "只看有需求" },
];

function createDefaultFilters() {
  const defaultDate = previousDate();
  return {
    material_code: "",
    country_code: [],
    shipments_country: [],
    store_name: [],
    seasonality: [],
    sales_department: [],
    salesman: [],
    product_manager: [],
    sales_property: [],
    product_property: [],
    msku_status: ["在售"],
    msku_life_process: [],
    risk_type: [],
    sales_start_date: defaultDate,
    sales_end_date: defaultDate,
    risk_only: false,
    positive_demand: false,
  };
}

function activeFilterCount(filters) {
  const defaults = createDefaultFilters();
  const textKeys = [
    "material_code",
    "country_code",
    "shipments_country",
    "store_name",
    "seasonality",
    "sales_department",
    "salesman",
    "product_manager",
    "sales_property",
    "product_property",
    "msku_status",
    "msku_life_process",
    "risk_type",
  ];
  const textCount = textKeys.filter((key) => filterValueKey(filters[key]) !== filterValueKey(defaults[key])).length;
  const toggleCount = Number(Boolean(filters.risk_only) !== Boolean(defaults.risk_only)) + Number(Boolean(filters.positive_demand) !== Boolean(defaults.positive_demand));
  const dateCount = filters.sales_start_date !== defaults.sales_start_date || filters.sales_end_date !== defaults.sales_end_date ? 1 : 0;
  return textCount + toggleCount + dateCount;
}

function optionValuesWithSelected(options, selectedValue) {
  const values = new Set((options || []).filter(Boolean));
  selectedValues(selectedValue).forEach((value) => values.add(value));
  return Array.from(values).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}

function optionValuesWithDefaults(defaultOptions, options, selectedValue) {
  const defaultValues = (defaultOptions || []).filter(Boolean);
  const seen = new Set(defaultValues);
  const extraValues = [...(options || []), ...selectedValues(selectedValue)].filter(Boolean).filter((value) => {
    if (seen.has(value)) return false;
    seen.add(value);
    return true;
  });
  return [...defaultValues, ...extraValues.sort((left, right) => left.localeCompare(right, "zh-Hans-CN"))];
}

function optionValuesFromItems(items, fieldName) {
  const values = new Set();
  (items || []).forEach((item) => {
    const rawValue = item?.[fieldName];
    selectedValues(Array.isArray(rawValue) ? rawValue : [rawValue]).forEach((value) => values.add(value));
  });
  return Array.from(values).sort((left, right) => left.localeCompare(right, "zh-Hans-CN"));
}

function appendActiveFilters(params, targetFilters) {
  Object.entries(targetFilters || {}).forEach(([key, value]) => {
    if (OMITTED_FILTER_KEYS.has(key)) return;
    if (Array.isArray(value)) {
      value.filter((item) => item !== "" && item !== null && item !== undefined).forEach((item) => {
        params.append(key, item);
      });
    } else if (value !== "" && value !== false && value !== null && value !== undefined) {
      params.set(key, value);
    }
  });
}

function selectedValues(value) {
  if (Array.isArray(value)) return value.filter((item) => item !== "" && item !== null && item !== undefined).map(String);
  if (value === "" || value === null || value === undefined) return [];
  return [String(value)];
}

function firstSelectedValue(value) {
  return selectedValues(value)[0] || "";
}

function nextSelectedValues(currentValue, optionValue, checked) {
  const current = selectedValues(currentValue);
  if (checked) return current.includes(optionValue) ? current : [...current, optionValue];
  return current.filter((value) => value !== optionValue);
}

function filterValueKey(value) {
  if (Array.isArray(value)) return selectedValues(value).sort((left, right) => left.localeCompare(right, "zh-Hans-CN")).join("|");
  return String(value ?? "");
}

function filterSummaryValueLabel(key, value) {
  if (key === "risk_type") return RISK_TYPE_OPTIONS.find((option) => option.value === value)?.label || riskTypeLabels[value] || value;
  return value;
}

function buildFilterSummaryChips(filters) {
  const defaults = createDefaultFilters();
  const chips = [];
  const materialCode = String(filters.material_code || "").trim();
  if (materialCode && materialCode !== String(defaults.material_code || "")) {
    chips.push({
      id: "material_code",
      mode: "field",
      key: "material_code",
      label: "SKU",
      valueLabel: materialCode,
    });
  }
  FILTER_SUMMARY_ARRAY_FIELDS.forEach(({ key, label }) => {
    if (filterValueKey(filters[key]) === filterValueKey(defaults[key])) return;
    const values = selectedValues(filters[key]);
    if (!values.length) {
      chips.push({
        id: `${key}:__empty__`,
        mode: "field",
        key,
        label,
        valueLabel: "全部",
      });
      return;
    }
    values.forEach((value) => {
      chips.push({
        id: `${key}:${value}`,
        mode: "array-value",
        key,
        value,
        label,
        valueLabel: filterSummaryValueLabel(key, value),
      });
    });
  });
  if (filters.sales_start_date !== defaults.sales_start_date || filters.sales_end_date !== defaults.sales_end_date) {
    chips.push({
      id: "sales_period",
      mode: "date-range",
      label: "销量区间",
      valueLabel: `${filters.sales_start_date || "-"} 至 ${filters.sales_end_date || "-"}`,
    });
  }
  FILTER_SUMMARY_TOGGLE_FIELDS.forEach(({ key, label }) => {
    if (Boolean(filters[key]) === Boolean(defaults[key])) return;
    chips.push({
      id: key,
      mode: "toggle",
      key,
      label,
      valueLabel: "已开启",
    });
  });
  return chips;
}

function App() {
  const [theme, setTheme] = useState(() => initialTheme());
  const [auth, setAuth] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [skuInvestigationExporting, setSkuInvestigationExporting] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [activeSkuItem, setActiveSkuItem] = useState(null);
  const [activeWorkspace, setActiveWorkspace] = useState("overview");
  const [activeWarehouseStage, setActiveWarehouseStage] = useState("local");
  const pageSize = 100;
  const [filters, setFilters] = useState(() => createDefaultFilters());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const loadAuth = async () => {
    setAuthLoading(true);
    try {
      const response = await apiFetch(`${API_BASE_URL}/auth/me`);
      if (!response.ok) throw new Error(`AUTH ${response.status}`);
      setAuth(await response.json());
    } catch (err) {
      setAuth({ authenticated: false, auth_required: false, permissions: { features: ["*"], all_data: true }, user: {} });
    } finally {
      setAuthLoading(false);
    }
  };

  const loginWithFeishu = () => {
    window.location.href = `${API_BASE_URL}/auth/feishu/login?next=${encodeURIComponent(window.location.href)}`;
  };

  const logout = async () => {
    await apiFetch(`${API_BASE_URL}/auth/logout`, { method: "POST" });
    setSummary(null);
    await loadAuth();
  };

  const loadSummary = async (targetPage = page, targetFilters = filters, options = {}) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      appendActiveFilters(params, targetFilters);
      params.set("page", String(targetPage));
      params.set("page_size", String(pageSize));
      params.set("max_rows", "20000");
      if (options.refresh) params.set("refresh", "true");
      const response = await apiFetch(`${API_BASE_URL}/control-tower/summary?${params.toString()}`);
      if (response.status === 401) {
        await loadAuth();
        throw new Error("请先通过飞书登录");
      }
      if (response.status === 403) throw new Error("当前账号没有查看控制塔的权限");
      if (!response.ok) throw new Error(`API ${response.status}`);
      const payload = await response.json();
      setSummary(payload);
      setPage(payload.pagination?.page || targetPage);
    } catch (err) {
      setError(err instanceof Error ? err.message : "控制塔数据加载失败");
    } finally {
      setLoading(false);
    }
  };

  const downloadSkuInvestigationExcel = async () => {
    setSkuInvestigationExporting(true);
    setError("");
    try {
      const params = new URLSearchParams();
      appendActiveFilters(params, filters);
      params.set("max_rows", "20000");
      const response = await apiFetch(`${API_BASE_URL}/control-tower/export/sku-investigation?${params.toString()}`);
      if (response.status === 403) throw new Error("当前账号没有导出权限");
      if (!response.ok) throw new Error(`导出失败 ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1];
      const fallbackName = disposition.match(/filename="?([^";]+)"?/)?.[1];
      const filename = encodedName
        ? decodeURIComponent(encodedName)
        : fallbackName || `当前SKU明细排查_${previousDate()}.xlsx`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "SKU明细排查导出失败");
    } finally {
      setSkuInvestigationExporting(false);
    }
  };

  useEffect(() => {
    loadAuth();
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (auth?.auth_required && !auth?.authenticated) {
      setLoading(false);
      return;
    }
    loadSummary(1);
  }, [authLoading, auth?.authenticated, auth?.auth_required]);

  const filteredItems = useMemo(() => {
    if (!summary?.items) return [];
    return summary.items;
  }, [summary]);
  const countryOptions = useMemo(
    () => optionValuesWithDefaults(COMMON_COUNTRY_OPTIONS, summary?.filter_options?.country_code, filters.country_code),
    [summary?.filter_options?.country_code, filters.country_code]
  );
  const mskuStatusOptions = useMemo(
    () => optionValuesWithDefaults(MSKU_STATUS_OPTIONS, summary?.filter_options?.msku_status, filters.msku_status),
    [summary?.filter_options?.msku_status, filters.msku_status]
  );
  const hasActiveDetailFilter = useMemo(() => {
    const defaults = createDefaultFilters();
    const keys = [
      "material_code",
      "country_code",
      "shipments_country",
      "store_name",
      "seasonality",
      "sales_department",
      "salesman",
      "product_manager",
      "sales_property",
      "product_property",
      "msku_status",
      "msku_life_process",
      "risk_type",
    ];
    return keys.some((key) => filterValueKey(filters[key]) !== filterValueKey(defaults[key]))
      || Boolean(filters.risk_only) !== Boolean(defaults.risk_only)
      || Boolean(filters.positive_demand) !== Boolean(defaults.positive_demand);
  }, [filters]);
  const filterCount = useMemo(() => activeFilterCount(filters), [filters]);
  const filterSummaryChips = useMemo(() => buildFilterSummaryChips(filters), [filters]);
  const riskTotal = useMemo(() => {
    const distribution = summary?.risk_type_distribution || {};
    return ["stockout", "overstock", "anomaly"].reduce((total, key) => total + Number(distribution[key] || 0), 0);
  }, [summary]);
  const workspaceTabs = useMemo(() => {
    const tabs = [
      { id: "overview", feature: "overview", label: "风险总览", meta: `${formatNumber(riskTotal)} 风险`, icon: Gauge },
      { id: "detail", feature: "detail", label: "SKU 明细", meta: `${formatNumber(summary?.pagination?.total_count ?? filteredItems.length)} 行`, icon: Boxes },
      { id: "warehouse", feature: "warehouse", label: "仓库明细", meta: "库存", icon: Warehouse },
      { id: "standards", feature: "standards", label: "字段口径", meta: `${formatNumber(summary?.field_decisions?.length || 0)} 字段`, icon: Database },
    ];
    return tabs.filter((tab) => hasFeature(auth, tab.feature));
  }, [auth, filteredItems.length, riskTotal, summary?.field_decisions?.length, summary?.pagination?.total_count]);
  useEffect(() => {
    if (!workspaceTabs.some((tab) => tab.id === activeWorkspace)) {
      setActiveWorkspace("overview");
    }
  }, [activeWorkspace, workspaceTabs]);

  const applySalesPeriod = (nextDates) => {
    const nextFilters = { ...filters, ...nextDates };
    setFilters(nextFilters);
    setPage(1);
    loadSummary(1, nextFilters);
  };

  const applyFilters = (nextFilters) => {
    setFilters(nextFilters);
    setPage(1);
    loadSummary(1, nextFilters);
  };

  const removeFilterChip = (chip) => {
    const defaults = createDefaultFilters();
    const nextFilters = { ...filters };
    if (chip.mode === "array-value") {
      const nextValues = selectedValues(filters[chip.key]).filter((value) => value !== chip.value);
      nextFilters[chip.key] = nextValues.length || !selectedValues(defaults[chip.key]).length ? nextValues : defaults[chip.key];
    } else if (chip.mode === "date-range") {
      nextFilters.sales_start_date = defaults.sales_start_date;
      nextFilters.sales_end_date = defaults.sales_end_date;
    } else if (chip.key) {
      nextFilters[chip.key] = defaults[chip.key];
    }
    applyFilters(nextFilters);
  };

  const drillIntoRiskDimension = (fieldName, entry) => {
    if (!entry?.key || entry.disabled || entry.key === "__blank__") return;
    const nextFilters = { ...filters, [fieldName]: [entry.key], risk_only: true };
    setFilters(nextFilters);
    setPage(1);
    loadSummary(1, nextFilters);
  };

  const drillIntoRiskType = (entry) => {
    if (!entry?.key || entry.disabled) return;
    const nextFilters = {
      ...filters,
      risk_type: [entry.key],
      risk_only: entry.key !== "healthy",
    };
    setFilters(nextFilters);
    setPage(1);
    loadSummary(1, nextFilters);
  };
  const openWarehouseDetail = (stage) => {
    setActiveWarehouseStage(stage);
    setActiveWorkspace("warehouse");
  };

  if (authLoading) {
    return (
      <main className="app-shell">
        <section className="loading-panel">正在校验飞书登录状态...</section>
      </main>
    );
  }

  if (auth?.auth_required && !auth?.authenticated) {
    return (
      <main className="app-shell">
        <section className="login-panel">
          <div>
            <div className="eyebrow">PMC Inventory Control Tower</div>
            <h1>库存控制塔</h1>
            <p>请使用飞书授权进入。</p>
          </div>
          <button className="primary-button" onClick={loginWithFeishu}>
            <LogIn size={16} />
            <span>飞书登录</span>
          </button>
        </section>
      </main>
    );
  }

  return (
    <>
    <main className="app-shell">
      <section className="topbar">
        <div>
          <div className="eyebrow">PMC Inventory Control Tower</div>
          <h1>库存控制塔</h1>
        </div>
        <div className="topbar-actions">
          <button
            className="theme-toggle-button"
            type="button"
            onClick={() => setTheme((current) => (current === "light" ? "dark" : "light"))}
            title={theme === "light" ? "切换为深色控制塔风格" : "切换为白底简约风格"}
            aria-label={theme === "light" ? "切换为深色控制塔风格" : "切换为白底简约风格"}
          >
            {theme === "light" ? <Moon size={16} /> : <Sun size={16} />}
            <span>{theme === "light" ? "深色" : "白底"}</span>
          </button>
          {auth?.authenticated && (
            <span className="user-pill" title={auth?.permissions?.role || ""}>
              <UserRound size={15} />
              <span>{authDisplayName(auth)}</span>
              <em>{auth?.permissions?.role || "member"}</em>
            </span>
          )}
          {hasFeature(auth, "export") && (
            <button className="primary-button" onClick={downloadSkuInvestigationExcel} disabled={skuInvestigationExporting}>
              <Download size={16} />
              <span>{skuInvestigationExporting ? "导出中" : "SKU排查"}</span>
            </button>
          )}
          <button className="primary-button" onClick={() => loadSummary(page, filters, { refresh: true })} disabled={loading}>
            <RefreshCw size={16} />
            <span>{loading ? "刷新中" : "刷新"}</span>
          </button>
          {auth?.authenticated && (
            <button className="ghost-icon-button" type="button" onClick={logout} title="退出登录" aria-label="退出登录">
              <LogOut size={16} />
            </button>
          )}
        </div>
      </section>

      <section className="toolbar" aria-label="控制塔筛选器">
        <div className="filter-summary-wrap" aria-label="筛选条件汇总">
          <Filter size={16} />
          <div className="filter-summary-scroll">
            {filterSummaryChips.length ? (
              filterSummaryChips.map((chip) => (
                <span className="filter-summary-chip" key={chip.id} title={`${chip.label}: ${chip.valueLabel}`}>
                  <span className="filter-summary-chip-text">
                    <b>{chip.label}</b>
                    <em>{chip.valueLabel}</em>
                  </span>
                  <button type="button" onClick={() => removeFilterChip(chip)} aria-label={`移除${chip.label}${chip.valueLabel}`}>
                    <X size={12} />
                  </button>
                </span>
              ))
            ) : (
              <span className="filter-summary-empty">暂无额外筛选条件</span>
            )}
          </div>
        </div>
        <label className="input-wrap">
          <Filter size={16} />
          <select
            value={firstSelectedValue(filters.country_code)}
            onChange={(event) => setFilters({ ...filters, country_code: event.target.value ? [event.target.value] : [] })}
            aria-label="国家"
          >
            <option value="">全部国家</option>
            {countryOptions.map((option) => (
              <option value={option} key={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label className="input-wrap">
          <CheckCircle2 size={16} />
          <select
            value={firstSelectedValue(filters.msku_status)}
            onChange={(event) => setFilters({ ...filters, msku_status: event.target.value ? [event.target.value] : [] })}
            aria-label="MSKU状态"
          >
            <option value="">MSKU状态</option>
            {mskuStatusOptions.map((option) => (
              <option value={option} key={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <select
          value={firstSelectedValue(filters.sales_property)}
          onChange={(event) => setFilters({ ...filters, sales_property: event.target.value ? [event.target.value] : [] })}
          aria-label="销售属性"
        >
          <option value="">全部属性</option>
          {SALES_PROPERTY_OPTIONS.map((option) => (
            <option value={option} key={option}>{option}</option>
          ))}
        </select>
        <select
          value={firstSelectedValue(filters.risk_type)}
          onChange={(event) => setFilters({ ...filters, risk_type: event.target.value ? [event.target.value] : [] })}
          aria-label="风险类型"
        >
          <option value="">全部风险类型</option>
          {RISK_TYPE_OPTIONS.map((option) => (
            <option value={option.value} key={option.value}>{option.label}</option>
          ))}
        </select>
        <label className="toggle">
          <input
            type="checkbox"
            checked={filters.risk_only}
            onChange={(event) => setFilters({ ...filters, risk_only: event.target.checked })}
          />
          <span>只看风险</span>
        </label>
        <button
          className="ghost-button"
          onClick={() => {
            setPage(1);
            loadSummary(1);
          }}
        >
          应用
        </button>
      </section>

      {error && (
        <section className="notice error">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </section>
      )}

      {loading && !summary ? (
        <section className="loading-panel">正在读取库存控制塔...</section>
      ) : (
        summary && (
          <>
            <ControlWorkspaceNav tabs={workspaceTabs} activeView={activeWorkspace} onChange={setActiveWorkspace} />
            {activeWorkspace === "overview" && (
              <section className="workspace-view overview-view">
                <KpiGrid summary={summary} />
                <InventoryFlowPanel
                  summary={summary}
                  items={filteredItems}
                  loading={loading}
                  selectedStage={activeWarehouseStage}
                  onStageSelect={openWarehouseDetail}
                />
                <RiskOverview
                  summary={summary}
                  onRiskTypeSelect={drillIntoRiskType}
                  onDimensionSelect={drillIntoRiskDimension}
                />
              </section>
            )}
            {activeWorkspace === "detail" && (
              <section className="workspace-view detail-view">
                <InventoryTable
                  items={filteredItems}
                  pagination={summary.pagination}
                  showSkuColumn={hasActiveDetailFilter}
                  filters={filters}
                  activeFilterCount={filterCount}
                  filterOptions={summary.filter_options || {}}
                  salesPeriod={formatSalesPeriod(filters.sales_start_date, filters.sales_end_date) || summary.sales_stat_date}
                  salesStartDate={filters.sales_start_date}
                  salesEndDate={filters.sales_end_date}
                  loading={loading}
                  onSalesPeriodChange={(nextDates) => setFilters({ ...filters, ...nextDates })}
                  onSalesPeriodApply={() => {
                    setPage(1);
                    loadSummary(1);
                  }}
                  onSalesPreset={applySalesPeriod}
                  onPageChange={(nextPage) => {
                    setPage(nextPage);
                    loadSummary(nextPage);
                  }}
                  onFiltersApply={applyFilters}
                  onOpenItem={setActiveSkuItem}
                />
              </section>
            )}
            {activeWorkspace === "warehouse" && (
              <section className="workspace-view warehouse-detail-view">
                <WarehouseDetailPanel
                  summary={summary}
                  activeStage={activeWarehouseStage}
                  onStageChange={setActiveWarehouseStage}
                />
              </section>
            )}
            {activeWorkspace === "standards" && (
              <section className="workspace-view standards-view">
                <SourcePanel summary={summary} />
                <FieldDecisionTable fields={summary.field_decisions} />
              </section>
            )}
          </>
        )
      )}
    </main>
    {activeSkuItem && <ActionDetailDialog item={activeSkuItem} onClose={() => setActiveSkuItem(null)} />}
    </>
  );
}

function ControlWorkspaceNav({ tabs, activeView, onChange }) {
  return (
    <nav className="workspace-nav" aria-label="控制塔工作台">
      {tabs.map((tab) => {
        const Icon = tab.icon;
        return (
          <button
            type="button"
            className={`workspace-tab ${activeView === tab.id ? "active" : ""}`}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            aria-current={activeView === tab.id ? "page" : undefined}
          >
            <Icon size={17} />
            <span>{tab.label}</span>
            <small>{tab.meta}</small>
          </button>
        );
      })}
    </nav>
  );
}

function KpiGrid({ summary }) {
  const kpis = summary.kpis || {};
  const cards = [
    { label: "SKU 数", value: kpis.sku_count, icon: Boxes, tone: "neutral" },
    { label: "总库存", value: formatNumber(kpis.total_inventory), icon: Layers3, tone: "neutral" },
    { label: "FBA 可售", value: formatNumber(kpis.fba_sellable), icon: Warehouse, tone: "neutral" },
    { label: "区间销量", value: formatNumber(kpis.daily_sales_volume), icon: Gauge, tone: "neutral" },
    { label: "断货风险", value: kpis.stockout_count, icon: ShieldAlert, tone: "danger" },
    { label: "库销比", value: formatInventorySalesRatio(kpis.total_inventory, kpis.demand_30d), icon: BarChart3, tone: "warn" },
  ];
  return (
    <section className="kpi-grid">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <article className={`kpi-card ${card.tone}`} key={card.label} title={KPI_RULE_TOOLTIPS[card.label] || undefined}>
            <div className="kpi-icon">
              <Icon size={19} />
            </div>
            <div>
              <div className="kpi-label">{card.label}</div>
              <strong>{card.value ?? "-"}</strong>
            </div>
          </article>
        );
      })}
    </section>
  );
}

function RiskOverview({ summary, onRiskTypeSelect, onDimensionSelect }) {
  const [activeRanking, setActiveRanking] = useState(null);
  const dimensions = summary.risk_dimensions || {};
  const riskLevelEntries = distributionPieEntries(summary.risk_distribution, riskLabels);
  const riskTypeEntries = distributionPieEntries(summary.risk_type_distribution, riskTypeLabels);
  const countryEntries = dimensionPieEntries(dimensions.country_code, {}, COMMON_COUNTRY_OPTIONS);
  const storeEntries = dimensionPieEntries(dimensions.store_name);
  const departmentEntries = dimensionPieEntries(dimensions.sales_department);
  const salesmanEntries = dimensionPieEntries(dimensions.salesman);
  const salesPropertyEntries = dimensionPieEntries(dimensions.sales_property, salesPropertyLabels, SALES_PROPERTY_OPTIONS);
  const seasonalityEntries = dimensionPieEntries(dimensions.seasonality, {}, SEASONALITY_OPTIONS);
  const countryRankingEntries = dimensionRankingEntries(dimensions.country_code);
  const storeRankingEntries = dimensionRankingEntries(dimensions.store_name);
  const departmentRankingEntries = dimensionRankingEntries(dimensions.sales_department);
  const salesmanRankingEntries = dimensionRankingEntries(dimensions.salesman);
  const salesPropertyRankingEntries = dimensionRankingEntries(dimensions.sales_property, salesPropertyLabels);
  const seasonalityRankingEntries = dimensionRankingEntries(dimensions.seasonality);
  const openRanking = (ranking) => {
    setActiveRanking({
      ...ranking,
      entries: (ranking.entries || []).filter((entry) => Number(entry.value || 0) > 0),
    });
  };
  const openDimensionRanking = (title, entries, fieldName, ruleTooltip = DIMENSION_RISK_RULE_TOOLTIP) => {
    openRanking({
      title: `${title}排名`,
      eyebrow: title,
      subtitle: "按风险 SKU 数降序",
      entries,
      showRiskMix: true,
      ruleTooltip,
      onEntrySelect: (entry) => onDimensionSelect(fieldName, entry),
    });
  };

  return (
    <>
      <section className="dashboard-grid risk-dashboard-grid">
        <RiskPieCard
          title="风险等级"
          entries={riskLevelEntries}
          centerLabel="SKU"
          ruleTooltip={RISK_LEVEL_RULE_TOOLTIP}
          onRankingOpen={() =>
            openRanking({
              title: "风险等级排名",
              eyebrow: "风险等级",
              subtitle: "按处理等级 SKU 数排序",
              entries: riskLevelEntries,
              ruleTooltip: RISK_LEVEL_RULE_TOOLTIP,
            })
          }
        />
        <RiskPieCard
          title="风险类型"
          entries={riskTypeEntries}
          centerLabel="SKU"
          ruleTooltip={RISK_TYPE_RULE_TOOLTIP}
          onEntrySelect={onRiskTypeSelect}
          onRankingOpen={() =>
            openRanking({
              title: "风险类型排名",
              eyebrow: "风险类型",
              subtitle: "按断货、冗余、异常风险 SKU 数排序",
              entries: riskTypeEntries,
              ruleTooltip: RISK_TYPE_RULE_TOOLTIP,
              onEntrySelect: onRiskTypeSelect,
            })
          }
        />
      </section>
      <section className="dashboard-grid risk-dimension-grid">
        <RiskPieCard
          title="国家风险"
          entries={countryEntries}
          centerLabel="风险SKU"
          ruleTooltip={DIMENSION_RISK_RULE_TOOLTIP}
          onEntrySelect={(entry) => onDimensionSelect("country_code", entry)}
          onRankingOpen={() => openDimensionRanking("国家风险", countryRankingEntries, "country_code")}
          showRiskMix
        />
        <RiskPieCard
          title="店铺风险"
          entries={storeEntries}
          centerLabel="风险SKU"
          ruleTooltip={DIMENSION_RISK_RULE_TOOLTIP}
          onEntrySelect={(entry) => onDimensionSelect("store_name", entry)}
          onRankingOpen={() => openDimensionRanking("店铺风险", storeRankingEntries, "store_name")}
          showRiskMix
        />
        <RiskPieCard
          title="部门风险"
          entries={departmentEntries}
          centerLabel="风险SKU"
          ruleTooltip={DIMENSION_RISK_RULE_TOOLTIP}
          onEntrySelect={(entry) => onDimensionSelect("sales_department", entry)}
          onRankingOpen={() => openDimensionRanking("部门风险", departmentRankingEntries, "sales_department")}
          showRiskMix
        />
        <RiskPieCard
          title="人员风险"
          entries={salesmanEntries}
          centerLabel="风险SKU"
          ruleTooltip={DIMENSION_RISK_RULE_TOOLTIP}
          onEntrySelect={(entry) => onDimensionSelect("salesman", entry)}
          onRankingOpen={() => openDimensionRanking("人员风险", salesmanRankingEntries, "salesman")}
          showRiskMix
        />
        <RiskPieCard
          title="爆旺平滞风险"
          entries={salesPropertyEntries}
          centerLabel="风险SKU"
          ruleTooltip={`${DIMENSION_RISK_RULE_TOOLTIP}\n${formatOverstockRuleHintText("爆")}\n${formatOverstockRuleHintText("平")}`}
          onEntrySelect={(entry) => onDimensionSelect("sales_property", entry)}
          onRankingOpen={() =>
            openDimensionRanking(
              "爆旺平滞风险",
              salesPropertyRankingEntries,
              "sales_property",
              `${DIMENSION_RISK_RULE_TOOLTIP}\n${formatOverstockRuleHintText("爆")}\n${formatOverstockRuleHintText("平")}`,
            )
          }
          showRiskMix
        />
        <RiskPieCard
          title="季节属性风险"
          entries={seasonalityEntries}
          centerLabel="风险SKU"
          ruleTooltip={DIMENSION_RISK_RULE_TOOLTIP}
          onEntrySelect={(entry) => onDimensionSelect("seasonality", entry)}
          onRankingOpen={() => openDimensionRanking("季节属性风险", seasonalityRankingEntries, "seasonality")}
          showRiskMix
        />
      </section>
      {activeRanking && <RiskRankingDialog ranking={activeRanking} onClose={() => setActiveRanking(null)} />}
    </>
  );
}

function RiskPieCard({ title, entries, centerLabel = "风险", onEntrySelect, onRankingOpen, showRiskMix = false, ruleTooltip = "" }) {
  const cleanEntries = (entries || []).filter((entry) => Number(entry.value || 0) > 0);
  const total = cleanEntries.reduce((sum, entry) => sum + Number(entry.value || 0), 0);
  const arcs = useMemo(() => {
    if (!total) return [];
    return d3
      .pie()
      .sort(null)
      .value((entry) => Number(entry.value || 0))(cleanEntries);
  }, [cleanEntries, total]);
  const arcPath = useMemo(() => d3.arc().innerRadius(44).outerRadius(70).cornerRadius(3), []);
  const percentOfTotal = (value) => (total ? Number(value || 0) / total : 0);

  return (
    <section className="panel risk-pie-panel">
      <div className="panel-title">
        <AlertTriangle size={17} />
        <h2 title={ruleTooltip || undefined}>{title}</h2>
        {onRankingOpen && (
          <button
            type="button"
            className="risk-rank-button"
            onClick={onRankingOpen}
            disabled={!total}
            title={[`${title}排名`, ruleTooltip].filter(Boolean).join("\n")}
            aria-label={`${title}排名`}
          >
            <BarChart3 size={16} />
          </button>
        )}
      </div>
      {total ? (
        <div className="risk-pie-body">
          <svg className="risk-pie-svg" viewBox="0 0 184 184" role="img" aria-label={`${title}饼图`}>
            <g transform="translate(92 92)">
              {arcs.map((arc, index) => {
                const entry = arc.data;
                return (
                  <path
                    key={entry.key}
                    d={arcPath(arc)}
                    fill={riskChartColor(entry, index)}
                    className={`risk-pie-slice ${onEntrySelect && !entry.disabled ? "clickable" : ""} ${entry.disabled ? "disabled" : ""}`}
                    onClick={() => {
                      if (!entry.disabled) onEntrySelect?.(entry);
                    }}
                  >
                    <title>{riskPieEntryTooltip(title, entry, percentOfTotal(entry.value), showRiskMix, ruleTooltip)}</title>
                  </path>
                );
              })}
              <circle r="35" className="risk-pie-center" />
              <text className="risk-pie-total" textAnchor="middle" y="-3">{formatNumber(total)}</text>
              <text className="risk-pie-label" textAnchor="middle" y="17">{centerLabel}</text>
            </g>
          </svg>
          <div className="risk-pie-legend">
            {cleanEntries.map((entry, index) => {
              const clickable = Boolean(onEntrySelect) && !entry.disabled;
              const LegendTag = clickable ? "button" : "div";
              return (
                <LegendTag
                  type={clickable ? "button" : undefined}
                  className={`risk-pie-legend-row ${clickable ? "clickable" : ""}`}
                  key={entry.key}
                  title={riskPieEntryTooltip(title, entry, percentOfTotal(entry.value), showRiskMix, ruleTooltip)}
                  onClick={clickable ? () => onEntrySelect(entry) : undefined}
                >
                  <span className="risk-pie-swatch" style={{ background: riskChartColor(entry, index) }} />
                  <span className="risk-pie-name">{entry.label}</span>
                  <strong>{formatNumber(entry.value)}</strong>
                  <small>{formatRatioPercent(percentOfTotal(entry.value))}</small>
                  {showRiskMix && (
                    <em>
                      断 {formatNumber(entry.stockoutCount || 0)} / 冗 {formatNumber(entry.overstockCount || 0)}
                    </em>
                  )}
                </LegendTag>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="risk-pie-empty">暂无风险分布</div>
      )}
    </section>
  );
}

function RiskRankingDialog({ ranking, onClose }) {
  if (typeof document === "undefined") return null;
  const entries = ranking.entries || [];
  const total = entries.reduce((sum, entry) => sum + Number(entry.value || 0), 0);
  const maxValue = Math.max(...entries.map((entry) => Number(entry.value || 0)), 1);
  const topEntry = entries[0];
  const ruleTooltip = ranking.ruleTooltip || "";

  return createPortal(
    <div className="risk-rank-backdrop" role="presentation" onClick={onClose}>
      <section className="risk-rank-dialog" role="dialog" aria-modal="true" aria-label={ranking.title} onClick={(event) => event.stopPropagation()}>
        <div className="risk-rank-head">
          <div>
            <span>{ranking.eyebrow || "风险排名"}</span>
            <strong>{ranking.title}</strong>
            <p title={ruleTooltip || undefined}>{ranking.subtitle || "按风险 SKU 数降序"}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭排名">
            <X size={18} />
          </button>
        </div>
        <div className="risk-rank-body">
          <div className="risk-rank-summary">
            <div>
              <span>排名项</span>
              <strong>{formatNumber(entries.length)}</strong>
            </div>
            <div>
              <span>风险SKU</span>
              <strong>{formatNumber(total)}</strong>
            </div>
            <div>
              <span>最多风险项</span>
              <strong>{topEntry ? `${topEntry.label} ${formatNumber(topEntry.value)}` : "-"}</strong>
            </div>
          </div>
          {entries.length ? (
            <div className="risk-rank-bars">
              {entries.map((entry, index) => {
                const value = Number(entry.value || 0);
                const canDrill = Boolean(ranking.onEntrySelect) && !entry.disabled;
                const RowTag = canDrill ? "button" : "div";
                const width = maxValue ? Math.max(5, (value / maxValue) * 100) : 0;
                const detailText = riskRankingDetailText(entry, ranking.showRiskMix);
                return (
                  <RowTag
                    type={canDrill ? "button" : undefined}
                    className={`risk-rank-row ${canDrill ? "clickable" : ""}`}
                    key={entry.key || `${entry.label}-${index}`}
                    title={riskPieEntryTooltip(ranking.eyebrow || ranking.title, entry, total ? value / total : 0, ranking.showRiskMix, ruleTooltip)}
                    onClick={
                      canDrill
                        ? () => {
                            onClose();
                            ranking.onEntrySelect(entry);
                          }
                        : undefined
                    }
                  >
                    <span className="risk-rank-index">{String(index + 1).padStart(2, "0")}</span>
                    <span className="risk-rank-name">
                      <i style={{ background: riskChartColor(entry, index) }} />
                      <span>{entry.label}</span>
                    </span>
                    <span className="risk-rank-track" aria-hidden="true">
                      <span className="risk-rank-fill" style={{ width: `${width}%`, background: riskChartColor(entry, index) }} />
                    </span>
                    <strong>{formatNumber(value)}</strong>
                    <small>{formatRatioPercent(total ? value / total : 0)}</small>
                    {detailText && <em>{detailText}</em>}
                  </RowTag>
                );
              })}
            </div>
          ) : (
            <div className="risk-rank-empty">暂无排名数据</div>
          )}
        </div>
      </section>
    </div>,
    document.body,
  );
}

function distributionPieEntries(data, labels = {}) {
  const order = ["critical", "high", "medium", "low", "normal", "stockout", "overstock", "anomaly", "healthy"];
  return Object.entries(data || {})
    .map(([key, value]) => ({
      key,
      label: labels[key] || key,
      value: Number(value || 0),
      totalCount: Number(value || 0),
    }))
    .filter((entry) => entry.value > 0)
    .sort((left, right) => {
      const leftRank = order.includes(left.key) ? order.indexOf(left.key) : 99;
      const rightRank = order.includes(right.key) ? order.indexOf(right.key) : 99;
      return leftRank - rightRank || right.value - left.value;
    });
}

function dimensionEntries(slices = [], labels = {}) {
  return (slices || [])
    .map((slice) => ({
      key: slice.key,
      label: labels[slice.key] || slice.label || slice.key,
      value: Number(slice.risk_count || 0),
      totalCount: Number(slice.total_count || 0),
      riskRate: Number(slice.risk_rate || 0),
      stockoutCount: Number(slice.stockout_count || 0),
      overstockCount: Number(slice.overstock_count || 0),
      anomalyCount: Number(slice.anomaly_count || 0),
      criticalCount: Number(slice.critical_count || 0),
      highCount: Number(slice.high_count || 0),
      mediumCount: Number(slice.medium_count || 0),
      lowCount: Number(slice.low_count || 0),
      normalCount: Number(slice.normal_count || 0),
      disabled: slice.key === "__blank__",
    }))
    .filter((entry) => entry.value > 0);
}

function dimensionPieEntries(slices = [], labels = {}, preferredOrder = []) {
  const orderIndex = new Map((preferredOrder || []).map((key, index) => [key, index]));
  const entries = dimensionEntries(slices, labels).sort((left, right) => {
    const leftRank = orderIndex.has(left.key) ? orderIndex.get(left.key) : 99;
    const rightRank = orderIndex.has(right.key) ? orderIndex.get(right.key) : 99;
    return leftRank - rightRank || right.value - left.value || String(left.label || "").localeCompare(String(right.label || ""), "zh-CN");
  });
  return compactPieEntries(entries, 7);
}

function dimensionRankingEntries(slices = [], labels = {}) {
  return dimensionEntries(slices, labels).sort((left, right) => {
    const valueRank = right.value - left.value;
    if (valueRank) return valueRank;
    return String(left.label || "").localeCompare(String(right.label || ""), "zh-CN");
  });
}

function compactPieEntries(entries, limit) {
  if (entries.length <= limit) return entries;
  const head = entries.slice(0, Math.max(limit - 1, 1));
  const tail = entries.slice(head.length);
  return [
    ...head,
    {
      key: "__other__",
      label: "其他",
      value: sumEntryField(tail, "value"),
      totalCount: sumEntryField(tail, "totalCount"),
      riskRate: 0,
      stockoutCount: sumEntryField(tail, "stockoutCount"),
      overstockCount: sumEntryField(tail, "overstockCount"),
      anomalyCount: sumEntryField(tail, "anomalyCount"),
      criticalCount: sumEntryField(tail, "criticalCount"),
      highCount: sumEntryField(tail, "highCount"),
      mediumCount: sumEntryField(tail, "mediumCount"),
      lowCount: sumEntryField(tail, "lowCount"),
      normalCount: sumEntryField(tail, "normalCount"),
      disabled: true,
    },
  ];
}

function sumEntryField(entries, fieldName) {
  return entries.reduce((sum, entry) => sum + Number(entry[fieldName] || 0), 0);
}

function riskChartColor(entry, index) {
  return chartColorMap[entry.key] || chartPalette[index % chartPalette.length];
}

function riskRankingDetailText(entry, showRiskMix) {
  if (!showRiskMix) return "";
  const parts = [
    `断 ${formatNumber(entry.stockoutCount || 0)}`,
    `冗 ${formatNumber(entry.overstockCount || 0)}`,
    `异 ${formatNumber(entry.anomalyCount || 0)}`,
  ];
  if (Number(entry.riskRate || 0) > 0) {
    parts.push(`风险率 ${formatRatioPercent(entry.riskRate)}`);
  }
  return parts.join(" / ");
}

function riskPieBusinessTooltip(title, entry) {
  const chartTitle = String(title || "");
  if (chartTitle.includes("风险等级")) {
    return RISK_LEVEL_ENTRY_TOOLTIPS[entry.key] || "";
  }
  if (chartTitle.includes("风险类型")) {
    return RISK_TYPE_ENTRY_TOOLTIPS[entry.key] || "";
  }
  if (chartTitle.includes("爆旺平滞")) {
    if (entry.key === "__blank__") {
      return "未维护：销售属性为空，无法套用爆旺或平滞冗余阈值；先补维护销售属性。";
    }
    return formatOverstockRuleHintText(entry.key);
  }
  return "";
}

function riskPieEntryTooltip(title, entry, ratio, showRiskMix = false, ruleTooltip = "") {
  const lines = [
    `${title}：${entry.label}`,
    `SKU数：${formatNumber(entry.value)}`,
    `占比：${formatRatioPercent(ratio)}`,
  ];
  if (showRiskMix) {
    lines.push(`构成：断货 ${formatNumber(entry.stockoutCount || 0)} / 冗余 ${formatNumber(entry.overstockCount || 0)} / 异常 ${formatNumber(entry.anomalyCount || 0)}`);
    lines.push(`维度总SKU：${formatNumber(entry.totalCount || 0)}；真实风险率：${formatRatioPercent(entry.riskRate || 0)}`);
  }
  if (entry.disabled) {
    lines.push("该项为汇总或未维护项，仅展示不下钻。");
  }
  const businessTooltip = riskPieBusinessTooltip(title, entry);
  if (businessTooltip) {
    lines.push("", businessTooltip);
  } else if (ruleTooltip) {
    lines.push("", ruleTooltip);
  }
  return lines.join("\n");
}

function SourcePanel({ summary }) {
  return (
    <section className="panel">
      <div className="panel-title">
        <Database size={17} />
        <h2>数据口径</h2>
      </div>
      <div className="source-line">
        <span>来源</span>
        <strong>{summary.data_source}</strong>
      </div>
      <div className="source-line">
        <span>销量区间</span>
        <strong>{summary.sales_stat_date || "-"}</strong>
      </div>
      <ul className="notes">
        {(summary.notes || []).map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </section>
  );
}

function InventoryFlowPanel({ summary, items = [], loading = false, selectedStage = "", onStageSelect }) {
  const flow = buildInventoryFlow(summary, items);
  return (
    <section className="inventory-flow-section">
      <div className="inventory-flow-board" aria-busy={loading}>
        <InventoryFlowStage
          stageKey="local"
          tone="local"
          icon={Warehouse}
          title="本地 / 供应商仓"
          value={flow.domesticSupply}
          helper="国内可发供给"
          active={selectedStage === "local"}
          onSelect={onStageSelect}
          rows={[
            ["本地仓", flow.localWarehouse],
            ["供应商/备货", flow.stockUp],
          ]}
        />
        <InventoryFlowArrow label="发运" />
        <InventoryFlowStage
          stageKey="transit"
          tone="transit"
          icon={Ship}
          title="头程在途"
          value={flow.inTransit}
          helper="FNSKU 头程与入仓路上"
          active={selectedStage === "transit"}
          onSelect={onStageSelect}
          rows={[
            ["在途合计", flow.inTransit],
            ["覆盖30天需求", flow.transitDemandCoverage],
          ]}
        />
        <InventoryFlowArrow label="入仓" />
        <InventoryFlowStage
          stageKey="overseas"
          tone="overseas"
          icon={Boxes}
          title="国外仓可售"
          value={flow.overseasSellable}
          helper="海外仓 + FBA 可售"
          active={selectedStage === "overseas"}
          onSelect={onStageSelect}
          rows={[
            ["海外仓", flow.overseasWarehouse],
            ["FBA可售", flow.fbaSellable],
          ]}
        />
      </div>
    </section>
  );
}

function InventoryFlowStage({ stageKey, tone, icon: Icon, title, value, helper, rows, active = false, onSelect }) {
  const Component = onSelect ? "button" : "article";
  const interactiveProps = onSelect
    ? {
        type: "button",
        onClick: () => onSelect(stageKey),
        "aria-pressed": active,
      }
    : {};
  return (
    <Component className={`inventory-flow-stage ${tone} ${active ? "active" : ""}`} {...interactiveProps}>
      <div className="inventory-flow-stage-head">
        <Icon size={21} />
        <div>
          <span>{title}</span>
          <strong>{formatNumber(value)}</strong>
        </div>
      </div>
      <p>{helper}</p>
      <div className="inventory-flow-stage-meter">
        <span style={{ width: `${flowMeterWidth(value, rows)}%` }} />
      </div>
    </Component>
  );
}

function InventoryFlowArrow({ label }) {
  return (
    <div className="inventory-flow-arrow">
      <span>{label}</span>
    </div>
  );
}

const WAREHOUSE_STAGE_OPTIONS = [
  { id: "local", label: "本地 / 供应商仓" },
  { id: "transit", label: "头程在途" },
  { id: "overseas", label: "国外仓可售" },
];

function WarehouseDetailPanel({ summary, activeStage, onStageChange }) {
  const details = WAREHOUSE_STAGE_OPTIONS.map((option) => buildWarehouseStageDetail(summary, option.id));
  const activeDetail = details.find((detail) => detail.id === activeStage) || details[0];
  return (
    <section className="warehouse-detail-section">
      <div className="warehouse-detail-head">
        <div>
          <h2>仓库明细</h2>
          <p>{activeDetail.subtitle}</p>
        </div>
        <div className="warehouse-stage-tabs" role="tablist" aria-label="仓库明细分组">
          {details.map((detail) => (
            <button
              type="button"
              className={`warehouse-stage-tab ${detail.id === activeDetail.id ? "active" : ""}`}
              key={detail.id}
              onClick={() => onStageChange(detail.id)}
              role="tab"
              aria-selected={detail.id === activeDetail.id}
            >
              <span>{detail.label}</span>
              <strong>{detail.primaryValue}</strong>
            </button>
          ))}
        </div>
      </div>

      <div className="warehouse-detail-grid">
        <div className="warehouse-metric-grid">
          {activeDetail.metrics.map((metric) => (
            <article className="warehouse-metric" key={metric.label}>
              <span>{metric.label}</span>
              <strong>{metric.value}</strong>
              <small>{metric.helper}</small>
            </article>
          ))}
        </div>
        <div className="warehouse-source-panel">
          <strong>底表口径</strong>
          {activeDetail.sources.map((source) => (
            <p key={source}>{source}</p>
          ))}
        </div>
      </div>

      <div className="warehouse-component-list">
        {activeDetail.components.map((component) => (
          <div key={component.field}>
            <span>{component.label}</span>
            <strong>{component.value}</strong>
            <em>{component.field}</em>
          </div>
        ))}
      </div>

      <WarehouseInventoryTable rows={activeDetail.warehouseRows} title={activeDetail.tableTitle} />
    </section>
  );
}

function buildWarehouseStageDetail(summary, stage) {
  const kpis = summary?.kpis || {};
  const flow = buildInventoryFlow(summary);
  const warehouseRows = Array.isArray(summary?.warehouse_inventory) ? summary.warehouse_inventory : [];
  const fbaInbound = numericValue(kpis.afn_inbound_receiving_quantity) + numericValue(kpis.afn_inbound_working_quantity);
  const warehouseOnway = numericValue(kpis.overseas_wh_product_onway) + numericValue(kpis.local_wh_product_onway);
  const baseSources = [
    "主宽表 ads_lingxing_all_warehouse_new 按当前筛选后的 FNSKU 聚合。",
    "仓库表 dwd_lingxing_inventory_details + dwd_lingxing_sc_warehouse 提供仓库名称、可用、锁定和在途明细。",
  ];

  if (stage === "transit") {
    return {
      id: "transit",
      label: "头程在途",
      primaryValue: formatNumber(flow.inTransit),
      subtitle: "在途合计 = FBA接收/工作 + 本地/海外发FBA在途 + 仓库在途 + 计划量。",
      metrics: [
        { label: "在途合计", value: formatNumber(flow.inTransit), helper: "全部在途与计划量" },
        { label: "FBA接收/处理中", value: formatNumber(fbaInbound), helper: "receiving + working" },
        { label: "仓库在途", value: formatNumber(warehouseOnway), helper: "海外仓/本地仓 onway" },
        { label: "覆盖30天需求", value: formatCoverageDays(flow.inTransit, kpis.demand_30d), helper: "按30天需求折算" },
      ],
      components: [
        warehouseComponent("FBA 接收中", "afn_inbound_receiving_quantity", kpis.afn_inbound_receiving_quantity),
        warehouseComponent("FBA 处理中", "afn_inbound_working_quantity", kpis.afn_inbound_working_quantity),
        warehouseComponent("海外仓发 FBA 在途", "oversease_afn_inbound_shipped_quantity", kpis.overseas_afn_inbound_shipped_quantity),
        warehouseComponent("本地仓发 FBA 在途", "local_afn_inbound_shipped_quantity", kpis.local_afn_inbound_shipped_quantity),
        warehouseComponent("海外仓在途", "overseas_wh_product_onway", kpis.overseas_wh_product_onway),
        warehouseComponent("本地仓在途", "local_wh_product_onway", kpis.local_wh_product_onway),
        warehouseComponent("计划量", "planned_quantity", kpis.planned_quantity),
      ],
      sources: baseSources,
      tableTitle: "仓库在途明细",
      warehouseRows: filterWarehouseRows(warehouseRows, "transit"),
    };
  }

  if (stage === "overseas") {
    return {
      id: "overseas",
      label: "国外仓可售",
      primaryValue: formatNumber(flow.overseasSellable),
      subtitle: "国外可售 = FBA可售 + 海外仓库存，用于判断当前国外端可卖和可补 FBA 能力。",
      metrics: [
        { label: "国外可售", value: formatNumber(flow.overseasSellable), helper: "FBA可售 + 海外仓" },
        { label: "FBA 可售", value: formatNumber(flow.fbaSellable), helper: "afn_fulfillable_quantity" },
        { label: "海外仓库存", value: formatNumber(flow.overseasWarehouse), helper: "overseas_warehouse_quantity" },
        { label: "国外覆盖", value: formatCoverageDays(flow.overseasSellable, kpis.demand_30d), helper: "按30天需求折算" },
      ],
      components: [
        warehouseComponent("FBA 可售", "afn_fulfillable_quantity", flow.fbaSellable),
        warehouseComponent("FBA 库存", "fba_warehouse_quantity", flow.fbaInventory),
        warehouseComponent("海外仓库存", "overseas_warehouse_quantity", flow.overseasWarehouse),
        warehouseComponent("海外仓在途", "overseas_wh_product_onway", kpis.overseas_wh_product_onway),
        warehouseComponent("海外仓发 FBA 在途", "oversease_afn_inbound_shipped_quantity", kpis.overseas_afn_inbound_shipped_quantity),
      ],
      sources: baseSources,
      tableTitle: "国外仓库明细",
      warehouseRows: filterWarehouseRows(warehouseRows, "overseas"),
    };
  }

  return {
    id: "local",
    label: "本地 / 供应商仓",
    primaryValue: formatNumber(flow.domesticSupply),
    subtitle: "国内供给 = 本地仓库存 + 备货/供应商仓，是发运前可调拨供给。",
    metrics: [
      { label: "国内供给", value: formatNumber(flow.domesticSupply), helper: "本地仓 + 备货" },
      { label: "本地仓", value: formatNumber(flow.localWarehouse), helper: "local_warehouse_quantity" },
      { label: "备货/供应商仓", value: formatNumber(flow.stockUp), helper: "stock_up_num" },
      { label: "覆盖30天需求", value: formatCoverageDays(flow.domesticSupply, kpis.demand_30d), helper: "按30天需求折算" },
    ],
    components: [
      warehouseComponent("本地仓库存", "local_warehouse_quantity", flow.localWarehouse),
      warehouseComponent("备货/供应商仓", "stock_up_num", flow.stockUp),
      warehouseComponent("本地仓在途", "local_wh_product_onway", kpis.local_wh_product_onway),
      warehouseComponent("本地仓发 FBA 在途", "local_afn_inbound_shipped_quantity", kpis.local_afn_inbound_shipped_quantity),
    ],
    sources: baseSources,
    tableTitle: "本地仓库明细",
    warehouseRows: filterWarehouseRows(warehouseRows, "local"),
  };
}

function warehouseComponent(label, field, value) {
  return {
    label,
    field,
    value: formatNumber(value),
  };
}

function filterWarehouseRows(rows, stage) {
  const cleanRows = (rows || []).filter(Boolean);
  if (stage === "transit") return cleanRows.filter((row) => numericValue(row.product_onway) > 0);
  if (stage === "overseas") return cleanRows.filter((row) => !isLocalWarehouseRow(row));
  return cleanRows.filter((row) => isLocalWarehouseRow(row));
}

function isLocalWarehouseRow(row) {
  const countryCode = String(row?.country_code || "").trim().toUpperCase();
  const text = [row?.country_name, row?.warehouse_name, row?.display_name, row?.warehouse_code].filter(Boolean).join(" ");
  return countryCode === "CN" || /中国|国内|本地|深圳|义乌|东莞|广州|CN/i.test(text);
}

function WarehouseInventoryTable({ rows, title }) {
  const sortedRows = [...(rows || [])].sort((a, b) => numericValue(b.product_total) - numericValue(a.product_total));
  return (
    <div className="warehouse-table-panel">
      <div className="warehouse-table-head">
        <strong>{title}</strong>
        <span>{formatNumber(sortedRows.length)} 个仓库</span>
      </div>
      {sortedRows.length ? (
        <div className="warehouse-table-wrap">
          <table className="warehouse-table">
            <thead>
              <tr>
                <th>仓库</th>
                <th>国家</th>
                <th>SKU</th>
                <th>总库存</th>
                <th>可用</th>
                <th>锁定</th>
                <th>在途</th>
                <th>可用率</th>
              </tr>
            </thead>
            <tbody>
              {sortedRows.slice(0, 20).map((row, index) => {
                const total = numericValue(row.product_total);
                const valid = numericValue(row.product_valid_num);
                return (
                  <tr key={`${row.warehouse_code || row.display_name || "warehouse"}-${index}`}>
                    <td>
                      <strong>{row.display_name || row.warehouse_name || row.warehouse_code || "-"}</strong>
                      <small>{row.warehouse_code || row.warehouse_name || "-"}</small>
                    </td>
                    <td>{row.country_code || row.country_name || "-"}</td>
                    <td>{formatNumber(row.sku_count)}</td>
                    <td>{formatNumber(total)}</td>
                    <td>{formatNumber(valid)}</td>
                    <td>{formatNumber(row.product_lock_num)}</td>
                    <td>{formatNumber(row.product_onway)}</td>
                    <td>{total > 0 ? formatPercentValue(valid, total) : "-"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="warehouse-empty">当前筛选下暂无可匹配的仓库明细，仍可参考上方主宽表聚合口径。</p>
      )}
    </div>
  );
}

function SkuFirstLegSummary({ item, shipments = [], loading = false, error = "" }) {
  const rows = Array.isArray(shipments) ? shipments : [];
  const stats = rows.reduce(
    (acc, row) => {
      acc.shipped += numericValue(row.ship_num);
      acc.received += numericValue(row.quantity_received);
      acc.inTransit += firstLegArrivalQuantity(row);
      const date = firstLegArrivalDate(row);
      if (date) acc.arrivalDates.push(date);
      return acc;
    },
    { shipped: 0, received: 0, inTransit: 0, arrivalDates: [] }
  );
  const nextArrival = stats.arrivalDates.sort()[0] || "";
  const previewRows = rows.slice(0, 5);
  return (
    <div className="sku-first-leg-panel">
      <div className="sku-first-leg-stats">
        <div>
          <span>FNSKU</span>
          <strong>{item.fnsku || "-"}</strong>
        </div>
        <div>
          <span>批次数</span>
          <strong>{loading ? "读取中" : formatNumber(rows.length)}</strong>
        </div>
        <div>
          <span>头程在途</span>
          <strong>{formatNumber(stats.inTransit)}</strong>
        </div>
        <div>
          <span>最近到货</span>
          <strong>{formatDateOrDash(nextArrival)}</strong>
        </div>
      </div>
      {error && <p className="sku-first-leg-error">{error}</p>}
      {!loading && !error && rows.length === 0 && (
        <p className="sku-first-leg-empty">当前 FNSKU 暂无头程批次记录。</p>
      )}
      {previewRows.length > 0 && (
        <div className="sku-first-leg-batches">
          {previewRows.map((row, index) => (
            <div key={`${row.ship_id || row.package_id || row.refer_id || "shipment"}-${index}`}>
              <span>{firstLegRelationLabel(row.source_relation)}</span>
              <strong>{row.ship_id || row.package_id || row.batch_num || "-"}</strong>
              <small>{formatNumber(firstLegArrivalQuantity(row))} 件 · {formatDateOrDash(firstLegArrivalDate(row))}</small>
              <small>{row.current_shipping_status || row.detail_status || row.shipping_method || "-"}</small>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function buildInventoryFlow(summary, items = []) {
  const kpis = summary?.kpis || {};
  const fallback = Array.isArray(items) ? items : [];
  const sumField = (field) => fallback.reduce((total, item) => total + numericValue(item?.[field]), 0);
  const totalInventory = numericOrFallback(kpis.total_inventory, sumField("total_inventory"));
  const fbaInventory = numericOrFallback(kpis.fba_inventory, sumField("fba_inventory"));
  const fbaSellable = numericOrFallback(kpis.fba_sellable, sumField("fba_sellable"));
  const overseasWarehouse = numericOrFallback(kpis.overseas_inventory, sumField("overseas_inventory"));
  const localWarehouse = numericOrFallback(kpis.local_inventory, sumField("local_inventory"));
  const stockUpFallback = fallback.reduce((total, item) => {
    const inferred = numericValue(item?.total_inventory)
      - numericValue(item?.fba_inventory)
      - numericValue(item?.overseas_inventory)
      - numericValue(item?.local_inventory);
    return total + Math.max(inferred, 0);
  }, 0);
  const stockUp = numericOrFallback(kpis.stock_up_inventory, stockUpFallback);
  const domesticSupply = numericOrFallback(kpis.domestic_supply_inventory, localWarehouse + stockUp);
  const inTransit = numericOrFallback(kpis.inbound_total, sumField("inbound_total"));
  const overseasSellable = numericOrFallback(kpis.overseas_sellable_inventory, overseasWarehouse + fbaSellable);
  const demand30d = numericOrFallback(kpis.demand_30d, sumField("demand_30d"));
  const flowTotal = domesticSupply + inTransit + overseasSellable;
  return {
    skuCount: numericOrFallback(kpis.sku_count, fallback.length),
    totalInventory,
    fbaInventory,
    fbaSellable,
    overseasWarehouse,
    localWarehouse,
    stockUp,
    domesticSupply,
    inTransit,
    overseasSellable,
    demand30d,
    transitShare: formatPercentValue(inTransit, flowTotal),
    overseasShare: formatPercentValue(overseasSellable, flowTotal),
    transitDemandCoverage: formatCoverageDays(inTransit, demand30d),
    overseasDemandCoverage: formatCoverageDays(overseasSellable, demand30d),
    stockSalesRatio: formatInventorySalesRatio(totalInventory, demand30d),
  };
}

function flowMeterWidth(value, rows = []) {
  const values = [value, ...rows.map(([, rowValue]) => rowValue)].map(numericValue).filter((item) => item > 0);
  const max = Math.max(...values, 1);
  return Math.max(8, Math.min(100, (numericValue(value) / max) * 100));
}

function numericValue(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

function numericOrFallback(value, fallback) {
  const number = Number(value);
  return Number.isFinite(number) ? number : numericValue(fallback);
}

function formatPercentValue(value, total) {
  const numerator = numericValue(value);
  const denominator = numericValue(total);
  if (denominator <= 0) return "0%";
  return `${formatNumber((numerator / denominator) * 100)}%`;
}

function formatCoverageDays(quantity, demand30d) {
  const dailyDemand = numericValue(demand30d) / 30;
  if (dailyDemand <= 0) return "-";
  return `${formatNumber(numericValue(quantity) / dailyDemand)}天`;
}

function formatInventorySalesRatio(inventory, demand30d) {
  const denominator = numericValue(demand30d);
  if (denominator <= 0) return "-";
  return `${formatNumber(numericValue(inventory) / denominator)}x`;
}

function MultiFilterField({ label, value, options, onChange, wide = false, fieldKey, openField, onOpenFieldChange }) {
  const selected = selectedValues(value);
  const isControlledOpen = Boolean(fieldKey && onOpenFieldChange);
  const isOpen = isControlledOpen ? openField === fieldKey : undefined;
  const normalizedOptions = (options || [])
    .map((option) => (typeof option === "string" ? { value: option, label: option } : option))
    .filter((option) => option?.value);
  const summary = selected.length
    ? `${selected.slice(0, 2).join("、")}${selected.length > 2 ? ` +${selected.length - 2}` : ""}`
    : "全部";
  const toggleOpen = (event) => {
    if (!isControlledOpen) return;
    event.preventDefault();
    onOpenFieldChange(isOpen ? null : fieldKey);
  };
  return (
    <details className={`filter-field multi-filter ${wide ? "wide" : ""}`} open={isOpen}>
      <summary onClick={toggleOpen}>
        <span>{label}</span>
        <strong>{summary}</strong>
      </summary>
      <div className="multi-filter-menu">
        <div className="multi-filter-menu-head">
          <span>{selected.length ? `已选 ${formatNumber(selected.length)} 项` : "全部"}</span>
          {selected.length > 0 && (
            <button type="button" onClick={() => onChange([])}>
              清空
            </button>
          )}
        </div>
        {normalizedOptions.length ? (
          <div className="multi-filter-options">
            {normalizedOptions.map((option) => (
              <label key={option.value}>
                <input
                  type="checkbox"
                  checked={selected.includes(String(option.value))}
                  onChange={(event) => onChange(nextSelectedValues(selected, String(option.value), event.target.checked))}
                />
                <span>{option.label || option.value}</span>
              </label>
            ))}
          </div>
        ) : (
          <p className="multi-filter-empty">暂无候选值</p>
        )}
      </div>
    </details>
  );
}

function InventoryTable({
  items,
  pagination,
  showSkuColumn,
  filters,
  activeFilterCount,
  filterOptions,
  salesPeriod,
  salesStartDate,
  salesEndDate,
  loading,
  onSalesPeriodChange,
  onSalesPeriodApply,
  onSalesPreset,
  onPageChange,
  onFiltersApply,
  onOpenItem,
}) {
  const [filterOpen, setFilterOpen] = useState(false);
  const [openFilterField, setOpenFilterField] = useState(null);
  const [draftFilters, setDraftFilters] = useState(filters);
  const [filterPopoverStyle, setFilterPopoverStyle] = useState({});
  const filterButtonRef = useRef(null);
  const currentPage = pagination?.page || 1;
  const totalPages = pagination?.total_pages || 1;
  const totalCount = pagination?.total_count ?? items.length;
  const pageSize = pagination?.page_size ?? items.length;
  const start = totalCount ? (currentPage - 1) * pageSize + 1 : 0;
  const end = totalCount ? start + items.length - 1 : 0;
  const countryOptions = optionValuesWithDefaults(COMMON_COUNTRY_OPTIONS, filterOptions?.country_code, draftFilters.country_code);
  const shipmentCountryOptions = optionValuesWithDefaults(COMMON_COUNTRY_OPTIONS, filterOptions?.shipments_country, draftFilters.shipments_country);
  const optionsForField = (fieldName, backendOptions) => optionValuesWithSelected(
    backendOptions?.length ? backendOptions : optionValuesFromItems(items, fieldName),
    draftFilters[fieldName]
  );
  const storeOptions = optionsForField("store_name", filterOptions?.store_name);
  const salesDepartmentOptions = optionsForField("sales_department", filterOptions?.sales_department);
  const salesmanOptions = optionsForField("salesman", filterOptions?.salesman);
  const productManagerOptions = optionsForField("product_manager", filterOptions?.product_manager);
  const productPropertyOptions = optionsForField("product_property", filterOptions?.product_property);
  const mskuStatusOptions = optionValuesWithDefaults(MSKU_STATUS_OPTIONS, filterOptions?.msku_status, draftFilters.msku_status);
  const seasonalityOptions = optionValuesWithDefaults(SEASONALITY_OPTIONS, filterOptions?.seasonality, draftFilters.seasonality);
  const mskuLifeProcessOptions = MSKU_LIFE_PROCESS_OPTIONS;
  useEffect(() => {
    if (!filterOpen) {
      setDraftFilters(filters);
      setOpenFilterField(null);
    }
  }, [filters, filterOpen]);
  const updateDraftFilters = (changes) => setDraftFilters((current) => ({ ...current, ...changes }));
  const closeFilterPopover = () => {
    setFilterOpen(false);
    setOpenFilterField(null);
  };
  const applyDraftFilters = () => {
    onFiltersApply(draftFilters);
    closeFilterPopover();
  };
  const resetDraftFilters = () => {
    const nextFilters = createDefaultFilters();
    setDraftFilters(nextFilters);
    onFiltersApply(nextFilters);
    closeFilterPopover();
  };
  const positionFilterPopover = useCallback(() => {
    if (typeof window === "undefined") return;
    const panelWidth = Math.min(980, window.innerWidth - 48);
    const left = Math.max(24, (window.innerWidth - panelWidth) / 2);
    const top = 24;
    const availableBelow = Math.max(420, window.innerHeight - top - 24);
    setFilterPopoverStyle({
      left: `${Math.round(left)}px`,
      top: `${Math.round(top)}px`,
      width: `${Math.round(panelWidth)}px`,
      maxHeight: `${Math.round(availableBelow)}px`,
    });
  }, []);
  useEffect(() => {
    if (!filterOpen) return undefined;
    positionFilterPopover();
    window.addEventListener("resize", positionFilterPopover);
    return () => window.removeEventListener("resize", positionFilterPopover);
  }, [filterOpen, positionFilterPopover]);
  const toggleFilterPopover = () => {
    setDraftFilters(filters);
    if (filterOpen) {
      closeFilterPopover();
      return;
    }
    setOpenFilterField(null);
    positionFilterPopover();
    setFilterOpen(true);
  };
  const multiFilterOpenProps = {
    openField: openFilterField,
    onOpenFieldChange: setOpenFilterField,
  };
  return (
    <section className="table-section">
      <div className="section-heading">
        <div>
          <h2>SKU 风险明细</h2>
          <p>共 {formatNumber(totalCount)} 条，当前显示 {formatNumber(start)}-{formatNumber(end)} 条，销量区间 {salesPeriod || "-"}</p>
        </div>
        <div className="table-actions">
          <div className="detail-filter-wrap">
            <button
              ref={filterButtonRef}
              type="button"
              className={`filter-popover-button ${activeFilterCount ? "active" : ""}`}
              onClick={toggleFilterPopover}
              aria-expanded={filterOpen}
            >
              <Filter size={16} />
              <span>高级筛选</span>
              {activeFilterCount > 0 && <b>{activeFilterCount}</b>}
            </button>
            {filterOpen &&
              typeof document !== "undefined" &&
              createPortal(
                <>
                <button className="popover-dismiss-layer" type="button" aria-label="关闭筛选" onClick={closeFilterPopover} />
                <div className="detail-filter-popover" role="dialog" aria-label="SKU 多条件筛选" style={filterPopoverStyle}>
                  <div className="filter-popover-head">
                    <div>
                      <strong>多条件筛选</strong>
                      <span>多个条件会同时生效</span>
                    </div>
                    <button type="button" onClick={closeFilterPopover} aria-label="关闭">
                      ×
                    </button>
                  </div>
                  <div className="filter-layout">
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>定位范围</strong>
                        <span>SKU、国家、店铺</span>
                      </div>
                      <div className="filter-section-grid">
                        <label className="filter-field">
                          <span>SKU / MSKU / FNSKU</span>
                          <input
                            value={draftFilters.material_code}
                            placeholder="输入 SKU、MSKU 或 FNSKU"
                            onChange={(event) => updateDraftFilters({ material_code: event.target.value })}
                          />
                        </label>
                        <MultiFilterField fieldKey="country_code" label="国家" value={draftFilters.country_code} options={countryOptions} onChange={(value) => updateDraftFilters({ country_code: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="shipments_country" label="发货国家" value={draftFilters.shipments_country} options={shipmentCountryOptions} onChange={(value) => updateDraftFilters({ shipments_country: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="store_name" label="店铺" value={draftFilters.store_name} options={storeOptions} onChange={(value) => updateDraftFilters({ store_name: value })} {...multiFilterOpenProps} />
                      </div>
                    </section>
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>组织维度</strong>
                        <span>部门、人员</span>
                      </div>
                      <div className="filter-section-grid">
                        <MultiFilterField fieldKey="sales_department" label="销售部门" value={draftFilters.sales_department} options={salesDepartmentOptions} onChange={(value) => updateDraftFilters({ sales_department: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="salesman" label="销售员" value={draftFilters.salesman} options={salesmanOptions} onChange={(value) => updateDraftFilters({ salesman: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="product_manager" label="产品经理" value={draftFilters.product_manager} options={productManagerOptions} onChange={(value) => updateDraftFilters({ product_manager: value })} {...multiFilterOpenProps} />
                      </div>
                    </section>
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>商品维度</strong>
                        <span>属性、状态、生命周期</span>
                      </div>
                      <div className="filter-section-grid">
                        <MultiFilterField fieldKey="sales_property" label="销售属性" value={draftFilters.sales_property} options={SALES_PROPERTY_OPTIONS} onChange={(value) => updateDraftFilters({ sales_property: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="product_property" label="产品属性" value={draftFilters.product_property} options={productPropertyOptions} onChange={(value) => updateDraftFilters({ product_property: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="seasonality" label="季节属性" value={draftFilters.seasonality} options={seasonalityOptions} onChange={(value) => updateDraftFilters({ seasonality: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="msku_status" label="MSKU 状态" value={draftFilters.msku_status} options={mskuStatusOptions} onChange={(value) => updateDraftFilters({ msku_status: value })} {...multiFilterOpenProps} />
                        <MultiFilterField fieldKey="msku_life_process" label="MSKU生命周期" value={draftFilters.msku_life_process} options={mskuLifeProcessOptions} onChange={(value) => updateDraftFilters({ msku_life_process: value })} {...multiFilterOpenProps} />
                      </div>
                    </section>
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>销量与风险</strong>
                        <span>销量区间、风险口径</span>
                      </div>
                      <div className="filter-section-grid">
                        <MultiFilterField fieldKey="risk_type" label="风险类型" value={draftFilters.risk_type} options={RISK_TYPE_OPTIONS} onChange={(value) => updateDraftFilters({ risk_type: value })} {...multiFilterOpenProps} />
                        <label className="filter-field">
                          <span>销量开始</span>
                          <input
                            type="date"
                            value={draftFilters.sales_start_date}
                            max={draftFilters.sales_end_date || undefined}
                            onChange={(event) => {
                              const nextStart = event.target.value;
                              const nextEnd = draftFilters.sales_end_date && draftFilters.sales_end_date < nextStart ? nextStart : draftFilters.sales_end_date;
                              updateDraftFilters({ sales_start_date: nextStart, sales_end_date: nextEnd });
                            }}
                          />
                        </label>
                        <label className="filter-field">
                          <span>销量结束</span>
                          <input
                            type="date"
                            value={draftFilters.sales_end_date}
                            min={draftFilters.sales_start_date || undefined}
                            onChange={(event) => updateDraftFilters({ sales_end_date: event.target.value })}
                          />
                        </label>
                        <div className="filter-presets" aria-label="销量区间快捷筛选">
                          <button type="button" onClick={() => updateDraftFilters(lastCompleteDaysRange(7))}>
                            上周销量
                          </button>
                          <button type="button" onClick={() => updateDraftFilters(lastCompleteDaysRange(30))}>
                            上月销量
                          </button>
                        </div>
                        <label className="filter-check">
                          <input
                            type="checkbox"
                            checked={draftFilters.risk_only}
                            onChange={(event) => updateDraftFilters({ risk_only: event.target.checked })}
                          />
                          <span>只看风险 SKU</span>
                        </label>
                        <label className="filter-check">
                          <input
                            type="checkbox"
                            checked={draftFilters.positive_demand}
                            onChange={(event) => updateDraftFilters({ positive_demand: event.target.checked })}
                          />
                          <span>只看有需求</span>
                        </label>
                      </div>
                    </section>
                  </div>
                  <div className="filter-popover-actions">
                    <button type="button" className="ghost-button compact-action" onClick={resetDraftFilters} disabled={loading}>
                      重置
                    </button>
                    <button type="button" className="primary-button compact-action" onClick={applyDraftFilters} disabled={loading}>
                      应用筛选
                    </button>
                  </div>
                </div>
                </>,
                document.body
              )}
          </div>
          <div className="sales-period-filter" aria-label="销量区间筛选器">
            <button type="button" className="period-preset" onClick={() => onSalesPreset(lastCompleteDaysRange(7))} disabled={loading}>
              上周销量
            </button>
            <button type="button" className="period-preset" onClick={() => onSalesPreset(lastCompleteDaysRange(30))} disabled={loading}>
              上月销量
            </button>
            <label className="input-wrap date-input compact">
              <CalendarDays size={16} />
              <input
                type="date"
                value={salesStartDate}
                aria-label="销量开始日期"
                max={salesEndDate || undefined}
                onChange={(event) => {
                  const nextStart = event.target.value;
                  const nextEnd = salesEndDate && salesEndDate < nextStart ? nextStart : salesEndDate;
                  onSalesPeriodChange({ sales_start_date: nextStart, sales_end_date: nextEnd });
                }}
              />
            </label>
            <span className="date-separator">至</span>
            <label className="input-wrap date-input compact">
              <CalendarDays size={16} />
              <input
                type="date"
                value={salesEndDate}
                aria-label="销量结束日期"
                min={salesStartDate || undefined}
                onChange={(event) => onSalesPeriodChange({ sales_end_date: event.target.value })}
              />
            </label>
            <button className="ghost-button compact-action" onClick={onSalesPeriodApply} disabled={loading}>
              销量区间
            </button>
          </div>
          <div className="pager">
            <button disabled={currentPage <= 1} onClick={() => onPageChange(currentPage - 1)}>
              上一页
            </button>
            <span>
              {currentPage} / {totalPages}
            </span>
            <button disabled={currentPage >= totalPages} onClick={() => onPageChange(currentPage + 1)}>
              下一页
            </button>
          </div>
        </div>
      </div>
      <div className="table-scroll">
        <table className={showSkuColumn ? "" : "without-sku-column"}>
          <thead>
            <tr>
              <th>风险</th>
              {showSkuColumn && <th>SKU</th>}
              <th>区间销量</th>
              <th>断货时间</th>
              <th>店铺 / 国家</th>
              <th>库存结构</th>
              <th>需求与覆盖</th>
              <th>预计 7 天</th>
              <th>建议动作</th>
            </tr>
          </thead>
          <tbody>
            {!items.length && (
              <tr className="empty-table-row">
                <td colSpan={showSkuColumn ? 9 : 8}>暂无匹配数据</td>
              </tr>
            )}
            {items.map((item) => (
              <tr key={`${item.material_code}-${item.store_name}-${item.fnsku}`}>
                <td>
                  <RiskBadges item={item} />
                </td>
                {showSkuColumn && (
                  <td>
                    <SkuCell item={item} />
                  </td>
                )}
                <td>
                  <span className="daily-sales">{formatNumber(item.daily_sales_volume)}</span>
                  <small>{salesPeriod || "-"}</small>
                </td>
                <td>
                  <ShortageCell item={item} />
                </td>
                <td>
                  <span>{item.store_name || "-"}</span>
                  <small>{[item.country_code, item.shipments_country].filter(Boolean).join(" / ") || "-"}</small>
                </td>
                <td>
                  <InventoryStructureCell item={item} />
                </td>
                <td>
                  <span>30 天 {formatNumber(item.demand_30d)}</span>
                  <small>FBA可售覆盖 {item.sellable_days ?? "-"} 天</small>
                </td>
                <td>
                  <span className={item.projected_7d < 0 ? "negative" : ""}>{formatNumber(item.projected_7d)}</span>
                  <small>提前期 {item.lead_time_days} 天</small>
                </td>
                <td className="action-cell">
                  <ActionSummaryCell
                    item={item}
                    onOpen={() => onOpenItem({ ...item, sales_start_date: salesStartDate, sales_end_date: salesEndDate })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function SkuCell({ item }) {
  return (
    <div className="sku-cell">
      <div className="sku-line">
        <strong>{item.material_code}</strong>
        {item.sales_property && <span className={`sales-property ${salesPropertyClass(item.sales_property)}`}>{item.sales_property}</span>}
      </div>
      <small>{item.sku_name || item.msku || item.fnsku}</small>
    </div>
  );
}

function ShortageCell({ item }) {
  const summary = piciShortageWindowSummary(item);
  if (!item.pici_first_shortage_days) {
    return (
      <div className="shortage-card calm">
        <strong>暂无断货</strong>
        <span>{item.pici_gap_values && Object.keys(item.pici_gap_values).length > 0 ? "合计断货 0 天" : "无 chazhi"}</span>
      </div>
    );
  }
  return (
    <div className="shortage-card">
      <strong>{formatPiciGap(item)}</strong>
      <span>合计 {formatNumber(summary.totalDays)} 天</span>
      <div className="shortage-segments">
        {summary.segments.slice(0, 4).map((segment) => (
          <em key={segment}>{segment}</em>
        ))}
        {summary.segments.length > 4 && <em>+{summary.segments.length - 4} 段</em>}
      </div>
    </div>
  );
}

function InventoryStructureCell({ item }) {
  return (
    <div className="inventory-structure">
      <div className="inventory-total">
        <span>总库存</span>
        <strong>{formatNumber(item.total_inventory)}</strong>
      </div>
      <div className="inventory-metrics">
        <Metric label="FBA" value={formatNumber(item.fba_sellable)} />
        <Metric label="在途" value={formatNumber(item.inbound_total)} />
        <Metric label="FBA天" value={formatDays(item.redundancy_sellable_days?.sellable_1)} tone="warn" />
        <Metric label="全链路" value={formatDays(item.redundancy_sellable_days?.sellable_6)} tone="warn" />
      </div>
      <div className="inventory-age">
        <span>长库龄</span>
        <strong>61天+ {formatNumber(item.long_age_inventory)}</strong>
        <strong>365天+ {formatNumber(item.fba_age_365_plus)}</strong>
      </div>
    </div>
  );
}

function Metric({ label, value, tone = "", tooltip = "" }) {
  return (
    <div className={`metric-chip ${tone}`} title={tooltip || undefined}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ActionSummaryCell({ onOpen }) {
  return (
    <div className="action-summary">
      <span aria-hidden="true" />
      <button type="button" onClick={onOpen}>
        详情
      </button>
    </div>
  );
}

function RiskRuleHint({ item }) {
  const overstockGroup = overstockRuleHintForSalesProperty(item?.sales_property);
  const stockoutAssertion = formatStockoutAssertion(item);
  const overstockAssertion = formatOverstockAssertion(item);
  const assertions = [
    stockoutAssertion ? { key: "stockout", text: stockoutAssertion, tooltip: STOCKOUT_RULE_TOOLTIP } : null,
    overstockAssertion ? { key: "overstock", text: `${overstockGroup.label}冗余：${overstockAssertion}`, tooltip: overstockRuleTooltip(item?.sales_property) } : null,
  ].filter(Boolean);
  if (!assertions.length) return null;
  return (
    <div className="risk-rule-hint" aria-label="风险命中断言" title={assertions.map((assertion) => `${assertion.text}\n${assertion.tooltip}`).join("\n\n")}>
      {assertions.map((assertion) => (
        <span className={assertion.key} key={assertion.key} title={assertion.tooltip}>{assertion.text}</span>
      ))}
    </div>
  );
}

function formatStockoutAssertion(item = {}) {
  const evidence = item?.evidence || {};
  const shortageDays = Number(evidence.stockout_shortage_days_0_45 || 0);
  const futureHintDays = evidence.stockout_future_replenishment_hint_days;
  const hasChazhi = Boolean(item?.pici_gap_values && Object.keys(item.pici_gap_values).length > 0);
  const keyGap = item?.pici_key_gap || "-";
  if (isActiveRiskLevel(item?.stockout_risk_level)) {
    const firstText = formatPiciGap(item);
    const warning = item.stockout_warning || riskBadgeLabel(stockoutRiskBadgeLabels, item.stockout_risk_level);
    return `断货风险：命中${warning}，0-45天内 chazhi 负数 ${formatNumber(shortageDays)} 天，${firstText}，关键缺口 ${keyGap}`;
  }
  if (futureHintDays !== null && futureHintDays !== undefined && futureHintDays !== "") {
    return `断货风险：未命中0-45天断货；第 ${formatNumber(futureHintDays)} 天后 chazhi 为负，仅作为补货提示，关键缺口 ${keyGap}`;
  }
  if (hasChazhi) return "";
  return "";
}

function formatOverstockAssertion(item = {}) {
  const warning = item?.overstock_warning || riskBadgeLabel(overstockRiskBadgeLabels, item?.overstock_risk_level || "normal");
  const reason = item?.evidence?.overstock_reason;
  if (isActiveRiskLevel(item?.overstock_risk_level)) {
    const action = extractOverstockActionAssertion(item);
    return `命中${warning}${reason ? `，${reason}` : ""}${action ? `；处理断言：${action}` : ""}`;
  }
  return "";
}

function extractOverstockActionAssertion(item = {}) {
  const text = String(item?.suggested_action || "");
  const match = text.match(/冗余：(.+?)(?:；异常：|。$|$)/);
  return match ? match[1].replace(/^按 SOP 冗余处理：/, "") : "";
}

function isActiveRiskLevel(level) {
  return ["critical", "high", "medium", "low"].includes(level);
}

function ActionDetailDialog({ item, onClose }) {
  const [activeTab, setActiveTab] = useState("detail");
  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [chatSending, setChatSending] = useState(false);
  const [diagnosisLoading, setDiagnosisLoading] = useState(false);
  const [forecastReview, setForecastReview] = useState(null);
  const [forecastReviewLoading, setForecastReviewLoading] = useState(false);
  const [forecastReviewError, setForecastReviewError] = useState("");
  const [riskDiagnosis, setRiskDiagnosis] = useState(null);
  const [riskDiagnosisLoading, setRiskDiagnosisLoading] = useState(false);
  const [riskDiagnosisError, setRiskDiagnosisError] = useState("");
  const [firstLegShipments, setFirstLegShipments] = useState([]);
  const [firstLegLoading, setFirstLegLoading] = useState(false);
  const [firstLegError, setFirstLegError] = useState("");
  const [shippingCostEstimate, setShippingCostEstimate] = useState(item.shipping_cost_estimate || null);
  const [shippingCostLoading, setShippingCostLoading] = useState(false);
  const [shippingCostError, setShippingCostError] = useState("");
  const [recordInput, setRecordInput] = useState("");
  const [records, setRecords] = useState([]);
  const shortageSummary = piciShortageWindowSummary(item);
  const riskFlags = item.evidence?.risk_flags || [];
  const piciEntries = Object.entries(item.pici_gap_values || {}).sort((a, b) => Number(a[0].split("_").pop()) - Number(b[0].split("_").pop()));

  useEffect(() => {
    setActiveTab("detail");
    setChatMessages([
      {
        role: "assistant",
        text: `已载入 ${item.material_code} 的库存上下文。你可以问断货原因、冗余依据、异常字段、处理建议，或让我生成发给销售/采购/物流的说明。`,
      },
    ]);
    setChatInput("");
    setForecastReview(null);
    setForecastReviewError("");
    setForecastReviewLoading(false);
    setRiskDiagnosis(null);
    setRiskDiagnosisError("");
    setRiskDiagnosisLoading(false);
    setFirstLegShipments([]);
    setFirstLegError("");
    setFirstLegLoading(false);
    setShippingCostEstimate(item.shipping_cost_estimate || null);
    setShippingCostError("");
    setShippingCostLoading(false);
    setDiagnosisLoading(false);
    setRecordInput("");
    setRecords([
      { time: "当前", title: "Agent 识别风险", content: item.warning_type || "正常" },
    ]);
  }, [item.material_code]);

  useEffect(() => {
    let cancelled = false;
    setFirstLegLoading(true);
    setFirstLegError("");
    fetchFirstLegShipments(item)
      .then((payload) => {
        if (cancelled) return;
        setFirstLegShipments(Array.isArray(payload.shipments) ? payload.shipments : []);
      })
      .catch((error) => {
        if (cancelled) return;
        setFirstLegShipments([]);
        setFirstLegError(error instanceof Error ? error.message : "头程批次查询失败");
      })
      .finally(() => {
        if (!cancelled) setFirstLegLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item.fnsku]);

  useEffect(() => {
    let cancelled = false;
    setShippingCostEstimate(item.shipping_cost_estimate || null);
    setShippingCostError("");
    setShippingCostLoading(true);
    fetchSkuShippingCost(item)
      .then((payload) => {
        if (cancelled) return;
        setShippingCostEstimate(payload.shipping_cost_estimate || null);
      })
      .catch((error) => {
        if (cancelled) return;
        setShippingCostError(error instanceof Error ? error.message : "补货成本估算失败");
      })
      .finally(() => {
        if (!cancelled) setShippingCostLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [item.material_code, item.msku, item.fnsku, item.asin, item.store_name, item.country_code]);

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!text || chatSending) return;
    const userMessage = { role: "user", text };
    setChatMessages((messages) => [...messages, userMessage]);
    setChatInput("");
    setChatSending(true);
    try {
      const reply = await askSkuAssistant(item, text, forecastReview, firstLegShipments);
      setChatMessages((messages) => [...messages, { role: "assistant", text: reply }]);
    } catch (error) {
      setChatMessages((messages) => [...messages, { role: "assistant", text: localSkuChatReply(item, text) }]);
    } finally {
      setChatSending(false);
    }
  };

  const runSkuDiagnosis = async () => {
    if (diagnosisLoading || chatSending) return;
    const question = "生成 SKU 全链路诊断";
    setChatMessages((messages) => [...messages, { role: "user", text: question }]);
    setDiagnosisLoading(true);
    setChatSending(true);
    try {
      const diagnosis = await fetchSkuDiagnosis(item, question, forecastReview, firstLegShipments);
      setRiskDiagnosis(diagnosis);
      setChatMessages((messages) => [...messages, { role: "assistant", text: formatSkuDiagnosisReply(diagnosis) }]);
    } catch (error) {
      setChatMessages((messages) => [...messages, { role: "assistant", text: localSkuChatReply(item, question) }]);
    } finally {
      setDiagnosisLoading(false);
      setChatSending(false);
    }
  };

  const runMonthlyForecastReview = async (options = {}) => {
    if (forecastReviewLoading) return;
    setForecastReviewLoading(true);
    setForecastReviewError("");
    try {
      const params = new URLSearchParams();
      params.set("month_offset", "2");
      if (options.refresh) params.set("refresh", "true");
      [
        ["material_code", item.material_code],
        ["msku", item.msku],
        ["fnsku", item.fnsku],
        ["asin", item.asin],
        ["store_name", item.store_name],
        ["country_code", item.country_code],
      ].forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      const response = await apiFetch(`${API_BASE_URL}/control-tower/monthly-forecast-review?${params.toString()}`);
      if (!response.ok) throw new Error(`复盘失败 ${response.status}`);
      setForecastReview(await response.json());
    } catch (error) {
      setForecastReviewError(error instanceof Error ? error.message : "月度预测复盘失败");
    } finally {
      setForecastReviewLoading(false);
    }
  };

  useEffect(() => {
    runMonthlyForecastReview();
  }, [item.material_code, item.msku, item.fnsku, item.asin, item.store_name, item.country_code]);

  useEffect(() => {
    let cancelled = false;
    if (forecastReviewLoading || firstLegLoading) return undefined;
    if (!forecastReview && !forecastReviewError) return undefined;
    setRiskDiagnosisLoading(true);
    setRiskDiagnosisError("");
    fetchSkuDiagnosis(item, "生成 SKU 全链路诊断", forecastReview, firstLegShipments)
      .then((diagnosis) => {
        if (cancelled) return;
        setRiskDiagnosis(diagnosis);
      })
      .catch((error) => {
        if (cancelled) return;
        setRiskDiagnosisError(error instanceof Error ? error.message : "归因诊断失败");
      })
      .finally(() => {
        if (!cancelled) setRiskDiagnosisLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    item.material_code,
    item.msku,
    item.fnsku,
    item.asin,
    item.store_name,
    item.country_code,
    forecastReview,
    forecastReviewError,
    forecastReviewLoading,
    firstLegLoading,
    firstLegShipments,
  ]);

  const addRecord = () => {
    const text = recordInput.trim();
    if (!text) return;
    setRecords((items) => [{ time: new Date().toLocaleString("zh-CN", { hour12: false }), title: "人工备注", content: text }, ...items]);
    setRecordInput("");
  };

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside className="sku-drawer" role="dialog" aria-modal="true" aria-label="FNSKU 工作台" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <span>FNSKU 工作台</span>
            <div className="drawer-title-line">
              <strong>{item.fnsku || item.material_code}</strong>
              {item.sales_property && <span className={`sales-property ${salesPropertyClass(item.sales_property)}`}>{item.sales_property}</span>}
            </div>
            <div className="drawer-subtitle-line">
              <p>{item.sku_name || item.msku || item.fnsku || "-"}</p>
              <RiskRuleHint item={item} />
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭条目详情">
            ×
          </button>
        </div>
        <div className="drawer-tabs" role="tablist" aria-label="FNSKU 工作台视图">
          {[
            ["detail", "详情"],
            ["ai", "AI 对话"],
            ["records", "处理记录"],
          ].map(([key, label]) => (
            <button key={key} type="button" className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>
              {label}
            </button>
          ))}
        </div>
        <div className="drawer-body">
          {activeTab === "detail" && (
            <SkuDetailPanel
              item={item}
              shortageSummary={shortageSummary}
              riskFlags={riskFlags}
              piciEntries={piciEntries}
              forecastReview={forecastReview}
              forecastReviewLoading={forecastReviewLoading}
              forecastReviewError={forecastReviewError}
              riskDiagnosis={riskDiagnosis}
              riskDiagnosisLoading={riskDiagnosisLoading}
              riskDiagnosisError={riskDiagnosisError}
              firstLegShipments={firstLegShipments}
              firstLegLoading={firstLegLoading}
              firstLegError={firstLegError}
              shippingCostEstimate={shippingCostEstimate}
              shippingCostLoading={shippingCostLoading}
              shippingCostError={shippingCostError}
              onForecastReview={runMonthlyForecastReview}
            />
          )}
          {activeTab === "ai" && (
            <SkuAiChatPanel
              item={item}
              messages={chatMessages}
              input={chatInput}
              sending={chatSending}
              onInputChange={setChatInput}
              onSend={sendChat}
              onRunDiagnosis={runSkuDiagnosis}
              onQuickAsk={(text) => {
                setChatInput(text);
              }}
            />
          )}
          {activeTab === "records" && (
            <HandlingRecordsPanel records={records} input={recordInput} onInputChange={setRecordInput} onAdd={addRecord} />
          )}
        </div>
      </aside>
    </div>
  );
}

function SkuDetailPanel({
  item,
  shortageSummary,
  riskFlags,
  piciEntries,
  forecastReview,
  forecastReviewLoading,
  forecastReviewError,
  riskDiagnosis,
  riskDiagnosisLoading,
  riskDiagnosisError,
  firstLegShipments = [],
  firstLegLoading = false,
  firstLegError = "",
  shippingCostEstimate,
  shippingCostLoading,
  shippingCostError,
  onForecastReview,
}) {
  const [supplySimulation, setSupplySimulation] = useState(() => createEmptySupplySimulation(item));
  const [forecastDetailOpen, setForecastDetailOpen] = useState(false);
  const [arrivalSourceMode, setArrivalSourceMode] = useState("pici");
  useEffect(() => {
    setSupplySimulation(createEmptySupplySimulation(item));
    setForecastDetailOpen(false);
    setArrivalSourceMode("pici");
  }, [item.material_code, item.msku, item.fnsku, item.asin, item.store_name, item.country_code, item.sales_property]);

  const firstLegArrivals = useMemo(
    () => buildFirstLegArrivalBatches(firstLegShipments, item),
    [firstLegShipments, item.material_code, item.msku, item.fnsku, item.asin, item.sales_end_date]
  );
  const supplySummaryOptions = useMemo(
    () => arrivalSourceMode === "first_leg"
      ? { arrivalSource: "first_leg", firstLegArrivals }
      : {},
    [arrivalSourceMode, firstLegArrivals]
  );
  const simulatedShortageSummary = useMemo(
    () => piciShortageWindowSummary(item, supplySimulation, supplySummaryOptions),
    [item, supplySimulation, supplySummaryOptions]
  );
  const safetyStockDays = safetyStockDaysForSimulation(supplySimulation, item);
  const standardSalesControlPlan = useMemo(
    () => buildSalesControlPlan(item, {
      id: "standard",
      targetLimitDay: 45,
      title: "爆旺控销策略",
      actionLabel: "填入爆旺控销策略",
      summaryOptions: supplySummaryOptions,
    }),
    [item, supplySummaryOptions]
  );
  const flatSlowSalesControlPlan = useMemo(() => {
    if (!isFlatOrStagnantSalesProperty(item.sales_property)) return null;
    const plan = buildSalesControlPlan(item, {
      id: "flat_slow_ship",
      targetLimitDay: 60,
      title: "平滞慢船控销",
      actionLabel: "填入60天控销+慢船",
      replenishmentMode: "slow_ship_only",
      controlMode: "recovery_segmented",
      summaryOptions: supplySummaryOptions,
    });
    const planSimulation = simulationForSalesControlSegments(plan.segments);
    const planSummary = piciShortageWindowSummary(item, planSimulation, supplySummaryOptions);
    return {
      ...plan,
      slowReplenishmentPlan: summarizeSlowShipWindowBeforeSafetyEnd(item, planSummary.days, safetyStockDays),
    };
  }, [item, supplySummaryOptions, safetyStockDays]);
  const salesControlPlans = useMemo(() => {
    if (!flatSlowSalesControlPlan) return [standardSalesControlPlan];
    return [
      {
        ...flatSlowSalesControlPlan,
        title: "平滞控销策略",
        actionLabel: "填入平滞控销策略",
      },
      {
        ...standardSalesControlPlan,
        title: "爆旺控销策略",
        actionLabel: "填入爆旺控销策略",
      },
    ];
  }, [standardSalesControlPlan, flatSlowSalesControlPlan]);
  const urgentAirReplenishmentPlan = useMemo(
    () => piciShortageWindowSummary(item, simulationForSalesControlOnly(supplySimulation), supplySummaryOptions).urgentAirReplenishmentWindow,
    [item, supplySimulation, supplySummaryOptions]
  );
  const standardAirReplenishmentPlan = useMemo(
    () => piciShortageWindowSummary(item, simulationWithoutChannels(supplySimulation, ["standard_air", "fast_ship", "slow_ship"]), supplySummaryOptions).standardAirReplenishmentWindow,
    [item, supplySimulation, supplySummaryOptions]
  );
  const fastReplenishmentPlan = useMemo(
    () => piciShortageWindowSummary(item, simulationWithoutChannels(supplySimulation, ["fast_ship", "slow_ship"]), supplySummaryOptions).fastReplenishmentWindow,
    [item, supplySimulation, supplySummaryOptions]
  );
  const slowReplenishmentPlan = useMemo(() => {
    const slowSummary = piciShortageWindowSummary(item, simulationWithoutChannels(supplySimulation, ["slow_ship"]), supplySummaryOptions);
    if (supplySimulation?.strategyMode === "slow_ship_only") {
      return summarizeSlowShipWindowBeforeSafetyEnd(item, slowSummary.days, safetyStockDays);
    }
    return slowSummary.slowReplenishmentWindow;
  }, [item, supplySimulation, supplySummaryOptions, safetyStockDays]);
  const replenishmentPlans = {
    urgent_air: urgentAirReplenishmentPlan,
    standard_air: standardAirReplenishmentPlan,
    fast_ship: fastReplenishmentPlan,
    slow_ship: slowReplenishmentPlan,
  };
  const applySalesControlPlan = (planId = "standard") => {
    const selectedPlan = salesControlPlans.find((plan) => plan.id === planId) || salesControlPlans[0];
    const slowSuggestedQuantity = selectedPlan?.slowReplenishmentPlan?.suggestedQuantity || 0;
    const standardShipPlans = standardShipPlansAfterSalesControl(item, supplySimulation, selectedPlan, supplySummaryOptions);
    const fastSuggestedQuantity = standardShipPlans.fast_ship?.suggestedQuantity || 0;
    const standardSlowSuggestedQuantity = standardShipPlans.slow_ship?.suggestedQuantity || 0;
    if (!selectedPlan?.segments?.length && !slowSuggestedQuantity && !fastSuggestedQuantity && !standardSlowSuggestedQuantity) return;
    setSupplySimulation((current) => {
      const empty = createEmptySupplySimulation();
      const plannedSimulation = simulationForSalesControlPlan(current, selectedPlan);
      const nextStandardShipPlans = standardShipPlansAfterSalesControl(item, current, selectedPlan, supplySummaryOptions);
      const nextFastSuggestedQuantity = nextStandardShipPlans.fast_ship?.suggestedQuantity || 0;
      const nextStandardSlowSuggestedQuantity = nextStandardShipPlans.slow_ship?.suggestedQuantity || 0;
      return {
        ...plannedSimulation,
        ...(selectedPlan.replenishmentMode === "slow_ship_only"
          ? {
              urgent_air: { ...empty.urgent_air },
              standard_air: { ...empty.standard_air },
              fast_ship: { ...empty.fast_ship },
              slow_ship: {
                ...empty.slow_ship,
                ...((current || {}).slow_ship || {}),
                replenishQuantity: slowSuggestedQuantity ? String(slowSuggestedQuantity) : "",
              },
            }
          : nextFastSuggestedQuantity || nextStandardSlowSuggestedQuantity
            ? {
                ...(nextFastSuggestedQuantity
                  ? {
                      fast_ship: {
                        ...empty.fast_ship,
                        ...((current || {}).fast_ship || {}),
                        replenishQuantity: String(nextFastSuggestedQuantity),
                      },
                    }
                  : {}),
                ...(nextStandardSlowSuggestedQuantity
                  ? {
                      slow_ship: {
                        ...empty.slow_ship,
                        ...((current || {}).slow_ship || {}),
                        replenishQuantity: String(nextStandardSlowSuggestedQuantity),
                      },
                    }
                  : {}),
              }
            : {}),
      };
    });
  };
  const applyReplenishmentPlan = (channel) => {
    if (supplySimulation?.strategyMode === "slow_ship_only" && channel !== "slow_ship") return;
    const plan = replenishmentPlans[channel];
    setSupplySimulation((current) => ({
      ...createEmptySupplySimulation(),
      ...(current || {}),
      [channel]: {
        ...createEmptySupplySimulation()[channel],
        ...((current || {})[channel] || {}),
        replenishQuantity: plan?.suggestedQuantity ? String(plan.suggestedQuantity) : "",
      },
    }));
  };
  return (
    <>
          <div className="detail-kpis">
            <Metric label="风险" value={riskLabels[item.risk_level] || item.risk_level || "-"} tooltip={RISK_LEVEL_RULE_TOOLTIP} />
            <Metric label="断货" value={formatNumber(simulatedShortageSummary.totalDays) + "天"} tone="warn" tooltip={STOCKOUT_RULE_TOOLTIP} />
            <Metric label="预计7天" value={formatNumber(item.projected_7d)} tone={item.projected_7d < 0 ? "danger" : ""} tooltip="预计7天=FBA可售库存-未来7天需求；小于0说明短期覆盖不足。" />
          </div>

          <DetailSection title="基础信息">
            <DetailGrid
              rows={[
                ["SKU", item.material_code],
                ["MSKU", item.msku],
                ["FNSKU", item.fnsku],
                ["ASIN", item.asin],
                ["店铺", item.store_name],
                ["国家", [item.country_code, item.shipments_country].filter(Boolean).join(" / ")],
                ["销售部门", item.sales_department],
                ["销售员", item.salesman],
                ["产品经理", item.product_manager],
                ["账号", item.seller_id],
                ["销售属性", item.sales_property],
                ["产品属性", item.product_property],
                ["季节属性", item.seasonality],
                ["MSKU状态", item.msku_status],
                ["MSKU生命周期", item.msku_life_process],
                ["物流模式", item.logistics_model],
                ["头程渠道", item.first_leg_logistics_channel],
              ]}
            />
          </DetailSection>

          <DetailSection title="风险判断" tooltip={RISK_LEVEL_RULE_TOOLTIP}>
            <DetailGrid
              rows={[
                ["风险类型", riskTypeLabels[item.risk_type] || item.risk_type, `${RISK_TYPE_RULE_TOOLTIP}\n${ANOMALY_RULE_TOOLTIP}`],
                ["处理等级", riskLabels[item.risk_level] || item.risk_level, RISK_LEVEL_RULE_TOOLTIP],
                ["断货等级", riskLabels[item.stockout_risk_level] || item.stockout_risk_level, STOCKOUT_RULE_TOOLTIP],
                ["冗余等级", riskLabels[item.overstock_risk_level] || item.overstock_risk_level, overstockRuleTooltip(item.sales_property)],
                ["提示", item.warning_type, WARNING_TYPE_RULE_TOOLTIP],
              ]}
            />
          </DetailSection>
          {riskFlags.length > 0 && (
            <DetailSection title="库存异常" tooltip={ANOMALY_RULE_TOOLTIP}>
              <DetailGrid
                rows={riskFlags.map((flag, index) => {
                  const normalized = normalizeRiskFlag(flag, index);
                  return [normalized.label, normalized.reason, ANOMALY_RULE_TOOLTIP];
                })}
              />
            </DetailSection>
          )}

          <DetailSection title="断货明细" tooltip={STOCKOUT_RULE_TOOLTIP}>
            <DetailGrid
              rows={[
                ["最早断货", formatPiciGap(item), "按 chazhi 批次差值找到最早为负的时间点。"],
                ["原始断货", `${formatNumber(shortageSummary.totalDays)} 天`, STOCKOUT_RULE_TOOLTIP],
                ["模拟断货", `${formatNumber(simulatedShortageSummary.totalDays)} 天`, `${STOCKOUT_RULE_TOOLTIP}\n${SUPPLY_CONTROL_RULE_TOOLTIP}`],
                ["最大缺口", formatNumber(item.pici_min_gap_quantity), "0-45天窗口内最深的 chazhi 负缺口。"],
                ["关键缺口", item.pici_key_gap, "优先取最早断货点缺口；无断货时取最后一个批次差值。"],
              ]}
            />
            <SupplyFishboneChart
              item={item}
              weeks={simulatedShortageSummary.fishboneWeeks || []}
              shippingCostEstimate={shippingCostEstimate}
              simulation={supplySimulation}
              onSimulationChange={setSupplySimulation}
              salesControlPlans={salesControlPlans}
              replenishmentPlans={replenishmentPlans}
              onApplySalesControlPlan={applySalesControlPlan}
              onApplyReplenishmentPlan={applyReplenishmentPlan}
              baseTotalDays={shortageSummary.totalDays}
              simulatedTotalDays={simulatedShortageSummary.totalDays}
              arrivalSourceMode={arrivalSourceMode}
              onArrivalSourceModeChange={setArrivalSourceMode}
              firstLegArrivalCount={firstLegArrivals.length}
              firstLegLoading={firstLegLoading}
              firstLegError={firstLegError}
            />
            <div className="pici-list">
              {piciEntries.length > 0 ? (
                piciEntries.map(([key, value]) => (
                  <div key={key} title={STOCKOUT_RULE_TOOLTIP}>
                    <span>{key.replace("_", "-")}天</span>
                    <strong>{value}</strong>
                  </div>
                ))
              ) : (
                <div title="缺少 chazhi 批次差值时，断货判断需要人工复核。">
                  <span>chazhi</span>
                  <strong>无数据</strong>
                </div>
              )}
            </div>
          </DetailSection>

          <DetailSection title="库存结构" tooltip={INVENTORY_STRUCTURE_RULE_TOOLTIP}>
            <DetailGrid
              rows={[
                ["总库存", formatNumber(item.total_inventory), "总库存=FBA库存+海外仓库存+本地仓库存+备货。"],
                ["FBA可售", formatNumber(item.fba_sellable), "FBA前端可售库存，是断货覆盖判断的核心库存。"],
                ["FBA库存", formatNumber(item.fba_inventory), "用于冗余可售天数1和库存结构判断。"],
                ["海外仓", formatNumber(item.overseas_inventory), "用于冗余可售天数3/4和补货覆盖判断。"],
                ["本地仓", formatNumber(item.local_inventory), "用于冗余可售天数5/6和采购前库存判断。"],
                ["在途合计", formatNumber(item.inbound_total), "包含FBA接收/工作、海外/本地在途、仓库在途和计划量。"],
                ["FBA覆盖", `${item.sellable_days ?? "-"} 天`, "优先使用底表FBA可售天数；缺失时用FBA库存/日需求估算。"],
                ["提前期", `${formatNumber(item.lead_time_days)} 天`, "补货倒计时和采购建议的交期参考。"],
              ]}
            />
          </DetailSection>

          <DetailSection title="头程批次" tooltip="头程批次按当前 FNSKU 查询，用于判断在途是否能覆盖断货窗口。">
            <SkuFirstLegSummary
              item={item}
              shipments={firstLegShipments}
              loading={firstLegLoading}
              error={firstLegError}
            />
          </DetailSection>

          <DetailSection title="月度预测复盘" tooltip={FORECAST_RULE_TOOLTIP}>
            <div className="forecast-review-head">
              <div>
                <strong>
                  {forecastReview
                    ? `${formatForecastMonthEstimate(forecastReview.target_month)} vs ${forecastReview.comparison_month} 周度实际`
                    : "按预估月份复盘"}
                </strong>
                <span>来源 {forecastReview?.forecast_source || "dim_lingxing_sales_estimates_monthly_v1"}</span>
              </div>
              <div className="forecast-review-actions">
                {forecastReview && (
                  <button type="button" className="secondary" onClick={() => setForecastDetailOpen(true)}>
                    <span>详情图</span>
                  </button>
                )}
                <button type="button" onClick={() => onForecastReview({ refresh: true })} disabled={forecastReviewLoading}>
                  <RefreshCw size={15} />
                  <span>{forecastReviewLoading ? "复盘中" : "手动复盘"}</span>
                </button>
              </div>
            </div>
            {forecastReviewError && <p className="forecast-review-error">{forecastReviewError}</p>}
            {forecastReview ? (
              <div className={`forecast-review-card ${forecastReview.result_type || ""}`}>
                <div className="forecast-review-result">
                  <span>{forecastReview.result_label || "-"}</span>
                  <strong>{formatPercent(forecastReview.variance_percent)}</strong>
                </div>
                <DetailGrid
                  rows={[
                    ["预估时间", `${formatForecastMonthEstimate(forecastReview.target_month)} · ${forecastReview.target_start_date} 至 ${forecastReview.target_end_date}`],
                    ["对比区间", `${forecastReview.review_start_date || forecastReview.comparison_start_date} 至 ${forecastReview.review_end_date || forecastReview.comparison_end_date}`],
                    ["快照日期", forecastReview.snapshot_date],
                    ["总预测", formatNumber(forecastReview.forecast_quantity)],
                    ["总销量", formatNumber(forecastReview.actual_sales)],
                    ["广告销售额", formatMoney(forecastReview.ad_sales_amount)],
                    ["广告订单量", formatNumber(forecastReview.ad_order_quantity)],
                    ["ACOS", formatRatioPercent(forecastReview.ad_acos)],
                    ["总差值", formatSignedNumber(forecastReview.difference)],
                    ["差值比例", formatPercent(forecastReview.variance_percent)],
                    ["快照行数", formatNumber(forecastReview.snapshot_row_count)],
                    ["预估行数", formatNumber(forecastReview.forecast_row_count)],
                    ["实际行数", formatNumber(forecastReview.actual_row_count)],
                  ]}
                />
                {forecastReview.weekly_estimates?.length > 0 && (
                  <>
                    <ForecastReviewChart
                      points={forecastReview.weekly_estimates}
                      forecastTotal={forecastReview.forecast_quantity}
                      actualTotal={forecastReview.actual_sales}
                      forecastVersions={forecastReview.forecast_versions || []}
                      pricePoints={forecastReview.daily_price_points || []}
                    />
                    <div className="weekly-estimate-list">
                      {forecastReview.weekly_estimates.map((week) => (
                        <div key={week.week}>
                          <span>{formatFullDateRange(week.week_start_date, week.week_end_date) || week.week}</span>
                          <strong>{formatNumber(week.actual_sales)} / {formatNumber(week.forecast_quantity)}</strong>
                          <small>{formatSignedNumber(week.difference)} · {formatPercent(week.variance_percent)}</small>
                          <small>ACOS {formatRatioPercent(week.ad_acos)}</small>
                        </div>
                      ))}
                    </div>
                  </>
                )}
                <p>{lastItem(forecastReview.notes) || "差值 = 实际销量 - 预测销量；比例 = 差值 / 预测销量。"}</p>
              </div>
            ) : (
              <p className="empty-detail">点击手动复盘后，系统会按实际预估月份读取快照，并和后续完整周实际销量对比。</p>
            )}
          </DetailSection>
          {forecastDetailOpen && forecastReview && (
            <ForecastReviewDetailDialog
              item={item}
              forecastReview={forecastReview}
              riskDiagnosis={riskDiagnosis}
              riskDiagnosisLoading={riskDiagnosisLoading}
              riskDiagnosisError={riskDiagnosisError}
              forecastReviewLoading={forecastReviewLoading}
              forecastReviewError={forecastReviewError}
              firstLegLoading={firstLegLoading}
              firstLegError={firstLegError}
              onClose={() => setForecastDetailOpen(false)}
            />
          )}

          <DetailSection title="冗余依据" tooltip={overstockRuleTooltip(item.sales_property)}>
            <DetailGrid
              rows={[
                ["FBA可售天数", formatDays(item.redundancy_sellable_days?.sellable_1), overstockSellableRuleTooltip(item.sales_property, "sellable_1")],
                ["FBA+在途天数", formatDays(item.redundancy_sellable_days?.sellable_2), overstockSellableRuleTooltip(item.sales_property, "sellable_2")],
                ["海外仓天数", formatDays(item.redundancy_sellable_days?.sellable_3), overstockSellableRuleTooltip(item.sales_property, "sellable_3")],
                ["海外+在途天数", formatDays(item.redundancy_sellable_days?.sellable_4), overstockSellableRuleTooltip(item.sales_property, "sellable_4")],
                ["本地仓天数", formatDays(item.redundancy_sellable_days?.sellable_5), overstockSellableRuleTooltip(item.sales_property, "sellable_5")],
                ["全链路天数", formatDays(item.redundancy_sellable_days?.sellable_6), overstockSellableRuleTooltip(item.sales_property, "sellable_6")],
                ["冗余原因", item.evidence?.overstock_reason, "只展示实际命中的可售天数或库龄冗余断言；未命中则不写。"],
              ]}
            />
          </DetailSection>

          <DetailSection title="库龄" tooltip={AGE_RULE_TOOLTIP}>
            <DetailGrid
              rows={[
                ["61-90天", formatNumber(item.fba_age_61_to_90), AGE_ROW_RULE_TOOLTIPS["61-90天"]],
                ["91-180天", formatNumber(item.fba_age_91_to_180), AGE_ROW_RULE_TOOLTIPS["91-180天"]],
                ["181-270天", formatNumber(item.fba_age_181_to_270), AGE_ROW_RULE_TOOLTIPS["181-270天"]],
                ["271-330天", formatNumber(item.fba_age_271_to_330), AGE_ROW_RULE_TOOLTIPS["271-330天"]],
                ["331-365天", formatNumber(item.fba_age_331_to_365), AGE_ROW_RULE_TOOLTIPS["331-365天"]],
                ["365天+", formatNumber(item.fba_age_365_plus), AGE_ROW_RULE_TOOLTIPS["365天+"]],
                ["长库龄合计", formatNumber(item.long_age_inventory), AGE_RULE_TOOLTIP],
                ["长库龄占比", item.fba_long_age_ratio === null || item.fba_long_age_ratio === undefined ? "-" : `${formatNumber(item.fba_long_age_ratio * 100)}%`, AGE_RULE_TOOLTIP],
              ]}
            />
          </DetailSection>

          <DetailSection title="建议动作" tooltip={`${overstockRuleTooltip(item.sales_property)}\n${SUPPLY_CONTROL_RULE_TOOLTIP}`}>
            <div className="action-list empty" aria-label="建议动作待填写" />
          </DetailSection>
    </>
  );
}

function SupplyFishboneChart({
  item,
  weeks,
  shippingCostEstimate,
  simulation,
  onSimulationChange,
  salesControlPlans,
  replenishmentPlans,
  onApplySalesControlPlan,
  onApplyReplenishmentPlan,
  baseTotalDays,
  simulatedTotalDays,
  arrivalSourceMode = "pici",
  onArrivalSourceModeChange,
  firstLegArrivalCount = 0,
  firstLegLoading = false,
  firstLegError = "",
}) {
  if (!weeks.length) {
    return (
      <div className="supply-fishbone empty">
        <span>暂无供货节点</span>
      </div>
    );
  }
  const safetyStockDays = safetyStockDaysForSimulation(simulation, item);
  const displayWeeks = annotateSupplyWeeksForShippingPolicy(weeks, item, safetyStockDays);
  const rows = chunkArray(displayWeeks, 5);
  const costByArrivalDay = shippingCostByArrivalDay(shippingCostEstimate);
  const costByChannel = shippingCostByChannel(shippingCostEstimate);
  const isFirstLegMode = arrivalSourceMode === "first_leg";
  const salesControlGuidance = buildSalesControlGuidance(salesControlPlans);
  const shippingGuidance = buildShippingGuidance(item, displayWeeks);

  return (
    <div className="supply-fishbone" aria-label="周维度供货断货鱼骨图">
      <SupplySimulatorControls
        item={item}
        simulation={simulation}
        onSimulationChange={onSimulationChange}
        costByChannel={costByChannel}
        salesControlPlans={salesControlPlans}
        replenishmentPlans={replenishmentPlans}
        onApplySalesControlPlan={onApplySalesControlPlan}
        onApplyReplenishmentPlan={onApplyReplenishmentPlan}
        baseTotalDays={baseTotalDays}
        simulatedTotalDays={simulatedTotalDays}
      />
      <div className="supply-fishbone-toolbar">
        <span>
          {firstLegLoading
            ? "正在查询头程批次"
            : firstLegError
              ? firstLegError
              : isFirstLegMode
                ? `头程批次 ${formatNumber(firstLegArrivalCount)} 批`
                : "当前按表内累计到货推演"}
        </span>
        <div className="supply-arrival-toggle" aria-label="到货推演口径">
          <button
            type="button"
            className={!isFirstLegMode ? "active" : ""}
            onClick={() => onArrivalSourceModeChange?.("pici")}
          >
            当前到货
          </button>
          <button
            type="button"
            className={isFirstLegMode ? "active" : ""}
            onClick={() => onArrivalSourceModeChange?.("first_leg")}
            disabled={firstLegLoading}
          >
            头程批次
          </button>
        </div>
      </div>
      <div className="supply-fishbone-legend">
        <span className="ok">供货正常</span>
        <span className="shortage">断货</span>
        <span className="sim-replenish">补货覆盖</span>
        <span className="control">控销覆盖</span>
        <span className="safety-stock">安全库存{formatNumber(safetyStockDays)}天</span>
        <span className="post-threshold-goods">安全库存后仍有货</span>
        <span className="arrival">到货</span>
        {isFirstLegMode && <span className="first-leg-arrival">头程批次</span>}
      </div>
      <div className="supply-guidance-strip" aria-label="控销和发货提示">
        <article>
          <span>控销提示</span>
          <strong>{salesControlGuidance.title}</strong>
          <small>{salesControlGuidance.detail}</small>
        </article>
        <article>
          <span>发货提示</span>
          <strong>{shippingGuidance.title}</strong>
          <small>{shippingGuidance.detail}</small>
        </article>
      </div>
      <div className="supply-fishbone-rows">
        {rows.map((row) => {
          const rowShortageDays = row.reduce((total, week) => total + week.shortageDays, 0);
          return (
            <div className="supply-fishbone-row" key={`${row[0].week}-${row[row.length - 1].week}`}>
              <div className="supply-row-summary">
                <span>第 {row[0].week}-{row[row.length - 1].week} 周</span>
                <strong>总计断货 {formatNumber(rowShortageDays)} 天</strong>
              </div>
              <div className="supply-fishbone-track">
                {row.map((week) => (
                  <div className={`supply-week-node ${week.shortageDays > 0 ? "has-shortage" : "ok"}`} key={week.week}>
                    <div className="supply-arrivals">
                      {week.arrivals.length > 0 ? (
                        week.arrivals.map((arrival, index) => (
                          <span
                            className={[
                              arrival.simulated ? "simulated" : "",
                              arrival.firstLeg ? "first-leg" : "",
                              arrival.channel ? `channel-${arrival.channel}` : "",
                            ].filter(Boolean).join(" ")}
                            key={`${week.week}-${arrival.day}-${index}`}
                            title={formatSupplyArrivalTitle(arrival)}
                            aria-label={formatSupplyArrivalTitle(arrival)}
                          >
                            {formatSupplyArrivalLabel(arrival)}
                          </span>
                        ))
                      ) : (
                        <span className="placeholder">无到货</span>
                      )}
                    </div>
                    <div className="supply-week-bar">
                      {week.days.map((day) => (
                        <span className={supplyDayClassName(day)} key={day.day} title={formatSupplyDayTitle(day)}>
                          <SupplyTimelineMarker day={day.day} costEstimate={costByArrivalDay.get(day.day)} estimateStatus={shippingCostEstimate} />
                        </span>
                      ))}
                    </div>
                    <small>
                      第 {formatNumber(week.startDay)}-{formatNumber(week.endDay)} 天
                    </small>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SupplySimulatorControls({
  item,
  simulation,
  onSimulationChange,
  costByChannel,
  salesControlPlans,
  replenishmentPlans,
  onApplySalesControlPlan,
  onApplyReplenishmentPlan,
  baseTotalDays,
  simulatedTotalDays,
}) {
  const update = (channel, field, value) => {
    onSimulationChange((current) => ({
      ...createEmptySupplySimulation(),
      ...(current || {}),
      [channel]: {
        ...createEmptySupplySimulation()[channel],
        ...((current || {})[channel] || {}),
        [field]: value,
      },
    }));
  };
  const salesControlRows = salesControlRowsForSimulation(simulation);
  const updateSalesControl = (index, field, value) => {
    onSimulationChange((current) => ({
      ...createEmptySupplySimulation(),
      ...(current || {}),
      salesControl: { ...createEmptySupplySimulation().salesControl },
      salesControls: salesControlRows.map((row, rowIndex) => (rowIndex === index ? { ...row, [field]: value } : row)),
    }));
  };
  const addSalesControl = () => {
    onSimulationChange((current) => ({
      ...createEmptySupplySimulation(),
      ...(current || {}),
      salesControl: { ...createEmptySupplySimulation().salesControl },
      salesControls: [...salesControlRows, { startDay: "", endDay: "", controlRatio: "" }],
    }));
  };
  const removeSalesControl = (index) => {
    onSimulationChange((current) => ({
      ...createEmptySupplySimulation(),
      ...(current || {}),
      salesControl: { ...createEmptySupplySimulation().salesControl },
      salesControls: salesControlRows.filter((_, rowIndex) => rowIndex !== index),
    }));
  };
  const urgentAirCost = costByChannel.get("urgent_air");
  const standardAirCost = costByChannel.get("standard_air") || costByChannel.get("air_or_urgent_transfer");
  const urgentAirReplenishmentPlan = replenishmentPlans?.urgent_air;
  const standardAirReplenishmentPlan = replenishmentPlans?.standard_air;
  const suggestedUrgentAirQuantity = urgentAirReplenishmentPlan?.suggestedQuantity || 0;
  const suggestedStandardAirQuantity = standardAirReplenishmentPlan?.suggestedQuantity || 0;
  const suggestedUrgentAirCost = urgentAirCost ? suggestedUrgentAirQuantity * Number(urgentAirCost.unit_shipping_cost_cny || 0) : null;
  const suggestedStandardAirCost = standardAirCost ? suggestedStandardAirQuantity * Number(standardAirCost.unit_shipping_cost_cny || 0) : null;
  const controlPlans = (salesControlPlans || []).filter(Boolean);
  const slowCost = costByChannel.get("slow_ship");
  const baselineChannel = baselineShippingChannelForItem(item);
  const baselineCost = baselineChannel ? costByChannel.get(baselineChannel) : null;
  const slowShipOnlyMode = simulation?.strategyMode === "slow_ship_only";
  const activeControlPercentText = formatControlRowsPercentText(salesControlRows);
  const controlQuantitySummary = buildSalesControlQuantitySummary(item, simulation, salesControlRows);
  const safetyStockDays = safetyStockDaysForSimulation(simulation, item);
  const updateSafetyStockDays = (value) => {
    onSimulationChange((current) => ({
      ...createEmptySupplySimulation(item),
      ...(current || {}),
      safetyStockDays: value,
    }));
  };

  return (
    <div className="supply-simulator">
      <div className="supply-simulator-head">
        <strong>补货模拟 / 独立控销</strong>
        <div className="supply-simulator-head-actions">
          <label className="supply-safety-stock-control">
            <span>安全库存</span>
            <input
              min="0"
              step="1"
              type="number"
              value={simulation?.safetyStockDays ?? String(safetyStockDays)}
              onChange={(event) => updateSafetyStockDays(event.target.value)}
            />
            <small>天</small>
          </label>
          <span>原始 {formatNumber(baseTotalDays)} 天 · 模拟 {formatNumber(simulatedTotalDays)} 天</span>
        </div>
      </div>
      {controlPlans.map((plan) => {
        const salesControlSegments = plan?.segments || [];
        const unresolvedControlSegments = plan?.unresolvedSegments || [];
        const unresolvedControlText = unresolvedControlSegments.flatMap((segment) => segment.shortageSegments || [segment]).map((segment) => `第${formatNumber(segment.startDay)}-${formatNumber(segment.endDay)}天`).join("、");
        const targetLimitDay = plan?.targetLimitDay || 45;
        const controlPlanName = plan?.title || (plan?.strategy === "balanced" ? "提前平滑控销" : "多段控销填入");
        const controlPlanActionName = plan?.actionLabel || (plan?.strategy === "balanced" ? "填入平滑控销" : "填入多段控销");
        const controlPlanNote = plan?.strategy === "balanced" ? `提前均摊后${formatNumber(targetLimitDay)}天前不断货` : `可控段填入后${formatNumber(targetLimitDay)}天前不断货`;
        const slowShipPolicyWindowText = `第${formatNumber(SLOW_SHIP_REPLENISHMENT_START_DAY)}-${formatNumber(shippingPolicyForItem(item).cutoffDay)}天`;
        const slowSuggestedQuantity = plan?.slowReplenishmentPlan?.suggestedQuantity || 0;
        const fastSuggestedQuantity = plan?.replenishmentMode === "slow_ship_only" ? 0 : replenishmentPlans?.fast_ship?.suggestedQuantity || 0;
        const standardSlowSuggestedQuantity = plan?.replenishmentMode === "slow_ship_only" ? 0 : replenishmentPlans?.slow_ship?.suggestedQuantity || 0;
        const slowSuggestedCost = slowCost ? slowSuggestedQuantity * Number(slowCost.unit_shipping_cost_cny || 0) : null;
        const canApplyPlan = Boolean(salesControlSegments.length || slowSuggestedQuantity || fastSuggestedQuantity || standardSlowSuggestedQuantity);
        return (
          <div className={`sales-control-plan ${plan?.replenishmentMode === "slow_ship_only" ? "slow-only" : ""}`} aria-label="控销动态建议" key={plan?.id || controlPlanName}>
            <div>
              <span>{controlPlanName}</span>
              <strong>
                {salesControlSegments.length
                  ? salesControlSegments.map((segment) => `第${formatNumber(segment.startDay)}-${formatNumber(segment.endDay)}天 控${formatNumber(segment.controlRatio)}%`).join("；")
                  : `${formatNumber(targetLimitDay)}天前无需控销`}
              </strong>
            </div>
            <small>
              {salesControlSegments.length
                ? `共 ${formatNumber(salesControlSegments.length)} 段，控销 ${formatControlSegmentsPercentText(salesControlSegments)}`
                : `现有数量可覆盖${formatNumber(targetLimitDay)}天前需求`}
              {plan?.residualShortageQuantity
                ? ` · 控销后仍缺 ${formatNumber(plan.residualShortageQuantity)} 件`
                : salesControlSegments.length
                  ? ` · ${controlPlanNote}`
                  : ` · ${formatNumber(targetLimitDay)}天前无需控销`}
              {unresolvedControlText ? ` · 仍会断货：${unresolvedControlText}` : ""}
              {plan?.replenishmentMode === "slow_ship_only"
                ? slowSuggestedQuantity
                  ? (
                      <>
                        {` · 仅慢船${slowShipPolicyWindowText}建议 `}
                        <span className="supply-channel-quantity slow-quantity">{formatNumber(slowSuggestedQuantity)} 件</span>
                        {slowSuggestedCost !== null ? ` / ${formatMoney(slowSuggestedCost)} 元` : ""}
                      </>
                    )
                  : ` · 慢船${slowShipPolicyWindowText}暂无缺口`
                : ""}
            </small>
            <button type="button" className="supply-suggestion-button" onClick={() => onApplySalesControlPlan(plan?.id)} disabled={!canApplyPlan}>
              {controlPlanActionName}
            </button>
          </div>
        );
      })}
      <div className="air-window-plan" aria-label="空运动态补货建议">
        <div>
          <span>空运覆盖窗口</span>
          <strong>
            加急第10-19天 <span className="supply-channel-quantity urgent-air-quantity">{formatNumber(suggestedUrgentAirQuantity)} 件</span>
            {" · "}
            普通第20-45天 <span className="supply-channel-quantity standard-air-quantity">{formatNumber(suggestedStandardAirQuantity)} 件</span>
          </strong>
        </div>
        <small>
          按当前控销动态计算
          {(urgentAirReplenishmentPlan?.controlSavedQuantity || standardAirReplenishmentPlan?.controlSavedQuantity) && activeControlPercentText !== "-" ? ` · 控销 ${activeControlPercentText}` : ""}
          {suggestedUrgentAirCost !== null ? ` · 加急 ${formatMoney(suggestedUrgentAirCost)} 元` : ""}
          {suggestedStandardAirCost !== null ? ` · 普通 ${formatMoney(suggestedStandardAirCost)} 元` : ""}
          {slowShipOnlyMode ? " · 慢船模式不填空运" : ""}
        </small>
      </div>
      <div className="supply-simulator-grid">
        {SUPPLY_SIMULATION_CHANNELS.map((channel) => {
          const values = simulation?.[channel.channel] || {};
          const cost = costByChannel.get(channel.channel);
          const replenishQuantity = Math.max(Number(values.replenishQuantity) || 0, 0);
          const replenishCost = cost ? replenishQuantity * Number(cost.unit_shipping_cost_cny || 0) : null;
          const plan = replenishmentPlans?.[channel.channel] || {};
          const disabledByStrategy = slowShipOnlyMode && channel.channel !== "slow_ship";
          const suggestedQuantity = disabledByStrategy ? 0 : plan.suggestedQuantity || 0;
          const suggestedCost = cost ? suggestedQuantity * Number(cost.unit_shipping_cost_cny || 0) : null;
          const marginImpactQuantity = replenishQuantity || suggestedQuantity;
          const marginImpact = buildMarginImpactEstimate(item, cost, baselineCost, marginImpactQuantity);
          return (
            <article className={`supply-simulator-card ${channel.className} ${disabledByStrategy ? "strategy-disabled" : ""}`} key={channel.channel}>
              <div className="supply-simulator-card-head">
                <strong>{channel.shortLabel}</strong>
                <span>第{formatNumber(channel.arrivalDay)}天到</span>
              </div>
              <div className="supply-simulator-inputs">
                <label className="wide">
                  <span>补</span>
                  <input
                    min="0"
                    step="1"
                    type="number"
                    value={values.replenishQuantity ?? ""}
                    disabled={disabledByStrategy}
                    onChange={(event) => update(channel.channel, "replenishQuantity", event.target.value)}
                  />
                </label>
                <button type="button" className="supply-suggestion-button" onClick={() => onApplyReplenishmentPlan(channel.channel)} disabled={disabledByStrategy || !suggestedQuantity}>
                  填入{channel.windowLabel}缺口
                </button>
              </div>
              <small>
                {cost ? `单件 ${formatMoney(cost.unit_shipping_cost_cny)} 元` : "单件运费 -"}
                {replenishQuantity ? (
                  <>
                    {" · 已填 "}
                    <span className="supply-channel-quantity">{formatNumber(replenishQuantity)} 件</span>
                  </>
                ) : ""}
                {replenishCost ? ` · ${formatMoney(replenishCost)} 元` : ""}
                {disabledByStrategy ? (
                  " · 慢船模式不填入"
                ) : suggestedQuantity ? (
                  <>
                    {" · 建议 "}
                    <span className="supply-channel-quantity">{formatNumber(suggestedQuantity)} 件</span>
                  </>
                ) : (
                  " · 暂无缺口"
                )}
                {suggestedCost ? ` · 建议成本 ${formatMoney(suggestedCost)} 元` : ""}
                {marginImpact && <span className="margin-impact-text">{formatMarginImpactText(marginImpact)}</span>}
              </small>
            </article>
          );
        })}
      </div>
      <article className="supply-control-card">
        <div className="supply-simulator-card-head">
          <strong>控销时段</strong>
          <div className="supply-control-head-meta">
            <span>支持多段，最高60%</span>
            <span className="supply-control-total-badge" title={formatControlQuantityTitle(controlQuantitySummary)}>
              合计 {formatControlQuantityPerDay(controlQuantitySummary.averagePerDay)} 个/天
            </span>
          </div>
        </div>
        <div className="supply-control-inputs">
          {salesControlRows.map((salesControl, index) => {
            const rowSummary = controlQuantitySummary.rowSummaries[index] || {};
            return (
              <div className="supply-control-row" key={`sales-control-${index}`}>
                <label>
                  <span>起</span>
                  <input
                    min="1"
                    step="1"
                    type="number"
                    value={salesControl.startDay ?? ""}
                    onChange={(event) => updateSalesControl(index, "startDay", event.target.value)}
                  />
                </label>
                <label>
                  <span>止</span>
                  <input
                    min="1"
                    step="1"
                    type="number"
                    value={salesControl.endDay ?? ""}
                    onChange={(event) => updateSalesControl(index, "endDay", event.target.value)}
                  />
                </label>
                <label>
                  <span>控%</span>
                  <input
                    max="60"
                    min="0"
                    step="1"
                    type="number"
                    value={salesControl.controlRatio ?? ""}
                    onChange={(event) => updateSalesControl(index, "controlRatio", event.target.value)}
                  />
                </label>
                <span className="supply-control-row-total" title={formatControlQuantityTitle(rowSummary)}>
                  约 {formatControlQuantityPerDay(rowSummary.averagePerDay)} 个/天
                </span>
                <button type="button" className="supply-remove-button" onClick={() => removeSalesControl(index)} disabled={salesControlRows.length <= 1}>
                  删除
                </button>
              </div>
            );
          })}
          <button type="button" className="supply-add-button" onClick={addSalesControl}>
            增加控销段
          </button>
        </div>
      </article>
    </div>
  );
}

function supplyDayClassName(day) {
  return [
    day.status,
    day.shippingWindowStatus || "",
    day.shippingSafetyStartBoundary ? "safety-start-boundary" : "",
    day.shippingSafetyEndBoundary ? "safety-end-boundary" : "",
    day.controlRatio > 0 ? "has-control" : "",
    day.partialReplenished ? "partial-replenished" : "",
    day.replenishmentChannel ? `channel-${day.replenishmentChannel}` : "",
  ]
    .filter(Boolean)
    .join(" ");
}

function formatSupplyDayTitle(day) {
  const statusLabel = day.status === "shortage" ? "断货" : day.status === "replenished" ? "补货覆盖" : "供货正常";
  const parts = [`第 ${day.day} 天 ${statusLabel}`];
  if (day.shippingWindowStatus === "safety-stock") {
    parts.push(`${day.shippingPolicyLabel || "当前"}款 ${formatNumber(day.shippingCutoffDay)} 天后保留 ${formatNumber(day.shippingSafetyStockDays)} 天安全库存窗口`);
  }
  if (day.shippingWindowStatus === "post-threshold-goods") {
    parts.push(`${day.shippingPolicyLabel || "当前"}款超过 ${formatNumber(day.shippingSafetyEndDay)} 天安全库存后仍有货/到货 ${formatNumber(day.shippingArrivalQuantity)} 件，复核是否多发`);
  }
  if (day.shippingWindowStatus === "post-threshold-replenished") {
    parts.push(`${day.shippingPolicyLabel || "当前"}款超过 ${formatNumber(day.shippingSafetyEndDay)} 天安全库存后由补货覆盖 ${formatNumber(day.shippingArrivalQuantity)} 件，复核是否仍需发货`);
  }
  if (day.controlSavedQuantity > 0) parts.push(`控销减少 ${formatPreciseNumber(day.controlSavedQuantity)} 件需求`);
  if (day.shortageQuantity > 0) parts.push(`剩余缺口 ${formatPreciseNumber(day.shortageQuantity)} 件`);
  if (day.replenishedQuantity > 0) parts.push(`${supplyChannelLabel(day.replenishmentChannel)}消耗 ${formatPreciseNumber(day.replenishedQuantity)} 件`);
  if (day.forecast > 0) parts.push(`需求 ${formatPreciseNumber(day.forecast)} 件`);
  return parts.join("\n");
}

function formatSupplyArrivalTitle(arrival) {
  const typeLabel = arrival.simulated ? "模拟补货" : arrival.firstLeg ? "头程批次到货" : "到货";
  const parts = [`第 ${arrival.day} 天${typeLabel} +${formatNumber(arrival.quantity)}`];
  if (arrival.date) parts.push(`到货日期 ${arrival.date}`);
  if (arrival.firstLeg && Array.isArray(arrival.batches) && arrival.batches.length > 0) {
    parts.push(`共 ${formatNumber(arrival.batches.length)} 单`);
    arrival.batches.forEach((batch) => {
      const detailParts = [
        batch.batchLabel || "未命名单据",
        `+${formatNumber(batch.quantity)}`,
        batch.status,
        batch.method,
      ].filter(Boolean);
      parts.push(`- ${detailParts.join(" · ")}`);
    });
    return parts.join("\n");
  }
  if (arrival.batchLabel) parts.push(`批次 ${arrival.batchLabel}`);
  if (arrival.status) parts.push(`状态 ${arrival.status}`);
  if (arrival.method) parts.push(`物流 ${arrival.method}`);
  return parts.join("\n");
}

function formatSupplyArrivalLabel(arrival) {
  const typeLabel = arrival.simulated ? "补" : arrival.firstLeg ? "头程" : "到货";
  const batchCount = arrival.firstLeg && Array.isArray(arrival.batches) && arrival.batches.length > 1
    ? ` · ${formatNumber(arrival.batches.length)}单`
    : "";
  return `${typeLabel} +${formatNumber(arrival.quantity)}${batchCount}`;
}

function formatControlSegmentsPercentText(segments = []) {
  const normalized = (segments || [])
    .map((segment) => ({
      startDay: Number(segment.startDay),
      endDay: Number(segment.endDay),
      controlRatio: Number(segment.controlRatio),
    }))
    .filter((segment) => Number.isFinite(segment.controlRatio) && segment.controlRatio > 0);
  if (!normalized.length) return "-";
  const ratios = Array.from(new Set(normalized.map((segment) => formatNumber(segment.controlRatio))));
  if (ratios.length === 1) return `${ratios[0]}%`;
  return normalized.map((segment) => `第${formatNumber(segment.startDay)}-${formatNumber(segment.endDay)}天 ${formatNumber(segment.controlRatio)}%`).join("；");
}

function formatControlRowsPercentText(rows = []) {
  const segments = (rows || []).filter((row) => Number(row.controlRatio) > 0);
  return formatControlSegmentsPercentText(segments);
}

function buildSalesControlQuantitySummary(item = {}, simulation = null, rows = []) {
  const rowSummaries = (rows || []).map(() => ({
    averagePerDay: null,
    totalQuantity: 0,
    days: 0,
  }));
  const normalizedRows = normalizeSalesControlRowsWithIndex(rows);
  if (!normalizedRows.length) {
    return { averagePerDay: null, totalQuantity: 0, days: 0, rowSummaries };
  }

  const controlSimulation = {
    ...createEmptySupplySimulation(item),
    ...(simulation || {}),
    salesControl: { ...createEmptySupplySimulation().salesControl },
    salesControls: normalizedRows.map(({ startDay, endDay, controlRatio }) => ({ startDay, endDay, controlRatio })),
  };
  const summary = piciShortageWindowSummary(item, controlSimulation);
  const days = Array.isArray(summary.days) ? summary.days : [];
  const dayByNumber = new Map(days.map((day) => [Number(day.day), day]));
  const activeDays = days.filter((day) => Number(day.controlSavedQuantity || 0) > 0);
  const totalQuantity = activeDays.reduce((total, day) => total + Math.max(Number(day.controlSavedQuantity || 0), 0), 0);

  normalizedRows.forEach((row) => {
    let rowTotal = 0;
    let rowDays = 0;
    for (let day = row.startDay; day <= row.endDay; day += 1) {
      const dayData = dayByNumber.get(day);
      const originalForecast = Number(dayData?.originalForecast || 0);
      if (originalForecast <= 0) continue;
      rowTotal += originalForecast * row.controlRatio / 100;
      rowDays += 1;
    }
    rowSummaries[row.index] = {
      averagePerDay: rowDays ? rowTotal / rowDays : null,
      totalQuantity: rowTotal,
      days: rowDays,
    };
  });

  return {
    averagePerDay: activeDays.length ? totalQuantity / activeDays.length : null,
    totalQuantity,
    days: activeDays.length,
    rowSummaries,
  };
}

function normalizeSalesControlRowsWithIndex(rows = []) {
  return (rows || [])
    .map((row, index) => {
      const startDay = Number(row?.startDay);
      const endDay = Number(row?.endDay);
      const controlRatio = Math.max(0, Math.min(Number(row?.controlRatio) || 0, 60));
      if (!Number.isFinite(startDay) || !Number.isFinite(endDay) || startDay <= 0 || endDay <= 0 || !controlRatio) {
        return null;
      }
      return {
        index,
        startDay: Math.min(startDay, endDay),
        endDay: Math.max(startDay, endDay),
        controlRatio,
      };
    })
    .filter(Boolean);
}

function formatControlQuantityPerDay(value) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) return "-";
  return formatPreciseNumber(number);
}

function formatControlQuantityTitle(summary = {}) {
  const days = Number(summary.days || 0);
  const total = Number(summary.totalQuantity || 0);
  const average = Number(summary.averagePerDay || 0);
  if (!days || !Number.isFinite(total) || total <= 0) {
    return "当前控销段暂无可计算的预测需求";
  }
  return `累计控销约 ${formatPreciseNumber(total)} 个，覆盖 ${formatNumber(days)} 天，平均 ${formatPreciseNumber(average)} 个/天`;
}

function dominantReplenishmentChannel(quantityByChannel) {
  return Object.entries(quantityByChannel || {}).sort((left, right) => Number(right[1] || 0) - Number(left[1] || 0))[0]?.[0] || "";
}

function supplyChannelLabel(channel) {
  if (channel === "urgent_air") return "加急空运补货";
  if (channel === "standard_air" || channel === "air_or_urgent_transfer") return "普通空运补货";
  if (channel === "fast_ship") return "快船补货";
  if (channel === "slow_ship") return "慢船补货";
  return "补货";
}

const SUPPLY_TIMELINE_MARKERS = {
  10: { icon: Plane, channel: "urgent_air", className: "urgent-air", label: "加急空运 10天" },
  20: { icon: Plane, channel: "standard_air", className: "standard-air", label: "普通空运 20天" },
  45: { icon: Ship, channel: "fast_ship", className: "fast-ship", label: "加急快船45天" },
  60: { icon: Ship, channel: "slow_ship", className: "slow-ship", label: "慢船 60天" },
};

const SUPPLY_SIMULATION_CHANNELS = [
  {
    channel: "urgent_air",
    shortLabel: "加急空运",
    className: "urgent-air",
    arrivalDay: 10,
    windowLabel: "10-19",
  },
  {
    channel: "standard_air",
    shortLabel: "普通空运",
    className: "standard-air",
    arrivalDay: 20,
    windowLabel: "20-45",
  },
  {
    channel: "fast_ship",
    shortLabel: "快船",
    className: "fast-ship",
    arrivalDay: 45,
    windowLabel: "45-60",
  },
  {
    channel: "slow_ship",
    shortLabel: "慢船",
    className: "slow-ship",
    arrivalDay: 60,
    windowLabel: "60天后",
  },
];

const FLAT_STAGNANT_SHIPPING_CUTOFF_DAY = 75;
const BOOM_WANG_SHIPPING_CUTOFF_DAY = 90;
const SLOW_SHIP_REPLENISHMENT_START_DAY = 61;
const BOOM_WANG_DEFAULT_SAFETY_STOCK_DAYS = 10;
const FLAT_STAGNANT_DEFAULT_SAFETY_STOCK_DAYS = 0;
const FISHBONE_EXTRA_WEEK_DAYS = 7;

function createEmptySupplySimulation(item = null) {
  const result = SUPPLY_SIMULATION_CHANNELS.reduce((items, channel) => {
    items[channel.channel] = { replenishQuantity: "" };
    return items;
  }, {});
  result.strategyMode = "";
  result.safetyStockDays = item ? String(defaultSafetyStockDaysForItem(item)) : "";
  result.salesControl = { startDay: "", endDay: "", controlRatio: "" };
  result.salesControls = [];
  return result;
}

function salesControlRowsForSimulation(simulation) {
  const source = simulation || {};
  if (Array.isArray(source.salesControls) && source.salesControls.length > 0) {
    return source.salesControls;
  }
  if (source.salesControl && Object.values(source.salesControl).some((value) => value !== "" && value !== null && value !== undefined)) {
    return [source.salesControl];
  }
  return [{ startDay: "", endDay: "", controlRatio: "" }];
}

function simulationForSalesControlOnly(simulation) {
  const empty = createEmptySupplySimulation();
  const source = simulation || {};
  return {
    ...empty,
    salesControl: { ...empty.salesControl, ...(source.salesControl || {}) },
    salesControls: Array.isArray(source.salesControls) ? source.salesControls : [],
  };
}

function simulationForSalesControlSegments(segments = []) {
  return {
    ...createEmptySupplySimulation(),
    salesControls: (segments || []).map((segment) => ({
      startDay: segment.startDay,
      endDay: segment.endDay,
      controlRatio: segment.controlRatio,
    })),
  };
}

function simulationForSalesControlPlan(currentSimulation, plan) {
  const empty = createEmptySupplySimulation();
  return {
    ...empty,
    ...(currentSimulation || {}),
    strategyMode: plan?.replenishmentMode === "slow_ship_only" ? "slow_ship_only" : "",
    salesControl: { ...empty.salesControl },
    salesControls: (plan?.segments || []).map((segment) => ({
      startDay: String(segment.startDay),
      endDay: String(segment.endDay),
      controlRatio: String(segment.controlRatio),
    })),
  };
}

function standardShipPlansAfterSalesControl(item, currentSimulation, plan, summaryOptions = {}) {
  if (!plan || plan.replenishmentMode === "slow_ship_only") {
    return { fast_ship: null, slow_ship: null };
  }
  const empty = createEmptySupplySimulation();
  const plannedSimulation = simulationForSalesControlPlan(currentSimulation, plan);
  const fastWindow = piciShortageWindowSummary(
    item,
    simulationWithoutChannels(plannedSimulation, ["fast_ship", "slow_ship"]),
    summaryOptions
  ).fastReplenishmentWindow;
  const fastSuggestedQuantity = fastWindow?.suggestedQuantity || 0;
  const withFastShip = {
    ...plannedSimulation,
    fast_ship: {
      ...empty.fast_ship,
      replenishQuantity: fastSuggestedQuantity ? String(fastSuggestedQuantity) : "",
    },
  };
  const slowWindow = piciShortageWindowSummary(
    item,
    simulationWithoutChannels(withFastShip, ["slow_ship"]),
    summaryOptions
  ).slowReplenishmentWindow;
  return { fast_ship: fastWindow, slow_ship: slowWindow };
}

function simulationWithoutChannels(simulation, channels = []) {
  const blocked = new Set(channels);
  const empty = createEmptySupplySimulation();
  const source = {
    ...empty,
    ...(simulation || {}),
  };
  blocked.forEach((channel) => {
    source[channel] = { ...empty[channel] };
  });
  return source;
}

function isFlatOrStagnantSalesProperty(value) {
  const text = String(value || "").trim();
  return text.includes("平") || text.includes("滞");
}

function isBoomOrWangSalesProperty(value) {
  const text = String(value || "").trim();
  return text.includes("爆") || text.includes("旺");
}

function overstockRuleHintForSalesProperty(value) {
  return isFlatOrStagnantSalesProperty(value)
    ? { key: "flat_stagnant", ...OVERSTOCK_RULE_HINTS.flat_stagnant }
    : { key: "boom_wang", ...OVERSTOCK_RULE_HINTS.boom_wang };
}

function formatOverstockRuleHintText(salesProperty) {
  const hint = overstockRuleHintForSalesProperty(salesProperty);
  return `${hint.label}冗余口径：${hint.lines.join("；")}`;
}

function overstockRuleTooltip(salesProperty) {
  const hint = overstockRuleHintForSalesProperty(salesProperty);
  return [`${hint.label}冗余判断：`, ...hint.lines, AGE_RULE_TOOLTIP].join("\n");
}

function overstockSellableRuleTooltip(salesProperty, sellableKey) {
  const hint = overstockRuleHintForSalesProperty(salesProperty);
  return hint.sellable?.[sellableKey] || overstockRuleTooltip(salesProperty);
}

function defaultSafetyStockDaysForItem(item = {}) {
  return isFlatOrStagnantSalesProperty(item.sales_property)
    ? FLAT_STAGNANT_DEFAULT_SAFETY_STOCK_DAYS
    : BOOM_WANG_DEFAULT_SAFETY_STOCK_DAYS;
}

function safetyStockDaysForSimulation(simulation, item = {}) {
  const fallback = defaultSafetyStockDaysForItem(item);
  const rawValue = simulation?.safetyStockDays;
  if (rawValue === "" || rawValue === null || rawValue === undefined) return fallback;
  const value = Math.max(0, Number(rawValue));
  return Number.isFinite(value) ? value : fallback;
}

function shippingPolicyForItem(item = {}) {
  const flatOrStagnant = isFlatOrStagnantSalesProperty(item.sales_property);
  return {
    label: flatOrStagnant ? "平滞" : isBoomOrWangSalesProperty(item.sales_property) ? "爆旺" : "爆旺",
    cutoffDay: flatOrStagnant ? FLAT_STAGNANT_SHIPPING_CUTOFF_DAY : BOOM_WANG_SHIPPING_CUTOFF_DAY,
  };
}

function shippingSafetyEndDayForItem(item = {}, safetyStockDays = defaultSafetyStockDaysForItem(item)) {
  return shippingPolicyForItem(item).cutoffDay + Math.max(0, Number(safetyStockDays) || 0);
}

function summarizeSlowShipWindowBeforeSafetyEnd(item = {}, days = [], safetyStockDays = defaultSafetyStockDaysForItem(item)) {
  return summarizeSupplyWindow(days, SLOW_SHIP_REPLENISHMENT_START_DAY, shippingSafetyEndDayForItem(item, safetyStockDays));
}

function annotateSupplyWeeksForShippingPolicy(weeks = [], item = {}, safetyStockDays = defaultSafetyStockDaysForItem(item)) {
  const policy = shippingPolicyForItem(item);
  const normalizedSafetyStockDays = Math.max(0, Number(safetyStockDays) || 0);
  const safetyEndDay = policy.cutoffDay + normalizedSafetyStockDays;
  return (Array.isArray(weeks) ? weeks : []).map((week) => {
    const arrivalQuantityByDay = new Map();
    (week.arrivals || []).forEach((arrival) => {
      const day = Number(arrival.day);
      const quantity = Number(arrival.quantity) || 0;
      if (!Number.isFinite(day) || quantity <= 0) return;
      arrivalQuantityByDay.set(day, (arrivalQuantityByDay.get(day) || 0) + quantity);
    });
    return {
      ...week,
      days: (week.days || []).map((day) => {
        const dayNumber = Number(day?.day);
        if (!day || dayNumber <= policy.cutoffDay) return day;
        const arrivalQuantity = arrivalQuantityByDay.get(Number(day.day)) || 0;
        const replenishedQuantity = Number(day.replenishedQuantity) || 0;
        if (dayNumber <= safetyEndDay) {
          return {
            ...day,
            shippingPolicyLabel: policy.label,
            shippingCutoffDay: policy.cutoffDay,
            shippingSafetyStockDays: normalizedSafetyStockDays,
            shippingSafetyEndDay: safetyEndDay,
            shippingSafetyStartBoundary: dayNumber === policy.cutoffDay + 1,
            shippingSafetyEndBoundary: dayNumber === safetyEndDay,
            shippingWindowStatus: "safety-stock",
            shippingArrivalQuantity: roundToOne(Math.max(arrivalQuantity, replenishedQuantity)),
          };
        }
        const hasGoods = day.status !== "shortage" || arrivalQuantity > 0 || replenishedQuantity > 0;
        const shippingWindowStatus = replenishedQuantity > 0 ? "post-threshold-replenished" : hasGoods ? "post-threshold-goods" : "";
        return {
          ...day,
          shippingPolicyLabel: policy.label,
          shippingCutoffDay: policy.cutoffDay,
          shippingSafetyStockDays: normalizedSafetyStockDays,
          shippingSafetyEndDay: safetyEndDay,
          shippingWindowStatus,
          shippingArrivalQuantity: roundToOne(Math.max(arrivalQuantity, replenishedQuantity)),
        };
      }),
    };
  });
}

function buildSalesControlGuidance(plans = []) {
  const controlPlans = (Array.isArray(plans) ? plans : []).filter(Boolean);
  const plan = controlPlans[0];
  const segments = plan?.segments || [];
  const targetLimitDay = plan?.targetLimitDay || 45;
  const logicLabel = String(plan?.title || "").includes("平滞") || String(plan?.id || "").includes("flat") ? "平滞控销口径" : "爆旺逻辑";
  if (!segments.length) {
    return {
      title: `按${logicLabel}，${formatNumber(targetLimitDay)}天前无需控销`,
      detail: "现有供货可覆盖目标窗口。",
    };
  }
  const controlDays = countCoveredDays(segments);
  const controlText = segments.map((segment) => `第${formatNumber(segment.startDay)}-${formatNumber(segment.endDay)}天控${formatNumber(segment.controlRatio)}%`).join("；");
  const residualText = plan?.residualShortageQuantity ? `；控销后仍缺 ${formatNumber(plan.residualShortageQuantity)} 件` : "";
  return {
    title: `按${logicLabel}，建议控销 ${formatNumber(controlDays)} 天`,
    detail: `${controlText}${residualText}。`,
  };
}

function buildShippingGuidance(item = {}, weeks = []) {
  const policy = shippingPolicyForItem(item);
  const days = (Array.isArray(weeks) ? weeks : []).flatMap((week) => week.days || []);
  const channelParts = SUPPLY_SIMULATION_CHANNELS
    .filter((channel) => channel.arrivalDay < policy.cutoffDay)
    .map((channel) => {
      const window = summarizeSupplyWindow(days, channel.arrivalDay, policy.cutoffDay);
      return `${channel.shortLabel}发货日+${formatNumber(channel.arrivalDay)}天起 ${formatNumber(window.suggestedQuantity)} 件`;
    });
  return {
    title: `${policy.label}款按发货日起 ${formatNumber(policy.cutoffDay)} 天内缺口计算发货量`,
    detail: `${channelParts.join("；")}。${formatNumber(policy.cutoffDay)}天后蓝色=不建议发货，紫色=补货覆盖需复核，橘色=已有/仍有货需复核。`,
  };
}

function countCoveredDays(segments = []) {
  const days = new Set();
  (segments || []).forEach((segment) => {
    const startDay = Math.min(Number(segment.startDay) || 0, Number(segment.endDay) || 0);
    const endDay = Math.max(Number(segment.startDay) || 0, Number(segment.endDay) || 0);
    for (let day = startDay; day <= endDay; day += 1) {
      if (day > 0) days.add(day);
    }
  });
  return days.size;
}

function normalizeSupplySimulation(simulation) {
  const source = simulation && typeof simulation === "object" ? simulation : {};
  const result = SUPPLY_SIMULATION_CHANNELS.reduce((items, channel) => {
    const legacyAirValues = channel.channel === "standard_air" ? source.air_or_urgent_transfer || {} : {};
    const values = source[channel.channel] || legacyAirValues || {};
    items[channel.channel] = {
      ...channel,
      replenishQuantity: Math.max(Number(values.replenishQuantity) || 0, 0),
    };
    return items;
  }, {});
  result.salesControls = normalizeSalesControlSegments(source);
  result.salesControl = result.salesControls[0] || { startDay: null, endDay: null, controlRatio: 0 };
  return result;
}

function normalizeSalesControlSegments(source) {
  const rawSegments = [];
  if (Array.isArray(source.salesControls)) {
    rawSegments.push(...source.salesControls);
  }
  if (source.salesControl && typeof source.salesControl === "object") {
    rawSegments.push(source.salesControl);
  }
  return rawSegments
    .map((control) => {
      const startDay = Number(control.startDay);
      const endDay = Number(control.endDay);
      const controlRatio = Math.max(0, Math.min(Number(control.controlRatio) || 0, 60));
      if (!Number.isFinite(startDay) || !Number.isFinite(endDay) || startDay <= 0 || endDay <= 0 || !controlRatio) {
        return null;
      }
      return {
        startDay: Math.min(startDay, endDay),
        endDay: Math.max(startDay, endDay),
        controlRatio,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.startDay - b.startDay || a.endDay - b.endDay);
}

function simulatedArrivalForDay(simulationConfig, day) {
  for (const channel of SUPPLY_SIMULATION_CHANNELS) {
    const values = simulationConfig[channel.channel];
    if (values.arrivalDay === day && values.replenishQuantity > 0) {
      return { channel: values.channel, quantity: values.replenishQuantity };
    }
  }
  return { channel: "", quantity: 0 };
}

function controlRatioForDay(simulationConfig, day) {
  return Math.min(
    60,
    Math.max(
      0,
      ...(simulationConfig.salesControls || []).map((control) =>
        day >= control.startDay && day <= control.endDay ? control.controlRatio : 0
      )
    )
  );
}

function SupplyTimelineMarker({ day, costEstimate, estimateStatus }) {
  const marker = SUPPLY_TIMELINE_MARKERS[day];
  if (!marker) return null;
  const Icon = marker.icon;
  const label = formatSupplyMarkerTooltip(marker.label, costEstimate, estimateStatus);
  return (
    <span className={`supply-day-marker ${marker.className}`} title={label} aria-label={label}>
      <Icon size={15} strokeWidth={2.8} />
    </span>
  );
}

function shippingCostByArrivalDay(estimate) {
  const map = new Map();
  if (!estimate?.ok || !Array.isArray(estimate.estimates)) return map;
  estimate.estimates.forEach((item) => {
    if (item.arrival_day !== null && item.arrival_day !== undefined) {
      map.set(Number(item.arrival_day), item);
    }
  });
  return map;
}

function shippingCostByChannel(estimate) {
  const map = new Map();
  if (!estimate?.ok || !Array.isArray(estimate.estimates)) return map;
  estimate.estimates.forEach((item) => {
    if (item.channel) map.set(item.channel, { ...item, current_month_profit_summary: estimate.current_month_profit_summary || {} });
  });
  return map;
}

function normalizeGrossMarginRatio(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  if (!Number.isFinite(number)) return null;
  return Math.abs(number) > 1 ? number / 100 : number;
}

function firstPositiveNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number) && number > 0) return number;
  }
  return null;
}

function firstFiniteNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function supplyChannelShortLabel(channel) {
  return SUPPLY_SIMULATION_CHANNELS.find((item) => item.channel === channel)?.shortLabel || "基准渠道";
}

function baselineShippingChannelForItem(item = {}) {
  const text = String(item.first_leg_logistics_channel || "").trim();
  if (text === "快船") return "fast_ship";
  if (text === "慢船") return "slow_ship";
  return "";
}

function currentMonthProjectionFactor(summary = {}) {
  const backendFactor = Number(summary.month_projection_factor);
  if (Number.isFinite(backendFactor) && backendFactor > 0) return backendFactor;
  const monthText = String(summary.report_month || "").trim();
  const monthMatch = monthText.match(/^(\d{4})-(\d{2})$/);
  if (!monthMatch) return 1;
  const year = Number(monthMatch[1]);
  const month = Number(monthMatch[2]);
  const monthDays = new Date(year, month, 0).getDate();
  const endMatch = String(summary.end_date || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!endMatch || `${endMatch[1]}-${endMatch[2]}` !== monthText) return 1;
  const elapsedDays = Math.max(1, Math.min(Number(endMatch[3]) || monthDays, monthDays));
  return monthDays / elapsedDays;
}

function buildMarginImpactEstimate(item = {}, channelCost, baselineCost, quantity) {
  const replenishQuantity = Math.max(Number(quantity) || 0, 0);
  const channelUnitCost = Number(channelCost?.unit_shipping_cost_cny);
  const baselineUnitCost = Number(baselineCost?.unit_shipping_cost_cny);
  if (!replenishQuantity || !Number.isFinite(channelUnitCost) || !Number.isFinite(baselineUnitCost)) return null;
  const currentMonthProfit = channelCost?.current_month_profit_summary || baselineCost?.current_month_profit_summary || item.current_month_profit_summary || {};
  const baselineChannel = baselineCost?.channel || baselineShippingChannelForItem(item);
  const baselineLabel = baselineChannel ? `头程${supplyChannelShortLabel(baselineChannel)}` : "头程基准渠道";
  const extraUnitCost = channelUnitCost - baselineUnitCost;
  const extraCost = extraUnitCost * replenishQuantity;
  const actualProfit = firstFiniteNumber(currentMonthProfit.gross_profit_cny, currentMonthProfit.gross_profit);
  const actualIncome = firstPositiveNumber(currentMonthProfit.gross_profit_income_cny, currentMonthProfit.gross_profit_income);
  const actualCost = firstFiniteNumber(
    currentMonthProfit.gross_profit_cost_cny,
    currentMonthProfit.gross_profit_cost,
    actualProfit !== null && actualIncome !== null ? actualIncome - actualProfit : null
  );
  const projectionFactor = currentMonthProjectionFactor(currentMonthProfit);
  const projectedProfit = actualProfit !== null ? actualProfit * projectionFactor : null;
  const projectedCost = actualCost !== null ? actualCost * projectionFactor : null;
  const estimatedProfit = projectedProfit !== null ? projectedProfit - extraCost : null;
  const estimatedCost = projectedCost !== null ? projectedCost + extraCost : null;
  const hasProfitBasis = Boolean(currentMonthProfit.ok && actualProfit !== null && actualCost !== null && actualCost > 0 && projectedCost > 0);
  const baseGrossMargin = hasProfitBasis ? projectedProfit / projectedCost : null;
  const estimatedGrossMargin = hasProfitBasis && estimatedCost > 0 ? estimatedProfit / estimatedCost : null;
  const marginDelta = baseGrossMargin !== null && estimatedGrossMargin !== null ? estimatedGrossMargin - baseGrossMargin : null;
  return {
    quantity: replenishQuantity,
    extraUnitCost,
    extraCost,
    reportMonth: currentMonthProfit.report_month || "",
    marginBasis: hasProfitBasis ? "current_month" : "missing",
    baselineChannel,
    baselineLabel,
    actualProfit,
    actualCost,
    projectedProfit,
    projectedCost,
    estimatedProfit,
    estimatedCost,
    projectionFactor,
    monthDays: Number(currentMonthProfit.month_days) || null,
    elapsedDays: Number(currentMonthProfit.elapsed_days) || null,
    baseGrossMargin,
    marginDelta,
    estimatedGrossMargin,
  };
}

function formatMarginPointChangeText(value) {
  if (value === null || value === undefined || value === "") return "";
  const points = Math.abs(Number(value) * 100);
  const direction = Number(value) < 0 ? "下降" : Number(value) > 0 ? "上涨" : "不变";
  return `${direction}${points.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}个百分点`;
}

function formatMarginImpactText(impact) {
  if (!impact) return "";
  if (impact.marginBasis === "current_month" && impact.marginDelta !== null) {
    return `较${impact.baselineLabel || "头程基准渠道"}预计利润率${formatMarginPointChangeText(impact.marginDelta)}`;
  }
  return "预计利润率暂不能估算";
}

function formatCurrentMonthProfitRate(summary = {}) {
  if (!summary?.ok) return "-";
  const profit = firstFiniteNumber(summary.gross_profit_cny, summary.gross_profit);
  const cost = firstFiniteNumber(
    summary.gross_profit_cost_cny,
    summary.gross_profit_cost,
    summary.gross_profit_income_cny !== null && summary.gross_profit_income_cny !== undefined && profit !== null
      ? Number(summary.gross_profit_income_cny) - profit
      : null
  );
  if (profit === null || !cost) return "-";
  return `${formatRatioPercent(profit / cost)}（利润/成本，${summary.report_month || "本月"}）`;
}

function formatCurrentMonthProfitAmount(summary = {}) {
  if (!summary?.ok || summary.gross_profit_cny === null || summary.gross_profit_cny === undefined) return "-";
  const projectedProfit = firstFiniteNumber(summary.projected_gross_profit_cny);
  const factor = currentMonthProjectionFactor(summary);
  if (projectedProfit !== null && Math.abs(factor - 1) > 0.005) {
    return `${formatMoney(summary.gross_profit_cny)} 元，扩整月 ${formatMoney(projectedProfit)} 元`;
  }
  return `${formatMoney(summary.gross_profit_cny)} 元（${summary.report_month || "本月"}）`;
}

function formatCurrentMonthCostAmount(summary = {}) {
  if (!summary?.ok) return "-";
  const profit = firstFiniteNumber(summary.gross_profit_cny, summary.gross_profit);
  const cost = firstFiniteNumber(
    summary.gross_profit_cost_cny,
    summary.gross_profit_cost,
    summary.gross_profit_income_cny !== null && summary.gross_profit_income_cny !== undefined && profit !== null
      ? Number(summary.gross_profit_income_cny) - profit
      : null
  );
  if (cost === null) return "-";
  const projectedCost = firstFiniteNumber(summary.projected_gross_profit_cost_cny);
  const factor = currentMonthProjectionFactor(summary);
  if (projectedCost !== null && Math.abs(factor - 1) > 0.005) {
    return `${formatMoney(cost)} 元，扩整月 ${formatMoney(projectedCost)} 元`;
  }
  return `${formatMoney(cost)} 元（${summary.report_month || "本月"}）`;
}

function formatCurrentMonthProfitBasis(summary = {}) {
  if (!summary?.ok) return "暂无本月利润";
  const profitRate = formatCurrentMonthProfitRate(summary);
  return [
    summary.report_month || "本月",
    summary.gross_profit_cny !== null && summary.gross_profit_cny !== undefined ? `利润 ${formatMoney(summary.gross_profit_cny)} 元` : "",
    formatCurrentMonthCostAmount(summary) !== "-" ? `成本 ${formatCurrentMonthCostAmount(summary).replace(`（${summary.report_month || "本月"}）`, "")}` : "",
    profitRate !== "-" ? `利润率 ${profitRate.replace(`（利润/成本，${summary.report_month || "本月"}）`, "")}` : "",
    summary.elapsed_days && summary.month_days ? `扩散 ${formatNumber(summary.elapsed_days)}/${formatNumber(summary.month_days)}天` : "",
  ].filter(Boolean).join(" · ");
}

function formatSupplyMarkerTooltip(label, costEstimate, estimateStatus) {
  if (costEstimate) {
    return [
      label,
      `单件运费：${formatMoney(costEstimate.unit_shipping_cost_cny)} 元/件`,
      `重量：${formatPreciseNumber(costEstimate.unit_weight_kg)} kg/件 · ${formatPreciseNumber(costEstimate.rate_cny_per_kg)} 元/kg`,
    ].join("\n");
  }
  if (estimateStatus && estimateStatus.ok === false) {
    return [label, estimateStatus.reason || "缺少 product info.weight_gram，暂不能估算成本。"].join("\n");
  }
  return [label, "成本估算加载中或暂无匹配渠道。"].join("\n");
}

function ReplenishmentCostEstimate({ estimate, loading, error, item = {}, urgentAirReplenishmentPlan, standardAirReplenishmentPlan }) {
  const [quantity, setQuantity] = useState(1);
  if (loading && !estimate) {
    return <p className="empty-detail">正在按 product info.weight_gram 估算补货成本...</p>;
  }
  if (error && !estimate) {
    return <p className="empty-detail">补货成本估算失败：{error}</p>;
  }
  if (!estimate) {
    return <p className="empty-detail">暂无补货成本估算数据</p>;
  }
  const rates = Object.values(estimate.rates_cny_per_kg || {});
  if (!estimate.ok) {
    return (
      <div className="replenishment-cost">
        <p className="empty-detail">{estimate.reason || "缺少 product info.weight_gram，暂不能估算补货成本。"}</p>
        <div className="cost-rate-row">
          {rates.map((rate) => (
            <span key={rate.label}>
              {rate.label} {formatPreciseNumber(rate.rate_cny_per_kg)} 元/kg
            </span>
          ))}
        </div>
      </div>
    );
  }
  const weight = estimate.weight || {};
  const estimates = Array.isArray(estimate.estimates) ? estimate.estimates : [];
  const replenishmentQuantity = Math.max(Number(quantity) || 0, 0);
  const suggestedUrgentAirQuantity = urgentAirReplenishmentPlan?.suggestedQuantity || 0;
  const suggestedStandardAirQuantity = standardAirReplenishmentPlan?.suggestedQuantity || 0;
  const costItems = Object.entries(estimate.rates_cny_per_kg || {}).map(([channel, rate]) => {
    const plan = estimates.find((item) => item.channel === channel) || {};
    const unitWeightKg = Number(weight.weight_kg || plan.unit_weight_kg || 0);
    const ratePerKg = Number(rate.rate_cny_per_kg || plan.rate_cny_per_kg || 0);
    return {
      channel,
      channel_label: rate.label || plan.channel_label || channel,
      arrival_day: plan.arrival_day,
      window: plan.window,
      rate_cny_per_kg: ratePerKg,
      unit_weight_kg: unitWeightKg,
      unit_shipping_cost_cny: unitWeightKg * ratePerKg,
      current_month_profit_summary: estimate.current_month_profit_summary || {},
    };
  });
  const urgentAirCostItem = costItems.find((item) => item.channel === "urgent_air");
  const standardAirCostItem = costItems.find((item) => item.channel === "standard_air") || costItems.find((item) => item.channel === "air_or_urgent_transfer");
  const baselineChannel = baselineShippingChannelForItem(item);
  const baselineCostItem = baselineChannel ? costItems.find((costItem) => costItem.channel === baselineChannel) : null;
  const suggestedUrgentAirCost = urgentAirCostItem ? suggestedUrgentAirQuantity * Number(urgentAirCostItem.unit_shipping_cost_cny || 0) : null;
  const suggestedStandardAirCost = standardAirCostItem ? suggestedStandardAirQuantity * Number(standardAirCostItem.unit_shipping_cost_cny || 0) : null;
  const suggestedUrgentAirMarginImpact = buildMarginImpactEstimate(item, urgentAirCostItem, baselineCostItem, suggestedUrgentAirQuantity);
  const suggestedStandardAirMarginImpact = buildMarginImpactEstimate(item, standardAirCostItem, baselineCostItem, suggestedStandardAirQuantity);
  return (
    <div className="replenishment-cost">
      {(urgentAirCostItem || standardAirCostItem) && (
        <div className="dynamic-air-cost">
          <div>
            <span>动态空运建议</span>
            <strong>
              加急第10-19天 {formatNumber(suggestedUrgentAirQuantity)} 件
              {" · "}
              普通第20-45天 {formatNumber(suggestedStandardAirQuantity)} 件
            </strong>
          </div>
          <small>
            {urgentAirCostItem ? `加急单件 ${formatMoney(urgentAirCostItem.unit_shipping_cost_cny)} 元` : ""}
            {urgentAirCostItem && standardAirCostItem ? " · " : ""}
            {standardAirCostItem ? `普通单件 ${formatMoney(standardAirCostItem.unit_shipping_cost_cny)} 元` : ""}
            {suggestedUrgentAirCost !== null ? ` · 加急成本 ${formatMoney(suggestedUrgentAirCost)} 元` : ""}
            {suggestedStandardAirCost !== null ? ` · 普通成本 ${formatMoney(suggestedStandardAirCost)} 元` : ""}
            {suggestedUrgentAirMarginImpact ? ` · 加急${formatMarginImpactText(suggestedUrgentAirMarginImpact)}` : ""}
            {suggestedStandardAirMarginImpact ? ` · 普通${formatMarginImpactText(suggestedStandardAirMarginImpact)}` : ""}
          </small>
        </div>
      )}
      <div className="cost-source">
        <div>
          <span>重量来源</span>
          <strong>{weight.source_table || "-"}{weight.source_field ? `.${weight.source_field}` : ""}</strong>
        </div>
        <div>
          <span>单件重量</span>
          <strong>{formatPreciseNumber(weight.weight_gram)}g / {formatPreciseNumber(weight.weight_kg)}kg</strong>
        </div>
        <div>
          <span>计算公式</span>
          <strong>预计利润率=(月扩散利润额-单件运费差×补货数量)/(月扩散成本+单件运费差×补货数量)</strong>
        </div>
        <div>
          <span>头程基准渠道</span>
          <strong>{baselineChannel ? supplyChannelShortLabel(baselineChannel) : "未写快船/慢船，不计算影响"}</strong>
        </div>
        <div>
          <span>本月利润口径</span>
          <strong>{formatCurrentMonthProfitBasis(estimate.current_month_profit_summary)}</strong>
        </div>
      </div>
      <label className="cost-quantity-control">
        <span>补货数量</span>
        <input
          min="0"
          step="1"
          type="number"
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
        />
      </label>
      <div className="cost-rate-row">
        {rates.map((rate) => (
          <span key={rate.label}>
            {rate.label} {formatPreciseNumber(rate.rate_cny_per_kg)} 元/kg
          </span>
        ))}
      </div>
      {costItems.length > 0 ? (
        <div className="cost-estimate-list">
          {costItems.map((costItem) => {
            const marginImpact = buildMarginImpactEstimate(item, costItem, baselineCostItem, replenishmentQuantity);
            return (
              <article className={`cost-estimate-item ${costItem.channel}`} key={costItem.channel}>
                <div className="cost-estimate-head">
                  <div>
                    <strong>{costItem.channel_label || costItem.channel}</strong>
                    <small>{costItem.window ? `${costItem.window} · ` : ""}{costItem.arrival_day ? `到货 第${formatNumber(costItem.arrival_day)}天` : "按当前重量和费率测算"}</small>
                  </div>
                  <span>{formatMoney(costItem.unit_shipping_cost_cny * replenishmentQuantity)} 元</span>
                </div>
                <div className="cost-estimate-metrics">
                  <span>单件 {formatMoney(costItem.unit_shipping_cost_cny)} 元</span>
                  <span>数量 {formatNumber(replenishmentQuantity)} 件</span>
                  <span>总重 {formatPreciseNumber(costItem.unit_weight_kg * replenishmentQuantity)} kg</span>
                  <span>{formatPreciseNumber(costItem.rate_cny_per_kg)} 元/kg</span>
                  {marginImpact && <span>{formatMarginImpactText(marginImpact)}</span>}
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <p className="empty-detail">当前缺少费率配置，暂不能估算补货成本。</p>
      )}
      {loading && <p className="cost-footnote">正在刷新最新重量和成本...</p>}
    </div>
  );
}

function chunkArray(items, size) {
  const chunks = [];
  for (let index = 0; index < items.length; index += size) {
    chunks.push(items.slice(index, index + size));
  }
  return chunks;
}

function SkuAiChatPanel({ item, messages, input, sending, onInputChange, onSend, onRunDiagnosis, onQuickAsk }) {
  const quickQuestions = ["为什么判定断货？", "冗余和断货为什么同时存在？", "生成给销售的处理建议", "这条能否先关闭？"];
  return (
    <div className="ai-panel">
      <div className="ai-context">
        <span>当前上下文</span>
        <strong>{item.material_code}</strong>
        <p>{item.warning_type || "正常"} · 区间销量 {formatNumber(item.daily_sales_volume)} · 预计7天 {formatNumber(item.projected_7d)}</p>
        <button type="button" className="diagnosis-button" onClick={onRunDiagnosis} disabled={sending}>
          SKU 全链路诊断
        </button>
      </div>
      <div className="quick-questions">
        {quickQuestions.map((question) => (
          <button key={question} type="button" onClick={() => onQuickAsk(question)}>
            {question}
          </button>
        ))}
      </div>
      <div className="chat-thread">
        {messages.map((message, index) => (
          <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            <span>{message.role === "user" ? "我" : "AI"}</span>
            <p>{message.text}</p>
          </div>
        ))}
        {sending && (
          <div className="chat-message assistant">
            <span>AI</span>
            <p>正在结合当前 SKU 上下文分析...</p>
          </div>
        )}
      </div>
      <div className="chat-input-row">
        <textarea
          value={input}
          rows={3}
          placeholder="围绕当前 SKU 提问，比如：帮我判断应该派给销售还是采购"
          onChange={(event) => onInputChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
              event.preventDefault();
              onSend();
            }
          }}
        />
        <button type="button" onClick={onSend} disabled={sending || !input.trim()}>
          发送
        </button>
      </div>
    </div>
  );
}

function HandlingRecordsPanel({ records, input, onInputChange, onAdd }) {
  return (
    <div className="records-panel">
      <div className="record-input">
        <textarea value={input} rows={3} placeholder="记录处理备注、沟通结论或下一步动作" onChange={(event) => onInputChange(event.target.value)} />
        <button type="button" onClick={onAdd} disabled={!input.trim()}>
          添加记录
        </button>
      </div>
      <div className="record-timeline">
        {records.map((record, index) => (
          <article className="record-item" key={`${record.time}-${record.title}-${index}`}>
            <span>{record.time}</span>
            <strong>{record.title}</strong>
            <p>{record.content}</p>
          </article>
        ))}
      </div>
    </div>
  );
}

function ForecastReviewDetailDialog({
  item,
  forecastReview,
  riskDiagnosis,
  riskDiagnosisLoading,
  riskDiagnosisError,
  forecastReviewLoading,
  forecastReviewError,
  firstLegLoading,
  firstLegError,
  onClose,
}) {
  if (!forecastReview || typeof document === "undefined") return null;
  const versionRows = Array.isArray(forecastReview.detail_forecast_versions) && forecastReview.detail_forecast_versions.length > 0
    ? forecastReview.detail_forecast_versions
    : Array.isArray(forecastReview.forecast_versions)
      ? forecastReview.forecast_versions
      : [];
  const actualRows = Array.isArray(forecastReview.detail_actual_sales) ? forecastReview.detail_actual_sales : [];
  const monthlyTotals = Array.isArray(forecastReview.detail_monthly_totals) ? forecastReview.detail_monthly_totals : [];
  return createPortal(
    <div className="detail-backdrop forecast-detail-backdrop" role="presentation" onClick={onClose}>
      <section className="detail-dialog forecast-detail-dialog" role="dialog" aria-modal="true" aria-label="销量预估详情" onClick={(event) => event.stopPropagation()}>
        <div className="detail-dialog-head">
          <div>
            <span>销量预估详情</span>
            <strong>{item.material_code}</strong>
            <p>各版本按底表 start_date / end_date 取 value 汇总周销量；2月前、1月前、当前保留首周，末周剔除；实际销量首周剔除 · 快照 {forecastReview.snapshot_date || "-"}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭销量预估详情">
            ×
          </button>
        </div>
        <div className="detail-dialog-body forecast-detail-body">
          <div className="forecast-detail-main">
            {versionRows.length > 0 && (
              <div className="forecast-version-summary" aria-label="预估版本汇总">
                {versionRows.map((version) => (
                  <div className={`forecast-version-card ${forecastVersionTone(version.month_offset)}`} key={`${version.month_offset}-${version.target_month}`}>
                    <span>{forecastVersionMonthLabel(version)}</span>
                    <strong>{formatNumber(version.forecast_quantity)}</strong>
                    <small>{formatFullDateRange(version.target_start_date, version.target_end_date)} · {formatNumber(version.forecast_row_count)} 行</small>
                  </div>
                ))}
              </div>
            )}
            <ForecastDetailChart forecastVersions={versionRows} actualPoints={actualRows} />
            <ForecastMonthlyTotalsChart totals={monthlyTotals} forecastVersions={versionRows} />
          </div>
          <aside className="forecast-detail-cause-panel" aria-label="断货/冗余归因">
            <div className="forecast-detail-cause-head">
              <span>断货/冗余归因</span>
              <strong>{riskDiagnosis?.overall_status || item.warning_type || "-"}</strong>
              <p>按月度销量对比图同口径实际/可能销量、当前风险和头程批次追因。</p>
            </div>
            <RootCauseSummary
              item={item}
              diagnosis={riskDiagnosis}
              loading={riskDiagnosisLoading}
              error={riskDiagnosisError}
              forecastReviewLoading={forecastReviewLoading}
              forecastReviewError={forecastReviewError}
              firstLegLoading={firstLegLoading}
              firstLegError={firstLegError}
            />
          </aside>
        </div>
      </section>
    </div>,
    document.body,
  );
}

function ForecastDetailChart({ forecastVersions = [], actualPoints = [] }) {
  const [activePoint, setActivePoint] = useState(null);
  const parseDate = d3.timeParse("%Y-%m-%d");
  const formatNodeDate = d3.timeFormat("%Y-%m-%d");
  const formatAxisDate = d3.timeFormat("%m-%d");
  const forecastSeries = (forecastVersions || [])
    .filter((version) => Array.isArray(version.weekly_estimates) && version.weekly_estimates.length > 0)
    .map((version, index) => {
      const toneClass = forecastVersionTone(version.month_offset, index);
      const versionMonthLabel = forecastVersionMonthLabel(version);
      const points = version.weekly_estimates
        .map((point) => {
          const dateValue = parseDate(point.week_start_date);
          return {
            week: point.week,
            label: formatFullDateRange(point.week_start_date, point.week_end_date) || point.week,
            date: point.week_start_date,
            dateValue,
            dateNode: point.week_start_date,
            value: Number(point.forecast_quantity || 0),
            rowCount: Number(point.row_count || 0),
          };
        })
        .filter((point) => point.dateValue);
      return {
        key: `detail-${version.month_offset ?? index}-${version.target_month || index}`,
        label: versionMonthLabel,
        shortLabel: versionMonthLabel,
        toneClass,
        targetMonth: version.target_month || "",
        total: Number(version.forecast_quantity || 0),
        points,
      };
    })
    .filter((series) => series.points.some((point) => point.rowCount > 0 || point.value !== 0));
  const actualSeries = (actualPoints || [])
    .map((point) => {
      const dateValue = parseDate(point.week_start_date);
      return {
        week: point.week,
        label: formatFullDateRange(point.week_start_date, point.week_end_date) || point.week,
        date: point.week_start_date,
        dateValue,
        dateNode: point.week_start_date,
        value: Number(point.actual_sales || 0),
        rowCount: Number(point.row_count || 0),
      };
    })
    .filter((point) => point.dateValue);
  if (!forecastSeries.length && !actualSeries.length) return null;

  const width = 920;
  const height = 390;
  const margin = { top: 22, right: 30, bottom: 46, left: 58 };
  const boundaryDates = [
    ...forecastVersions.flatMap((version) => [parseDate(version.target_start_date), parseDate(version.target_end_date)]),
    ...forecastSeries.flatMap((series) => series.points.map((point) => point.dateValue)),
    ...actualSeries.map((point) => point.dateValue),
  ].filter(Boolean);
  const minDate = d3.min(boundaryDates);
  const maxDate = d3.max(boundaryDates);
  const dateRecords = new Map();
  const addDateRecord = (dateValue, dateNode) => {
    if (!dateValue) return;
    const key = dateNode || formatNodeDate(dateValue);
    if (!dateRecords.has(key)) dateRecords.set(key, { key, dateValue: new Date(dateValue.valueOf()) });
  };
  if (minDate && maxDate) {
    const cursor = new Date(minDate.valueOf());
    while (cursor <= maxDate) {
      addDateRecord(cursor);
      cursor.setDate(cursor.getDate() + 7);
    }
    addDateRecord(maxDate);
  }
  forecastSeries.forEach((series) => series.points.forEach((point) => addDateRecord(point.dateValue, point.dateNode)));
  actualSeries.forEach((point) => addDateRecord(point.dateValue, point.dateNode));
  const dateDomain = Array.from(dateRecords.values())
    .sort((left, right) => left.dateValue - right.dateValue)
    .map((item) => item.key);
  const tickStep = Math.max(1, Math.ceil(dateDomain.length / 10));
  const xTicks = dateDomain.filter((dateNode, index) => index % tickStep === 0 || index === dateDomain.length - 1);
  const maxValue = Math.max(
    d3.max(forecastSeries, (series) => d3.max(series.points, (point) => point.value) || 0) || 0,
    d3.max(actualSeries, (point) => point.value) || 0,
    1
  );
  const xScale = d3
    .scalePoint()
    .domain(dateDomain)
    .range([margin.left, width - margin.right])
    .padding(0.5);
  const yScale = d3
    .scaleLinear()
    .domain([0, maxValue * 1.15])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const line = d3
    .line()
    .x((point) => xScale(point.dateNode) || margin.left)
    .y((point) => yScale(point.value))
    .curve(d3.curveMonotoneX);
  const yTicks = yScale.ticks(5);
  const buildTooltip = (point, series) => ({
    id: `${series.key}-${point.week}`,
    activeIds: [`${series.key}-${point.week}`],
    x: xScale(point.dateNode) || margin.left,
    y: yScale(point.value),
    label: point.label,
    title: series.label,
    lines: [
      series.type === "actual" ? "实际销量 = volume 按周求和" : `${series.shortLabel} = value × 覆盖天数`,
      series.type === "actual" ? `本周实际销量 = ${formatNumber(point.value)}` : `本周预估销量 = ${formatNumber(point.value)}`,
      ...(series.type === "actual" ? [] : [`预估时间 = ${series.shortLabel}`]),
      `来源行数 = ${formatNumber(point.rowCount)}`,
    ],
  });
  const drawableSeries = [
    ...forecastSeries,
    {
      key: "detail-actual",
      label: "实际销量",
      shortLabel: "实际销量",
      toneClass: "actual",
      type: "actual",
      points: actualSeries,
    },
  ].filter((series) => series.points.length > 0);

  return (
    <div className="forecast-chart detail forecast-detail-chart" aria-label="销量预估版本详情图">
      <div className="forecast-chart-legend">
        {forecastSeries.map((series) => (
          <span className={`forecast-version ${series.toneClass}`} key={series.key}>{series.shortLabel}</span>
        ))}
        <span className="actual">实际销量</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        {yTicks.map((tick) => (
          <g key={`detail-y-${tick}`}>
            <line x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />
            <text x={margin.left - 10} y={yScale(tick) + 4} textAnchor="end">
              {formatNumber(tick)}
            </text>
          </g>
        ))}
        {xTicks.map((tick) => (
          <text key={`detail-x-${tick}`} className="x-label" x={xScale(tick)} y={height - 18} textAnchor="middle">
            {formatAxisDate(parseDate(tick) || new Date(tick))}
          </text>
        ))}
        {forecastSeries.map((series) => (
          <path className={`forecast-version-line ${series.toneClass}`} d={line(series.points) || ""} key={series.key} />
        ))}
        {actualSeries.length > 0 && <path className="detail-actual-line" d={line(actualSeries) || ""} />}
        {drawableSeries.map((series) => (
          <React.Fragment key={`detail-points-${series.key}`}>
            {series.points.map((point) => {
              const pointId = `${series.key}-${point.week}`;
              const isActive = activePoint?.activeIds?.includes(pointId);
              return (
                <circle
                  className={`${series.type === "actual" ? "actual-dot" : `forecast-version-dot ${series.toneClass}`} ${isActive ? "active" : ""}`}
                  cx={xScale(point.dateNode) || margin.left}
                  cy={yScale(point.value)}
                  key={pointId}
                  onMouseEnter={() => setActivePoint(buildTooltip(point, series))}
                  onMouseLeave={() => setActivePoint(null)}
                  r={isActive ? "5.8" : "3.8"}
                />
              );
            })}
          </React.Fragment>
        ))}
        {activePoint && <ForecastSvgTooltip point={activePoint} width={width} height={height} />}
      </svg>
    </div>
  );
}

const MONTHLY_TOTAL_BAR_WIDTH = 16;
const MONTHLY_TOTAL_BAR_GAP = 8;

function ForecastMonthlyTotalsChart({ totals = [], forecastVersions = [] }) {
  const [activeBar, setActiveBar] = useState(null);
  const parseMonth = d3.timeParse("%Y-%m");
  const formatMonth = d3.timeFormat("%m月");
  const rawData = (totals || [])
    .map((item) => {
      const monthDate = parseMonth(item.month);
      const monthOffset = Number.isFinite(Number(item.forecast_month_offset))
        ? Number(item.forecast_month_offset)
        : forecastMonthOffsetFromLabel(item.forecast_label || "");
      const forecast = Number(item.forecast_quantity || 0);
      return {
        month: item.month,
        label: monthDate ? formatMonth(monthDate) : item.month,
        forecast,
        actual: Number(item.actual_sales || 0),
        actualProjected: Number(item.actual_sales_projected ?? item.actual_sales ?? 0),
        actualVirtual: Number(item.actual_sales_virtual || 0),
        actualCoveredDays: Number(item.actual_covered_days || 0),
        monthDayCount: Number(item.month_day_count || 0),
        forecastMonth: item.forecast_month || "",
        forecastMonthLabel: formatForecastMonthEstimate(item.forecast_month || ""),
        forecastMonthOffset: monthOffset,
        forecastToneClass: monthOffset === null ? "month-forecast" : forecastVersionTone(monthOffset),
        forecastLabel: item.forecast_label || "",
        forecastRowCount: Number(item.forecast_row_count || 0),
        actualRowCount: Number(item.actual_row_count || 0),
        forecastVersionTotals: Array.isArray(item.forecast_version_totals) ? item.forecast_version_totals : [],
      };
    })
    .filter((item) => item.month);
  const actualMonthKeys = rawData
    .filter((item) => Number(item.actualCoveredDays) > 0)
    .map((item) => item.month)
    .sort();
  const currentMonthKey = actualMonthKeys[actualMonthKeys.length - 1] || "";
  const normalizeForecastBars = (item) => {
    const versionBars = item.forecastVersionTotals
      .map((version, index) => {
        const offset = Number.isFinite(Number(version.forecast_month_offset))
          ? Number(version.forecast_month_offset)
          : forecastMonthOffsetFromLabel(version.forecast_label || "");
        const forecastMonth = version.forecast_month || "";
        const value = Number(version.forecast_quantity || 0);
        if (!Number.isFinite(value) || value <= 0) return null;
        return {
          key: `forecast-${offset ?? "x"}-${forecastMonth || index}`,
          type: "forecast",
          value,
          label: formatForecastMonthEstimate(forecastMonth) || forecastVersionShortLabel(offset),
          forecastMonth,
          forecastMonthOffset: offset,
          toneClass: Number.isFinite(Number(offset)) ? forecastVersionTone(offset) : "month-forecast",
          rowCount: Number(version.forecast_row_count || 0),
        };
      })
      .filter(Boolean)
      .sort((left, right) => String(left.forecastMonth).localeCompare(String(right.forecastMonth)) || Number(left.forecastMonthOffset) - Number(right.forecastMonthOffset));
    if (!versionBars.length && item.forecast > 0) {
      return [
        {
          key: `forecast-${item.forecastMonthOffset ?? "selected"}-${item.forecastMonth || item.month}`,
          type: "forecast",
          value: item.forecast,
          label: item.forecastMonthLabel || "月份预估总量",
          forecastMonth: item.forecastMonth,
          forecastMonthOffset: item.forecastMonthOffset,
          toneClass: item.forecastToneClass,
          rowCount: item.forecastRowCount,
        },
      ];
    }
    if (currentMonthKey && item.month >= currentMonthKey && versionBars.length > 1) {
      return [...versionBars]
        .sort((left, right) => String(right.forecastMonth).localeCompare(String(left.forecastMonth)))
        .slice(0, 3)
        .sort((left, right) => String(left.forecastMonth).localeCompare(String(right.forecastMonth)));
    }
    const selected = versionBars.find((bar) =>
      bar.forecastMonth === item.forecastMonth ||
      Number(bar.forecastMonthOffset) === Number(item.forecastMonthOffset)
    );
    return selected ? [selected] : versionBars.slice(-1);
  };
  const data = rawData.map((item) => ({
    ...item,
    forecastBars: normalizeForecastBars(item),
  }));
  if (!data.length) return null;

  const width = 920;
  const height = 276;
  const margin = { top: 38, right: 30, bottom: 42, left: 58 };
  const forecastLegendByKey = new Map();
  data.forEach((item) => {
    item.forecastBars.forEach((bar) => {
      if (!forecastLegendByKey.has(bar.key)) forecastLegendByKey.set(bar.key, bar);
    });
  });
  const forecastLegendItems = Array.from(forecastLegendByKey.values()).sort((left, right) =>
    String(left.forecastMonth).localeCompare(String(right.forecastMonth)) ||
    Number(left.forecastMonthOffset) - Number(right.forecastMonthOffset)
  );
  const hasVirtualActual = data.some((item) => Number(item.actualVirtual) > 0);
  const maxValue = Math.max(
    d3.max(data, (item) => Math.max(
      item.actualProjected,
      ...item.forecastBars.map((bar) => bar.value),
    )) || 0,
    1
  );
  const xScale = d3
    .scaleBand()
    .domain(data.map((item) => item.month))
    .range([margin.left, width - margin.right])
    .padding(0.24);
  const yScale = d3
    .scaleLinear()
    .domain([0, maxValue * 1.28])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const yTicks = yScale.ticks(4);
  const actualBarForItem = (item) => (
    Number(item.actual) > 0 || Number(item.actualProjected) > 0 || Number(item.actualRowCount) > 0
      ? [{
          key: "actual",
          type: "actual",
          value: item.actual,
          label: "月份销量总量",
        }]
      : []
  );
  const barsForItem = (item) => [...item.forecastBars, ...actualBarForItem(item)];
  const barXForItem = (item, index, count) => {
    const monthCenter = (xScale(item.month) || margin.left) + xScale.bandwidth() / 2;
    const groupWidth = count * MONTHLY_TOTAL_BAR_WIDTH + Math.max(0, count - 1) * MONTHLY_TOTAL_BAR_GAP;
    return monthCenter - groupWidth / 2 + index * (MONTHLY_TOTAL_BAR_WIDTH + MONTHLY_TOTAL_BAR_GAP);
  };
  const barXByKey = (item, bar) => {
    const bars = barsForItem(item);
    const index = Math.max(0, bars.findIndex((candidate) => candidate.key === bar.key));
    return barXForItem(item, index, bars.length || 1);
  };
  const buildTooltip = (item, bar) => {
    const value = bar.type === "actual" ? item.actual : bar.value;
    const x = barXByKey(item, bar) + MONTHLY_TOTAL_BAR_WIDTH / 2;
    return {
      id: `monthly-${bar.key}-${item.month}`,
      activeIds: [`monthly-${bar.key}-${item.month}`],
      x,
      y: yScale(value),
      title: bar.label,
      label: item.month,
      lines: bar.type === "forecast"
          ? [
              `目标月 = ${item.label}`,
              `${bar.label} = ${formatNumber(bar.value)}`,
              `预估版本月 = ${bar.forecastMonth || "-"}`,
              `来源行数 = ${formatNumber(bar.rowCount)}`,
            ]
          : [
              `月份销量总量 = ${formatNumber(item.actual)}`,
              ...(item.actualVirtual > 0
                ? [
                    `可能销量 = ${formatNumber(item.actualProjected)}`,
                    `虚拟补足 = ${formatNumber(item.actualVirtual)}`,
                    `覆盖天数 = ${formatNumber(item.actualCoveredDays)} / ${formatNumber(item.monthDayCount)}`,
                  ]
                : []),
              `实际销量 = volume 按月求和`,
              `来源行数 = ${formatNumber(item.actualRowCount)}`,
            ],
    };
  };

  return (
    <div className="forecast-chart detail forecast-monthly-total-chart" aria-label="月度预估销量总量对比图">
      <div className="forecast-chart-legend">
        {forecastLegendItems.length > 0
          ? forecastLegendItems.map((bar) => (
              <span className={bar.toneClass} key={`monthly-legend-${bar.key}`}>
                {bar.label}
              </span>
            ))
          : <span className="month-forecast">月份预估总量</span>}
        <span className="month-actual">月份销量总量</span>
        {hasVirtualActual && <span className="month-actual-virtual">可能销量补足</span>}
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        {yTicks.map((tick) => (
          <g key={`monthly-y-${tick}`}>
            <line x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />
            <text x={margin.left - 10} y={yScale(tick) + 4} textAnchor="end">
              {formatNumber(tick)}
            </text>
          </g>
        ))}
        {data.map((item) => (
          <text key={`monthly-x-${item.month}`} className="x-label" x={(xScale(item.month) || margin.left) + xScale.bandwidth() / 2} y={height - 16} textAnchor="middle">
            {item.label}
          </text>
        ))}
        {data.flatMap((item) => {
          const monthBars = barsForItem(item);
          return monthBars.map((bar, barIndex) => {
            const barId = `monthly-${bar.key}-${item.month}`;
            const value = bar.type === "actual" ? item.actual : bar.value;
            const isActive = activeBar?.activeIds?.includes(barId);
            const x = barXForItem(item, barIndex, monthBars.length);
            const y = yScale(value);
            const barHeight = Math.max(0, yScale(0) - y);
            if (bar.type === "actual") {
              const projectedValue = Math.max(item.actualProjected, item.actual);
              const projectedY = yScale(projectedValue);
              const actualY = yScale(item.actual);
              const virtualHeight = Math.max(0, actualY - projectedY);
              return (
                <React.Fragment key={barId}>
                  {virtualHeight > 0 && (
                    <rect
                      className={`monthly-total-bar actual-virtual ${isActive ? "active" : ""}`}
                      height={virtualHeight}
                      onMouseEnter={() => setActiveBar(buildTooltip(item, bar))}
                      onMouseLeave={() => setActiveBar(null)}
                      rx="2"
                      width={MONTHLY_TOTAL_BAR_WIDTH}
                      x={x}
                      y={projectedY}
                    />
                  )}
                  <rect
                    className={`monthly-total-bar actual ${isActive ? "active" : ""}`}
                    height={Math.max(0, yScale(0) - actualY)}
                    onMouseEnter={() => setActiveBar(buildTooltip(item, bar))}
                    onMouseLeave={() => setActiveBar(null)}
                    rx="2"
                    width={MONTHLY_TOTAL_BAR_WIDTH}
                    x={x}
                    y={actualY}
                  />
                </React.Fragment>
              );
            }
            return (
              <rect
                className={`monthly-total-bar forecast ${bar.toneClass} ${isActive ? "active" : ""}`}
                height={barHeight}
                key={barId}
                onMouseEnter={() => setActiveBar(buildTooltip(item, bar))}
                onMouseLeave={() => setActiveBar(null)}
                rx="2"
                width={MONTHLY_TOTAL_BAR_WIDTH}
                x={x}
                y={y}
              />
            );
          });
        })}
        {activeBar && <ForecastSvgTooltip point={activeBar} width={width} height={height} />}
      </svg>
    </div>
  );
}

function normalizeForecastSeries(forecastVersions, data) {
  const versions = Array.isArray(forecastVersions) ? forecastVersions : [];
  const normalized = versions
    .filter((version) => Array.isArray(version.weekly_estimates)
      && version.weekly_estimates.some((point) => Number(point.row_count || 0) > 0 || Number(point.forecast_quantity || 0) !== 0))
    .map((version, index) => {
      const toneClass = forecastVersionTone(version.month_offset, index);
      const versionMonthLabel = forecastVersionMonthLabel(version);
      const valueByWeek = new Map(
        version.weekly_estimates.map((point) => [point.week, Number(point.forecast_quantity || 0)])
      );
      return {
        key: `forecast-${version.month_offset ?? index}-${version.target_month || index}`,
        monthOffset: version.month_offset,
        targetMonth: version.target_month || "",
        label: versionMonthLabel,
        shortLabel: versionMonthLabel,
        toneClass,
        total: Number(version.forecast_quantity || 0),
        valueByWeek,
        points: data.map((point) => ({
          week: point.week,
          value: valueByWeek.get(point.week) ?? 0,
        })),
      };
    });
  if (normalized.length > 0) return normalized;
  const valueByWeek = new Map(data.map((point) => [point.week, point.forecast]));
  return [
    {
      key: "forecast-fallback",
      monthOffset: 2,
      targetMonth: "",
      label: "预测销量",
      shortLabel: "预测销量",
      toneClass: "version-two",
      total: data.reduce((sum, point) => sum + point.forecast, 0),
      valueByWeek,
      points: data.map((point) => ({ week: point.week, value: point.forecast })),
    },
  ];
}

function forecastVersionTone(monthOffset, index = 0) {
  const offset = Number(monthOffset);
  if (offset === 0) return "version-current";
  if (offset === 1) return "version-one";
  if (offset === 2) return "version-two";
  if (offset === 3) return "version-three";
  return `version-extra-${index % 3}`;
}

function forecastVersionLabel(monthOffset) {
  const offset = Number(monthOffset);
  if (offset === 0) return "当前的预估线";
  if (Number.isFinite(offset)) return `${offset}个月之前的预估线`;
  return "预估线";
}

function forecastVersionShortLabel(monthOffset) {
  const offset = Number(monthOffset);
  if (offset === 0) return "当前预估";
  if (Number.isFinite(offset)) return `${offset}月前预估`;
  return "预估";
}

function forecastVersionMonthLabel(version) {
  const monthValue = version?.target_month || String(version?.target_start_date || "").slice(0, 7);
  return formatForecastMonthEstimate(monthValue) || forecastVersionShortLabel(version?.month_offset);
}

function forecastMonthOffsetFromLabel(label) {
  if (!label) return null;
  if (label.includes("当前")) return 0;
  const match = label.match(/(\d+)个月之前/);
  return match ? Number(match[1]) : null;
}

function formatForecastMonthEstimate(value) {
  if (!value) return "";
  const parts = String(value).split("-");
  const month = Number(parts[1]);
  if (Number.isFinite(month) && month >= 1 && month <= 12) return `${month}月预估`;
  return `${value}预估`;
}

function ForecastReviewChart({ points, forecastTotal, actualTotal, forecastVersions = [], pricePoints = [], variant = "compact" }) {
  const [activeSalesPoint, setActiveSalesPoint] = useState(null);
  const data = (points || []).map((point) => ({
    week: point.week,
    label: formatFullDateRange(point.week_start_date, point.week_end_date) || point.week,
    labelStart: formatFullDate(point.week_start_date),
    labelEnd: formatFullDate(point.week_end_date),
    forecast: Number(point.forecast_quantity || 0),
    actual: Number(point.actual_sales || 0),
    organic: Number(point.organic_sales || 0),
    adOrders: Number(point.ad_order_quantity || 0),
    adSpend: Number(point.ad_spend || 0),
  }));
  if (!data.length) return null;
  const isDetail = variant === "detail";
  const allForecastSeries = normalizeForecastSeries(forecastVersions, data);
  const selectedForecastSeries = allForecastSeries.filter((series) => {
    const offset = Number(series.monthOffset);
    return offset === 3 || offset === 2;
  });
  const forecastSeries = selectedForecastSeries.length ? selectedForecastSeries : allForecastSeries;
  const primaryForecastSeries =
    forecastSeries.find((series) => Number(series.monthOffset) === 2) ||
    forecastSeries.find((series) => Number(series.monthOffset) === 3) ||
    forecastSeries[0];
  const primaryForecastTotal = Number(primaryForecastSeries?.total ?? forecastTotal ?? 0);

  const totals = [
    { key: "actual", label: "实际总量", value: Number(actualTotal || 0) },
    { key: "forecast", label: `${primaryForecastSeries?.shortLabel || "预估"}总量`, value: primaryForecastTotal },
  ];
  const maxTotal = Math.max(...totals.map((item) => item.value), 1);
  const width = isDetail ? 920 : 680;
  const height = isDetail ? 330 : 292;
  const margin = { top: 22, right: 28, bottom: 82, left: 54 };
  const totalBar = {
    labelX: margin.left + 4,
    trackX: margin.left + 122,
    maxWidth: width - margin.right - margin.left - 142,
    startY: height - 52,
    rowGap: 24,
    height: 14,
  };
  const xScale = d3
    .scalePoint()
    .domain(data.map((point) => point.week))
    .range([margin.left, width - margin.right])
    .padding(0.5);
  const maxForecastValue = d3.max(forecastSeries, (series) => d3.max(series.points, (point) => point.value) || 0) || 0;
  const maxValue = Math.max(d3.max(data, (point) => point.actual) || 0, maxForecastValue, 1);
  const yScale = d3
    .scaleLinear()
    .domain([0, maxValue * 1.15])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const line = d3
    .line()
    .x((point) => xScale(point.week) || margin.left)
    .y((point) => yScale(point.value))
    .curve(d3.curveMonotoneX);
  const forecastLines = forecastSeries.map((series) => ({
    ...series,
    path: line(series.points),
  }));
  const actualLine = line(data.map((point) => ({ week: point.week, value: point.actual })));
  const yTicks = yScale.ticks(4);
  const salesSeries = [
    ...forecastSeries.map((series) => ({
      key: series.key,
      dotClass: `forecast-version-dot ${series.toneClass}`,
      label: series.label,
      value: (point) => series.valueByWeek.get(point.week) ?? 0,
      rule: (point) => {
        const value = series.valueByWeek.get(point.week) ?? 0;
        return [
          `${series.shortLabel} = value × 覆盖天数`,
          `预估时间 = ${series.shortLabel}`,
          `本周预估销量 = ${formatNumber(value)}`,
        ];
      },
    })),
    {
      key: "actual",
      dotClass: "actual-dot",
      label: "实际销量",
      value: (point) => point.actual,
      rule: (point) => [`实际销量 = volume 按周求和`, `本周实际销量 = ${formatNumber(point.actual)}`],
    },
  ];
  const valuesMatch = (a, b) => Math.abs(Number(a || 0) - Number(b || 0)) < 0.05;
  const overlapSegments =
    salesSeries.length <= 3
      ? data.slice(0, -1).flatMap((point, index) => {
          const nextPoint = data[index + 1];
          const groups = [];
          const allOverlap = salesSeries.every(
            (series) =>
              valuesMatch(salesSeries[0].value(point), series.value(point)) &&
              valuesMatch(salesSeries[0].value(nextPoint), series.value(nextPoint))
          );
          if (allOverlap) {
            groups.push({ keys: salesSeries.map((series) => series.key), count: salesSeries.length });
          } else {
            salesSeries.forEach((series, seriesIndex) => {
              salesSeries.slice(seriesIndex + 1).forEach((otherSeries) => {
                if (
                  valuesMatch(series.value(point), otherSeries.value(point)) &&
                  valuesMatch(series.value(nextPoint), otherSeries.value(nextPoint))
                ) {
                  groups.push({ keys: [series.key, otherSeries.key], count: 2 });
                }
              });
            });
          }
          return groups.map((group) => {
            const sourceSeries = salesSeries.find((series) => series.key === group.keys[0]);
            return {
              id: `${point.week}-${nextPoint.week}-${group.keys.join("-")}`,
              count: group.count,
              path: line([
                { week: point.week, value: sourceSeries.value(point) },
                { week: nextPoint.week, value: sourceSeries.value(nextPoint) },
              ]),
            };
          });
        })
      : [];
  const buildSalesTooltip = (point, series) => {
    const anchorX = xScale(point.week) || margin.left;
    const anchorY = yScale(series.value(point));
    const closeItems = salesSeries
      .map((item) => ({
        id: `${point.week}-${item.key}`,
        label: item.label,
        y: yScale(item.value(point)),
        lines: item.rule(point),
      }))
      .filter((item) => Math.abs(item.y - anchorY) <= 9);
    return {
      id: `${point.week}-${series.key}`,
      activeIds: closeItems.map((item) => item.id),
      x: anchorX,
      y: anchorY,
      label: point.label,
      title: closeItems.length > 1 ? "接近/重合点" : series.label,
      lines: closeItems.flatMap((item, index) => [
        `${item.label}`,
        ...item.lines,
        ...(index < closeItems.length - 1 ? [""] : []),
      ]),
    };
  };

  return (
    <div className={`forecast-chart ${isDetail ? "detail" : ""}`} aria-label="周度预测和实际销量折线图">
      <div className="forecast-chart-legend">
        {forecastSeries.map((series) => (
          <span className={`forecast-version ${series.toneClass}`} key={series.key}>{series.shortLabel}</span>
        ))}
        <span className="actual">实际销量</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        {yTicks.map((tick) => (
          <g key={`sales-${tick}`}>
            <line x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />
            <text x={margin.left - 10} y={yScale(tick) + 4} textAnchor="end">
              {formatNumber(tick)}
            </text>
          </g>
        ))}
        {forecastLines.map((series) => (
          <path className={`forecast-version-line ${series.toneClass}`} d={series.path || ""} key={series.key} />
        ))}
        <path className="actual-line" d={actualLine || ""} />
        {overlapSegments.map((segment) => (
          <path
            className={`overlap-line ${segment.count === 3 ? "triple" : "double"}`}
            d={segment.path || ""}
            key={segment.id}
          />
        ))}
        {data.map((point) => (
          <React.Fragment key={point.week}>
            {salesSeries.map((series) => {
              const value = series.value(point);
              const x = xScale(point.week) || margin.left;
              const y = yScale(value);
              const pointId = `${point.week}-${series.key}`;
              const isActive = activeSalesPoint?.activeIds?.includes(pointId);
              return (
                <circle
                  className={`${series.dotClass} ${isActive ? "active" : ""}`}
                  cx={x}
                  cy={y}
                  key={series.key}
                  onMouseEnter={() => setActiveSalesPoint(buildSalesTooltip(point, series))}
                  onMouseLeave={() => setActiveSalesPoint(null)}
                  r={isActive ? "6" : "4"}
                />
              );
            })}
          </React.Fragment>
        ))}
        {data.map((point) => (
          <React.Fragment key={`sales-hit-${point.week}`}>
            {salesSeries.map((series) => {
              const x = xScale(point.week) || margin.left;
              const y = yScale(series.value(point));
              return (
                <circle
                  className="sales-hit-area"
                  cx={x}
                  cy={y}
                  key={series.key}
                  onMouseEnter={() => setActiveSalesPoint(buildSalesTooltip(point, series))}
                  onMouseLeave={() => setActiveSalesPoint(null)}
                  r="10"
                />
              );
            })}
          </React.Fragment>
        ))}
        <g className="forecast-total-svg" aria-label="预测总量和实际总量">
          {totals.map((item, index) => {
            const y = totalBar.startY + index * totalBar.rowGap;
            const barWidth = Math.max((item.value / maxTotal) * totalBar.maxWidth, 28);
            return (
              <g className={`forecast-total-svg-row ${item.key}`} key={item.key}>
                <text x={totalBar.labelX} y={y + 11} textAnchor="start">
                  {item.label}
                </text>
                <rect x={totalBar.trackX} y={y} width={barWidth} height={totalBar.height} rx="4" />
                <text className="forecast-total-svg-value" x={totalBar.trackX + barWidth - 8} y={y + 11} textAnchor="end">
                  {formatNumber(item.value)}
                </text>
              </g>
            );
          })}
        </g>
        {activeSalesPoint && <ForecastSvgTooltip point={activeSalesPoint} width={width} height={height} />}
      </svg>
      <ForecastAdSignalStrip data={data} pricePoints={pricePoints} variant={variant} />
    </div>
  );
}

function ForecastSvgTooltip({ point, width, height }) {
  const boxWidth = 236;
  const lineHeight = 15;
  const boxHeight = 38 + point.lines.length * lineHeight;
  const x = point.x > width - boxWidth - 18 ? point.x - boxWidth - 12 : point.x + 12;
  const y = Math.max(10, Math.min(point.y - boxHeight - 12, height - boxHeight - 10));

  return (
    <g className="forecast-svg-tooltip" pointerEvents="none">
      <line className="hover-guide" x1={point.x} x2={point.x} y1="18" y2={height - 48} />
      <circle className="hover-ring" cx={point.x} cy={point.y} r="9" />
      <g transform={`translate(${x}, ${y})`}>
        <rect width={boxWidth} height={boxHeight} rx="6" />
        <text x="10" y="18">
          <tspan className="tooltip-title">{point.title}</tspan>
          <tspan x="10" dy="16">{point.label}</tspan>
          {point.lines.map((line, index) => (
            <tspan x="10" dy={lineHeight} key={`${line}-${index}`}>
              {line}
            </tspan>
          ))}
        </text>
      </g>
    </g>
  );
}

function ForecastAdSignalStrip({ data, pricePoints = [], variant = "compact" }) {
  const [activeAdPoint, setActiveAdPoint] = useState(null);
  const isDetail = variant === "detail";
  const width = isDetail ? 920 : 680;
  const height = isDetail ? 210 : 190;
  const margin = { top: 18, right: 28, bottom: 50, left: 54 };
  const parseDate = d3.timeParse("%Y-%m-%d");
  const datedAdData = data
    .map((point) => ({
      ...point,
      dateValue: parseDate(point.labelStart),
      endDateValue: parseDate(point.labelEnd),
    }))
    .filter((point) => point.dateValue);
  const priceData = (pricePoints || [])
    .map((point) => {
      const dateValue = parseDate(point.date);
      const price = point.price === null || point.price === undefined ? null : Number(point.price);
      return {
        date: point.date,
        dateValue,
        price,
        listingPrice: point.listing_price === null || point.listing_price === undefined ? null : Number(point.listing_price),
        landedPrice: point.landed_price === null || point.landed_price === undefined ? null : Number(point.landed_price),
        currencyCode: point.currency_code || "",
        sourceRowCount: Number(point.source_row_count || 0),
      };
    })
    .filter((point) => point.dateValue && point.price !== null)
    .sort((a, b) => a.dateValue - b.dateValue);
  const weekXScale = d3
    .scalePoint()
    .domain(datedAdData.map((point) => point.week))
    .range([margin.left, width - margin.right])
    .padding(0.5);
  const xForWeek = (point) => weekXScale(point.week) || margin.left;
  const firstWeekPoint = datedAdData[0];
  const secondWeekPoint = datedAdData[1];
  const firstWeekX = firstWeekPoint ? xForWeek(firstWeekPoint) : margin.left;
  const weekStepX = firstWeekPoint && secondWeekPoint ? xForWeek(secondWeekPoint) - firstWeekX : width - margin.left - margin.right;
  const weekStepMs =
    firstWeekPoint && secondWeekPoint
      ? secondWeekPoint.dateValue.getTime() - firstWeekPoint.dateValue.getTime()
      : 7 * 24 * 60 * 60 * 1000;
  const leadingWeekDate = firstWeekPoint ? new Date(firstWeekPoint.dateValue.getTime() - weekStepMs) : null;
  const leadingWeekX = firstWeekPoint ? Math.max(12, firstWeekX - weekStepX) : margin.left;
  const axisStartX = firstWeekPoint ? Math.min(margin.left, leadingWeekX) : margin.left;
  const xForDate = (dateValue) => {
    if (!dateValue || !firstWeekPoint || !Number.isFinite(weekStepMs) || weekStepMs <= 0) return margin.left;
    const shiftedTime = dateValue.getTime() - weekStepMs;
    const ratio = (shiftedTime - firstWeekPoint.dateValue.getTime()) / weekStepMs;
    const x = firstWeekX + ratio * weekStepX;
    return Math.max(axisStartX, Math.min(width - margin.right, x));
  };
  const maxSpend = d3.max(data, (point) => point.adSpend) || 1;
  const priceExtent = d3.extent(priceData, (point) => point.price);
  const minPrice = priceExtent[0] ?? 0;
  const maxPrice = priceExtent[1] ?? 1;
  const pricePadding = Math.max((maxPrice - minPrice) * 0.16, maxPrice ? maxPrice * 0.04 : 1);
  const spendScale = d3
    .scaleLinear()
    .domain([0, maxSpend * 1.15])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const priceScale = d3
    .scaleLinear()
    .domain([Math.max(0, minPrice - pricePadding), maxPrice + pricePadding])
    .nice()
    .range([height - margin.bottom, margin.top]);
  const spendLine = d3
    .line()
    .x((point) => xForWeek(point))
    .y((point) => spendScale(point.adSpend))
    .curve(d3.curveMonotoneX)(datedAdData);
  const priceLine = d3
    .line()
    .defined((point) => point.price !== null)
    .x((point) => xForDate(point.dateValue))
    .y((point) => priceScale(point.price))
    .curve(d3.curveMonotoneX)(priceData);
  const spendTicks = spendScale.ticks(3);
  const priceTicks = priceData.length ? priceScale.ticks(3) : [];
  const tickStep = Math.max(1, Math.ceil(datedAdData.length / 8));
  const xTicks = datedAdData
    .filter((point, index) => index % tickStep === 0 || index === datedAdData.length - 1)
    .map((point) => ({ key: point.week, dateValue: new Date(point.dateValue.getTime() + weekStepMs), x: xForWeek(point) }));
  if (leadingWeekDate) {
    xTicks.unshift({
      key: "price-leading-week",
      dateValue: new Date(leadingWeekDate.getTime() + weekStepMs),
      x: leadingWeekX,
      textAnchor: "start",
    });
  }
  const formatAxisDate = d3.timeFormat("%m-%d");
  const priceChangeMarkers = (() => {
    const markers = [];
    let activeChange = null;
    const continuousChangeMaxGapMs = 36 * 60 * 60 * 1000;
    const normalizePrice = (value) => Math.round(Number(value) * 100) / 100;
    const flushActiveChange = () => {
      if (!activeChange || activeChange.startPrice <= 0) {
        activeChange = null;
        return;
      }
      const ratio = (activeChange.endPrice - activeChange.startPrice) / activeChange.startPrice;
      const startX = xForDate(activeChange.firstChangeDateValue);
      const endX = xForDate(activeChange.endDateValue);
      markers.push({
        id: `${activeChange.firstChangeDate}-${activeChange.endDate}-${activeChange.direction}`,
        date: activeChange.endDate,
        startDate: activeChange.firstChangeDate,
        endDate: activeChange.endDate,
        x: activeChange.count > 1 ? (startX + endX) / 2 : endX,
        direction: activeChange.direction,
        label: formatSignedRatioPercent(ratio),
        count: activeChange.count,
        startPrice: activeChange.startPrice,
        endPrice: activeChange.endPrice,
      });
      activeChange = null;
    };

    priceData.forEach((point, index) => {
      if (index === 0) return;
      const previous = priceData[index - 1];
      const previousPrice = normalizePrice(previous.price);
      const currentPrice = normalizePrice(point.price);
      if (!Number.isFinite(previousPrice) || !Number.isFinite(currentPrice) || previousPrice <= 0) {
        flushActiveChange();
        return;
      }
      if (previousPrice === currentPrice) return;
      const direction = currentPrice > previousPrice ? "up" : "down";
      const isContinuousChange =
        activeChange &&
        activeChange.direction === direction &&
        point.dateValue.getTime() - activeChange.endDateValue.getTime() <= continuousChangeMaxGapMs;
      if (isContinuousChange) {
        activeChange.endDate = point.date;
        activeChange.endDateValue = point.dateValue;
        activeChange.endPrice = currentPrice;
        activeChange.count += 1;
        return;
      }
      flushActiveChange();
      activeChange = {
        direction,
        firstChangeDate: point.date,
        firstChangeDateValue: point.dateValue,
        endDate: point.date,
        endDateValue: point.dateValue,
        startPrice: previousPrice,
        endPrice: currentPrice,
        count: 1,
      };
    });
    flushActiveChange();

    let previousMarker = null;
    return markers.map((marker) => {
      const nextMarker = {
        ...marker,
        lane: previousMarker && Math.abs(marker.x - previousMarker.x) < 54 ? (previousMarker.lane + 1) % 2 : 0,
      };
      previousMarker = nextMarker;
      return nextMarker;
    });
  })();
  const adSeries = [
    {
      key: "spend",
      dotClass: "ad-spend-dot",
      label: "广告花费",
      value: (point) => point.adSpend,
      y: (point) => spendScale(point.adSpend),
      rule: (point) => [`广告花费 = spend 按周求和`, `${point.label} 广告花费 = ${formatMoney(point.adSpend)}`],
    },
  ];

  return (
    <div className="forecast-ad-strip" aria-label="广告与价格日趋势参考">
      <div className="forecast-ad-head">
        <span>广告参考</span>
        <div className="forecast-ad-legend">
          <span className="spend">广告花费</span>
          <span className="price">价格</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        {spendTicks.map((tick) => (
          <g key={`ad-spend-${tick}`}>
            <line x1={axisStartX} x2={width - margin.right} y1={spendScale(tick)} y2={spendScale(tick)} />
            <text x={margin.left - 9} y={spendScale(tick) + 4} textAnchor="end">
              {formatMoney(tick)}
            </text>
          </g>
        ))}
        {priceTicks.map((tick) => (
          <text key={`price-${tick}`} className="price-axis-label" x={width - margin.right - 8} y={priceScale(tick) + 4} textAnchor="end">
            {formatMoney(tick)}
          </text>
        ))}
        <path className="ad-spend-line" d={spendLine || ""} />
        {priceData.length > 0 && <path className="price-line" d={priceLine || ""} />}
        {datedAdData.map((point) => (
          <React.Fragment key={`ad-point-${point.week}`}>
            {adSeries.map((series) => {
              if (series.value(point) === null) return null;
              const x = xForWeek(point);
              const y = series.y(point);
              const isActive = activeAdPoint?.id === `${point.week}-${series.key}`;
              return (
                <circle
                  className={`${series.dotClass} ${isActive ? "active" : ""}`}
                  cx={x}
                  cy={y}
                  key={series.key}
                  onMouseEnter={() =>
                    setActiveAdPoint({
                      id: `${point.week}-${series.key}`,
                      x,
                      y,
                      label: point.label,
                      title: series.label,
                      lines: series.rule(point),
                    })
                  }
                  onMouseLeave={() => setActiveAdPoint(null)}
                  r={isActive ? "5.5" : "3.5"}
                />
              );
            })}
          </React.Fragment>
        ))}
        {priceData.map((point, index) => {
          const x = xForDate(point.dateValue);
          const y = priceScale(point.price);
          const isActive = activeAdPoint?.id === `${point.date}-price`;
          const previous = index > 0 ? priceData[index - 1] : null;
          const previousPrice = previous ? Number(previous.price) : null;
          const currentPrice = Number(point.price);
          const changeRatio =
            previousPrice && previousPrice > 0 && Math.round(previousPrice * 100) !== Math.round(currentPrice * 100)
              ? (currentPrice - previousPrice) / previousPrice
              : null;
          return (
            <circle
              className={`price-dot ${isActive ? "active" : ""}`}
              cx={x}
              cy={y}
              key={`${point.date}-${index}`}
              onMouseEnter={() =>
                setActiveAdPoint({
                  id: `${point.date}-price`,
                  x,
                  y,
                  label: point.date,
                  title: "日价格",
                  lines: [
                    `价格 = ${formatMoney(point.price)} ${point.currencyCode}`.trim(),
                    ...(changeRatio !== null ? [`较上次 = ${formatSignedRatioPercent(changeRatio)}`] : []),
                    `Listing = ${formatMoney(point.listingPrice)} ${point.currencyCode}`.trim(),
                    `Landed = ${formatMoney(point.landedPrice)} ${point.currencyCode}`.trim(),
                    `来源行数 = ${formatNumber(point.sourceRowCount)}`,
                  ],
                })
              }
              onMouseLeave={() => setActiveAdPoint(null)}
              r={isActive ? "4.8" : "2.1"}
            />
          );
        })}
        {xTicks.map((tick) => (
            <text key={`ad-label-${tick.key}`} className="ad-x-label" x={tick.x} y={height - 28} textAnchor={tick.textAnchor || "middle"}>
              {formatAxisDate(tick.dateValue)}
            </text>
        ))}
        {priceChangeMarkers.map((marker) => (
          <text
            className={`price-change-marker ${marker.direction}`}
            key={marker.id}
            x={marker.x}
            y={height - 9 - marker.lane * 11}
            textAnchor={marker.x < margin.left + 18 ? "start" : marker.x > width - margin.right - 18 ? "end" : "middle"}
          >
            <title>
              {marker.startDate === marker.endDate
                ? `${marker.endDate} 价格${marker.direction === "up" ? "上涨" : "下降"} ${marker.label}`
                : `${marker.startDate} 至 ${marker.endDate} 连续${marker.direction === "up" ? "上涨" : "下降"} ${marker.label}`}
            </title>
            <tspan className="price-change-arrow">{marker.direction === "up" ? "▲" : "▼"}</tspan>
            <tspan dx="3">{marker.label}</tspan>
          </text>
        ))}
        {activeAdPoint && <ForecastSvgTooltip point={activeAdPoint} width={width} height={height} />}
      </svg>
    </div>
  );
}

function DetailSection({ title, tooltip = "", children }) {
  return (
    <section className="detail-section">
      <h3 title={tooltip || undefined}>{title}</h3>
      {children}
    </section>
  );
}

function DetailGrid({ rows }) {
  return (
    <dl className="detail-grid">
      {rows.map((row) => {
        const { label, value, tooltip } = normalizeDetailRow(row);
        return (
        <div key={label} title={tooltip || undefined}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === "" ? "-" : value}</dd>
        </div>
        );
      })}
    </dl>
  );
}

function normalizeDetailRow(row) {
  if (Array.isArray(row)) {
    const [label, value, tooltip = ""] = row;
    return { label, value, tooltip };
  }
  return row || { label: "-", value: "-", tooltip: "" };
}

function RootCauseSummary({
  item,
  diagnosis,
  loading,
  error,
  forecastReviewLoading,
  forecastReviewError,
  firstLegLoading,
  firstLegError,
}) {
  const causes = Array.isArray(diagnosis?.root_cause_analysis) ? diagnosis.root_cause_analysis : [];
  const sections = rootCauseSections(causes);
  const anomalies = diagnosisSignalAnomalies(diagnosis);
  const isBusy = Boolean(loading || forecastReviewLoading || firstLegLoading);
  const stockoutSummary = useMemo(() => item ? piciShortageWindowSummary(item) : null, [item]);
  const stockoutWeeks = stockoutSummary?.fishboneWeeks || [];
  const stockoutSectionKeys = new Set(sections.map((section) => section.key));
  const displaySections = stockoutWeeks.length > 0 && !stockoutSectionKeys.has("inventory")
    ? [
        ...sections,
        {
          key: "inventory",
          title: "库存明细",
          description: "看 FBA 前端可售、库存位置、缺口和库龄结构。",
          items: [],
        },
      ]
    : sections;
  return (
    <div className="root-cause-panel">
      {isBusy && (
        <p className="root-cause-status">
          {forecastReviewLoading
            ? "正在读取月度预测复盘，用于判断超卖/低卖/计划异常。"
            : firstLegLoading
              ? "正在读取头程批次，用于判断物流延期/采购延期。"
              : "正在生成断货/冗余归因。"}
        </p>
      )}
      {error && <p className="root-cause-error">归因诊断失败：{error}</p>}
      {forecastReviewError && <p className="root-cause-warning">月度复盘未取到：{forecastReviewError}</p>}
      {firstLegError && <p className="root-cause-warning">供应追因头程数据未取到：{firstLegError}</p>}
      {causes.length > 0 ? (
        <div className="root-cause-sections">
          {displaySections.map((section) => {
            const isStockoutDetailSection = section.key === "inventory" && stockoutWeeks.length > 0;
            const visibleItems = isStockoutDetailSection
              ? section.items.filter((cause) => cause?.type !== "inventory_position")
              : section.items;
            return (
            <section className={`root-cause-section ${section.key} ${isStockoutDetailSection ? "stockout-detail" : ""}`} key={section.key}>
              <div className="root-cause-section-head">
                <div>
                  <strong>{isStockoutDetailSection ? "断货明细" : section.title}</strong>
                  <p>{isStockoutDetailSection ? "按现有到货与缺口逐周展示断货窗口。" : section.description}</p>
                </div>
                <span>{isStockoutDetailSection ? `断${formatNumber(stockoutSummary?.totalDays || 0)}天` : `${formatNumber(section.items.length)}项`}</span>
              </div>
              <div className="root-cause-list">
                {isStockoutDetailSection && <RootCauseStockoutDetail weeks={stockoutWeeks} />}
                {visibleItems.map((cause, index) => (
                  <RootCauseItem cause={cause} sectionKey={section.key} index={index} key={`${section.key}-${cause.type || "cause"}-${index}`} />
                ))}
              </div>
            </section>
          );
          })}
        </div>
      ) : (
        <p className="empty-detail">
          {isBusy ? "归因生成中，稍等几秒会自动刷新在这里。" : "暂无断货/冗余归因。若需要按月判断，请先完成月度预测复盘。"}
        </p>
      )}
      {anomalies.length > 0 && (
        <div className="root-cause-signals" aria-label="销售提示">
          <strong>销售提示</strong>
          <ul>
            {anomalies.map((item, index) => (
              <li key={`${item.kind}-${index}`}>
                <span>{item.kind}</span>
                <p>{item.text}</p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function RootCauseStockoutDetail({ weeks = [] }) {
  const rows = chunkArray(weeks, 5);
  if (!rows.length) {
    return <p className="empty-detail">暂无断货明细。</p>;
  }
  return (
    <div className="root-stockout-detail" aria-label="断货明细">
      {rows.map((row) => {
        const rowShortageDays = row.reduce((total, week) => total + week.shortageDays, 0);
        return (
          <div className="root-stockout-row" key={`${row[0].week}-${row[row.length - 1].week}`}>
            <div className="root-stockout-row-summary">
              <span>第 {row[0].week}-{row[row.length - 1].week} 周</span>
              <strong>总计断货 {formatNumber(rowShortageDays)} 天</strong>
            </div>
            <div className="root-stockout-track" style={{ "--stockout-week-count": row.length }}>
              {row.map((week) => (
                <div className={`supply-week-node ${week.shortageDays > 0 ? "has-shortage" : "ok"}`} key={week.week}>
                  <div className="supply-arrivals">
                    {week.arrivals.length > 0 ? (
                      week.arrivals.map((arrival, index) => (
                        <span
                          className={[
                            arrival.simulated ? "simulated" : "",
                            arrival.firstLeg ? "first-leg" : "",
                            arrival.channel ? `channel-${arrival.channel}` : "",
                          ].filter(Boolean).join(" ")}
                          key={`${week.week}-${arrival.day}-${index}`}
                          title={formatSupplyArrivalTitle(arrival)}
                          aria-label={formatSupplyArrivalTitle(arrival)}
                        >
                          {formatSupplyArrivalLabel(arrival)}
                        </span>
                      ))
                    ) : (
                      <span className="placeholder">无到货</span>
                    )}
                  </div>
                  <div className="supply-week-bar">
                    {week.days.map((day) => (
                      <span className={supplyDayClassName(day)} key={day.day} title={formatSupplyDayTitle(day)}>
                        <SupplyTimelineMarker day={day.day} />
                      </span>
                    ))}
                  </div>
                  <small>
                    第 {formatNumber(week.startDay)}-{formatNumber(week.endDay)} 天
                  </small>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function RootCauseItem({ cause }) {
  const segment = cause?.segment && typeof cause.segment === "object" ? cause.segment : null;
  const reasons = Array.isArray(segment?.reasons) ? segment.reasons : [];
  return (
    <article className={`root-cause-item ${cause?.type || "default"}`}>
      <div>
        <span>{rootCauseTypeLabels[cause?.type] || cause?.type || "归因"}</span>
        <strong>{cause?.cause || "-"}</strong>
      </div>
      <p>{cause?.evidence || "-"}</p>
      {segment && (
        <div className="segment-cause-meta">
          <span>{segment.label || "断货段"}</span>
          <span>缺口 {formatNumber(segment.shortage_quantity)} 件</span>
          <span>断 {formatNumber(segment.shortage_days)} 天</span>
        </div>
      )}
      {reasons.length > 0 && (
        <ol className="segment-reason-list">
          {reasons.map((reason, reasonIndex) => (
            <li key={`${reason.reason || "reason"}-${reasonIndex}`}>
              <strong>{String.fromCharCode(97 + reasonIndex)}. {reason.direction || "归因"}：{reason.reason || "-"}</strong>
              <p>{reason.detail || "-"}</p>
            </li>
          ))}
        </ol>
      )}
    </article>
  );
}

function rootCauseSections(causes) {
  const rows = Array.isArray(causes) ? causes.filter(Boolean) : [];
  const used = new Set();
  const sections = rootCauseSectionDefinitions
    .map((definition) => {
      const types = new Set(definition.types);
      const items = rows.filter((cause, index) => {
        if (used.has(index) || !types.has(cause?.type)) return false;
        used.add(index);
        return true;
      });
      return { ...definition, items };
    })
    .filter((section) => section.items.length > 0);
  const otherItems = rows.filter((_, index) => !used.has(index));
  if (otherItems.length > 0) {
    sections.push({
      key: "other",
      title: "其他原因",
      description: "未归入固定方向的补充证据。",
      items: otherItems,
    });
  }
  return sections;
}

function diagnosisSignalAnomalies(diagnosis) {
  const sales = diagnosis?.direction_recommendations?.sales || {};
  const performance = sales.sales_performance || {};
  const potential = sales.sales_potential || {};
  const forecast = sales.forecast_accuracy || {};
  const control = sales.stockout_and_sales_control || {};
  const rows = [];
  if (control.reminder) {
    rows.push({
      kind: "控销提醒",
      text: control.reminder,
    });
  }
  [
    ...(Array.isArray(performance.sales_anomalies) ? performance.sales_anomalies : []),
    ...(Array.isArray(potential.sales_anomalies) ? potential.sales_anomalies : []),
  ].forEach((item) => {
    rows.push({
      kind: "销量异常",
      text: `${item.label || item.type || "-"}：${item.reason || item.evidence || "-"}`,
    });
  });
  (Array.isArray(forecast.forecast_anomalies) ? forecast.forecast_anomalies : []).forEach((item) => {
    const reason = Array.isArray(item.reasons) ? item.reasons.join("；") : item.reason || item.evidence || "-";
    rows.push({
      kind: "预估异常",
      text: `${item.label || item.type || "-"}：${reason}`,
    });
  });
  return rows;
}

function RiskBadges({ item }) {
  const stockoutLevel = item.stockout_risk_level || "normal";
  const overstockLevel = item.overstock_risk_level || "normal";
  const stockoutTitle = [
    riskBadgeLabel(stockoutRiskBadgeLabels, stockoutLevel),
    formatStockoutAssertion(item),
    STOCKOUT_RULE_TOOLTIP,
  ].filter(Boolean).join("\n");
  const overstockTitle = [
    riskBadgeLabel(overstockRiskBadgeLabels, overstockLevel),
    formatOverstockAssertion(item),
    overstockRuleTooltip(item.sales_property),
  ].filter(Boolean).join("\n");

  return (
    <div className="risk-stack">
      <span className={`risk-pill stockout ${stockoutLevel}`} title={stockoutTitle}>
        {riskBadgeLabel(stockoutRiskBadgeLabels, stockoutLevel)}
      </span>
      <span className={`risk-pill overstock ${overstockLevel}`} title={overstockTitle}>
        {riskBadgeLabel(overstockRiskBadgeLabels, overstockLevel)}
      </span>
    </div>
  );
}

function FieldDecisionTable({ fields }) {
  const included = (fields || []).filter((field) => field.included);
  const excluded = (fields || []).filter((field) => !field.included);
  return (
    <section className="field-section">
      <div className="section-heading">
        <div>
          <h2>主表字段准入</h2>
          <p>已纳入 {included.length} 个字段，暂不纳入 {excluded.length} 个字段</p>
        </div>
        <CheckCircle2 size={20} />
      </div>
      <div className="field-grid">
        {(fields || []).map((field) => (
          <article className={`field-item ${field.included ? "included" : "excluded"}`} key={`${field.name}-${field.included}`}>
            <div>
              <strong>{field.label}</strong>
              <code>{field.name}</code>
            </div>
            <span>{field.group}</span>
            <p>{field.reason}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 1 });
}

function formatFullDateRange(start, end) {
  const startText = formatFullDate(start);
  const endText = formatFullDate(end);
  if (!startText || !endText) return "";
  return `${startText} 至 ${endText}`;
}

function formatFullDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return "";
  return `${match[1]}-${match[2]}-${match[3]}`;
}

function formatDateOrDash(value) {
  return formatFullDate(value) || "-";
}

function firstLegRelationLabel(value) {
  const labels = {
    in_transit_package: "在途明细",
    fba_shipment_confirmation: "FBA货件",
    fba_reference: "Reference",
  };
  return labels[value] || value || "头程";
}

function formatSignedNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${formatNumber(number)}`;
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  const number = Number(value);
  const sign = number > 0 ? "+" : "";
  return `${sign}${number.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
}

function formatRatioPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${(Number(value) * 100).toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
}

function formatSignedRatioPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  const percent = Number(value) * 100;
  const sign = percent > 0 ? "+" : "";
  return `${sign}${percent.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%`;
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

function formatPreciseNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 3 });
}

function lastItem(values) {
  return Array.isArray(values) && values.length > 0 ? values[values.length - 1] : "";
}

function formatDays(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${formatNumber(value)}天`;
}

function formatPiciGap(item) {
  if (item.pici_first_shortage_days) {
    const summary = piciShortageWindowSummary(item);
    return summary.firstStartDay <= 0 ? "今天起断货" : `最早第 ${formatNumber(summary.firstStartDay)} 天断货`;
  }
  if (item.pici_min_gap_quantity !== null && item.pici_min_gap_quantity !== undefined) {
    return "暂无断货";
  }
  return "-";
}

function formatPiciDetail(item) {
  if (item.pici_first_shortage_days) {
    const summary = piciShortageWindowSummary(item);
    return `合计断货 ${formatNumber(summary.totalDays)} 天；${summary.segments.join("、")}`;
  }
  if (item.pici_gap_values && Object.keys(item.pici_gap_values).length > 0) {
    return "合计断货 0 天";
  }
  return "无 chazhi";
}

function normalizeRiskFlag(flag, index) {
  if (flag && typeof flag === "object") {
    return {
      field: flag.field || `fnsku_out_of_stock_risk_${index + 1}`,
      label: flag.label || `断货风险 ${index + 1}`,
      value: flag.value || "-",
      reason: flag.reason || "底表风险标记命中",
    };
  }
  return {
    field: `fnsku_out_of_stock_risk_${index + 1}`,
    label: `断货风险 ${index + 1}`,
    value: String(flag || "-"),
    reason: `历史接口仅返回异常值：${flag || "-"}`,
  };
}

async function askSkuAssistant(item, question, forecastReview = null, firstLegShipments = []) {
  if (isSkuDiagnosisQuestion(question)) {
    const diagnosis = await fetchSkuDiagnosis(item, question, forecastReview, firstLegShipments);
    return formatSkuDiagnosisReply(diagnosis);
  }
  const response = await apiFetch(`${API_BASE_URL}/agent/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: buildSkuAssistantPrompt(item, question) }),
  });
  if (!response.ok) {
    throw new Error(`AI ${response.status}`);
  }
  const payload = await response.json();
  return extractAgentReply(payload) || localSkuChatReply(item, question);
}

async function fetchSkuDiagnosis(item, question = "生成 SKU 全链路诊断", forecastReview = null, firstLegShipments = []) {
  const shipmentRows = Array.isArray(firstLegShipments) ? firstLegShipments : [];
  const reviewPayload = forecastReview && typeof forecastReview === "object"
    ? { forecast_review: forecastReview, monthly_forecast_review: forecastReview }
    : {};
  const shipmentPayload = shipmentRows.length > 0
    ? { first_leg_shipments: shipmentRows, shipments: shipmentRows }
    : {};
  const enrichedItem = { ...item, ...reviewPayload, ...shipmentPayload };
  const response = await apiFetch(`${API_BASE_URL}/control-tower/sku-diagnosis/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item: enrichedItem, question }),
  });
  if (!response.ok) throw new Error(`诊断失败 ${response.status}`);
  return response.json();
}

async function fetchSkuShippingCost(item) {
  const response = await apiFetch(`${API_BASE_URL}/control-tower/sku-shipping-cost`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item }),
  });
  if (!response.ok) throw new Error(`成本估算失败 ${response.status}`);
  return response.json();
}

async function fetchFirstLegShipments(item) {
  const fnsku = String(item?.fnsku || "").trim();
  if (!fnsku) {
    return { query: { material_codes: [] }, row_count: 0, shipments: [] };
  }
  const params = new URLSearchParams();
  params.set("fnsku", fnsku);
  params.set("latest_only", "true");
  params.set("limit", "200");
  const endpoint = `/control-tower/first-leg-shipments?${params.toString()}`;
  const bases = Array.from(new Set([
    API_BASE_URL,
    "http://127.0.0.1:8016",
    "http://127.0.0.1:8015",
  ]));
  const errors = [];
  for (const baseUrl of bases) {
    try {
      const response = await fetchWithTimeout(`${baseUrl}${endpoint}`, {}, 8000);
      if (!response.ok) {
        errors.push(`${baseUrl} ${response.status}`);
        continue;
      }
      return response.json();
    } catch (error) {
      errors.push(`${baseUrl} ${error instanceof Error ? error.message : "请求失败"}`);
    }
  }
  throw new Error(`头程批次查询失败：${errors.join("；")}`);
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, credentials: "include", signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }
}

function isSkuDiagnosisQuestion(question) {
  return /全链路|诊断|库存情况|售卖情况|补救措施/.test(question);
}

function formatSkuDiagnosisReply(diagnosis) {
  if (diagnosis?.ai_reply) {
    return String(diagnosis.ai_reply);
  }
  const directionalReply = formatDirectionRecommendations(diagnosis);
  if (directionalReply) return directionalReply;
  const lines = [
    `SKU 全链路诊断：${diagnosis.material_code || "-"}`,
    `整体状态：${diagnosis.overall_status || "-"}；风险等级：${riskLabels[diagnosis.risk_level] || diagnosis.risk_level || "-"}`,
    "",
    "库存情况",
    ...formatFindingLines(diagnosis.inventory?.findings),
    "",
    "售卖情况",
    ...formatFindingLines(diagnosis.sales?.findings),
    "",
    "断货风险",
    ...formatFindingLines(diagnosis.stockout?.findings),
    "",
    "冗余风险",
    ...formatFindingLines(diagnosis.overstock?.findings),
    "",
    "归因",
    ...formatFindingLines(diagnosis.attribution),
    "",
    "处理逻辑",
    ...formatNumberedLines(diagnosis.handling_logic),
    "",
    "补救措施",
    ...formatRemedyLines(diagnosis.remedies),
  ];
  return lines.join("\n");
}

function formatDirectionRecommendations(diagnosis) {
  const directions = diagnosis?.direction_recommendations;
  if (!directions || typeof directions !== "object") return "";
  return [
    `SKU 全链路诊断：${diagnosis.material_code || "-"}`,
    `整体状态：${diagnosis.overall_status || "-"}；风险等级：${riskLabels[diagnosis.risk_level] || diagnosis.risk_level || "-"}`,
    "",
    "归因",
    ...formatRootCauseLines(diagnosis.root_cause_analysis),
    "",
    "销售方向",
    ...formatDirectionSection(directions.sales),
    "",
    "物流方向",
    ...formatDirectionSection(directions.logistics),
    "",
    "计划方向",
    ...formatDirectionSection(directions.plan),
  ].join("\n");
}

function formatRootCauseLines(values) {
  const rows = Array.isArray(values) ? values : [];
  if (!rows.length) return ["- 暂无"];
  return rows.map((item) =>
    `- ${item.cause || "-"}：${item.evidence || "-"}；建议：${item.recommendation || "-"}`
  );
}

function formatDirectionSection(section) {
  if (!section || typeof section !== "object") return ["- 暂无"];
  const lines = [`- ${section.summary || "暂无"}`];
  if (section.sales_performance) {
    const performance = section.sales_performance;
    const demand = performance.demand_reference || {};
    lines.push(
      `- 售卖表现：复盘实际销量 ${formatNumber(performance.actual_sales)}；区间 ${performance.review_start_date || "-"} 至 ${performance.review_end_date || "-"}；${performance.sales_curve || "-"}；需求参考 7天 ${formatNumber(demand.demand_7d)}、30天 ${formatNumber(demand.demand_30d)}、日均 ${formatNumber(demand.daily_demand)}`
    );
    (Array.isArray(performance.sales_anomalies) ? performance.sales_anomalies : []).forEach((item) => {
      lines.push(`- 销量异常：${item.label || item.type || "-"}；${item.reason || "-"}`);
    });
  }
  if (section.sales_potential) {
    lines.push(
      `- 销售潜力：${section.sales_potential.label || "-"}；销量/广告费 ${section.sales_potential.weekly_sales_ad_ratio ?? "-"}；${section.sales_potential.sales_curve || "-"}`
    );
  }
  if (section.stockout_and_sales_control) {
    const control = section.stockout_and_sales_control;
    lines.push(
      `- 断货/控销：${control.stockout_window || "-"}；控销 ${formatNumber(control.control_quantity)} 件 / ${formatNumber(control.control_days)} 天；${control.recommendation || "-"}`
    );
  }
  if (section.forecast_accuracy) {
    const forecast = section.forecast_accuracy;
    lines.push(
      `- 销售预测：预测 ${formatNumber(forecast.forecast_quantity)}，实际 ${formatNumber(forecast.actual_sales)}，偏差 ${formatNumber(forecast.variance_percent)}%；${forecast.recommendation || "-"}`
    );
    (Array.isArray(forecast.forecast_anomalies) ? forecast.forecast_anomalies : []).forEach((item) => {
      const reasons = Array.isArray(item.reasons) ? item.reasons.join("；") : item.reason || "";
      lines.push(`- 预估异常：${item.label || item.type || "-"}；${reasons || "-"}`);
    });
  }
  (Array.isArray(section.detected_anomalies) ? section.detected_anomalies : []).forEach((item) => {
    lines.push(`- 异常：${item.cause || "-"}；证据：${item.evidence || "-"}；建议：${item.recommendation || "-"}`);
  });
  (Array.isArray(section.checks) ? section.checks : []).forEach((item) => {
    lines.push(`- 检查：${item}`);
  });
  const inventory = section.inventory_replenishment || null;
  if (inventory && typeof inventory === "object") {
    if (inventory.strategy_label || inventory.source) {
      lines.push(`- 计划口径：${inventory.strategy_label || "-"}；来源 ${inventory.source || "-"}`);
    }
    if (inventory.pmc_recommendation || inventory.replenishment_text) {
      lines.push(`- 程序补货建议：${inventory.pmc_recommendation || inventory.replenishment_text}`);
    }
    lines.push(`- 补货数量：合计 ${formatNumber(inventory.total_replenishment_quantity)} 件`);
    const purchase = inventory.purchase || null;
    if (purchase && typeof purchase === "object") {
      lines.push(`- 采购：建议采购草稿量 ${formatNumber(purchase.suggested_purchase_quantity)}；${purchase.summary || "-"}`);
    }
    (Array.isArray(inventory.methods) ? inventory.methods : []).forEach((method) => {
      lines.push(`- 补货方式：${method.channel_label || method.channel || "-"} ${formatNumber(method.suggested_quantity)} 件，到货第 ${formatNumber(method.arrival_day)} 天`);
    });
  }
  if (section.cost_comparison?.recommendation) {
    lines.push(`- 成本：${section.cost_comparison.recommendation}`);
  }
  (Array.isArray(section.actions) ? section.actions : []).forEach((item) => {
    lines.push(`- 动作：${item}`);
  });
  (Array.isArray(section.skill_placeholders) ? section.skill_placeholders : []).forEach((item) => {
    lines.push(`- Skill草稿：${item.name || "-"}（仅打印草稿）`);
  });
  return lines;
}

function formatShippingCostEstimate(estimate) {
  if (!estimate || typeof estimate !== "object") return "";
  const rateText = "费率：加急空运 85 元/kg，普通空运 60 元/kg，快船 11.5 元/kg，慢船 9 元/kg";
  if (!estimate.ok) {
    return [
      "发货成本粗估",
      `未计算：${estimate.reason || "缺少 product info.weight_gram"}`,
      `公式：${estimate.formula || "unit_shipping_cost_cny = unit_weight_kg * rate_cny_per_kg"}`,
      rateText,
    ].join("\n");
  }
  const weight = estimate.weight || {};
  const lines = [
    "发货成本粗估",
    `重量：${formatPreciseNumber(weight.weight_gram)}g（${formatPreciseNumber(weight.weight_kg)}kg），来源：${weight.source_table || "-"}${weight.source_field ? `.${weight.source_field}` : ""}`,
    `公式：${estimate.formula || "unit_shipping_cost_cny = unit_weight_kg * rate_cny_per_kg"}`,
    rateText,
  ];
  const estimates = Array.isArray(estimate.estimates) ? estimate.estimates : [];
  if (!estimates.length) {
    lines.push("暂无可套用的加急空运/普通空运/快船/慢船候选数量。");
    return lines.join("\n");
  }
  estimates.forEach((item) => {
    const quantityText = Number.isFinite(Number(item.suggested_quantity)) ? `；建议量 ${formatNumber(item.suggested_quantity)} 件` : "";
    const totalCostText = Number.isFinite(Number(item.estimated_cost_cny)) ? `；预计总成本 ${formatMoney(item.estimated_cost_cny)} 元` : "";
    lines.push(
      `- ${item.channel_label || item.channel}: 单件 ${formatMoney(item.unit_shipping_cost_cny)} 元（${formatPreciseNumber(item.unit_weight_kg)}kg * ${formatPreciseNumber(item.rate_cny_per_kg)} 元/kg）${quantityText}${totalCostText}`
    );
  });
  const comparison = estimate.cost_comparison || {};
  if (comparison.recommendation) {
    lines.push(`成本建议：${comparison.recommendation}`);
  }
  return lines.join("\n");
}

function formatAiReview(review) {
  if (!review || typeof review !== "object") return "";
  const input = safePrettyJson(review.input);
  const output = safePrettyJson(review.output);
  return [
    "—— 模型输入输出审阅 ——",
    `模型：${review.model || "-"}`,
    `记录：${review.record_path || "-"}`,
    "",
    "模型输入",
    input,
    "",
    "模型原始输出",
    output,
  ].join("\n");
}

function safePrettyJson(value) {
  try {
    const text = JSON.stringify(value ?? null, null, 2);
    return text.length > 16000 ? `${text.slice(0, 16000)}\n...（已截断，完整内容见模型记录文件）` : text;
  } catch (error) {
    return String(value ?? "");
  }
}

function formatFindingLines(values) {
  if (!Array.isArray(values) || values.length === 0) return ["- 暂无"];
  return values.map((value) => `- ${value}`);
}

function formatNumberedLines(values) {
  if (!Array.isArray(values) || values.length === 0) return ["1. 暂无"];
  return values.map((value, index) => `${index + 1}. ${value}`);
}

function formatRemedyLines(values) {
  if (!Array.isArray(values) || values.length === 0) return ["- 暂无"];
  return values.map((item) => {
    if (!item || typeof item !== "object") return `- ${item}`;
    return `- [${item.priority || "-"}] ${item.owner || "-"}：${item.action || "-"}`;
  });
}

function buildSkuAssistantPrompt(item, question) {
  const shortage = piciShortageWindowSummary(item);
  return [
    "你是 PMC 库存控制塔里的 SKU 助手。请只围绕下面这个 SKU 上下文回答，回答要简洁、可执行。",
    "回答限制：不要输出风险分、评分、score、最高分，也不要输出“命中等级”列；解释冗余时只按可售天数、合理阈值、冗余判定阈值、对应动作说明。",
    `SKU: ${item.material_code}`,
    `名称: ${item.sku_name || "-"}`,
    `店铺/国家: ${item.store_name || "-"} / ${item.country_code || item.shipments_country || "-"}`,
    `销售属性: ${item.sales_property || "-"}`,
    `风险: ${item.warning_type || "-"}，处理等级 ${riskLabels[item.risk_level] || item.risk_level || "-"}`,
    `断货: ${formatPiciGap(item)}，合计 ${formatNumber(shortage.totalDays)} 天，最大缺口 ${formatNumber(item.pici_min_gap_quantity)}`,
    `库存: 总 ${formatNumber(item.total_inventory)}，FBA ${formatNumber(item.fba_sellable)}，在途 ${formatNumber(item.inbound_total)}，海外 ${formatNumber(item.overseas_inventory)}，本地 ${formatNumber(item.local_inventory)}`,
    `需求: 区间销量 ${formatNumber(item.daily_sales_volume)}，7天 ${formatNumber(item.demand_7d)}，30天 ${formatNumber(item.demand_30d)}，日均 ${formatNumber(item.daily_demand)}`,
    `冗余阈值提示: ${formatOverstockRuleHintText(item.sales_property)}`,
    `冗余原因: ${item.evidence?.overstock_reason || "-"}`,
    `异常标记: ${(item.evidence?.risk_flags || []).map((flag, index) => normalizeRiskFlag(flag, index).reason).join("；") || "-"}`,
    `建议动作: ${item.suggested_action || "-"}`,
    `用户问题: ${question}`,
  ].join("\n");
}

function extractAgentReply(payload) {
  if (!payload || typeof payload !== "object") return "";
  if (payload.reply) return String(payload.reply);
  if (payload.result?.reply) return String(payload.result.reply);
  if (payload.artifacts?.chat_reply?.reply) return String(payload.artifacts.chat_reply.reply);
  if (Array.isArray(payload.decisions) && payload.decisions.length > 0) {
    const first = payload.decisions[0];
    const actions = Array.isArray(first.recommended_actions) ? first.recommended_actions.join("；") : "";
    return [first.summary, actions && `建议：${actions}`].filter(Boolean).join("\n");
  }
  return "";
}

function localSkuChatReply(item, question) {
  const shortage = piciShortageWindowSummary(item);
  const flags = item.evidence?.risk_flags || [];
  const lowered = question.toLowerCase();
  if (isSkuDiagnosisQuestion(question)) {
    return [
      `SKU 全链路诊断：${item.material_code}`,
      `整体状态：${item.warning_type || "正常"}；风险等级：${riskLabels[item.risk_level] || item.risk_level || "-"}`,
      "",
      `库存情况：总库存 ${formatNumber(item.total_inventory)}，FBA可售 ${formatNumber(item.fba_sellable)}，海外 ${formatNumber(item.overseas_inventory)}，本地 ${formatNumber(item.local_inventory)}，在途 ${formatNumber(item.inbound_total)}，预计7天 ${formatNumber(item.projected_7d)}。`,
      `售卖情况：销售属性 ${item.sales_property || "-"}，区间销量 ${formatNumber(item.daily_sales_volume)}，7天需求 ${formatNumber(item.demand_7d)}，30天需求 ${formatNumber(item.demand_30d)}，日均 ${formatNumber(item.daily_demand)}。`,
      `断货风险：${formatPiciGap(item)}，合计断货 ${formatNumber(shortage.totalDays)} 天，关键缺口 ${item.pici_key_gap || "-"}。`,
      `冗余提示：${formatOverstockRuleHintText(item.sales_property)}；${item.evidence?.overstock_reason || "当前未返回具体冗余原因"}。`,
      `归因：${item.stockout_risk_level !== "normal" && item.overstock_risk_level !== "normal" ? "断货和冗余并存，优先按库存位置、库龄和补货节奏错配处理。" : item.suggested_action || "暂无明确异常。"}`,
      `补救措施：先核查 chazhi 和在途覆盖；能转化库存则调拨/催上架，不能覆盖则复核采购补救；若命中冗余，同步冻结非必要采购和发货，交由销售清货。`,
    ].join("\n");
  }
  if (question.includes("断货")) {
    return `${item.material_code} 当前${formatPiciGap(item)}，合计断货 ${formatNumber(shortage.totalDays)} 天。优先看 FBA 可售 ${formatNumber(item.fba_sellable)}、在途 ${formatNumber(item.inbound_total)} 和 chazhi 缺口 ${item.pici_key_gap || "-"}，再判断是否加急发货或补采购。`;
  }
  if (question.includes("冗余")) {
    return `${item.material_code} 的冗余依据是：${item.evidence?.overstock_reason || "当前未返回具体冗余原因"}。${formatOverstockRuleHintText(item.sales_property)}。如果同时断货，通常说明库存位置或库龄结构有问题，不是简单总量不足。`;
  }
  if (question.includes("异常")) {
    return flags.length
      ? `库存异常来自底表风险标记：${flags.map((flag, index) => normalizeRiskFlag(flag, index).reason).join("；")}。建议先复核底表来源，再决定是否关闭异常。`
      : "当前没有命中库存异常底表标记。";
  }
  if (question.includes("销售")) {
    return `可以发给销售：${item.material_code} 当前${item.warning_type || "存在库存风险"}，请确认是否需要控销、促销或调整销售节奏。关键数据：区间销量 ${formatNumber(item.daily_sales_volume)}，30天需求 ${formatNumber(item.demand_30d)}，预计7天 ${formatNumber(item.projected_7d)}。`;
  }
  if (question.includes("关闭") || lowered.includes("close")) {
    return `不建议直接关闭。先确认三件事：1. chazhi 缺口是否仍为负；2. FBA/在途/海外仓是否能覆盖最早断货日；3. 底表异常标记是否已复核。三项都无风险后再关闭。`;
  }
  return `${item.material_code} 当前提示为 ${item.warning_type || "正常"}。建议先按“断货明细 -> 库存结构 -> 冗余依据 -> 库存异常”的顺序复核，再决定派给销售、采购、发货或 PMC 关闭。`;
}

function salesPropertyClass(value) {
  const text = String(value || "").trim();
  if (text === "爆") return "hot";
  if (text === "旺") return "strong";
  if (text === "平") return "steady";
  if (text === "滞") return "slow";
  return "other";
}

function piciShortageWindowSummary(item, simulation = null, options = {}) {
  const entries = Object.entries(item.pici_gap_values || {})
    .map(([key, value]) => {
      const horizon = Number(key.split("_").pop());
      const parsed = parsePiciValue(value);
      return Number.isFinite(horizon) && parsed ? { horizon, ...parsed } : null;
    })
    .filter(Boolean)
    .sort((a, b) => a.horizon - b.horizon);
  let previousHorizon = 0;
  let previousAvailable = 0;
  let previousForecast = 0;
  let basePool = 0;
  const simulationPools = [];
  let totalDays = 0;
  const segments = [];
  const fishboneDays = [];
  const arrivals = [];
  let activeShortageStart = null;
  let firstStartDay = null;
  const simulationConfig = normalizeSupplySimulation(simulation);
  const summaryOptions = options && typeof options === "object" ? options : {};
  const firstLegArrivalMode = summaryOptions.arrivalSource === "first_leg";
  const firstLegArrivalsByDay = groupFirstLegArrivalsByDay(summaryOptions.firstLegArrivals || []);

  entries.forEach((entry) => {
    const intervalDays = Math.max(entry.horizon - previousHorizon, 0);
    const intervalForecast = Math.max(entry.forecast - previousForecast, 0);
    const intervalSupply = firstLegArrivalMode
      ? (previousHorizon === 0 ? Math.max(entry.available, 0) : 0)
      : Math.max(entry.available - previousAvailable, 0);
    const intervalStartDay = previousHorizon + 1;
    const intervalEndDay = entry.horizon;

    if (intervalDays > 0) {
      const dailyForecast = intervalForecast / intervalDays;
      basePool += intervalSupply;

      if (!firstLegArrivalMode && previousHorizon > 0 && intervalSupply > 0) {
        arrivals.push({ day: intervalStartDay, quantity: intervalSupply });
      }

      for (let day = intervalStartDay; day <= intervalEndDay; day += 1) {
        if (firstLegArrivalMode) {
          (firstLegArrivalsByDay.get(day) || []).forEach((arrival) => {
            basePool += arrival.quantity;
            arrivals.push(arrival);
          });
        }

        const simulationArrival = simulatedArrivalForDay(simulationConfig, day);
        if (simulationArrival.quantity > 0) {
          simulationPools.push({
            channel: simulationArrival.channel,
            quantity: simulationArrival.quantity,
          });
          arrivals.push({
            day,
            quantity: simulationArrival.quantity,
            simulated: true,
            channel: simulationArrival.channel,
          });
        }

        const controlRatio = controlRatioForDay(simulationConfig, day);
        const effectiveForecast = dailyForecast * (1 - controlRatio / 100);
        const controlSavedQuantity = Math.max(dailyForecast - effectiveForecast, 0);
        let remainingDemand = effectiveForecast;
        let replenishedQuantity = 0;
        const replenishedByChannel = {};

        const baseUsed = Math.min(basePool, remainingDemand);
        basePool -= baseUsed;
        remainingDemand -= baseUsed;

        while (remainingDemand > 0 && simulationPools.length > 0) {
          const pool = simulationPools[0];
          const usedQuantity = Math.min(pool.quantity, remainingDemand);
          replenishedQuantity += usedQuantity;
          replenishedByChannel[pool.channel] = (replenishedByChannel[pool.channel] || 0) + usedQuantity;
          pool.quantity -= usedQuantity;
          remainingDemand -= usedQuantity;
          if (pool.quantity <= 0.000001) {
            simulationPools.shift();
          }
        }

        const shortageQuantity = Math.max(remainingDemand, 0);
        const isCovered = dailyForecast <= 0 || remainingDemand <= 0.000001;
        const status = isCovered && replenishedQuantity > 0 ? "replenished" : isCovered ? "ok" : "shortage";
        const replenishmentChannel = dominantReplenishmentChannel(replenishedByChannel);
        fishboneDays.push({
          day,
          status,
          controlRatio,
          forecast: effectiveForecast,
          originalForecast: dailyForecast,
          controlSavedQuantity,
          shortageQuantity,
          replenishedQuantity,
          replenishmentChannel,
          partialReplenished: !isCovered && replenishedQuantity > 0,
        });

        if (isCovered) {
          if (activeShortageStart !== null) {
            segments.push(formatShortageSegment(activeShortageStart, day - activeShortageStart));
            activeShortageStart = null;
          }
        } else {
          totalDays += 1;
          firstStartDay = firstStartDay === null ? day : Math.min(firstStartDay, day);
          activeShortageStart = activeShortageStart ?? day;
        }
      }
    }

    previousHorizon = entry.horizon;
    previousAvailable = entry.available;
    previousForecast = entry.forecast;
  });
  if (activeShortageStart !== null) {
    const lastDay = fishboneDays[fishboneDays.length - 1]?.day || activeShortageStart;
    segments.push(formatShortageSegment(activeShortageStart, lastDay - activeShortageStart + 1));
  }
  const slowShipEndDay = shippingSafetyEndDayForItem(item, safetyStockDaysForSimulation(simulation, item));
  return {
    totalDays,
    firstStartDay: firstStartDay ?? item.pici_first_shortage_days ?? 0,
    segments,
    days: fishboneDays,
    urgentAirReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 10, 19),
    standardAirReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 20, 45),
    fastReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 46, 60),
    slowReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 61, slowShipEndDay),
    fishboneWeeks: buildSupplyFishboneWeeks(fishboneDays, arrivals),
  };
}

function buildFirstLegArrivalBatches(rows = [], item = {}) {
  const baseDate = parseIsoDate(item.sales_end_date) || parseIsoDate(previousDate());
  const maxHorizon = maxPiciHorizon(item);
  return (Array.isArray(rows) ? rows : [])
    .map((row, index) => {
      const arrivalDate = firstLegArrivalDate(row);
      const arrivalDateValue = parseIsoDate(arrivalDate);
      const quantity = firstLegArrivalQuantity(row);
      if (!baseDate || !arrivalDateValue || quantity <= 0) return null;
      const day = Math.floor((arrivalDateValue - baseDate) / 86400000) + 1;
      if (!Number.isFinite(day) || day < 1 || day > maxHorizon) return null;
      return {
        day,
        quantity,
        firstLeg: true,
        date: arrivalDate,
        batchLabel: row.batch_num || row.ship_id || row.package_id || row.refer_id || row.warehouse_inbound_number || `批次${index + 1}`,
        status: row.current_shipping_status || row.detail_status || "",
        method: [row.shipping_method, row.logistics_provider || row.detail_logistics_provider].filter(Boolean).join(" / "),
      };
    })
    .filter(Boolean)
    .sort((left, right) => left.day - right.day || String(left.batchLabel).localeCompare(String(right.batchLabel), "zh-Hans-CN"));
}

function firstLegArrivalDate(row = {}) {
  return [
    row.actual_delivery_time,
    row.estimated_delivery_time,
    row.actual_arrival_time,
    row.estimated_arrival_time,
    row.plan_delivery_time,
  ].map(formatFullDate).find(Boolean) || "";
}

function firstLegArrivalQuantity(row = {}) {
  const inTransit = Number(row.in_transit_qty);
  const shipped = Number(row.ship_num);
  const received = Number(row.quantity_received);
  if (Number.isFinite(inTransit) && inTransit > 0) return inTransit;
  if (Number.isFinite(shipped) && shipped > 0) {
    if (Number.isFinite(received) && received > 0) {
      return Math.max(shipped - received, 0);
    }
    return shipped;
  }
  const totalItems = Number(row.total_item_count);
  return Number.isFinite(totalItems) && totalItems > 0 ? totalItems : 0;
}

function groupFirstLegArrivalsByDay(arrivals = []) {
  const grouped = new Map();
  (Array.isArray(arrivals) ? arrivals : []).forEach((arrival) => {
    const day = Number(arrival.day);
    const quantity = Number(arrival.quantity);
    if (!Number.isFinite(day) || !Number.isFinite(quantity) || quantity <= 0) return;
    const item = { ...arrival, day, quantity };
    grouped.set(day, [...(grouped.get(day) || []), item]);
  });
  grouped.forEach((items, day) => {
    const sortedItems = items.sort((left, right) => String(left.batchLabel).localeCompare(String(right.batchLabel), "zh-Hans-CN"));
    const totalQuantity = sortedItems.reduce((total, item) => total + Number(item.quantity || 0), 0);
    grouped.set(day, [{
      day,
      quantity: totalQuantity,
      firstLeg: true,
      date: sortedItems[0]?.date || "",
      batchLabel: sortedItems.length > 1 ? `${sortedItems.length}单` : sortedItems[0]?.batchLabel || "",
      status: sortedItems.length === 1 ? sortedItems[0]?.status || "" : "",
      method: sortedItems.length === 1 ? sortedItems[0]?.method || "" : "",
      batches: sortedItems,
    }]);
  });
  return grouped;
}

function maxPiciHorizon(item = {}) {
  const horizons = Object.keys(item.pici_gap_values || {})
    .map((key) => Number(key.split("_").pop()))
    .filter(Number.isFinite);
  return Math.max(98, ...horizons);
}

function buildSalesControlPlan(item, options = {}) {
  const startDay = options.startDay || 1;
  const targetLimitDay = options.targetLimitDay || 45;
  const maxControlRatio = 60;
  const summaryOptions = options.summaryOptions || {};
  const baseSummary = piciShortageWindowSummary(item, createEmptySupplySimulation(), summaryOptions);
  const baseWindow = summarizeSupplyWindow(baseSummary.days, startDay, targetLimitDay);
  const planMeta = {
    id: options.id || `target_${targetLimitDay}`,
    title: options.title,
    actionLabel: options.actionLabel,
    replenishmentMode: options.replenishmentMode || "standard",
    targetLimitDay,
  };
  if (!baseWindow.suggestedQuantity) {
    return {
      ...planMeta,
      segments: [],
      unresolvedSegments: [],
      controlSavedQuantity: 0,
      residualShortageQuantity: 0,
      shortageQuantity: 0,
      strategy: "none",
    };
  }

  const balancedPlan = solveBalancedSalesControlPlan(item, baseSummary.days, startDay, targetLimitDay, maxControlRatio, baseWindow, summaryOptions);
  const segmentedPlan = solveSegmentedSalesControlPlan(item, startDay, targetLimitDay, maxControlRatio, baseWindow, summaryOptions);
  if (options.controlMode === "recovery_segmented") {
    return {
      ...solveRecoverySegmentedSalesControlPlan(
        item,
        startDay,
        targetLimitDay,
        maxControlRatio,
        baseWindow,
        summaryOptions
      ),
      ...planMeta,
    };
  }
  if (balancedPlan && shouldUseBalancedControlPlan(balancedPlan, segmentedPlan)) {
    return { ...balancedPlan, ...planMeta };
  }
  return { ...segmentedPlan, ...planMeta };
}

function solveBalancedSalesControlPlan(item, baseDays, startDay, targetLimitDay, maxControlRatio, baseWindow, summaryOptions = {}) {
  const baseSegments = shortageSegmentsInWindow(baseDays, startDay, targetLimitDay);
  if (!baseSegments.length) return null;
  const endDay = baseSegments[baseSegments.length - 1].endDay;
  const buildSimulation = (controlRatio) => ({
    ...createEmptySupplySimulation(),
    salesControls: [
      {
        startDay,
        endDay,
        controlRatio,
      },
    ],
  });
  const maxSummary = piciShortageWindowSummary(item, buildSimulation(maxControlRatio), summaryOptions);
  const maxWindow = summarizeSupplyWindow(maxSummary.days, startDay, endDay);
  if (maxWindow.shortageQuantity > 0) {
    return {
      segments: [
        {
          startDay,
          endDay,
          targetStartDay: startDay,
          targetEndDay: endDay,
          controlRatio: maxControlRatio,
          controlSavedQuantity: maxWindow.controlSavedQuantity,
          residualShortageQuantity: maxWindow.shortageQuantity,
          residualShortageSegments: shortageSegmentsInWindow(maxSummary.days, startDay, endDay),
          unresolved: true,
        },
      ],
      unresolvedSegments: [
        {
          startDay,
          endDay,
          shortageQuantity: maxWindow.shortageQuantity,
          shortageSegments: shortageSegmentsInWindow(maxSummary.days, startDay, endDay),
          reason: "最高60%平滑控销仍无法覆盖。",
        },
      ],
      controlSavedQuantity: maxWindow.controlSavedQuantity,
      residualShortageQuantity: maxWindow.shortageQuantity,
      shortageQuantity: baseWindow.shortageQuantity,
      targetLimitDay,
      strategy: "balanced",
    };
  }

  let lower = 0;
  let upper = maxControlRatio;
  for (let index = 0; index < 10; index += 1) {
    const middle = (lower + upper) / 2;
    const summary = piciShortageWindowSummary(item, buildSimulation(middle), summaryOptions);
    const window = summarizeSupplyWindow(summary.days, startDay, endDay);
    if (window.shortageQuantity > 0) {
      lower = middle;
    } else {
      upper = middle;
    }
  }
  const controlRatio = Math.ceil(upper);
  const finalSummary = piciShortageWindowSummary(item, buildSimulation(controlRatio), summaryOptions);
  const finalWindow = summarizeSupplyWindow(finalSummary.days, startDay, endDay);
  return {
    segments: [
      {
        startDay,
        endDay,
        targetStartDay: startDay,
        targetEndDay: endDay,
        controlRatio,
        controlSavedQuantity: finalWindow.controlSavedQuantity,
        residualShortageQuantity: finalWindow.shortageQuantity,
        residualShortageSegments: [],
        unresolved: false,
      },
    ],
    unresolvedSegments: [],
    controlSavedQuantity: finalWindow.controlSavedQuantity,
    residualShortageQuantity: finalWindow.shortageQuantity,
    shortageQuantity: baseWindow.shortageQuantity,
    targetLimitDay,
    strategy: "balanced",
  };
}

function solveSegmentedSalesControlPlan(item, startDay, targetLimitDay, maxControlRatio, baseWindow, summaryOptions = {}) {
  const segments = [];
  const unresolvedSegments = [];
  let handledUntil = startDay - 1;

  for (let guard = 0; guard < 20; guard += 1) {
    const currentSummary = piciShortageWindowSummary(item, {
      ...createEmptySupplySimulation(),
      salesControls: segments,
    }, summaryOptions);
    const nextSegment = shortageSegmentsInWindow(currentSummary.days, startDay, targetLimitDay).find((segment) => segment.endDay > handledUntil);
    if (!nextSegment) break;

    const controlStartDay = Math.max(startDay, handledUntil + 1);
    const solved = solveSalesControlSegment(
      item,
      segments,
      controlStartDay,
      nextSegment.startDay,
      nextSegment.endDay,
      maxControlRatio,
      summaryOptions
    );
    if (solved) {
      segments.push(solved);
    }
    if (solved?.unresolved) {
      unresolvedSegments.push({
        startDay: solved.targetStartDay,
        endDay: solved.targetEndDay,
        shortageQuantity: solved.residualShortageQuantity,
        shortageSegments: solved.residualShortageSegments,
        reason: "最高60%控销仍无法覆盖该断货段",
      });
    }
    handledUntil = nextSegment.endDay;
  }

  const finalSummary = piciShortageWindowSummary(item, {
    ...createEmptySupplySimulation(),
    salesControls: segments,
  }, summaryOptions);
  const finalWindow = summarizeSupplyWindow(finalSummary.days, startDay, targetLimitDay);
  return {
    segments,
    unresolvedSegments,
    controlSavedQuantity: roundToOne(segments.reduce((total, segment) => total + Number(segment.controlSavedQuantity || 0), 0)),
    residualShortageQuantity: finalWindow.shortageQuantity,
    shortageQuantity: baseWindow.shortageQuantity,
    targetLimitDay,
    strategy: "segmented",
  };
}

function solveRecoverySegmentedSalesControlPlan(item, startDay, targetLimitDay, maxControlRatio, baseWindow, summaryOptions = {}) {
  const segments = [];
  const unresolvedSegments = [];
  let handledUntil = startDay - 1;

  for (let guard = 0; guard < 20; guard += 1) {
    const currentSummary = piciShortageWindowSummary(item, {
      ...createEmptySupplySimulation(),
      salesControls: segments,
    }, summaryOptions);
    const nextSegment = shortageSegmentsInWindow(currentSummary.days, startDay, targetLimitDay).find((segment) => segment.endDay > handledUntil);
    if (!nextSegment) break;

    const recoveryDay = firstRecoveredSupplyDay(currentSummary.days, handledUntil, nextSegment.startDay);
    const controlStartDay = recoveryDay || Math.max(startDay, handledUntil + 1);
    const solved = solveSalesControlSegment(
      item,
      segments,
      controlStartDay,
      nextSegment.startDay,
      nextSegment.endDay,
      maxControlRatio,
      summaryOptions
    );
    if (solved) {
      segments.push(solved);
    }
    if (solved?.unresolved) {
      unresolvedSegments.push({
        startDay: solved.targetStartDay,
        endDay: solved.targetEndDay,
        shortageQuantity: solved.residualShortageQuantity,
        shortageSegments: solved.residualShortageSegments,
        reason: "最高60%分段控销仍无法覆盖该断货段",
      });
    }
    handledUntil = nextSegment.endDay;
  }

  const finalSummary = piciShortageWindowSummary(item, {
    ...createEmptySupplySimulation(),
    salesControls: segments,
  }, summaryOptions);
  const finalWindow = summarizeSupplyWindow(finalSummary.days, startDay, targetLimitDay);
  return {
    segments,
    unresolvedSegments,
    controlSavedQuantity: roundToOne(segments.reduce((total, segment) => total + Number(segment.controlSavedQuantity || 0), 0)),
    residualShortageQuantity: finalWindow.shortageQuantity,
    shortageQuantity: baseWindow.shortageQuantity,
    targetLimitDay,
    strategy: "recovery_segmented",
  };
}

function firstRecoveredSupplyDay(days, handledUntil, targetStartDay) {
  return (days || []).find((day) => day.day > handledUntil && day.day <= targetStartDay && day.status !== "shortage")?.day || null;
}

function shouldUseBalancedControlPlan(balancedPlan, segmentedPlan) {
  const balancedMax = maxControlRatioInPlan(balancedPlan);
  const segmentedMax = maxControlRatioInPlan(segmentedPlan);
  if (!balancedPlan.residualShortageQuantity && segmentedPlan.residualShortageQuantity) return true;
  if (balancedPlan.residualShortageQuantity && !segmentedPlan.residualShortageQuantity) return false;
  if ((segmentedPlan.segments || []).length > 1 && balancedMax <= segmentedMax) return true;
  return balancedMax + 6 < segmentedMax;
}

function maxControlRatioInPlan(plan) {
  return Math.max(0, ...(plan?.segments || []).map((segment) => Number(segment.controlRatio) || 0));
}

function solveSalesControlSegment(item, existingSegments, controlStartDay, targetStartDay, targetEndDay, maxControlRatio, summaryOptions = {}) {
  const buildSimulation = (controlRatio) => ({
    ...createEmptySupplySimulation(),
    salesControls: [
      ...existingSegments,
      {
        startDay: controlStartDay,
        endDay: targetEndDay,
        controlRatio,
      },
    ],
  });
  const maxSummary = piciShortageWindowSummary(item, buildSimulation(maxControlRatio), summaryOptions);
  const maxTargetWindow = summarizeSupplyWindow(maxSummary.days, targetStartDay, targetEndDay);
  if (maxTargetWindow.shortageQuantity > 0) {
    const maxControlWindow = summarizeSupplyWindow(maxSummary.days, controlStartDay, targetEndDay);
    return {
      startDay: controlStartDay,
      endDay: targetEndDay,
      targetStartDay,
      targetEndDay,
      controlRatio: maxControlRatio,
      controlSavedQuantity: maxControlWindow.controlSavedQuantity,
      residualShortageQuantity: maxTargetWindow.shortageQuantity,
      residualShortageSegments: shortageSegmentsInWindow(maxSummary.days, targetStartDay, targetEndDay),
      unresolved: true,
    };
  }

  let lower = 0;
  let upper = maxControlRatio;
  for (let index = 0; index < 10; index += 1) {
    const middle = (lower + upper) / 2;
    const summary = piciShortageWindowSummary(item, buildSimulation(middle), summaryOptions);
    const targetWindow = summarizeSupplyWindow(summary.days, targetStartDay, targetEndDay);
    if (targetWindow.shortageQuantity > 0) {
      lower = middle;
    } else {
      upper = middle;
    }
  }

  const controlRatio = Math.ceil(upper);
  const finalSummary = piciShortageWindowSummary(item, buildSimulation(controlRatio), summaryOptions);
  const controlWindow = summarizeSupplyWindow(finalSummary.days, controlStartDay, targetEndDay);
  const targetWindow = summarizeSupplyWindow(finalSummary.days, targetStartDay, targetEndDay);
  return {
    startDay: controlStartDay,
    endDay: targetEndDay,
    targetStartDay,
    targetEndDay,
    controlRatio,
    controlSavedQuantity: controlWindow.controlSavedQuantity,
    residualShortageQuantity: targetWindow.shortageQuantity,
    residualShortageSegments: [],
    unresolved: false,
  };
}

function shortageSegmentsInWindow(days, startDay, endDay) {
  const segments = [];
  let activeStart = null;
  let shortageQuantity = 0;
  (days || []).forEach((day) => {
    if (day.day < startDay || day.day > endDay) return;
    if (day.status === "shortage") {
      activeStart = activeStart ?? day.day;
      shortageQuantity += Math.max(Number(day.shortageQuantity) || 0, 0);
      return;
    }
    if (activeStart !== null) {
      segments.push({ startDay: activeStart, endDay: day.day - 1, shortageQuantity: roundToOne(shortageQuantity) });
      activeStart = null;
      shortageQuantity = 0;
    }
  });
  if (activeStart !== null) {
    const latestDay = Math.min(endDay, (days || [])[days.length - 1]?.day || endDay);
    segments.push({ startDay: activeStart, endDay: latestDay, shortageQuantity: roundToOne(shortageQuantity) });
  }
  return segments;
}

function summarizeSupplyWindow(days, startDay, endDay) {
  const windowDays = (days || []).filter((day) => day.day >= startDay && day.day <= endDay);
  const shortageQuantity = windowDays.reduce((total, day) => total + Math.max(Number(day.shortageQuantity) || 0, 0), 0);
  const controlSavedQuantity = windowDays.reduce((total, day) => total + Math.max(Number(day.controlSavedQuantity) || 0, 0), 0);
  const demandQuantity = windowDays.reduce((total, day) => total + Math.max(Number(day.forecast) || 0, 0), 0);
  const originalDemandQuantity = windowDays.reduce((total, day) => total + Math.max(Number(day.originalForecast) || 0, 0), 0);
  return {
    startDay,
    endDay,
    shortageDays: windowDays.filter((day) => day.status === "shortage").length,
    shortageQuantity: roundToOne(shortageQuantity),
    suggestedQuantity: Math.ceil(shortageQuantity),
    controlSavedQuantity: roundToOne(controlSavedQuantity),
    demandQuantity: roundToOne(demandQuantity),
    originalDemandQuantity: roundToOne(originalDemandQuantity),
  };
}

function roundToOne(value) {
  return Math.round((Number(value) || 0) * 10) / 10;
}

function buildSupplyFishboneWeeks(days, arrivals) {
  if (!days.length) return [];
  const actualMaxDay = Math.max(...days.map((day) => day.day));
  const maxDay = actualMaxDay + FISHBONE_EXTRA_WEEK_DAYS;
  const dayByNumber = new Map(days.map((day) => [day.day, day]));
  const lastDay = days.find((day) => day.day === actualMaxDay) || days[days.length - 1];
  const weekCount = Math.ceil(maxDay / 7);

  return Array.from({ length: weekCount }, (_, index) => {
    const week = index + 1;
    const startDay = index * 7 + 1;
    const endDay = Math.min(startDay + 6, maxDay);
    const weekDays = [];

    for (let day = startDay; day <= endDay; day += 1) {
      const sourceDay = dayByNumber.get(day);
      weekDays.push(sourceDay || projectedSupplyDay(lastDay, day));
    }

    return {
      week,
      startDay,
      endDay,
      days: weekDays,
      shortageDays: weekDays.filter((day) => day.status === "shortage").length,
      arrivals: arrivals.filter((arrival) => arrival.day >= startDay && arrival.day <= endDay),
    };
  });
}

function projectedSupplyDay(sourceDay, day) {
  if (!sourceDay) return { day, status: "ok", projected: true };
  return {
    day,
    status: sourceDay.status,
    forecast: sourceDay.forecast,
    originalForecast: sourceDay.originalForecast,
    controlRatio: sourceDay.controlRatio,
    controlSavedQuantity: sourceDay.controlSavedQuantity,
    shortageQuantity: sourceDay.status === "shortage" ? sourceDay.shortageQuantity : 0,
    replenishedQuantity: 0,
    replenishmentChannel: "",
    partialReplenished: false,
    projected: true,
  };
}

function parsePiciValue(value) {
  const text = String(value || "");
  const match = text.match(/^\s*([\d,]+(?:\.\d+)?)\s*\/\s*([\d,]+(?:\.\d+)?)\s*\((-?[\d,]+(?:\.\d+)?)\)/);
  if (!match) return null;
  return {
    available: Number(match[1].replace(/,/g, "")),
    forecast: Number(match[2].replace(/,/g, "")),
    gap: Number(match[3].replace(/,/g, "")),
  };
}

function formatShortageSegment(startDay, shortageDays) {
  const startLabel = startDay <= 0 ? "今天起" : `第 ${formatNumber(startDay)} 天起`;
  return `${startLabel}断 ${formatNumber(shortageDays)} 天`;
}

function previousDate() {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  return formatIsoDate(date);
}

function lastCompleteDaysRange(days) {
  const end = new Date();
  end.setDate(end.getDate() - 1);
  const start = new Date(end);
  start.setDate(start.getDate() - Math.max(days - 1, 0));
  return {
    sales_start_date: formatIsoDate(start),
    sales_end_date: formatIsoDate(end),
  };
}

function formatIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseIsoDate(value) {
  const match = String(value || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const date = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatSalesPeriod(start, end) {
  if (!start && !end) return "";
  if (!start || start === end) return end || start;
  if (!end) return start;
  return `${start} 至 ${end}`;
}

createRoot(document.getElementById("root")).render(<App />);
