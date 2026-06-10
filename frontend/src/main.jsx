import React, { useEffect, useMemo, useState } from "react";
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
  RefreshCw,
  Search,
  ShieldAlert,
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

const riskTypeLabels = {
  stockout: "断货",
  overstock: "冗余",
  anomaly: "异常",
  healthy: "正常",
};

function App() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [activeSkuItem, setActiveSkuItem] = useState(null);
  const pageSize = 100;
  const [filters, setFilters] = useState({
    material_code: "",
    country_code: "",
    store_name: "",
    sales_property: "",
    risk_type: "",
    sales_start_date: previousDate(),
    sales_end_date: previousDate(),
    risk_only: false,
  });

  const loadSummary = async (targetPage = page, targetFilters = filters) => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams();
      Object.entries(targetFilters).forEach(([key, value]) => {
        if (value !== "" && value !== false) params.set(key, value);
      });
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

  useEffect(() => {
    loadSummary(1);
  }, []);

  const filteredItems = useMemo(() => {
    if (!summary?.items) return [];
    return summary.items;
  }, [summary]);

  const applySalesPeriod = (nextDates) => {
    const nextFilters = { ...filters, ...nextDates };
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
          <input
            value={filters.country_code}
            placeholder="国家，如 US"
            onChange={(event) => setFilters({ ...filters, country_code: event.target.value })}
          />
        </label>
        <label className="input-wrap">
          <Warehouse size={16} />
          <input
            value={filters.store_name}
            placeholder="店铺"
            onChange={(event) => setFilters({ ...filters, store_name: event.target.value })}
          />
        </label>
        <select
          value={filters.sales_property}
          onChange={(event) => setFilters({ ...filters, sales_property: event.target.value })}
          aria-label="销售属性"
        >
          <option value="">全部属性</option>
          <option value="爆">爆</option>
          <option value="旺">旺</option>
          <option value="平">平</option>
          <option value="滞">滞</option>
        </select>
        <select
          value={filters.risk_type}
          onChange={(event) => setFilters({ ...filters, risk_type: event.target.value })}
          aria-label="风险类型"
        >
          <option value="">全部风险类型</option>
          <option value="stockout">断货预警</option>
          <option value="overstock">冗余库存</option>
          <option value="anomaly">库存异常</option>
          <option value="healthy">正常 SKU</option>
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
            <KpiGrid summary={summary} />
            <InventoryMap
              nodes={summary.map_nodes || []}
              selectedCountry={filters.country_code}
              onCountrySelect={(countryCode) => {
                const nextFilters = { ...filters, country_code: countryCode };
                setFilters(nextFilters);
                setPage(1);
                loadSummary(1, nextFilters);
              }}
            />
            <WarehouseInventoryPanel countryCode={filters.country_code} rows={summary.warehouse_inventory || []} />
            <section className="dashboard-grid">
              <RiskBreakdown title="风险等级" data={summary.risk_distribution} labels={riskLabels} />
              <RiskBreakdown title="风险类型" data={summary.risk_type_distribution} labels={riskTypeLabels} />
              <SourcePanel summary={summary} />
            </section>
            <InventoryTable
              items={filteredItems}
              pagination={summary.pagination}
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
              onOpenItem={setActiveSkuItem}
            />
            <FieldDecisionTable fields={summary.field_decisions} />
          </>
        )
      )}
    </main>
    {activeSkuItem && <ActionDetailDialog item={activeSkuItem} onClose={() => setActiveSkuItem(null)} />}
    </>
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

function InventoryTable({
  items,
  pagination,
  salesPeriod,
  salesStartDate,
  salesEndDate,
  loading,
  onSalesPeriodChange,
  onSalesPeriodApply,
  onSalesPreset,
  onPageChange,
  onOpenItem,
}) {
  const currentPage = pagination?.page || 1;
  const totalPages = pagination?.total_pages || 1;
  const totalCount = pagination?.total_count ?? items.length;
  const pageSize = pagination?.page_size ?? items.length;
  const start = totalCount ? (currentPage - 1) * pageSize + 1 : 0;
  const end = totalCount ? start + items.length - 1 : 0;
  return (
    <section className="table-section">
      <div className="section-heading">
        <div>
          <h2>SKU 风险明细</h2>
          <p>共 {formatNumber(totalCount)} 条，当前显示 {formatNumber(start)}-{formatNumber(end)} 条，销量区间 {salesPeriod || "-"}</p>
        </div>
        <div className="table-actions">
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
        <table>
          <thead>
            <tr>
              <th>风险</th>
              <th>SKU</th>
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
            {items.map((item) => (
              <tr key={`${item.material_code}-${item.store_name}-${item.fnsku}`}>
                <td>
                  <RiskBadges item={item} />
                </td>
                <td>
                  <SkuCell item={item} />
                </td>
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
                  <ActionSummaryCell item={item} onOpen={() => onOpenItem(item)} />
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
  const [forecastReview, setForecastReview] = useState(null);
  const [forecastReviewLoading, setForecastReviewLoading] = useState(false);
  const [forecastReviewError, setForecastReviewError] = useState("");
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
    setRecordInput("");
    setRecords([
      { time: "当前", title: "Agent 识别风险", content: item.warning_type || "正常" },
    ]);
  }, [item.material_code]);

  const sendChat = async () => {
    const text = chatInput.trim();
    if (!text || chatSending) return;
    const userMessage = { role: "user", text };
    setChatMessages((messages) => [...messages, userMessage]);
    setChatInput("");
    setChatSending(true);
    try {
      const reply = await askSkuAssistant(item, text);
      setChatMessages((messages) => [...messages, { role: "assistant", text: reply }]);
    } catch (error) {
      setChatMessages((messages) => [...messages, { role: "assistant", text: localSkuChatReply(item, text) }]);
    } finally {
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

  const addRecord = () => {
    const text = recordInput.trim();
    if (!text) return;
    setRecords((items) => [{ time: new Date().toLocaleString("zh-CN", { hour12: false }), title: "人工备注", content: text }, ...items]);
    setRecordInput("");
  };

  return (
    <div className="drawer-backdrop" role="presentation" onClick={onClose}>
      <aside className="sku-drawer" role="dialog" aria-modal="true" aria-label="SKU 工作台" onClick={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <span>SKU 工作台</span>
            <strong>{item.material_code}</strong>
            <p>{item.sku_name || item.msku || item.fnsku || "-"}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="关闭条目详情">
            ×
          </button>
        </div>
        <div className="drawer-tabs" role="tablist" aria-label="SKU 工作台视图">
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
  onForecastReview,
}) {
  return (
    <>
          <div className="detail-kpis">
            <Metric label="风险" value={riskLabels[item.risk_level] || item.risk_level || "-"} />
            <Metric label="断货" value={formatNumber(shortageSummary.totalDays) + "天"} tone="warn" />
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
                ["销售属性", item.sales_property],
                ["季节属性", item.seasonality],
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
                ["合计断货", `${formatNumber(shortageSummary.totalDays)} 天`],
                ["最大缺口", formatNumber(item.pici_min_gap_quantity)],
                ["关键缺口", item.pici_key_gap],
              ]}
            />
            <div className="detail-tags">
              {shortageSummary.segments.length > 0 ? shortageSummary.segments.map((segment) => <span key={segment}>{segment}</span>) : <span>暂无断货段</span>}
            </div>
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
                    ? `${forecastReview.target_month} 版本预测 vs ${forecastReview.comparison_month} 周度实际`
                    : "按当前月份 -2 取预测版本月"}
                </strong>
                <span>来源 {forecastReview?.forecast_source || "dim_lingxing_sales_estimates_monthly_v1"}</span>
              </div>
              <button type="button" onClick={onForecastReview} disabled={forecastReviewLoading}>
                <RefreshCw size={15} />
                <span>{forecastReviewLoading ? "复盘中" : "手动复盘"}</span>
              </button>
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
                    ["预测版本月", `${forecastReview.target_start_date} 至 ${forecastReview.target_end_date}`],
                    ["对比区间", `${forecastReview.review_start_date || forecastReview.comparison_start_date} 至 ${forecastReview.review_end_date || forecastReview.comparison_end_date}`],
                    ["快照日期", forecastReview.snapshot_date],
                    ["总预测", formatNumber(forecastReview.forecast_quantity)],
                    ["总销量", formatNumber(forecastReview.actual_sales)],
                    ["总差值", formatSignedNumber(forecastReview.difference)],
                    ["差值比例", formatPercent(forecastReview.variance_percent)],
                    ["快照行数", formatNumber(forecastReview.snapshot_row_count)],
                    ["预估行数", formatNumber(forecastReview.forecast_row_count)],
                    ["实际行数", formatNumber(forecastReview.actual_row_count)],
                  ]}
                />
                {forecastReview.weekly_estimates?.length > 0 && (
                  <>
                    <ForecastReviewChart points={forecastReview.weekly_estimates} />
                    <div className="weekly-estimate-list">
                      {forecastReview.weekly_estimates.map((week) => (
                        <div key={week.week}>
                          <span>{week.week}</span>
                          <strong>{formatNumber(week.actual_sales)} / {formatNumber(week.forecast_quantity)}</strong>
                          <small>{week.week_start_date} 至 {week.week_end_date} · {formatSignedNumber(week.difference)} · {formatPercent(week.variance_percent)}</small>
                        </div>
                      ))}
                    </div>
                  </>
                )}
                <p>{lastItem(forecastReview.notes) || "差值 = 实际销量 - 预测销量；比例 = 差值 / 预测销量。"}</p>
              </div>
            ) : (
              <p className="empty-detail">点击手动复盘后，系统会用当前月份 -2 的预测版本月，从该月月初到今天按周对比预测销量和实际销量。</p>
            )}
          </DetailSection>

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

          <DetailSection title="库存异常">
            {riskFlags.length > 0 ? (
              <div className="flag-detail-list">
                {riskFlags.map((flag, index) => {
                  const detail = normalizeRiskFlag(flag, index);
                  return (
                    <div className="flag-detail-item" key={`${detail.field}-${index}`}>
                      <div>
                        <strong>{detail.label}</strong>
                        <code>{detail.field}</code>
                      </div>
                      <span>{detail.value}</span>
                      <p>{detail.reason}</p>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="empty-detail">未命中底表异常标记</p>
            )}
          </DetailSection>

          <DetailSection title="建议动作">
            <div className="action-list empty" aria-label="建议动作待填写" />
          </DetailSection>
    </>
  );
}

function SkuAiChatPanel({ item, messages, input, sending, onInputChange, onSend, onQuickAsk }) {
  const quickQuestions = ["为什么判定断货？", "冗余和断货为什么同时存在？", "生成给销售的处理建议", "这条能否先关闭？"];
  return (
    <div className="ai-panel">
      <div className="ai-context">
        <span>当前上下文</span>
        <strong>{item.material_code}</strong>
        <p>{item.warning_type || "正常"} · 区间销量 {formatNumber(item.daily_sales_volume)} · 预计7天 {formatNumber(item.projected_7d)}</p>
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

function ForecastReviewChart({ points }) {
  const data = (points || []).map((point) => ({
    week: point.week,
    forecast: Number(point.forecast_quantity || 0),
    actual: Number(point.actual_sales || 0),
  }));
  if (!data.length) return null;

  const width = 680;
  const height = 250;
  const margin = { top: 22, right: 22, bottom: 46, left: 54 };
  const xScale = d3
    .scalePoint()
    .domain(data.map((point) => point.week))
    .range([margin.left, width - margin.right])
    .padding(0.5);
  const maxValue = d3.max(data, (point) => Math.max(point.forecast, point.actual)) || 1;
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
  const forecastLine = line(data.map((point) => ({ week: point.week, value: point.forecast })));
  const actualLine = line(data.map((point) => ({ week: point.week, value: point.actual })));
  const yTicks = yScale.ticks(4);
  const labelEvery = Math.max(1, Math.ceil(data.length / 6));

  return (
    <div className="forecast-chart" aria-label="周度预测和实际销量折线图">
      <div className="forecast-chart-legend">
        <span className="forecast">预测</span>
        <span className="actual">实际</span>
      </div>
      <svg viewBox={`0 0 ${width} ${height}`} role="img">
        {yTicks.map((tick) => (
          <g key={tick}>
            <line x1={margin.left} x2={width - margin.right} y1={yScale(tick)} y2={yScale(tick)} />
            <text x={margin.left - 10} y={yScale(tick) + 4} textAnchor="end">
              {formatNumber(tick)}
            </text>
          </g>
        ))}
        <path className="forecast-line" d={forecastLine || ""} />
        <path className="actual-line" d={actualLine || ""} />
        {data.map((point) => (
          <React.Fragment key={point.week}>
            <circle className="forecast-dot" cx={xScale(point.week)} cy={yScale(point.forecast)} r="4" />
            <circle className="actual-dot" cx={xScale(point.week)} cy={yScale(point.actual)} r="4" />
          </React.Fragment>
        ))}
        {data.map((point, index) =>
          index % labelEvery === 0 || index === data.length - 1 ? (
            <text key={point.week} className="x-label" x={xScale(point.week)} y={height - 18} textAnchor="middle">
              {point.week}
            </text>
          ) : null
        )}
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

function RiskBadges({ item }) {
  return (
    <div className="risk-stack">
      <span className={`risk-pill stockout ${item.stockout_risk_level || "normal"}`}>
        断货{riskLabels[item.stockout_risk_level] || "正常"}
      </span>
      <span className={`risk-pill overstock ${item.overstock_risk_level || "normal"}`}>
        冗余{riskLabels[item.overstock_risk_level] || "正常"}
      </span>
      <small>{item.warning_type}</small>
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

async function askSkuAssistant(item, question) {
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

function piciShortageWindowSummary(item) {
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
  let totalDays = 0;
  const segments = [];
  let firstStartDay = null;

  entries.forEach((entry) => {
    const intervalDays = Math.max(entry.horizon - previousHorizon, 0);
    const intervalForecast = Math.max(entry.forecast - previousForecast, 0);
    const intervalSupply = Math.max(entry.available - previousAvailable, 0);
    const carriedAvailable = Math.max(previousAvailable - previousForecast, 0);
    const intervalAvailable = carriedAvailable + intervalSupply;

    if (intervalDays > 0 && intervalForecast > intervalAvailable) {
      const dailyForecast = intervalForecast / intervalDays;
      const coveredDays = Math.min(intervalDays, Math.floor(intervalAvailable / dailyForecast));
      const shortageDays = intervalDays - coveredDays;
      const startDay = previousHorizon === 0 ? coveredDays : previousHorizon + Math.max(coveredDays, 1);
      totalDays += shortageDays;
      firstStartDay = firstStartDay === null ? startDay : Math.min(firstStartDay, startDay);
      segments.push(formatShortageSegment(startDay, shortageDays));
    }

    previousHorizon = entry.horizon;
    previousAvailable = entry.available;
    previousForecast = entry.forecast;
  });
  return { totalDays, firstStartDay: firstStartDay ?? item.pici_first_shortage_days ?? 0, segments };
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

function formatSalesPeriod(start, end) {
  if (!start && !end) return "";
  if (!start || start === end) return end || start;
  if (!end) return start;
  return `${start} 至 ${end}`;
}

createRoot(document.getElementById("root")).render(<App />);
