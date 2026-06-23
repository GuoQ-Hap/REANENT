import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";
import * as d3 from "d3";
import { feature, mesh } from "topojson-client";
import worldAtlas from "world-atlas/countries-50m.json";
import {
  AlertTriangle,
  Boxes,
  CalendarDays,
  CheckCircle2,
  Database,
  Download,
  Filter,
  Gauge,
  Layers3,
  MapPin,
  Plane,
  RefreshCw,
  Search,
  ShieldAlert,
  Ship,
  TrendingDown,
  Warehouse,
  ZoomOut,
} from "lucide-react";
import "./styles.css";
import { warehouseLocationStats, warehouseLocations } from "./warehouseLocations";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

const riskLabels = {
  critical: "紧急",
  high: "高",
  medium: "中",
  low: "低",
  normal: "正常",
};

const stockoutRiskBadgeLabels = {
  critical: "紧急断货风险",
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

function App() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [recommendationsExporting, setRecommendationsExporting] = useState(false);
  const [skuInvestigationExporting, setSkuInvestigationExporting] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [activeSkuItem, setActiveSkuItem] = useState(null);
  const [activeWorkspace, setActiveWorkspace] = useState("overview");
  const pageSize = 100;
  const [filters, setFilters] = useState(() => createDefaultFilters());

  const loadSummary = async (targetPage = page, targetFilters = filters) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      appendActiveFilters(params, targetFilters);
      params.set("page", String(targetPage));
      params.set("page_size", String(pageSize));
      params.set("max_rows", "20000");
      const response = await fetch(`${API_BASE_URL}/control-tower/summary?${params.toString()}`);
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

  const downloadInvestigationExcel = async () => {
    setExporting(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("max_rows", "20000");
      const response = await fetch(`${API_BASE_URL}/control-tower/export/daily-investigation?${params.toString()}`);
      if (!response.ok) throw new Error(`导出失败 ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const encodedName = disposition.match(/filename\\*=UTF-8''([^;]+)/)?.[1];
      const fallbackName = disposition.match(/filename="?([^";]+)"?/)?.[1];
      const filename = encodedName
        ? decodeURIComponent(encodedName)
        : fallbackName || `爆旺断货冗余排查_${previousDate()}.xlsx`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "排查表生成失败");
    } finally {
      setExporting(false);
    }
  };

  const downloadRecommendationsExcel = async () => {
    setRecommendationsExporting(true);
    setError("");
    try {
      const params = new URLSearchParams();
      appendActiveFilters(params, filters);
      params.set("max_rows", "20000");
      const response = await fetch(`${API_BASE_URL}/control-tower/export/recommendations?${params.toString()}`);
      if (!response.ok) throw new Error(`导出失败 ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1];
      const fallbackName = disposition.match(/filename="?([^";]+)"?/)?.[1];
      const filename = encodedName
        ? decodeURIComponent(encodedName)
        : fallbackName || `库存控销补货建议_${previousDate()}.xlsx`;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "建议导出失败");
    } finally {
      setRecommendationsExporting(false);
    }
  };

  const downloadSkuInvestigationExcel = async () => {
    setSkuInvestigationExporting(true);
    setError("");
    try {
      const params = new URLSearchParams();
      appendActiveFilters(params, filters);
      params.set("max_rows", "20000");
      const response = await fetch(`${API_BASE_URL}/control-tower/export/sku-investigation?${params.toString()}`);
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
    loadSummary(1);
  }, []);

  const filteredItems = useMemo(() => {
    if (!summary?.items) return [];
    return summary.items;
  }, [summary]);
  const countryOptions = useMemo(
    () => optionValuesWithDefaults(COMMON_COUNTRY_OPTIONS, summary?.filter_options?.country_code, filters.country_code),
    [summary?.filter_options?.country_code, filters.country_code]
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
  const riskTotal = useMemo(() => {
    const distribution = summary?.risk_type_distribution || {};
    return ["stockout", "overstock", "anomaly"].reduce((total, key) => total + Number(distribution[key] || 0), 0);
  }, [summary]);
  const workspaceTabs = useMemo(() => [
    { id: "overview", label: "风险总览", meta: `${formatNumber(riskTotal)} 风险`, icon: Gauge },
    { id: "geo", label: "地域库存", meta: `${formatNumber(summary?.warehouse_inventory?.length || 0)} 仓`, icon: MapPin },
    { id: "detail", label: "SKU 明细", meta: `${formatNumber(summary?.pagination?.total_count ?? filteredItems.length)} 行`, icon: Boxes },
    { id: "firstLeg", label: "头程查询", meta: "货件", icon: Ship },
    { id: "standards", label: "字段口径", meta: `${formatNumber(summary?.field_decisions?.length || 0)} 字段`, icon: Database },
  ], [filteredItems.length, riskTotal, summary?.field_decisions?.length, summary?.pagination?.total_count, summary?.warehouse_inventory?.length]);

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

  return (
    <>
    <main className="app-shell">
      <section className="topbar">
        <div>
          <div className="eyebrow">PMC Inventory Control Tower</div>
          <h1>库存控制塔</h1>
        </div>
        <div className="topbar-actions">
          <button className="primary-button" onClick={downloadInvestigationExcel} disabled={exporting}>
            <Download size={16} />
            <span>{exporting ? "生成中" : "生成排查表"}</span>
          </button>
          <button className="primary-button" onClick={downloadRecommendationsExcel} disabled={recommendationsExporting}>
            <Download size={16} />
            <span>{recommendationsExporting ? "导出中" : "导出建议"}</span>
          </button>
          <button className="primary-button" onClick={downloadSkuInvestigationExcel} disabled={skuInvestigationExporting}>
            <Download size={16} />
            <span>{skuInvestigationExporting ? "导出中" : "导出SKU排查"}</span>
          </button>
          <button className="primary-button" onClick={() => loadSummary(page)} disabled={loading}>
            <RefreshCw size={16} />
            <span>{loading ? "刷新中" : "刷新"}</span>
          </button>
        </div>
      </section>

      <section className="toolbar" aria-label="控制塔筛选器">
        <label className="input-wrap">
          <Search size={16} />
          <input
            value={filters.material_code}
            placeholder="SKU / MSKU / FNSKU"
            onChange={(event) => setFilters({ ...filters, material_code: event.target.value })}
          />
        </label>
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
          <Warehouse size={16} />
          <input
            value={firstSelectedValue(filters.store_name)}
            placeholder="店铺"
            onChange={(event) => setFilters({ ...filters, store_name: event.target.value ? [event.target.value] : [] })}
          />
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
                <section className="dashboard-grid risk-dashboard-grid">
                  <RiskBreakdown title="风险等级" data={summary.risk_distribution} labels={riskLabels} />
                  <RiskBreakdown title="风险类型" data={summary.risk_type_distribution} labels={riskTypeLabels} />
                </section>
              </section>
            )}
            {activeWorkspace === "geo" && (
              <section className="workspace-view geo-view">
                <InventoryMap
                  nodes={summary.map_nodes || []}
                  selectedCountry={firstSelectedValue(filters.country_code)}
                  onCountrySelect={(countryCode) => {
                    const nextFilters = { ...filters, country_code: countryCode ? [countryCode] : [] };
                    setFilters(nextFilters);
                    setPage(1);
                    loadSummary(1, nextFilters);
                  }}
                />
                <WarehouseInventoryPanel countryCode={firstSelectedValue(filters.country_code)} rows={summary.warehouse_inventory || []} />
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
            {activeWorkspace === "standards" && (
              <section className="workspace-view standards-view">
                <SourcePanel summary={summary} />
                <FieldDecisionTable fields={summary.field_decisions} />
              </section>
            )}
            {activeWorkspace === "firstLeg" && (
              <section className="workspace-view first-leg-view">
                <FirstLegShipmentPanel initialQuery={filters.material_code} />
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

const isoNumericByAlpha2 = {
  AU: "036",
  BR: "076",
  CA: "124",
  CN: "156",
  CZ: "203",
  DE: "276",
  ES: "724",
  FR: "250",
  GB: "826",
  UK: "826",
  IN: "356",
  IT: "380",
  JP: "392",
  MX: "484",
  NL: "528",
  PL: "616",
  US: "840",
};

const alpha2ByIsoNumeric = Object.fromEntries(Object.entries(isoNumericByAlpha2).map(([alpha2, numeric]) => [numeric, alpha2]));

function createCountryProjection(countryCode) {
  if (countryCode === "US") {
    return d3.geoAlbersUsa();
  }
  if (countryCode === "CA") {
    return d3.geoConicConformal().parallels([49, 77]).rotate([96, 0]).center([0, 58]);
  }
  if (countryCode === "JP") {
    return d3.geoConicConformal().parallels([30, 46]).rotate([-138, 0]).center([0, 38]);
  }
  return d3.geoMercator();
}

const countryFocusBounds = {
  CA: { lon: [-142, -52], lat: [41, 84] },
  DE: { lon: [5, 16], lat: [47, 56] },
  GB: { lon: [-9, 3], lat: [49, 61] },
  JP: { lon: [122, 154], lat: [20, 46] },
  UK: { lon: [-9, 3], lat: [49, 61] },
  US: { lon: [-170, -50], lat: [15, 75] },
};

function isRingInBounds(ring, bounds) {
  return ring.some(([lon, lat]) => lon >= bounds.lon[0] && lon <= bounds.lon[1] && lat >= bounds.lat[0] && lat <= bounds.lat[1]);
}

function focusCountryFeature(feature, countryCode) {
  const bounds = countryFocusBounds[countryCode];
  if (!feature || !bounds) return feature;
  const geometry = feature.geometry;
  if (geometry.type === "Polygon") return feature;
  if (geometry.type !== "MultiPolygon") return feature;
  const coordinates = geometry.coordinates.filter((polygon) => polygon.some((ring) => isRingInBounds(ring, bounds)));
  if (!coordinates.length) return feature;
  return {
    ...feature,
    geometry: {
      ...geometry,
      coordinates,
    },
  };
}

function truncateMapLabel(value, maxLength = 34) {
  const text = String(value || "");
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

function isSameWarehouse(left, right) {
  return Boolean(left && right && left.code === right.code && left.postal === right.postal);
}

const warehouseClusterByCountry = {
  JP: { cellSize: 34, minPoints: 12 },
  US: { cellSize: 50, minPoints: 70 },
};

function clusterWarehousePoints(points, countryCode) {
  const config = warehouseClusterByCountry[countryCode];
  if (!config || points.length < config.minPoints) return points;
  const { cellSize } = config;
  const cells = new Map();
  points.forEach((point) => {
    const key = `${Math.round(point.x / cellSize)}:${Math.round(point.y / cellSize)}`;
    const list = cells.get(key) || [];
    list.push(point);
    cells.set(key, list);
  });
  return [...cells.entries()].flatMap(([key, group], index) => {
    if (group.length === 1) return group;
    const x = d3.mean(group, (point) => point.x);
    const y = d3.mean(group, (point) => point.y);
    const side = index % 2 === 0 ? 1 : -1;
    const lane = index % 3;
    return {
      isCluster: true,
      key: `cluster-${key}`,
      warehouses: group.map((point) => point.warehouse),
      warehouse: {
        isCluster: true,
        code: `${group.length}`,
        name: `${group.length} 个仓库`,
        postal: "区域聚合",
        address: group.map((point) => point.warehouse.code).slice(0, 8).join(", "),
        locationQuality: "cluster",
      },
      x,
      y,
      labelX: side * (26 + lane * 6),
      labelY: -16 - lane * 5,
    };
  });
}

function InventoryMap({ nodes, selectedCountry, onCountrySelect }) {
  const [activeNode, setActiveNode] = useState(null);
  const [activeCountry, setActiveCountry] = useState(null);
  const [activeWarehouse, setActiveWarehouse] = useState(null);
  const [selectedWarehouse, setSelectedWarehouse] = useState(null);
  const [rotation, setRotation] = useState(0);

  useEffect(() => {
    setActiveWarehouse(null);
    setSelectedWarehouse(null);
  }, [selectedCountry]);

  const nodeByNumeric = useMemo(() => {
    const pairs = new Map();
    nodes.forEach((node) => {
      const numeric = isoNumericByAlpha2[node.country_code];
      if (numeric) pairs.set(numeric, node);
    });
    return pairs;
  }, [nodes]);

  const countryCodeByNumeric = useMemo(() => {
    const pairs = new Map(Object.entries(alpha2ByIsoNumeric));
    warehouseLocations.forEach((warehouse) => {
      if (warehouse.isoNumeric && warehouse.countryCode) pairs.set(warehouse.isoNumeric, warehouse.countryCode);
    });
    nodes.forEach((node) => {
      const numeric = isoNumericByAlpha2[node.country_code];
      if (numeric) pairs.set(numeric, node.country_code);
    });
    return pairs;
  }, [nodes]);

  const warehousesByNumeric = useMemo(() => {
    const pairs = new Map();
    warehouseLocations.forEach((warehouse) => {
      if (!warehouse.isoNumeric || warehouse.lat === null || warehouse.lon === null) return;
      const list = pairs.get(warehouse.isoNumeric) || [];
      list.push(warehouse);
      pairs.set(warehouse.isoNumeric, list);
    });
    return pairs;
  }, []);

  const warehouseCountryCode = selectedCountry === "UK" ? "GB" : selectedCountry;
  const selectedNumeric = selectedCountry ? isoNumericByAlpha2[selectedCountry] : "";
  const selectedWarehouses = useMemo(
    () =>
      warehouseLocations.filter(
        (warehouse) => warehouse.countryCode === warehouseCountryCode && warehouse.lat !== null && warehouse.lon !== null,
      ),
    [warehouseCountryCode],
  );

  const mapData = useMemo(() => {
    const countries = feature(worldAtlas, worldAtlas.objects.countries).features.filter((item) => item.id !== "010");
    const selectedFeature = selectedNumeric
      ? countries.find((item) => String(item.id).padStart(3, "0") === selectedNumeric)
      : null;
    const focusedFeature = selectedFeature ? focusCountryFeature(selectedFeature, selectedCountry) : null;
    const displayCountries = focusedFeature ? [focusedFeature] : countries;
    const border = focusedFeature || mesh(worldAtlas, worldAtlas.objects.countries, (a, b) => a !== b);
    const land = { type: "FeatureCollection", features: countries };
    const target = focusedFeature || land;
    const baseProjection = d3.geoNaturalEarth1().fitExtent(
      [
        [-10, 26],
        [1010, 496],
      ],
      land,
    );
    const projection = selectedFeature
      ? createCountryProjection(selectedCountry).fitExtent(
          [
            [118, 82],
            [820, 430],
          ],
          target,
        )
      : d3.geoNaturalEarth1().rotate([rotation, 0, 0]).scale(baseProjection.scale()).translate(baseProjection.translate());
    const path = d3.geoPath(projection);
    const markerSource = focusedFeature ? selectedWarehouses : [];
    const warehousePoints = markerSource
      .map((warehouse, index) => {
        if (warehouse.lat === null || warehouse.lon === null) return null;
        const point = projection([warehouse.lon, warehouse.lat]);
        if (!point || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) return null;
        const side = index % 2 === 0 ? 1 : -1;
        const lane = Math.floor(index / 2) % 4;
        const labelX = side * (28 + lane * 8);
        const labelY = -18 - lane * 7;
        return { warehouse, x: point[0], y: point[1], labelX, labelY };
      })
      .filter(Boolean);
    const displayWarehousePoints = clusterWarehousePoints(warehousePoints, selectedCountry);
    const countryClusters = countries
      .map((country) => {
        const numeric = String(country.id).padStart(3, "0");
        const node = nodeByNumeric.get(numeric);
        const warehouses = warehousesByNumeric.get(numeric) || [];
        if (!warehouses.length || focusedFeature) return null;
        const projected = warehouses
          .map((warehouse) => projection([warehouse.lon, warehouse.lat]))
          .filter((point) => point && Number.isFinite(point[0]) && Number.isFinite(point[1]));
        if (!projected.length) return null;
        const x = d3.mean(projected, (point) => point[0]);
        const y = d3.mean(projected, (point) => point[1]);
        if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
        const calloutOffsetByCode = {
          CA: [18, -32],
          US: [22, 28],
          UK: [-52, -36],
          GB: [-52, -36],
          DE: [52, -18],
          JP: [42, 18],
          MX: [-44, 28],
        };
        return {
          country,
          node,
          warehouses,
          x,
          y,
          calloutOffset: calloutOffsetByCode[node?.country_code || warehouses[0]?.countryCode] || [38, -28],
        };
      })
      .filter(Boolean);
    return {
      border,
      countries: displayCountries,
      countryClusters,
      isCountryView: Boolean(focusedFeature),
      path,
      warehousePoints: displayWarehousePoints,
    };
  }, [nodeByNumeric, rotation, selectedNumeric, selectedWarehouses, warehousesByNumeric]);

  const topNodes = [...nodes].sort((a, b) => b.stockout_count - a.stockout_count).slice(0, 6);
  const currentCountryName =
    selectedWarehouses[0]?.countryName || nodes.find((node) => node.country_code === selectedCountry)?.country_name || selectedCountry;
  const displayWarehouse = activeWarehouse || selectedWarehouse;
  const activeWarehousePoint = useMemo(() => {
    if (!displayWarehouse) return null;
    return (
      mapData.warehousePoints.find((point) => {
        if (isSameWarehouse(point.warehouse, displayWarehouse)) return true;
        return point.isCluster && point.warehouses.some((warehouse) => isSameWarehouse(warehouse, displayWarehouse));
      }) || null
    );
  }, [displayWarehouse, mapData.warehousePoints]);
  const activeReadout = selectedCountry && displayWarehouse
    ? `${displayWarehouse.code} · ${displayWarehouse.postal}`
    : activeNode
      ? `${activeNode.country_code} · ${activeNode.country_name} · 仓库 ${formatNumber(activeNode.warehouse_count)} · 断货 ${formatNumber(activeNode.stockout_count)}`
      : activeCountry
        ? `${activeCountry.name} · ${activeCountry.countryCode || "无库存节点"}`
        : selectedCountry
          ? `${selectedCountry} · ${formatNumber(selectedWarehouses.length)} 个仓库`
          : `全球仓库 ${formatNumber(warehouseLocationStats.total)} 个 · 按国家聚合显示`;

  const selectCountryByNumeric = (numeric) => {
    const padded = String(numeric).padStart(3, "0");
    const countryCode = countryCodeByNumeric.get(padded);
    if (countryCode) onCountrySelect(countryCode);
  };

  return (
    <section className="map-panel">
      <div className="section-heading map-heading">
        <div>
          <h2>{selectedCountry ? `${currentCountryName}仓库地图` : "全球库存风险地图"}</h2>
          <p>
            {selectedCountry
              ? `当前国家 ${formatNumber(selectedWarehouses.length)} 个海外仓，点击返回可回到全球视图`
              : "点击国家后切换为国家铺满视图，并标注该国家全部海外仓"}
          </p>
        </div>
        <span className="map-source">{selectedCountry ? "COUNTRY WAREHOUSE VIEW" : "WORLD WAREHOUSE VIEW"}</span>
      </div>
      <div className={`map-body ${selectedCountry ? "country-mode" : ""}`}>
        <div className="inventory-map-stage" aria-label="全球库存风险地图">
          <div className="inventory-map-shell">
            <svg className="world" viewBox="0 0 1000 520" role="img" aria-label="海外仓地图">
              <defs>
                <linearGradient id="inventoryLand" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stopColor="#36f1ff" />
                  <stop offset=".45" stopColor="#1bb9cf" />
                  <stop offset="1" stopColor="#0b748a" />
                </linearGradient>
              </defs>
              <g id="mapSurface">
                {mapData.countries.map((country, index) => {
                  const numeric = String(country.id).padStart(3, "0");
                  const node = nodeByNumeric.get(numeric);
                  const warehouses = warehousesByNumeric.get(numeric) || [];
                  const countryCode = countryCodeByNumeric.get(numeric) || "";
                  const isSelectedMapCountry = selectedNumeric === numeric;
                  const isOriginCountry = numeric === "156";
                  const isWarehouseCountry = warehouses.length > 0;
                  if (mapData.isCountryView && !isSelectedMapCountry) return null;
                  const countryKey = `${numeric}-${countryCode || "context"}-${index}`;
                  return (
                    <path
                      className={`land ${node ? "has-node" : ""} ${isWarehouseCountry ? "warehouse-country" : ""} ${isOriginCountry ? "origin-country" : ""} ${mapData.isCountryView && !isSelectedMapCountry ? "context-land" : ""} ${isSelectedMapCountry ? "active" : ""}`}
                      key={countryKey}
                      d={mapData.path(country) || ""}
                      onMouseEnter={() =>
                        setActiveCountry({
                          name: node?.country_name || warehouses[0]?.countryName || `国家 ${numeric}`,
                          countryCode,
                        })
                      }
                      onMouseLeave={() => setActiveCountry(null)}
                      onClick={() => selectCountryByNumeric(numeric)}
                    />
                  );
                })}
              </g>
              <g id="mapLines">
                <path className="country-line" d={mapData.path(mapData.border) || ""} />
              </g>
              {!mapData.isCountryView && (
                <g id="countryClusterMarkers">
                  {mapData.countryClusters.map(({ node, warehouses, x, y, calloutOffset }) => {
                    const countryCode = node?.country_code || warehouses[0]?.countryCode;
                    const countryName = node?.country_name || warehouses[0]?.countryName;
                    const riskLevel = node?.risk_level || "normal";
                    const [labelX, labelY] = calloutOffset;
                    return (
                    <g
                      className={`country-cluster-marker ${riskLevel}`}
                      key={countryCode}
                      transform={`translate(${x} ${y})`}
                      onMouseEnter={() =>
                        setActiveNode({
                          ...node,
                          country_code: countryCode,
                          country_name: countryName,
                          warehouse_count: warehouses.length,
                        })
                      }
                      onMouseLeave={() => setActiveNode(null)}
                      onClick={() => onCountrySelect(countryCode)}
                    >
                      <circle className="country-cluster-anchor" r="3.5" />
                      <path className="country-cluster-leader" d={`M0,0 L${labelX * 0.72},${labelY * 0.72} L${labelX},${labelY}`} />
                      <g className="country-cluster-label" transform={`translate(${labelX} ${labelY})`}>
                        <rect className="country-cluster-pill" x="-30" y="-17" width="60" height="34" rx="3" />
                        <text className="country-cluster-code" x="-20" y="5">{countryCode}</text>
                        <text className="country-cluster-count" x="11" y="5">{warehouses.length}</text>
                      </g>
                    </g>
                  )})}
                </g>
              )}
              <g id="warehouseLocationMarkers">
                {mapData.warehousePoints.map(({ warehouse, warehouses, isCluster, key, x, y, labelX, labelY }) => {
                  const isActiveMarker = displayWarehouse
                    ? isCluster
                      ? warehouses.some((item) => item.code === displayWarehouse.code && item.postal === displayWarehouse.postal)
                      : warehouse.code === displayWarehouse.code && warehouse.postal === displayWarehouse.postal
                    : false;
                  return (
                    <g
                      className={`warehouse-location-marker ${isCluster ? "cluster" : ""} ${isActiveMarker ? "active" : ""}`}
                      key={key || `${warehouse.code}-${warehouse.postal}`}
                      transform={`translate(${x} ${y})`}
                      onMouseEnter={() => setActiveWarehouse(warehouse)}
                      onMouseLeave={() => setActiveWarehouse(null)}
                      onClick={() => {
                        setActiveWarehouse(warehouse);
                        setSelectedWarehouse(warehouse);
                        if (!selectedCountry) onCountrySelect(warehouse.countryCode);
                      }}
                    >
                      <circle className="warehouse-location-dot" r={isCluster ? Math.min(12.5, 6.4 + warehouses.length * 0.38) : mapData.isCountryView ? 4.2 : 3.6} />
                      {isCluster && <text className="warehouse-cluster-count" x="0" y="4">{warehouses.length}</text>}
                    </g>
                  );
                })}
              </g>
              {mapData.isCountryView && displayWarehouse && activeWarehousePoint && (
                <g id="warehouseFixedCallout">
                  <path
                    className="warehouse-fixed-leader"
                    d={`M${activeWarehousePoint.x},${activeWarehousePoint.y} L334,80`}
                  />
                  <g className="warehouse-fixed-callout" transform="translate(34 34)">
                    <rect width="300" height="92" rx="4" />
                    <text className="warehouse-fixed-title" x="15" y="26">{truncateMapLabel(displayWarehouse.name, 28)}</text>
                    <text x="15" y="50">{displayWarehouse.code} · {displayWarehouse.postal}</text>
                    <text className="warehouse-fixed-address" x="15" y="73">{truncateMapLabel(displayWarehouse.address, 30)}</text>
                  </g>
                </g>
              )}
            </svg>
          </div>
          <div className="scan"></div>
          <div className="map-actions" aria-label="地图控制">
            {selectedCountry ? (
              <button
                className="map-button wide"
                type="button"
                title="返回全球地图"
                onClick={() => {
                  setActiveWarehouse(null);
                  setSelectedWarehouse(null);
                  setActiveNode(null);
                  onCountrySelect("");
                }}
              >
                <ZoomOut size={15} />
                <span>全球</span>
              </button>
            ) : (
              <>
                <button className="map-button" type="button" title="向左旋转" onClick={() => setRotation((value) => value - 18)}>‹</button>
                <button className="map-button" type="button" title="重置视角" onClick={() => setRotation(0)}>◎</button>
                <button className="map-button" type="button" title="向右旋转" onClick={() => setRotation((value) => value + 18)}>›</button>
              </>
            )}
          </div>
          <div className="geo-readout">{activeReadout}</div>
          {activeNode && !selectedCountry && (
            <div className="map-tooltip-card">
              <strong>{activeNode.country_name}</strong>
              <span>仓库 {formatNumber(activeNode.warehouse_count)}</span>
              <span>SKU {formatNumber(activeNode.sku_count)}</span>
              <span>库存 {formatNumber(activeNode.total_inventory)}</span>
              <span>断货 {formatNumber(activeNode.stockout_count)} / 冗余 {formatNumber(activeNode.overstock_count)}</span>
            </div>
          )}
        </div>
        <div className="map-rank">
          <div className="panel-title-inline">{selectedCountry ? `${selectedCountry} 仓库清单` : "断货风险国家排行"}</div>
          {selectedCountry ? (
            <div className="warehouse-location-list">
              {selectedWarehouses.map((warehouse) => (
                <button
                  className={`warehouse-location-row ${isSameWarehouse(selectedWarehouse, warehouse) ? "selected" : ""}`}
                  key={`${warehouse.code}-${warehouse.postal}`}
                  onMouseEnter={() => setActiveWarehouse(warehouse)}
                  onMouseLeave={() => setActiveWarehouse(null)}
                  onClick={() => {
                    setActiveWarehouse(warehouse);
                    setSelectedWarehouse(warehouse);
                  }}
                >
                  <MapPin size={15} />
                  <span>{warehouse.code}</span>
                  <strong>{warehouse.postal}</strong>
                  <small>{warehouse.name}</small>
                </button>
              ))}
            </div>
          ) : (
            topNodes.map((node) => (
              <button
                className={`rank-row ${node.risk_level} ${selectedCountry === node.country_code ? "selected" : ""}`}
                key={node.country_code}
                onMouseEnter={() => setActiveNode(node)}
                onMouseLeave={() => setActiveNode(null)}
                onClick={() => onCountrySelect(node.country_code)}
              >
                <span>{node.country_code}</span>
                <strong>{formatNumber(node.stockout_count)}</strong>
                <small>{formatNumber(node.sku_count)} SKU</small>
              </button>
            ))
          )}
        </div>
      </div>
    </section>
  );
}

function WarehouseInventoryPanel({ countryCode, rows }) {
  const title = countryCode ? `${countryCode} 仓库库存` : "仓库库存分布";
  const total = rows.reduce(
    (sum, item) => ({
      product_total: sum.product_total + Number(item.product_total || 0),
      product_valid_num: sum.product_valid_num + Number(item.product_valid_num || 0),
      product_lock_num: sum.product_lock_num + Number(item.product_lock_num || 0),
      product_onway: sum.product_onway + Number(item.product_onway || 0),
      sku_count: sum.sku_count + Number(item.sku_count || 0),
    }),
    { product_total: 0, product_valid_num: 0, product_lock_num: 0, product_onway: 0, sku_count: 0 },
  );

  return (
    <section className="warehouse-section">
      <div className="section-heading">
        <div>
          <h2>{title}</h2>
          <p>来自 dwd_lingxing_inventory_details + dwd_lingxing_sc_warehouse</p>
        </div>
        <div className="warehouse-totals">
          <span>仓库 {formatNumber(rows.length)}</span>
          <span>库存 {formatNumber(total.product_total)}</span>
          <span>可用 {formatNumber(total.product_valid_num)}</span>
          <span>在途 {formatNumber(total.product_onway)}</span>
        </div>
      </div>
      <div className="warehouse-grid">
        {rows.slice(0, 12).map((row) => (
          <article className="warehouse-card" key={`${row.country_code}-${row.display_name}-${row.warehouse_code}`}>
            <div className="warehouse-card-head">
              <strong>{row.display_name || row.warehouse_name || row.warehouse_code || "未命名仓库"}</strong>
              <span>{row.country_code || "-"}</span>
            </div>
            <div className="warehouse-metrics">
              <div><span>总库存</span><strong>{formatNumber(row.product_total)}</strong></div>
              <div><span>可用</span><strong>{formatNumber(row.product_valid_num)}</strong></div>
              <div><span>锁定</span><strong>{formatNumber(row.product_lock_num)}</strong></div>
              <div><span>在途</span><strong>{formatNumber(row.product_onway)}</strong></div>
            </div>
            <small>{formatNumber(row.sku_count)} SKU · {row.warehouse_code || row.warehouse_name || "无仓库编码"}</small>
          </article>
        ))}
      </div>
    </section>
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
    { label: "冗余风险", value: kpis.overstock_count, icon: TrendingDown, tone: "warn" },
  ];
  return (
    <section className="kpi-grid">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <article className={`kpi-card ${card.tone}`} key={card.label}>
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

function RiskBreakdown({ title, data, labels }) {
  const entries = Object.entries(data || {});
  const total = entries.reduce((sum, [, value]) => sum + Number(value || 0), 0) || 1;
  const ordered = entries.sort((a, b) => Number(b[1]) - Number(a[1]));
  return (
    <section className="panel">
      <div className="panel-title">
        <AlertTriangle size={17} />
        <h2>{title}</h2>
      </div>
      <div className="bar-list">
        {ordered.map(([key, value]) => {
          const width = Math.max(6, (Number(value) / total) * 100);
          return (
            <div className="bar-row" key={key}>
              <span>{labels[key] || key}</span>
              <div className="bar-track">
                <div className={`bar-fill ${key}`} style={{ width: `${width}%` }} />
              </div>
              <strong>{value}</strong>
            </div>
          );
        })}
      </div>
    </section>
  );
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

function FirstLegShipmentPanel({ initialQuery = "" }) {
  const [query, setQuery] = useState(initialQuery || "");
  const [latestOnly, setLatestOnly] = useState(true);
  const [limit, setLimit] = useState(100);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [payload, setPayload] = useState(null);
  const rows = payload?.shipments || [];

  useEffect(() => {
    if (!query && initialQuery) {
      setQuery(initialQuery);
    }
  }, [initialQuery, query]);

  const runSearch = async () => {
    const materialCode = query.trim();
    if (!materialCode) {
      setError("请输入 SKU / MSKU / FNSKU / ASIN");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      params.set("material_code", materialCode);
      params.set("latest_only", String(latestOnly));
      params.set("limit", String(limit));
      const response = await fetch(`${API_BASE_URL}/control-tower/first-leg-shipments?${params.toString()}`);
      if (!response.ok) throw new Error(`头程查询失败 ${response.status}`);
      setPayload(await response.json());
    } catch (err) {
      setPayload(null);
      setError(err instanceof Error ? err.message : "头程查询失败");
    } finally {
      setLoading(false);
    }
  };

  const handleSubmit = (event) => {
    event.preventDefault();
    runSearch();
  };

  return (
    <section className="first-leg-section">
      <div className="section-heading">
        <div>
          <h2>头程货件查询</h2>
          <p>{payload ? `命中 ${formatNumber(payload.row_count)} 条货件记录` : "按产品身份码查询飞书头程货件"}</p>
        </div>
        <Ship size={20} />
      </div>
      <form className="first-leg-query" onSubmit={handleSubmit}>
        <label className="input-wrap first-leg-search">
          <Search size={16} />
          <input
            value={query}
            placeholder="SKU / MSKU / FNSKU / ASIN"
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <label className="toggle first-leg-toggle">
          <input
            type="checkbox"
            checked={latestOnly}
            onChange={(event) => setLatestOnly(event.target.checked)}
          />
          <span>最新快照</span>
        </label>
        <label className="input-wrap first-leg-limit">
          <Database size={16} />
          <input
            type="number"
            min="1"
            max="500"
            value={limit}
            aria-label="返回行数"
            onChange={(event) => setLimit(Math.max(1, Math.min(Number(event.target.value) || 1, 500)))}
          />
        </label>
        <button className="primary-button" type="submit" disabled={loading}>
          <Search size={16} />
          <span>{loading ? "查询中" : "查询"}</span>
        </button>
      </form>
      {error && (
        <div className="notice error first-leg-notice">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}
      <div className="first-leg-summary">
        <div>
          <span>输入</span>
          <strong>{payload?.query?.material_codes?.join(" / ") || query || "-"}</strong>
        </div>
        <div>
          <span>返回</span>
          <strong>{payload ? `${formatNumber(payload.row_count)} 条` : "-"}</strong>
        </div>
        <div>
          <span>主链路</span>
          <strong>ship_id = package_id</strong>
        </div>
      </div>
      <FirstLegShipmentTable rows={rows} loading={loading} />
    </section>
  );
}

function FirstLegShipmentTable({ rows, loading }) {
  return (
    <div className="table-scroll first-leg-table-scroll">
      <table className="first-leg-table">
        <thead>
          <tr>
            <th>产品</th>
            <th>货件</th>
            <th>物流</th>
            <th>数量</th>
            <th>到港</th>
            <th>签收</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          {!rows.length && (
            <tr className="empty-table-row">
              <td colSpan={7}>{loading ? "正在查询头程货件..." : "暂无头程货件记录"}</td>
            </tr>
          )}
          {rows.map((row, index) => (
            <tr key={`${row.ship_id || row.package_id || row.refer_id || "shipment"}-${row.sku || row.fnsku || row.msku || index}-${index}`}>
              <td>
                <strong>{row.sku || "-"}</strong>
                <small>{[row.msku, row.fnsku].filter(Boolean).join(" / ") || "-"}</small>
              </td>
              <td>
                <strong>{row.ship_id || row.package_id || "-"}</strong>
                <small>{row.batch_num || row.refer_id || row.warehouse_inbound_number || "-"}</small>
                <span className="first-leg-source">{firstLegRelationLabel(row.source_relation)}</span>
              </td>
              <td>
                <strong>{row.shipping_method || "-"}</strong>
                <small>{row.logistics_provider || row.detail_logistics_provider || "-"}</small>
                <small>{row.logistics_tracking_number || "-"}</small>
              </td>
              <td>
                <span>发货 {formatNumber(row.ship_num)}</span>
                <small>在途 {formatNumber(row.in_transit_qty)} / 签收 {formatNumber(row.quantity_received)}</small>
              </td>
              <td>
                <span>预计 {formatDateOrDash(row.estimated_arrival_time)}</span>
                <small>实际 {formatDateOrDash(row.actual_arrival_time)}</small>
              </td>
              <td>
                <span>计划 {formatDateOrDash(row.plan_delivery_time)}</span>
                <small>预计 {formatDateOrDash(row.estimated_delivery_time)}</small>
                <small>实际 {formatDateOrDash(row.actual_delivery_time)}</small>
              </td>
              <td>
                <strong>{row.current_shipping_status || row.detail_status || "-"}</strong>
                <small>{row.exception || row.destination_warehouse || row.putaway_warehouse || "-"}</small>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function MultiFilterField({ label, value, options, onChange, wide = false }) {
  const selected = selectedValues(value);
  const normalizedOptions = (options || [])
    .map((option) => (typeof option === "string" ? { value: option, label: option } : option))
    .filter((option) => option?.value);
  const summary = selected.length
    ? `${selected.slice(0, 2).join("、")}${selected.length > 2 ? ` +${selected.length - 2}` : ""}`
    : "全部";
  return (
    <details className={`filter-field multi-filter ${wide ? "wide" : ""}`}>
      <summary>
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
    }
  }, [filters, filterOpen]);
  const updateDraftFilters = (changes) => setDraftFilters((current) => ({ ...current, ...changes }));
  const applyDraftFilters = () => {
    onFiltersApply(draftFilters);
    setFilterOpen(false);
  };
  const resetDraftFilters = () => {
    const nextFilters = createDefaultFilters();
    setDraftFilters(nextFilters);
    onFiltersApply(nextFilters);
    setFilterOpen(false);
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
      setFilterOpen(false);
      return;
    }
    positionFilterPopover();
    setFilterOpen(true);
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
                <button className="popover-dismiss-layer" type="button" aria-label="关闭筛选" onClick={() => setFilterOpen(false)} />
                <div className="detail-filter-popover" role="dialog" aria-label="SKU 多条件筛选" style={filterPopoverStyle}>
                  <div className="filter-popover-head">
                    <div>
                      <strong>多条件筛选</strong>
                      <span>多个条件会同时生效</span>
                    </div>
                    <button type="button" onClick={() => setFilterOpen(false)} aria-label="关闭">
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
                        <label className="filter-field wide">
                          <span>SKU / MSKU / FNSKU</span>
                          <input
                            value={draftFilters.material_code}
                            placeholder="输入 SKU、MSKU 或 FNSKU"
                            onChange={(event) => updateDraftFilters({ material_code: event.target.value })}
                          />
                        </label>
                        <MultiFilterField label="国家" value={draftFilters.country_code} options={countryOptions} onChange={(value) => updateDraftFilters({ country_code: value })} />
                        <MultiFilterField label="发货国家" value={draftFilters.shipments_country} options={shipmentCountryOptions} onChange={(value) => updateDraftFilters({ shipments_country: value })} />
                        <MultiFilterField label="店铺" value={draftFilters.store_name} options={storeOptions} onChange={(value) => updateDraftFilters({ store_name: value })} wide />
                      </div>
                    </section>
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>组织维度</strong>
                        <span>部门、人员</span>
                      </div>
                      <div className="filter-section-grid">
                        <MultiFilterField label="销售部门" value={draftFilters.sales_department} options={salesDepartmentOptions} onChange={(value) => updateDraftFilters({ sales_department: value })} />
                        <MultiFilterField label="销售员" value={draftFilters.salesman} options={salesmanOptions} onChange={(value) => updateDraftFilters({ salesman: value })} />
                        <MultiFilterField label="产品经理" value={draftFilters.product_manager} options={productManagerOptions} onChange={(value) => updateDraftFilters({ product_manager: value })} />
                      </div>
                    </section>
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>商品维度</strong>
                        <span>属性、状态、生命周期</span>
                      </div>
                      <div className="filter-section-grid">
                        <MultiFilterField label="销售属性" value={draftFilters.sales_property} options={SALES_PROPERTY_OPTIONS} onChange={(value) => updateDraftFilters({ sales_property: value })} />
                        <MultiFilterField label="产品属性" value={draftFilters.product_property} options={productPropertyOptions} onChange={(value) => updateDraftFilters({ product_property: value })} />
                        <MultiFilterField label="季节属性" value={draftFilters.seasonality} options={seasonalityOptions} onChange={(value) => updateDraftFilters({ seasonality: value })} />
                        <MultiFilterField label="MSKU 状态" value={draftFilters.msku_status} options={mskuStatusOptions} onChange={(value) => updateDraftFilters({ msku_status: value })} />
                        <MultiFilterField label="MSKU生命周期" value={draftFilters.msku_life_process} options={mskuLifeProcessOptions} onChange={(value) => updateDraftFilters({ msku_life_process: value })} />
                      </div>
                    </section>
                    <section className="filter-section">
                      <div className="filter-section-head">
                        <strong>销量与风险</strong>
                        <span>销量区间、风险口径</span>
                      </div>
                      <div className="filter-section-grid">
                        <MultiFilterField label="风险类型" value={draftFilters.risk_type} options={RISK_TYPE_OPTIONS} onChange={(value) => updateDraftFilters({ risk_type: value })} />
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

function Metric({ label, value, tone = "" }) {
  return (
    <div className={`metric-chip ${tone}`}>
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
  }, [item.material_code, item.msku, item.fnsku, item.asin]);

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

  const runMonthlyForecastReview = async () => {
    if (forecastReviewLoading) return;
    setForecastReviewLoading(true);
    setForecastReviewError("");
    try {
      const params = new URLSearchParams();
      params.set("month_offset", "2");
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
      const response = await fetch(`${API_BASE_URL}/control-tower/monthly-forecast-review?${params.toString()}`);
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
            <strong>{item.fnsku || item.material_code}</strong>
            <p>{item.sku_name || item.msku || item.fnsku || "-"}</p>
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
  const [supplySimulation, setSupplySimulation] = useState(createEmptySupplySimulation());
  const [forecastDetailOpen, setForecastDetailOpen] = useState(false);
  const [arrivalSourceMode, setArrivalSourceMode] = useState("pici");
  useEffect(() => {
    setSupplySimulation(createEmptySupplySimulation());
    setForecastDetailOpen(false);
    setArrivalSourceMode("pici");
  }, [item.material_code, item.msku, item.fnsku, item.asin, item.store_name, item.country_code]);

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
  const standardSalesControlPlan = useMemo(
    () => buildSalesControlPlan(item, { id: "standard", targetLimitDay: 45, summaryOptions: supplySummaryOptions }),
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
    return {
      ...plan,
      slowReplenishmentPlan: piciShortageWindowSummary(item, planSimulation, supplySummaryOptions).slowReplenishmentWindow,
    };
  }, [item, supplySummaryOptions]);
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
  const slowReplenishmentPlan = useMemo(
    () => piciShortageWindowSummary(item, simulationWithoutChannels(supplySimulation, ["slow_ship"]), supplySummaryOptions).slowReplenishmentWindow,
    [item, supplySimulation, supplySummaryOptions]
  );
  const replenishmentPlans = {
    urgent_air: urgentAirReplenishmentPlan,
    standard_air: standardAirReplenishmentPlan,
    fast_ship: fastReplenishmentPlan,
    slow_ship: slowReplenishmentPlan,
  };
  const applySalesControlPlan = (planId = "standard") => {
    const selectedPlan = salesControlPlans.find((plan) => plan.id === planId) || salesControlPlans[0];
    const slowSuggestedQuantity = selectedPlan?.slowReplenishmentPlan?.suggestedQuantity || 0;
    if (!selectedPlan?.segments?.length && !slowSuggestedQuantity) return;
    setSupplySimulation((current) => ({
      ...createEmptySupplySimulation(),
      ...(current || {}),
      strategyMode: selectedPlan.replenishmentMode === "slow_ship_only" ? "slow_ship_only" : "",
      salesControl: { ...createEmptySupplySimulation().salesControl },
      salesControls: (selectedPlan.segments || []).map((segment) => ({
        startDay: String(segment.startDay),
        endDay: String(segment.endDay),
        controlRatio: String(segment.controlRatio),
      })),
      ...(selectedPlan.replenishmentMode === "slow_ship_only"
        ? {
            urgent_air: { ...createEmptySupplySimulation().urgent_air },
            standard_air: { ...createEmptySupplySimulation().standard_air },
            fast_ship: { ...createEmptySupplySimulation().fast_ship },
            slow_ship: {
              ...createEmptySupplySimulation().slow_ship,
              ...((current || {}).slow_ship || {}),
              replenishQuantity: slowSuggestedQuantity ? String(slowSuggestedQuantity) : "",
            },
          }
        : {}),
    }));
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
            <Metric label="风险" value={riskLabels[item.risk_level] || item.risk_level || "-"} />
            <Metric label="断货" value={formatNumber(simulatedShortageSummary.totalDays) + "天"} tone="warn" />
            <Metric label="预计7天" value={formatNumber(item.projected_7d)} tone={item.projected_7d < 0 ? "danger" : ""} />
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
              ]}
            />
          </DetailSection>

          <DetailSection title="风险判断">
            <DetailGrid
              rows={[
                ["风险类型", riskTypeLabels[item.risk_type] || item.risk_type],
                ["整体等级", riskLabels[item.risk_level] || item.risk_level],
                ["断货等级", riskLabels[item.stockout_risk_level] || item.stockout_risk_level],
                ["冗余等级", riskLabels[item.overstock_risk_level] || item.overstock_risk_level],
                ["风险分", item.risk_score],
                ["提示", item.warning_type],
              ]}
            />
          </DetailSection>

          <DetailSection title="断货明细">
            <DetailGrid
              rows={[
                ["最早断货", formatPiciGap(item)],
                ["原始断货", `${formatNumber(shortageSummary.totalDays)} 天`],
                ["模拟断货", `${formatNumber(simulatedShortageSummary.totalDays)} 天`],
                ["最大缺口", formatNumber(item.pici_min_gap_quantity)],
                ["关键缺口", item.pici_key_gap],
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
                  <div key={key}>
                    <span>{key.replace("_", "-")}天</span>
                    <strong>{value}</strong>
                  </div>
                ))
              ) : (
                <div>
                  <span>chazhi</span>
                  <strong>无数据</strong>
                </div>
              )}
            </div>
          </DetailSection>

          <DetailSection title="库存结构">
            <DetailGrid
              rows={[
                ["总库存", formatNumber(item.total_inventory)],
                ["FBA可售", formatNumber(item.fba_sellable)],
                ["FBA库存", formatNumber(item.fba_inventory)],
                ["海外仓", formatNumber(item.overseas_inventory)],
                ["本地仓", formatNumber(item.local_inventory)],
                ["在途合计", formatNumber(item.inbound_total)],
                ["FBA覆盖", `${item.sellable_days ?? "-"} 天`],
                ["提前期", `${formatNumber(item.lead_time_days)} 天`],
              ]}
            />
          </DetailSection>

          <DetailSection title="需求与销量">
            <DetailGrid
              rows={[
                ["区间销量", formatNumber(item.daily_sales_volume)],
                ["7天需求", formatNumber(item.demand_7d)],
                ["30天需求", formatNumber(item.demand_30d)],
                ["日均需求", formatNumber(item.daily_demand)],
                ["预计7天库存", formatNumber(item.projected_7d)],
              ]}
            />
          </DetailSection>

          <DetailSection title="月度预测复盘">
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
                <button type="button" onClick={onForecastReview} disabled={forecastReviewLoading}>
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

          <DetailSection title="冗余依据">
            <DetailGrid
              rows={[
                ["FBA可售天数", formatDays(item.redundancy_sellable_days?.sellable_1)],
                ["FBA+在途天数", formatDays(item.redundancy_sellable_days?.sellable_2)],
                ["海外仓天数", formatDays(item.redundancy_sellable_days?.sellable_3)],
                ["海外+在途天数", formatDays(item.redundancy_sellable_days?.sellable_4)],
                ["本地仓天数", formatDays(item.redundancy_sellable_days?.sellable_5)],
                ["全链路天数", formatDays(item.redundancy_sellable_days?.sellable_6)],
                ["冗余原因", item.evidence?.overstock_reason],
              ]}
            />
          </DetailSection>

          <DetailSection title="库龄">
            <DetailGrid
              rows={[
                ["61-90天", formatNumber(item.fba_age_61_to_90)],
                ["91-180天", formatNumber(item.fba_age_91_to_180)],
                ["181-270天", formatNumber(item.fba_age_181_to_270)],
                ["271-330天", formatNumber(item.fba_age_271_to_330)],
                ["331-365天", formatNumber(item.fba_age_331_to_365)],
                ["365天+", formatNumber(item.fba_age_365_plus)],
                ["长库龄合计", formatNumber(item.long_age_inventory)],
                ["长库龄占比", item.fba_long_age_ratio === null || item.fba_long_age_ratio === undefined ? "-" : `${formatNumber(item.fba_long_age_ratio * 100)}%`],
              ]}
            />
          </DetailSection>

          <DetailSection title="补货成本估算">
            <ReplenishmentCostEstimate
              estimate={shippingCostEstimate}
              loading={shippingCostLoading}
              error={shippingCostError}
              urgentAirReplenishmentPlan={urgentAirReplenishmentPlan}
              standardAirReplenishmentPlan={standardAirReplenishmentPlan}
            />
          </DetailSection>

          <DetailSection title="建议动作">
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
  const displayWeeks = annotateSupplyWeeksForShippingPolicy(weeks, item);
  const rows = chunkArray(displayWeeks, 5);
  const costByArrivalDay = shippingCostByArrivalDay(shippingCostEstimate);
  const costByChannel = shippingCostByChannel(shippingCostEstimate);
  const isFirstLegMode = arrivalSourceMode === "first_leg";
  const salesControlGuidance = buildSalesControlGuidance(salesControlPlans);
  const shippingGuidance = buildShippingGuidance(item, displayWeeks);

  return (
    <div className="supply-fishbone" aria-label="周维度供货断货鱼骨图">
      <SupplySimulatorControls
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
        <span className="no-ship">阈值后不发货</span>
        <span className="post-threshold-goods">阈值后仍有货</span>
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
  const slowShipOnlyMode = simulation?.strategyMode === "slow_ship_only";
  const activeControlPercentText = formatControlRowsPercentText(salesControlRows);

  return (
    <div className="supply-simulator">
      <div className="supply-simulator-head">
        <strong>补货模拟 / 独立控销</strong>
        <span>原始 {formatNumber(baseTotalDays)} 天 · 模拟 {formatNumber(simulatedTotalDays)} 天</span>
      </div>
      {controlPlans.map((plan) => {
        const salesControlSegments = plan?.segments || [];
        const unresolvedControlSegments = plan?.unresolvedSegments || [];
        const unresolvedControlText = unresolvedControlSegments.flatMap((segment) => segment.shortageSegments || [segment]).map((segment) => `第${formatNumber(segment.startDay)}-${formatNumber(segment.endDay)}天`).join("、");
        const targetLimitDay = plan?.targetLimitDay || 45;
        const controlPlanName = plan?.title || (plan?.strategy === "balanced" ? "提前平滑控销" : "多段控销填入");
        const controlPlanActionName = plan?.actionLabel || (plan?.strategy === "balanced" ? "填入平滑控销" : "填入多段控销");
        const controlPlanNote = plan?.strategy === "balanced" ? `提前均摊后${formatNumber(targetLimitDay)}天前不断货` : `可控段填入后${formatNumber(targetLimitDay)}天前不断货`;
        const slowSuggestedQuantity = plan?.slowReplenishmentPlan?.suggestedQuantity || 0;
        const slowSuggestedCost = slowCost ? slowSuggestedQuantity * Number(slowCost.unit_shipping_cost_cny || 0) : null;
        const canApplyPlan = Boolean(salesControlSegments.length || slowSuggestedQuantity);
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
                        {" · 仅慢船建议 "}
                        <span className="supply-channel-quantity slow-quantity">{formatNumber(slowSuggestedQuantity)} 件</span>
                        {slowSuggestedCost !== null ? ` / ${formatMoney(slowSuggestedCost)} 元` : ""}
                      </>
                    )
                  : " · 60天后暂无慢船缺口"
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
              </small>
            </article>
          );
        })}
      </div>
      <article className="supply-control-card">
        <div className="supply-simulator-card-head">
          <strong>控销时段</strong>
          <span>支持多段，最高60%</span>
        </div>
        <div className="supply-control-inputs">
          {salesControlRows.map((salesControl, index) => (
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
              <button type="button" className="supply-remove-button" onClick={() => removeSalesControl(index)} disabled={salesControlRows.length <= 1}>
                删除
              </button>
            </div>
          ))}
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
  if (day.shippingWindowStatus === "no-ship") {
    parts.push(`${day.shippingPolicyLabel || "当前"}款 ${formatNumber(day.shippingCutoffDay)} 天后不建议新增发货`);
  }
  if (day.shippingWindowStatus === "post-threshold-goods") {
    parts.push(`${day.shippingPolicyLabel || "当前"}款 ${formatNumber(day.shippingCutoffDay)} 天后仍有货/到货 ${formatNumber(day.shippingArrivalQuantity)} 件，复核是否多发`);
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

function createEmptySupplySimulation() {
  const result = SUPPLY_SIMULATION_CHANNELS.reduce((items, channel) => {
    items[channel.channel] = { replenishQuantity: "" };
    return items;
  }, {});
  result.strategyMode = "";
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

function shippingPolicyForItem(item = {}) {
  const flatOrStagnant = isFlatOrStagnantSalesProperty(item.sales_property);
  return {
    label: flatOrStagnant ? "平滞" : isBoomOrWangSalesProperty(item.sales_property) ? "爆旺" : "爆旺",
    cutoffDay: flatOrStagnant ? 75 : 90,
  };
}

function annotateSupplyWeeksForShippingPolicy(weeks = [], item = {}) {
  const policy = shippingPolicyForItem(item);
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
        if (!day || Number(day.day) <= policy.cutoffDay) return day;
        const arrivalQuantity = arrivalQuantityByDay.get(Number(day.day)) || 0;
        const replenishedQuantity = Number(day.replenishedQuantity) || 0;
        const hasGoods = day.status !== "shortage" || arrivalQuantity > 0 || replenishedQuantity > 0;
        return {
          ...day,
          shippingPolicyLabel: policy.label,
          shippingCutoffDay: policy.cutoffDay,
          shippingWindowStatus: hasGoods ? "post-threshold-goods" : "no-ship",
          shippingArrivalQuantity: roundToOne(Math.max(arrivalQuantity, replenishedQuantity)),
        };
      }),
    };
  });
}

function buildSalesControlGuidance(plans = []) {
  const controlPlans = (Array.isArray(plans) ? plans : []).filter(Boolean);
  const plan = controlPlans.find((item) => item?.id === "standard") || controlPlans.find((item) => String(item?.title || "").includes("爆旺")) || controlPlans[0];
  const segments = plan?.segments || [];
  const targetLimitDay = plan?.targetLimitDay || 45;
  if (!segments.length) {
    return {
      title: `按爆旺逻辑，${formatNumber(targetLimitDay)}天前无需控销`,
      detail: "现有供货可覆盖目标窗口。",
    };
  }
  const controlDays = countCoveredDays(segments);
  const controlText = segments.map((segment) => `第${formatNumber(segment.startDay)}-${formatNumber(segment.endDay)}天控${formatNumber(segment.controlRatio)}%`).join("；");
  const residualText = plan?.residualShortageQuantity ? `；控销后仍缺 ${formatNumber(plan.residualShortageQuantity)} 件` : "";
  return {
    title: `按爆旺逻辑，建议控销 ${formatNumber(controlDays)} 天`,
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
    detail: `${channelParts.join("；")}。${formatNumber(policy.cutoffDay)}天后蓝色=不建议发货，橘色=已有/仍有货需复核。`,
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
    if (item.channel) map.set(item.channel, item);
  });
  return map;
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

function ReplenishmentCostEstimate({ estimate, loading, error, urgentAirReplenishmentPlan, standardAirReplenishmentPlan }) {
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
    };
  });
  const urgentAirCostItem = costItems.find((item) => item.channel === "urgent_air");
  const standardAirCostItem = costItems.find((item) => item.channel === "standard_air") || costItems.find((item) => item.channel === "air_or_urgent_transfer");
  const suggestedUrgentAirCost = urgentAirCostItem ? suggestedUrgentAirQuantity * Number(urgentAirCostItem.unit_shipping_cost_cny || 0) : null;
  const suggestedStandardAirCost = standardAirCostItem ? suggestedStandardAirQuantity * Number(standardAirCostItem.unit_shipping_cost_cny || 0) : null;
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
          <strong>单件运费 * 自填补货数量</strong>
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
          {costItems.map((item) => (
            <article className={`cost-estimate-item ${item.channel}`} key={item.channel}>
              <div className="cost-estimate-head">
                <div>
                  <strong>{item.channel_label || item.channel}</strong>
                  <small>{item.window ? `${item.window} · ` : ""}{item.arrival_day ? `到货 第${formatNumber(item.arrival_day)}天` : "按当前重量和费率测算"}</small>
                </div>
                <span>{formatMoney(item.unit_shipping_cost_cny * replenishmentQuantity)} 元</span>
              </div>
              <div className="cost-estimate-metrics">
                <span>单件 {formatMoney(item.unit_shipping_cost_cny)} 元</span>
                <span>数量 {formatNumber(replenishmentQuantity)} 件</span>
                <span>总重 {formatPreciseNumber(item.unit_weight_kg * replenishmentQuantity)} kg</span>
                <span>{formatPreciseNumber(item.rate_cny_per_kg)} 元/kg</span>
              </div>
            </article>
          ))}
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
  const localBarScale = (item) => d3
    .scaleBand()
    .domain(barsForItem(item).map((bar) => bar.key))
    .range([0, xScale.bandwidth()])
    .padding(0.16);
  const buildTooltip = (item, bar) => {
    const value = bar.type === "actual" ? item.actual : bar.value;
    const monthScale = localBarScale(item);
    const x = (xScale(item.month) || margin.left) + (monthScale(bar.key) || 0) + monthScale.bandwidth() / 2;
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
          const monthScale = localBarScale(item);
          return barsForItem(item).map((bar) => {
            const barId = `monthly-${bar.key}-${item.month}`;
            const value = bar.type === "actual" ? item.actual : bar.value;
            const isActive = activeBar?.activeIds?.includes(barId);
            const x = (xScale(item.month) || margin.left) + (monthScale(bar.key) || 0);
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
                      width={monthScale.bandwidth()}
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
                    width={monthScale.bandwidth()}
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
                width={monthScale.bandwidth()}
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

function DetailSection({ title, children }) {
  return (
    <section className="detail-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function DetailGrid({ rows }) {
  return (
    <dl className="detail-grid">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value === null || value === undefined || value === "" ? "-" : value}</dd>
        </div>
      ))}
    </dl>
  );
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

  return (
    <div className="risk-stack">
      <span className={`risk-pill stockout ${stockoutLevel}`}>
        {riskBadgeLabel(stockoutRiskBadgeLabels, stockoutLevel)}
      </span>
      <span className={`risk-pill overstock ${overstockLevel}`}>
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
  const response = await fetch(`${API_BASE_URL}/agent/run`, {
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
  const response = await fetch(`${API_BASE_URL}/control-tower/sku-diagnosis/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item: enrichedItem, question }),
  });
  if (!response.ok) throw new Error(`诊断失败 ${response.status}`);
  return response.json();
}

async function fetchSkuShippingCost(item) {
  const response = await fetch(`${API_BASE_URL}/control-tower/sku-shipping-cost`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item }),
  });
  if (!response.ok) throw new Error(`成本估算失败 ${response.status}`);
  return response.json();
}

async function fetchFirstLegShipments(item) {
  const params = new URLSearchParams();
  [
    ["material_code", item.material_code],
    ["msku", item.msku],
    ["fnsku", item.fnsku],
    ["asin", item.asin],
  ].forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
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
    return await fetch(url, { ...options, signal: controller.signal });
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
      `- 销售潜力：${section.sales_potential.label || "-"}；评分 ${formatNumber(section.sales_potential.score)}；销量/广告费 ${section.sales_potential.weekly_sales_ad_ratio ?? "-"}；${section.sales_potential.sales_curve || "-"}`
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
    `SKU: ${item.material_code}`,
    `名称: ${item.sku_name || "-"}`,
    `店铺/国家: ${item.store_name || "-"} / ${item.country_code || item.shipments_country || "-"}`,
    `销售属性: ${item.sales_property || "-"}`,
    `风险: ${item.warning_type || "-"}，整体等级 ${riskLabels[item.risk_level] || item.risk_level || "-"}`,
    `断货: ${formatPiciGap(item)}，合计 ${formatNumber(shortage.totalDays)} 天，最大缺口 ${formatNumber(item.pici_min_gap_quantity)}`,
    `库存: 总 ${formatNumber(item.total_inventory)}，FBA ${formatNumber(item.fba_sellable)}，在途 ${formatNumber(item.inbound_total)}，海外 ${formatNumber(item.overseas_inventory)}，本地 ${formatNumber(item.local_inventory)}`,
    `需求: 区间销量 ${formatNumber(item.daily_sales_volume)}，7天 ${formatNumber(item.demand_7d)}，30天 ${formatNumber(item.demand_30d)}，日均 ${formatNumber(item.daily_demand)}`,
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
      `冗余风险：${riskLabels[item.overstock_risk_level] || item.overstock_risk_level || "正常"}；${item.evidence?.overstock_reason || "当前未返回具体冗余原因"}。`,
      `归因：${item.stockout_risk_level !== "normal" && item.overstock_risk_level !== "normal" ? "断货和冗余并存，优先按库存位置、库龄和补货节奏错配处理。" : item.suggested_action || "暂无明确异常。"}`,
      `补救措施：先核查 chazhi 和在途覆盖；能转化库存则调拨/催上架，不能覆盖则复核采购补救；若命中冗余，同步冻结非必要采购和发货，交由销售清货。`,
    ].join("\n");
  }
  if (question.includes("断货")) {
    return `${item.material_code} 当前${formatPiciGap(item)}，合计断货 ${formatNumber(shortage.totalDays)} 天。优先看 FBA 可售 ${formatNumber(item.fba_sellable)}、在途 ${formatNumber(item.inbound_total)} 和 chazhi 缺口 ${item.pici_key_gap || "-"}，再判断是否加急发货或补采购。`;
  }
  if (question.includes("冗余")) {
    return `${item.material_code} 的冗余等级是 ${riskLabels[item.overstock_risk_level] || item.overstock_risk_level || "-"}。依据是：${item.evidence?.overstock_reason || "当前未返回具体冗余原因"}。如果同时断货，通常说明库存位置或库龄结构有问题，不是简单总量不足。`;
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
  return {
    totalDays,
    firstStartDay: firstStartDay ?? item.pici_first_shortage_days ?? 0,
    segments,
    days: fishboneDays,
    urgentAirReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 10, 19),
    standardAirReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 20, 45),
    fastReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 46, 60),
    slowReplenishmentWindow: summarizeSupplyWindow(fishboneDays, 61, Number.POSITIVE_INFINITY),
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
  const maxDay = Math.max(...days.map((day) => day.day));
  const dayByNumber = new Map(days.map((day) => [day.day, day]));
  const weekCount = Math.ceil(maxDay / 7);

  return Array.from({ length: weekCount }, (_, index) => {
    const week = index + 1;
    const startDay = index * 7 + 1;
    const endDay = Math.min(startDay + 6, maxDay);
    const weekDays = [];

    for (let day = startDay; day <= endDay; day += 1) {
      weekDays.push(dayByNumber.get(day) || { day, status: "ok" });
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
