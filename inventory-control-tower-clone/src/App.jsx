import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Bell,
  Bot,
  Box,
  CalendarDays,
  Castle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  ClipboardList,
  Database,
  Download,
  Eye,
  FileSpreadsheet,
  Layers3,
  Loader2,
  LogIn,
  LogOut,
  MessageSquare,
  PackageSearch,
  PieChart,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  ShoppingCart,
  Star,
  TrendingUp,
  TriangleAlert,
  Truck,
  Upload,
  UserRound,
  Wallet,
  X,
} from "lucide-react";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
const nf = new Intl.NumberFormat("zh-CN");
const PAGE_SIZE = 100;

const tabs = ["风险总览", "SKU 明细", "仓库明细", "头程在途", "补货建议", "异常监控", "字段口径"];
const rangeOptions = ["昨日", "近7天", "近30天", "本月"];
const compareOptions = ["对比前30天", "对比上月", "不对比"];
const riskFilterOptions = [
  { value: "", label: "全部风险" },
  { value: "stockout", label: "断货预警" },
  { value: "overstock", label: "冗余库存" },
  { value: "anomaly", label: "库存异常" },
  { value: "healthy", label: "正常 SKU" },
];
const salesPropertyOptions = ["爆", "旺", "平", "滞"];
const mskuStatusOptions = ["在售", "待售", "共享", "停售", "待淘汰", "淘汰"];
const lifeProcessOptions = ["新品期", "非新品期"];
const commonCountryOptions = ["US", "JP", "CA", "UK", "DE", "MX", "CN", "FR", "IT", "ES", "AU", "NL", "PL", "SE", "AE", "SA", "BR"];
const exportOptions = [
  { key: "sku", label: "SKU 排查", endpoint: "/control-tower/export/sku-investigation", filename: "sku_investigation.xlsx" },
  { key: "daily", label: "每日排查", endpoint: "/control-tower/export/daily-investigation", filename: "daily_investigation.xlsx" },
  { key: "recommendations", label: "补货建议", endpoint: "/control-tower/export/recommendations", filename: "recommendations.xlsx" },
];

const riskTypeMeta = {
  stockout: { label: "断货预警", color: "#ff5b52", tone: "red" },
  overstock: { label: "冗余库存", color: "#ff8b21", tone: "orange" },
  anomaly: { label: "库存异常", color: "#ffc32a", tone: "orange" },
  healthy: { label: "正常 SKU", color: "#22b981", tone: "green" },
  normal: { label: "其他", color: "#aab5c8", tone: "orange" },
};

const riskLevelLabel = {
  critical: "严重",
  high: "高",
  medium: "中",
  low: "低",
  normal: "正常",
};

const countryNameMap = {
  美国: "US",
  英国: "UK",
  德国: "DE",
  日本: "JP",
  法国: "FR",
  US: "US",
  UK: "UK",
  GB: "GB",
  DE: "DE",
  JP: "JP",
  FR: "FR",
};

const fallbackKpis = [
  { label: "SKU 数", value: "6,500", delta: "3.2%", trend: "up", tone: "blue", icon: Box },
  { label: "总库存", value: "736,949", delta: "4.8%", trend: "down", tone: "blue", icon: Layers3 },
  { label: "FBA 可售", value: "419,182", delta: "6.5%", trend: "up", tone: "green", icon: ShoppingCart },
  { label: "区间销量", value: "8,357", delta: "8.1%", trend: "up", tone: "purple", icon: TrendingUp },
  { label: "断货风险", value: "1,248", delta: "11.7%", trend: "up", tone: "orange", icon: TriangleAlert },
  { label: "库销比", value: "2.9x", delta: "0.3x", trend: "down", tone: "blue", icon: PieChart },
];

const fallbackFlowStages = [
  { label: "本地 / 供应商仓", value: "287,562", delta: "5.1%", trend: "down" },
  { label: "头库在途", value: "142,731", delta: "8.3%", trend: "up" },
  { label: "国外仓可售", value: "419,182", delta: "2.6%", trend: "down" },
  { label: "在途入仓", value: "76,320", delta: "12.4%", trend: "up" },
  { label: "预留库存", value: "23,154", delta: "3.7%", trend: "down" },
  { label: "客户可售", value: "419,182", delta: "2.6%", trend: "down", active: true },
];

const fallbackRiskTypes = [
  { label: "断货风险", value: 1248, pct: "23.1%", color: "#ff5b52" },
  { label: "库销比过高", value: 1873, pct: "34.6%", color: "#ff8b21" },
  { label: "滞销风险", value: 1012, pct: "18.7%", color: "#ffc32a" },
  { label: "库存不足", value: 658, pct: "12.2%", color: "#5e8cff" },
  { label: "到货延迟", value: 369, pct: "6.8%", color: "#31bec8" },
  { label: "其他", value: 240, pct: "4.6%", color: "#aab5c8" },
];

const fallbackCountryRiskTypes = [
  { label: "美国", value: 1002, pct: "24.1%", color: "#2368e8" },
  { label: "英国", value: 687, pct: "19.3%", color: "#4d8fff" },
  { label: "德国", value: 498, pct: "14.0%", color: "#65a6ff" },
  { label: "日本", value: 321, pct: "9.0%", color: "#31bec8" },
  { label: "法国", value: 276, pct: "7.6%", color: "#ffc32a" },
  { label: "其他", value: 2616, pct: "26.0%", color: "#ff8b21" },
];

const fallbackRiskCards = [
  { label: "高风险 SKU", value: "542", delta: "18.6%", trend: "up", tone: "red", icon: ShieldCheck },
  { label: "中风险 SKU", value: "1,873", delta: "6.3%", trend: "up", tone: "orange", icon: AlertTriangle },
  { label: "低风险 SKU", value: "2,985", delta: "4.2%", trend: "down", tone: "yellow", icon: AlertTriangle },
  { label: "健康 SKU", value: "1,100", delta: "7.1%", trend: "down", tone: "green", icon: CheckCircle2 },
];

const fallbackAlerts = [
  { type: "断货风险", object: "美国站", desc: "预计 7 天内将断货", sku: 265, inventory: "32,156", tone: "red" },
  { type: "库销比过高", object: "英国站", desc: "库销比 > 6x", sku: 312, inventory: "61,872", tone: "orange" },
  { type: "滞销风险", object: "德国站", desc: "30 天销量为 0", sku: 198, inventory: "18,933", tone: "red" },
  { type: "到货延迟", object: "头程在途", desc: "预计到仓延迟 > 7 天", sku: 156, inventory: "12,675", tone: "orange" },
  { type: "库存不足", object: "日本站", desc: "可售库存 < 安全库存", sku: 143, inventory: "8,456", tone: "orange" },
];

const fallbackCountryRows = [
  { name: "美国", high: 218, risk: "1,002", share: "24.1%", width: 88 },
  { name: "英国", high: 142, risk: "687", share: "19.3%", width: 72 },
  { name: "德国", high: 96, risk: "498", share: "14.0%", width: 54 },
  { name: "日本", high: 58, risk: "321", share: "9.0%", width: 36 },
  { name: "法国", high: 44, risk: "276", share: "7.6%", width: 28 },
];

const fallbackStoreRows = [
  { name: "Amazon US", high: 176, risk: "824", share: "21.2%", width: 82 },
  { name: "Amazon UK", high: 131, risk: "641", share: "16.8%", width: 66 },
  { name: "Amazon DE", high: 88, risk: "420", share: "13.4%", width: 51 },
  { name: "Amazon JP", high: 63, risk: "319", share: "9.6%", width: 38 },
  { name: "Amazon FR", high: 41, risk: "255", share: "7.1%", width: 26 },
];

const fallbackSkuRows = [
  { sku: "B0C-LAMP-001", site: "美国站", risk: "断货风险", inventory: "1,246", sales: "326", owner: "PM", action: "优先补货" },
  { sku: "B0D-STAND-019", site: "英国站", risk: "库销比过高", inventory: "6,872", sales: "48", owner: "Doris", action: "控补清货" },
  { sku: "B0F-BAG-228", site: "德国站", risk: "滞销风险", inventory: "3,193", sales: "0", owner: "Alex", action: "促销复盘" },
  { sku: "B0A-CABLE-076", site: "日本站", risk: "库存不足", inventory: "456", sales: "88", owner: "Yuki", action: "加急调拨" },
  { sku: "B0K-HOLDER-315", site: "美国站", risk: "到货延迟", inventory: "987", sales: "121", owner: "PM", action: "跟催物流" },
];

const fallbackWarehouseRows = [
  { warehouse: "LAX-西部仓", type: "海外仓", available: "92,406", transit: "18,320", reserved: "5,483", risk: "21.2%", owner: "供应链一部" },
  { warehouse: "NJ-东部仓", type: "海外仓", available: "76,311", transit: "14,782", reserved: "4,216", risk: "16.8%", owner: "供应链一部" },
  { warehouse: "UK-MAN仓", type: "海外仓", available: "52,988", transit: "9,012", reserved: "2,143", risk: "13.4%", owner: "欧洲运营组" },
  { warehouse: "FBA-US-WEST", type: "FBA", available: "119,604", transit: "26,592", reserved: "8,905", risk: "12.1%", owner: "精品运营部" },
  { warehouse: "JP-大阪仓", type: "海外仓", available: "31,205", transit: "7,614", reserved: "1,804", risk: "7.1%", owner: "日本运营组" },
];

const fallbackTransitRows = [
  { batch: "US-SEA-240609", route: "宁波 -> LAX", eta: "2025-06-16", sku: 86, qty: "32,840", status: "预计延迟 2 天" },
  { batch: "UK-AIR-240608", route: "深圳 -> MAN", eta: "2025-06-12", sku: 41, qty: "9,320", status: "优先清关" },
  { batch: "DE-SEA-240603", route: "上海 -> Hamburg", eta: "2025-06-22", sku: 73, qty: "18,560", status: "在途正常" },
  { batch: "JP-AIR-240607", route: "广州 -> Osaka", eta: "2025-06-11", sku: 29, qty: "6,842", status: "到港待提" },
];

const fallbackReplenishRows = [
  { sku: "B0C-LAMP-001", site: "美国站", suggestion: "补 12,500 件", reason: "预计 7 天内断货", priority: "高" },
  { sku: "B0A-CABLE-076", site: "日本站", suggestion: "空运 2,800 件", reason: "低于安全库存", priority: "高" },
  { sku: "B0D-STAND-019", site: "英国站", suggestion: "暂停补货 21 天", reason: "库销比 > 6x", priority: "中" },
  { sku: "B0F-BAG-228", site: "德国站", suggestion: "清仓促销", reason: "30 天销量为 0", priority: "中" },
];

function defaultFilterState() {
  return {
    range: rangeOptions[0],
    compare: compareOptions[0],
    materialCode: "",
    site: "全部站点",
    country: "全部",
    shipmentCountry: "全部发货国",
    type: "全部",
    warehouse: "全部仓库",
    store: "全部店铺",
    department: "全部",
    owner: "全部",
    salesman: "全部销售员",
    risk: "全部风险",
    skuLevel: "全部属性",
    productProperty: "全部产品属性",
    season: "全部季节",
    mskuStatus: "在售",
    lifeProcess: "全部生命周期",
    riskOnly: false,
    positiveDemand: false,
  };
}

function apiFetch(url, options = {}) {
  return fetch(url, { ...options, credentials: "include" });
}

export function App() {
  const [activeTab, setActiveTab] = useState("风险总览");
  const [filterState, setFilterState] = useState(defaultFilterState);
  const [expanded, setExpanded] = useState(false);
  const [favorite, setFavorite] = useState(false);
  const [auth, setAuth] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState("");
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState("");
  const [message, setMessage] = useState("");
  const [page, setPage] = useState(1);
  const [activeWarehouseStage, setActiveWarehouseStage] = useState("local");
  const [riskDimension, setRiskDimension] = useState("风险类型");
  const [rankDimension, setRankDimension] = useState("国家风险");
  const [selectedRisk, setSelectedRisk] = useState("");
  const [drawerItem, setDrawerItem] = useState(null);
  const [skuWorkbenchItem, setSkuWorkbenchItem] = useState(null);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [exportMenuOpen, setExportMenuOpen] = useState(false);

  const dashboard = useMemo(() => buildDashboardData(summary), [summary]);
  const filterDefs = useMemo(() => buildFilterDefs(summary), [summary]);
  const extraFilterDefs = useMemo(() => buildExtraFilterDefs(summary), [summary]);
  const distribution = riskDimension === "国家/地区" ? dashboard.countryDistribution : dashboard.riskTypeDistribution;
  const rankRows = rankDimension === "店铺风险" ? dashboard.storeRows : dashboard.countryRows;

  useEffect(() => {
    loadAuth();
  }, []);

  useEffect(() => {
    if (authLoading) return;
    if (auth?.auth_required && !auth?.authenticated) {
      setLoading(false);
      return;
    }
    loadSummary(defaultFilterState(), { initial: true, page: 1 });
  }, [authLoading, auth?.authenticated, auth?.auth_required]);

  const querySummary = useMemo(() => {
    const allDefs = [...filterDefs, ...extraFilterDefs];
    const active = Object.entries(filterState).filter(([key, value]) => {
      const source = allDefs.find((item) => item.key === key);
      if (!source) return false;
      if (source.type === "checkbox") return Boolean(value);
      if (source.type === "text") return String(value || "").trim();
      return value !== source.options[0];
    });
    if (!active.length) return "当前筛选：全部范围";
    return `当前筛选：${active.map(([key, value]) => `${fieldLabel(key, allDefs)}=${checkboxLabel(value)}`).join(" / ")}`;
  }, [filterState, filterDefs, extraFilterDefs]);

  async function loadAuth() {
    setAuthLoading(true);
    try {
      const response = await apiFetch(`${API_BASE_URL}/auth/me`);
      if (!response.ok) throw new Error(`AUTH ${response.status}`);
      setAuth(await response.json());
    } catch {
      setAuth({ authenticated: false, auth_required: false, permissions: { features: ["*"], all_data: true }, user: {} });
    } finally {
      setAuthLoading(false);
    }
  }

  async function loadSummary(targetFilters = filterState, options = {}) {
    setLoading(true);
    setError("");
    try {
      const targetPage = options.page || 1;
      const params = buildSummaryParams(targetFilters, { ...options, page: targetPage });
      const response = await apiFetch(`${API_BASE_URL}/control-tower/summary?${params.toString()}`);
      if (response.status === 401) {
        await loadAuth();
        throw new Error("接口需要登录，请先在原系统完成登录");
      }
      if (response.status === 403) throw new Error("当前账号没有查看控制塔数据的权限");
      if (!response.ok) throw new Error(`接口返回 ${response.status}`);
      const payload = await response.json();
      setSummary(payload);
      setPage(payload.pagination?.page || targetPage);
      setLastUpdate(payload.sales_stat_date || new Date().toLocaleString("zh-CN", { hour12: false }));
      if (!options.initial) setMessage(options.refresh ? "真实数据已刷新" : "查询完成，已载入真实控制塔数据");
    } catch (err) {
      const text = err instanceof Error ? err.message : "控制塔数据加载失败";
      setError(text);
      if (!summary) setLastUpdate("2025-06-09 09:30");
      setMessage(`${text}，当前显示兜底样例数据`);
    } finally {
      setLoading(false);
    }
  }

  function updateFilter(key, value) {
    setFilterState((current) => ({ ...current, [key]: value }));
  }

  function resetFilters() {
    const next = defaultFilterState();
    setFilterState(next);
    setPage(1);
    loadSummary(next, { page: 1 });
  }

  function runQuery() {
    setPage(1);
    loadSummary(filterState, { page: 1 });
  }

  function refresh() {
    loadSummary(filterState, { refresh: true, page });
  }

  function changePage(nextPage) {
    const bounded = Math.max(1, nextPage);
    setPage(bounded);
    loadSummary(filterState, { page: bounded });
  }

  function loginWithFeishu() {
    window.location.href = `${API_BASE_URL}/auth/feishu/login?next=${encodeURIComponent(window.location.href)}`;
  }

  async function logout() {
    await apiFetch(`${API_BASE_URL}/auth/logout`, { method: "POST" });
    setSummary(null);
    await loadAuth();
  }

  function drillRiskType(label) {
    const matched = riskFilterOptions.find((item) => item.label === label);
    if (!matched?.value) return;
    const next = { ...filterState, risk: matched.label, riskOnly: matched.value !== "healthy" };
    setFilterState(next);
    setSelectedRisk(label);
    setPage(1);
    loadSummary(next, { page: 1 });
  }

  function drillRank(row) {
    if (!row?.filterKey || !row?.filterValue) {
      setDrawerItem({ type: "维度风险", object: row?.name, desc: `${row?.name || "-"} 风险占比 ${row?.share || "-"}`, sku: row?.high, inventory: row?.risk });
      return;
    }
    const keyMap = {
      country_code: "country",
      store_name: "store",
      sales_department: "department",
      product_manager: "owner",
      salesman: "salesman",
      sales_property: "skuLevel",
    };
    const nextKey = keyMap[row.filterKey];
    if (!nextKey) return;
    const next = { ...filterState, [nextKey]: row.filterValue, riskOnly: true };
    setFilterState(next);
    setPage(1);
    loadSummary(next, { page: 1 });
  }

  async function exportData(option = exportOptions[0]) {
    setExporting(option.key);
    setExportMenuOpen(false);
    try {
      const params = buildSummaryParams(filterState, { page });
      params.set("max_rows", "20000");
      params.delete("page");
      params.delete("page_size");
      const response = await apiFetch(`${API_BASE_URL}${option.endpoint}?${params.toString()}`);
      if (!response.ok) throw new Error(`导出失败 ${response.status}`);
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const encodedName = disposition.match(/filename\*=UTF-8''([^;]+)/)?.[1];
      const fallbackName = disposition.match(/filename="?([^";]+)"?/)?.[1];
      const filename = encodedName ? decodeURIComponent(encodedName) : fallbackName || option.filename;
      downloadBlob(blob, filename);
      setMessage(`已导出${option.label}`);
    } catch (err) {
      const rows = [["风险类型", "风险对象", "风险描述", "涉及SKU数", "涉及库存"], ...dashboard.alerts.map((row) => [row.type, row.object, row.desc, row.sku, row.inventory])];
      const csv = rows.map((row) => row.join(",")).join("\n");
      downloadBlob(new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }), "inventory-control-tower-alerts.csv");
      setMessage(`${option.label}导出不可用，已导出当前看板 CSV`);
    } finally {
      setExporting("");
    }
  }

  if (authLoading) {
    return (
      <main className="clone-shell">
        <section className="loading-panel">正在校验飞书登录状态...</section>
      </main>
    );
  }

  if (auth?.auth_required && !auth?.authenticated) {
    return (
      <main className="clone-shell">
        <section className="login-panel">
          <div>
            <span className="strategy-pill">Feishu Auth</span>
            <h1>库存控制塔</h1>
            <p>请使用飞书授权进入控制塔。</p>
          </div>
          <button className="query-button" type="button" onClick={loginWithFeishu}>
            <LogIn size={16} />
            飞书登录
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="clone-shell">
      <header className="clone-header">
        <div className="brand-block">
          <div className="tower-mark" aria-hidden="true">
            <Castle size={30} strokeWidth={2.7} />
          </div>
          <h1>库存控制塔</h1>
          <span className="strategy-pill">{summary ? "实时战略室" : "白底战略室"}</span>
        </div>
        <div className="header-actions">
          <IconButton label={loading ? "刷新中" : "刷新"} icon={RefreshCw} onClick={refresh} disabled={loading} />
          <IconButton label={favorite ? "已收藏" : "收藏"} icon={Star} active={favorite} onClick={() => setFavorite((value) => !value)} />
          <div className="export-menu-wrap">
            <IconButton label={exporting ? "导出中" : "导出"} icon={Upload} onClick={() => setExportMenuOpen((value) => !value)} disabled={Boolean(exporting)} />
            {exportMenuOpen ? (
              <div className="export-menu">
                {exportOptions.map((option) => (
                  <button key={option.key} type="button" onClick={() => exportData(option)}>
                    <FileSpreadsheet size={15} />
                    {option.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <span className="header-divider" />
          <button className="icon-only notification-button" type="button" title="通知" onClick={() => setNotificationsOpen((value) => !value)}>
            <Bell size={19} />
            <span>{Math.min(dashboard.alerts.length || 0, 99)}</span>
          </button>
          <button className="help-button" type="button" onClick={() => setHelpOpen((value) => !value)}>
            <CircleHelp size={17} />
            <span>帮助</span>
          </button>
          <button className="profile-button" type="button" onClick={() => setProfileOpen((value) => !value)}>
            <span>{authInitials(auth)}</span>
            <ChevronDown size={15} />
          </button>
        </div>
        {notificationsOpen ? <Popover title="通知中心" lines={dashboard.alerts.slice(0, 3).map((row) => `${row.type}：${row.object}，${row.sku} 个 SKU`)} /> : null}
        {helpOpen ? <Popover title="字段说明" right lines={dashboard.notes} /> : null}
        {profileOpen ? (
          <div className="floating-popover right offset">
            <strong>PM 工作台</strong>
            <span>{authDisplayName(auth)}</span>
            <span>{auth?.permissions?.role || "member"}</span>
            <span>数据源：{summary?.data_source || "兜底样例"}</span>
            <button type="button" onClick={logout}>
              <LogOut size={14} />
              退出登录
            </button>
          </div>
        ) : null}
      </header>

      <section className="filters-band" aria-label="筛选条件">
        <div className="filters-grid">
          {filterDefs.map((item) => (
            <FilterControl key={item.key} item={item} value={filterState[item.key]} onChange={updateFilter} />
          ))}
          <div className="filter-actions">
            <button className="plain-action" type="button" onClick={resetFilters} disabled={loading}>重置</button>
            <button className="query-button" type="button" onClick={runQuery} disabled={loading}>
              <Search size={16} />
              {loading ? "查询中" : "查询"}
            </button>
            <button className="plain-action expand-action" type="button" onClick={() => setExpanded((value) => !value)}>
              展开
              <ChevronDown size={15} className={expanded ? "rotated" : ""} />
            </button>
          </div>
        </div>
        {expanded ? (
          <div className="extra-filters">
            {extraFilterDefs.map((item) => (
              <FilterControl key={item.key} item={item} value={filterState[item.key]} onChange={updateFilter} compact />
            ))}
            <span className="query-summary">{querySummary}</span>
          </div>
        ) : null}
      </section>

      {(loading || error) ? (
        <div className={`data-banner ${error ? "error" : ""}`}>
          {loading ? "正在载入真实库存控制塔数据..." : error}
        </div>
      ) : null}

      <nav className="tab-row" aria-label="库存控制塔视图">
        {tabs.map((tab) => (
          <button key={tab} className={activeTab === tab ? "active" : ""} type="button" onClick={() => setActiveTab(tab)}>
            {tab}
          </button>
        ))}
      </nav>

      <section className="kpi-strip" aria-label="核心指标">
        {dashboard.kpis.map((item) => (
          <KpiCard key={item.label} item={item} />
        ))}
      </section>

      {activeTab === "风险总览" ? (
        <RiskOverview
          data={dashboard}
          distribution={distribution}
          riskDimension={riskDimension}
          setRiskDimension={setRiskDimension}
          selectedRisk={selectedRisk}
          setSelectedRisk={setSelectedRisk}
          rankDimension={rankDimension}
          setRankDimension={setRankDimension}
          rankRows={rankRows}
          onRiskDrill={drillRiskType}
          onRankDrill={drillRank}
          onStageSelect={(stage) => {
            setActiveWarehouseStage(stage);
            setActiveTab("仓库明细");
          }}
          onView={setDrawerItem}
        />
      ) : (
        <SecondaryView
          tab={activeTab}
          data={dashboard}
          loading={loading}
          page={page}
          activeWarehouseStage={activeWarehouseStage}
          setActiveWarehouseStage={setActiveWarehouseStage}
          onPageChange={changePage}
          onView={setDrawerItem}
          onOpenSku={setSkuWorkbenchItem}
        />
      )}

      <footer className="page-footer">
        <span>数据更新时间： {lastUpdate || dashboard.salesPeriod}</span>
        <span>{summary ? `真实数据 · ${dashboard.salesPeriod}` : "兜底样例数据"}</span>
        <button type="button" onClick={() => setHelpOpen((value) => !value)}>口径说明 <CircleHelp size={14} /></button>
      </footer>

      {message ? (
        <div className="toast" role="status">
          {message}
          <button type="button" onClick={() => setMessage("")}>
            <X size={14} />
          </button>
        </div>
      ) : null}
      {drawerItem ? <DetailDrawer item={drawerItem} onClose={() => setDrawerItem(null)} /> : null}
      {skuWorkbenchItem ? <SkuWorkbench item={skuWorkbenchItem} onClose={() => setSkuWorkbenchItem(null)} /> : null}
    </main>
  );
}

function buildFilterDefs(summary) {
  const options = summary?.filter_options || {};
  const warehouseOptions = uniqueValues((summary?.warehouse_inventory || []).map((row) => row.display_name || row.warehouse_name || row.warehouse_code));
  return [
    { key: "range", label: "时间范围", icon: CalendarDays, options: rangeOptions },
    { key: "compare", label: "对比", options: compareOptions },
    { key: "site", label: "站点", options: withDefault("全部站点", options.store_name) },
    { key: "country", label: "国家/地区", options: withDefault("全部", [...commonCountryOptions, ...(options.country_code || [])]) },
    { key: "type", label: "仓库类型", options: ["全部", "FBA", "海外仓", "本地仓", "预留库存"] },
    { key: "warehouse", label: "仓库", options: withDefault("全部仓库", warehouseOptions) },
    { key: "store", label: "店铺", options: withDefault("全部店铺", options.store_name) },
    { key: "department", label: "部门", options: withDefault("全部", options.sales_department) },
    { key: "owner", label: "负责人", options: withDefault("全部", options.product_manager || options.salesman) },
  ];
}

function buildExtraFilterDefs(summary) {
  const options = summary?.filter_options || {};
  return [
    { key: "materialCode", label: "SKU / MSKU / FNSKU", type: "text", placeholder: "输入 SKU" },
    { key: "shipmentCountry", label: "发货国家", options: withDefault("全部发货国", [...commonCountryOptions, ...(options.shipments_country || [])]) },
    { key: "salesman", label: "销售员", options: withDefault("全部销售员", options.salesman) },
    { key: "risk", label: "风险类型", options: riskFilterOptions.map((item) => item.label) },
    { key: "skuLevel", label: "销售属性", options: withDefault("全部属性", [...salesPropertyOptions, ...(options.sales_property || [])]) },
    { key: "productProperty", label: "产品属性", options: withDefault("全部产品属性", options.product_property) },
    { key: "season", label: "季节属性", options: withDefault("全部季节", options.seasonality) },
    { key: "mskuStatus", label: "MSKU 状态", options: withDefault("全部状态", [...mskuStatusOptions, ...(options.msku_status || [])]) },
    { key: "lifeProcess", label: "生命周期", options: withDefault("全部生命周期", lifeProcessOptions) },
    { key: "riskOnly", label: "只看风险 SKU", type: "checkbox" },
    { key: "positiveDemand", label: "只看有需求", type: "checkbox" },
  ];
}

function buildSummaryParams(filters, options = {}) {
  const params = new URLSearchParams();
  params.set("page", String(options.page || 1));
  params.set("page_size", String(PAGE_SIZE));
  params.set("max_rows", "20000");
  const range = salesRange(filters.range);
  if (range) {
    params.set("sales_start_date", range.start);
    params.set("sales_end_date", range.end);
  }
  if (options.refresh) params.set("refresh", "true");
  appendParam(params, "material_code", String(filters.materialCode || "").trim(), "");
  appendParam(params, "country_code", normalizeCountry(filters.country), "全部");
  appendParam(params, "shipments_country", normalizeCountry(filters.shipmentCountry), "全部发货国");
  appendParam(params, "store_name", filters.site, "全部站点");
  appendParam(params, "store_name", filters.store, "全部店铺");
  appendParam(params, "sales_department", filters.department, "全部");
  appendParam(params, "product_manager", filters.owner, "全部");
  appendParam(params, "salesman", filters.salesman, "全部销售员");
  appendParam(params, "sales_property", filters.skuLevel, "全部属性");
  appendParam(params, "product_property", filters.productProperty, "全部产品属性");
  appendParam(params, "seasonality", filters.season, "全部季节");
  appendParam(params, "msku_status", filters.mskuStatus, "全部状态");
  appendParam(params, "msku_life_process", filters.lifeProcess, "全部生命周期");
  const riskKey = riskFilterOptions.find((item) => item.label === filters.risk)?.value;
  if (riskKey) params.append("risk_type", riskKey);
  if (filters.riskOnly) params.set("risk_only", "true");
  if (filters.positiveDemand) params.set("positive_demand", "true");
  return params;
}

function buildDashboardData(summary) {
  if (!summary) {
    return {
      source: "fallback",
      salesPeriod: "2025-06-09",
      notes: ["当前显示兜底样例数据。", "后端 /control-tower/summary 可用时会自动切换到真实数据。", "筛选查询会传递国家、店铺、部门、负责人、风险类型和日期区间。"],
      kpis: fallbackKpis,
      flowStages: fallbackFlowStages,
      riskTypeDistribution: fallbackRiskTypes,
      countryDistribution: fallbackCountryRiskTypes,
      riskCards: fallbackRiskCards,
      alerts: fallbackAlerts,
      countryRows: fallbackCountryRows,
      storeRows: fallbackStoreRows,
      skuRows: fallbackSkuRows,
      warehouseRows: fallbackWarehouseRows,
      transitRows: fallbackTransitRows,
      replenishRows: fallbackReplenishRows,
      fieldRows: [],
      rawItems: [],
      pagination: { page: 1, total_pages: 1, total_count: fallbackSkuRows.length, page_size: PAGE_SIZE },
    };
  }

  const k = summary.kpis || {};
  const items = Array.isArray(summary.items) ? summary.items : [];
  const dayLabel = `${number(summary.sales_day_count) || 1}天区间`;
  const compareLabel = "实时口径";
  const kpis = [
    { label: "SKU 数", value: formatNumber(k.sku_count), delta: dayLabel, trend: "flat", compareLabel, tone: "blue", icon: Box },
    { label: "总库存", value: formatNumber(k.total_inventory), delta: dayLabel, trend: "flat", compareLabel, tone: "blue", icon: Layers3 },
    { label: "FBA 可售", value: formatNumber(k.fba_sellable), delta: dayLabel, trend: "flat", compareLabel, tone: "green", icon: ShoppingCart },
    { label: "区间销量", value: formatNumber(k.daily_sales_volume), delta: dayLabel, trend: "flat", compareLabel, tone: "purple", icon: TrendingUp },
    { label: "断货风险", value: formatNumber(k.stockout_count), delta: dayLabel, trend: "flat", compareLabel, tone: "orange", icon: TriangleAlert },
    { label: "库销比", value: formatInventorySalesRatio(k.total_inventory, k.demand_30d), delta: dayLabel, trend: "flat", compareLabel, tone: "blue", icon: PieChart },
  ];

  const flowStages = [
    { id: "local", label: "本地 / 供应商仓", value: formatNumber(k.domestic_supply_inventory), delta: dayLabel, trend: "flat" },
    { id: "transit", label: "头库在途", value: formatNumber(k.inbound_total), delta: dayLabel, trend: "flat" },
    { id: "overseas", label: "国外仓可售", value: formatNumber(k.overseas_sellable_inventory), delta: dayLabel, trend: "flat" },
    { id: "transit", label: "在途入仓", value: formatNumber(number(k.afn_inbound_receiving_quantity) + number(k.afn_inbound_working_quantity)), delta: dayLabel, trend: "flat" },
    { id: "planned", label: "预留库存", value: formatNumber(k.planned_quantity), delta: dayLabel, trend: "flat" },
    { id: "overseas", label: "客户可售", value: formatNumber(k.fba_sellable), delta: dayLabel, trend: "flat", active: true },
  ];

  const riskTypeDistribution = distributionFromMap(summary.risk_type_distribution, riskTypeMeta, fallbackRiskTypes);
  const countryDistribution = distributionFromDimensions(summary.risk_dimensions?.country_code, fallbackCountryRiskTypes);
  const riskCards = [
    { label: "高风险 SKU", value: formatNumber(number(k.critical_count) + number(k.high_count)), delta: dayLabel, trend: "flat", compareLabel, tone: "red", icon: ShieldCheck },
    { label: "中风险 SKU", value: formatNumber(k.medium_count), delta: dayLabel, trend: "flat", compareLabel, tone: "orange", icon: AlertTriangle },
    { label: "低风险 SKU", value: formatNumber(k.low_count), delta: dayLabel, trend: "flat", compareLabel, tone: "yellow", icon: AlertTriangle },
    { label: "健康 SKU", value: formatNumber(k.healthy_count), delta: dayLabel, trend: "flat", compareLabel, tone: "green", icon: CheckCircle2 },
  ];

  return {
    source: "api",
    salesPeriod: summary.sales_stat_date || `${summary.sales_start_date || "-"} 至 ${summary.sales_end_date || "-"}`,
    notes: (summary.notes || []).slice(0, 3),
    kpis,
    flowStages,
    riskTypeDistribution,
    countryDistribution,
    riskCards,
    alerts: buildAlerts(items),
    countryRows: rankingRows(summary.risk_dimensions?.country_code, fallbackCountryRows, "country_code"),
    storeRows: rankingRows(summary.risk_dimensions?.store_name, fallbackStoreRows, "store_name"),
    skuRows: buildSkuRows(items),
    warehouseRows: buildWarehouseRows(summary.warehouse_inventory),
    transitRows: buildTransitRows(items),
    replenishRows: buildReplenishRows(items),
    fieldRows: buildFieldRows(summary.field_decisions, summary.notes),
    rawItems: items,
    pagination: summary.pagination || { page: 1, total_pages: 1, total_count: items.length, page_size: PAGE_SIZE },
  };
}

function IconButton({ label, icon: Icon, active, disabled, onClick }) {
  return (
    <button className={`header-button ${active ? "active" : ""}`} type="button" onClick={onClick} disabled={disabled}>
      <Icon size={17} />
      <span>{label}</span>
    </button>
  );
}

function Popover({ title, lines, right, offset }) {
  return (
    <div className={`floating-popover ${right ? "right" : ""} ${offset ? "offset" : ""}`}>
      <strong>{title}</strong>
      {(lines.length ? lines : ["暂无提醒"]).map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  );
}

function FilterControl({ item, value, onChange, compact }) {
  const Icon = item.icon;
  const options = item.options || [];
  if (item.type === "checkbox") {
    return (
      <label className={`filter-select checkbox-filter ${compact ? "compact" : ""}`}>
        <span>{item.label}</span>
        <div>
          <input
            type="checkbox"
            checked={Boolean(value)}
            onChange={(event) => onChange(item.key, event.target.checked)}
          />
          <strong>{value ? "已开启" : "未开启"}</strong>
        </div>
      </label>
    );
  }
  if (item.type === "text") {
    return (
      <label className={`filter-select text-filter ${compact ? "compact" : ""}`}>
        <span>{item.label}</span>
        <div>
          {Icon ? <Icon size={16} /> : <PackageSearch size={16} />}
          <input
            value={value || ""}
            placeholder={item.placeholder || "请输入"}
            onChange={(event) => onChange(item.key, event.target.value)}
          />
        </div>
      </label>
    );
  }
  return (
    <label className={`filter-select ${compact ? "compact" : ""}`}>
      <span>{item.label}</span>
      <div>
        {Icon ? <Icon size={16} /> : null}
        <select value={value} onChange={(event) => onChange(item.key, event.target.value)}>
          {options.map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
        <ChevronDown size={14} aria-hidden="true" />
      </div>
    </label>
  );
}

function KpiCard({ item }) {
  const Icon = item.icon;
  const deltaTone = item.trend === "up" ? "bad" : "good";
  const trendText = item.trend === "up" ? "上升" : item.trend === "down" ? "下降" : "";
  return (
    <article className="kpi-card">
      <div className={`kpi-icon tone-${item.tone}`}>
        <Icon size={31} strokeWidth={2.1} />
      </div>
      <div className="kpi-copy">
        <span>{item.label}</span>
        <strong>{item.value ?? "-"}</strong>
        <small>
          {item.compareLabel || "较前30天"}
          <em className={deltaTone}>{trendText ? `${trendText} ${item.delta}` : item.delta}</em>
        </small>
      </div>
    </article>
  );
}

function RiskOverview({
  data,
  distribution,
  riskDimension,
  setRiskDimension,
  selectedRisk,
  setSelectedRisk,
  rankDimension,
  setRankDimension,
  rankRows,
  onRiskDrill,
  onRankDrill,
  onStageSelect,
  onView,
}) {
  return (
    <section className="overview-grid">
      <div className="left-stack">
        <Panel
          title="库存流转全景"
          meta={<><span>单位：件</span><button type="button" onClick={() => onView({ type: "库存流转全景", object: "全链路库存", desc: "按当前筛选条件汇总", inventory: data.flowStages.map((item) => `${item.label}:${item.value}`).join(" / ") })}>查看明细</button></>}
        >
          <div className="flow-row">
            {data.flowStages.map((stage, index) => (
              <FlowStage key={stage.label} stage={stage} showArrow={index < data.flowStages.length - 1} onSelect={onStageSelect} />
            ))}
          </div>
        </Panel>

        <Panel title="风险概览">
          <div className="risk-card-grid">
            {data.riskCards.map((card) => (
              <RiskMiniCard key={card.label} item={card} />
            ))}
          </div>
          <div className="table-title">高风险预警（Top 5）</div>
          <WarningTable alerts={data.alerts} onView={onView} />
        </Panel>
      </div>

      <div className="right-stack">
        <Panel
          title="风险分布"
          meta={
            <label className="inline-select">
              <span>切换维度</span>
              <select value={riskDimension} onChange={(event) => setRiskDimension(event.target.value)}>
                <option>风险类型</option>
                <option>国家/地区</option>
              </select>
            </label>
          }
        >
          <div className="donut-layout">
            <DonutChart items={distribution} selectedRisk={selectedRisk} />
            <div className="donut-legend">
              {distribution.map((item) => (
                <button
                  key={item.label}
                  className={selectedRisk === item.label ? "active" : ""}
                  type="button"
                  onClick={() => {
                    setSelectedRisk((current) => (current === item.label ? "" : item.label));
                    onRiskDrill?.(item.label);
                  }}
                >
                  <i style={{ backgroundColor: item.color }} />
                  <span>{item.label}</span>
                  <strong>{formatNumber(item.value)}</strong>
                  <em>({item.pct})</em>
                </button>
              ))}
            </div>
          </div>
        </Panel>

        <Panel
          title="维度风险排行"
          meta={
            <label className="inline-select">
              <span>维度</span>
              <select value={rankDimension} onChange={(event) => setRankDimension(event.target.value)}>
                <option>国家风险</option>
                <option>店铺风险</option>
              </select>
            </label>
          }
        >
          <RankingTable rows={rankRows} onView={onView} onDrill={onRankDrill} />
        </Panel>
      </div>
    </section>
  );
}

function Panel({ title, meta, children }) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        <CircleHelp size={15} />
        {meta ? <div className="panel-meta">{meta}</div> : null}
      </div>
      {children}
    </section>
  );
}

function FlowStage({ stage, showArrow, onSelect }) {
  return (
    <div className="flow-stage-wrap">
      <article className={`flow-stage ${stage.active ? "active" : ""}`} onClick={() => onSelect?.(stage.id || stage.label)}>
        <span>{stage.label}</span>
        <strong>{stage.value}</strong>
        <small>
          {stage.compareLabel || "实时口径"}
          <em className={stage.trend === "up" ? "bad" : "good"}>{stage.trend === "up" ? "上升" : stage.trend === "down" ? "下降" : ""} {stage.delta}</em>
        </small>
      </article>
      {showArrow ? <ChevronRight className="flow-arrow" size={22} /> : null}
    </div>
  );
}

function RiskMiniCard({ item }) {
  const Icon = item.icon;
  return (
    <article className="risk-mini-card">
      <Icon className={`mini-icon tone-${item.tone}`} size={38} strokeWidth={2} />
      <div>
        <span>{item.label}</span>
        <strong>{item.value}</strong>
        <small>
          {item.compareLabel || "较前30天"}
          <em className={item.trend === "up" ? "bad" : "good"}>{item.trend === "up" ? "上升" : item.trend === "down" ? "下降" : ""} {item.delta}</em>
        </small>
      </div>
    </article>
  );
}

function DonutChart({ items, selectedRisk }) {
  const total = items.reduce((sum, item) => sum + number(item.value), 0);
  let start = 0;
  const gradient = (total ? items : fallbackRiskTypes).map((item) => {
    const end = start + (number(item.value) / Math.max(total, 1)) * 100;
    const segment = `${item.color} ${start}% ${end}%`;
    start = end;
    return segment;
  }).join(", ");
  const selected = items.find((item) => item.label === selectedRisk);

  return (
    <div className="donut-chart" style={{ "--donut": `conic-gradient(${gradient})` }}>
      <div className="donut-hole">
        <span>{selectedRisk || "风险 SKU 数"}</span>
        <strong>{formatNumber(selected ? selected.value : total)}</strong>
        <small>{selected ? selected.pct : "100%"}</small>
      </div>
    </div>
  );
}

function WarningTable({ alerts, onView }) {
  return (
    <div className="table-shell warning-table">
      <table>
        <thead>
          <tr>
            <th>风险类型</th>
            <th>风险对象</th>
            <th>风险描述</th>
            <th>涉及 SKU 数</th>
            <th>涉及库存</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((row) => (
            <tr key={`${row.type}-${row.object}`}>
              <td><span className={`dot ${row.tone}`} />{row.type}</td>
              <td>{row.object}</td>
              <td>{row.desc}</td>
              <td className="num">{row.sku}</td>
              <td className="num">{row.inventory}</td>
              <td><button type="button" onClick={() => onView(row)}>查看</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="all-link" type="button">
        查看全部预警
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

function RankingTable({ rows, onView, onDrill }) {
  return (
    <div className="table-shell rank-table">
      <table>
        <thead>
          <tr>
            <th>排名</th>
            <th>维度值</th>
            <th>高风险 SKU 数</th>
            <th>风险 SKU 数</th>
            <th>风险占比</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.name}>
              <td>{index + 1}</td>
              <td>{row.name}</td>
              <td className="num">{row.high}</td>
              <td className="num">{row.risk}</td>
              <td>
                <div className="rank-share">
                  <span>{row.share}</span>
                  <i><b style={{ width: `${row.width}%` }} /></i>
                </div>
              </td>
              <td><button type="button" onClick={() => onDrill ? onDrill(row) : onView({ type: "维度风险", object: row.name, desc: `${row.name} 风险占比 ${row.share}`, sku: row.high, inventory: row.risk })}>查看</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="all-link" type="button">
        查看全部排行
        <ChevronRight size={16} />
      </button>
    </div>
  );
}

function SecondaryView({ tab, data, loading, page, activeWarehouseStage, setActiveWarehouseStage, onPageChange, onView, onOpenSku }) {
  if (tab === "SKU 明细") {
    return (
      <DataView
        title="SKU 风险明细"
        rows={data.skuRows}
        columns={["sku", "site", "risk", "inventory", "sales", "owner", "action"]}
        headers={["SKU", "站点", "风险类型", "总库存", "区间销量", "负责人", "建议动作"]}
        pagination={data.pagination}
        loading={loading}
        page={page}
        onPageChange={onPageChange}
        onView={onView}
        onOpenSku={onOpenSku}
      />
    );
  }
  if (tab === "仓库明细") {
    const stageRows = filterWarehouseStageRows(data.warehouseRows, activeWarehouseStage);
    return (
      <section className="secondary-view">
        <WarehouseStageTabs active={activeWarehouseStage} onChange={setActiveWarehouseStage} />
        <DataView title="仓库库存明细" rows={stageRows} columns={["warehouse", "type", "available", "transit", "reserved", "risk", "owner"]} headers={["仓库", "国家", "可用库存", "在途", "锁定", "可用率", "仓库编码"]} onView={onView} />
      </section>
    );
  }
  if (tab === "头程在途") {
    return <DataView title="头程在途明细" rows={data.transitRows} columns={["batch", "route", "eta", "sku", "qty", "status"]} headers={["SKU/批次", "线路", "预计窗口", "SKU 数", "数量", "状态"]} onView={onView} />;
  }
  if (tab === "补货建议") {
    return <DataView title="补货建议队列" rows={data.replenishRows} columns={["sku", "site", "suggestion", "reason", "priority"]} headers={["SKU", "站点", "建议", "原因", "优先级"]} onView={onView} />;
  }
  if (tab === "异常监控") {
    return <DataView title="异常监控" rows={data.alerts} columns={["type", "object", "desc", "sku", "inventory"]} headers={["异常类型", "对象", "描述", "SKU 数", "库存"]} onView={onView} />;
  }
  return <MethodView rows={data.fieldRows} />;
}

function DataView({ title, rows, columns, headers, pagination, loading, onPageChange, onView, onOpenSku }) {
  const currentPage = pagination?.page || 1;
  const totalPages = pagination?.total_pages || 1;
  const totalCount = pagination?.total_count ?? rows.length;
  return (
    <section className={title === "仓库库存明细" ? "" : "secondary-view"}>
      <Panel
        title={title}
        meta={
          <div className="table-meta-actions">
            {pagination ? <span>共 {formatNumber(totalCount)} 条 · 第 {formatNumber(currentPage)} / {formatNumber(totalPages)} 页</span> : null}
            <button type="button" onClick={() => onView({ type: title, object: "全部", desc: "当前页明细口径", sku: rows.length, inventory: "已汇总" })}>批量查看</button>
          </div>
        }
      >
        <div className="table-shell wide-table">
          <table>
            <thead>
              <tr>
                {headers.map((header) => <th key={header}>{header}</th>)}
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.length ? rows.map((row, index) => (
                <tr key={`${title}-${index}`}>
                  {columns.map((column) => <td key={column}>{row[column] ?? "-"}</td>)}
                  <td>
                    {row.raw && onOpenSku ? (
                      <button type="button" onClick={() => onOpenSku(row.raw)}>详情</button>
                    ) : (
                      <button type="button" onClick={() => onView({ type: title, object: row[columns[0]], desc: row.reason || row.desc || row.action || row.status, sku: row.sku || index + 1, inventory: row.inventory || row.qty || row.available || "-" })}>查看</button>
                    )}
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={headers.length + 1} className="empty-cell">当前筛选下暂无明细</td></tr>
              )}
            </tbody>
          </table>
        </div>
        {pagination ? (
          <div className="pager-row">
            <button type="button" disabled={loading || currentPage <= 1} onClick={() => onPageChange(currentPage - 1)}>上一页</button>
            <span>{formatNumber(currentPage)} / {formatNumber(totalPages)}</span>
            <button type="button" disabled={loading || currentPage >= totalPages} onClick={() => onPageChange(currentPage + 1)}>下一页</button>
          </div>
        ) : null}
      </Panel>
    </section>
  );
}

function WarehouseStageTabs({ active, onChange }) {
  const stages = [
    { id: "local", label: "本地/供应商仓", icon: Database },
    { id: "transit", label: "头库在途", icon: Truck },
    { id: "overseas", label: "海外/FBA", icon: Layers3 },
    { id: "planned", label: "预留库存", icon: ClipboardList },
  ];
  return (
    <div className="warehouse-stage-row">
      {stages.map((stage) => {
        const Icon = stage.icon;
        return (
          <button key={stage.id} className={active === stage.id ? "active" : ""} type="button" onClick={() => onChange(stage.id)}>
            <Icon size={16} />
            {stage.label}
          </button>
        );
      })}
    </div>
  );
}

function MethodView({ rows }) {
  const methods = rows.length ? rows : [
    { title: "断货风险", desc: "近 7 天预计可售库存低于预测销量，按 SKU、站点、仓库聚合。" },
    { title: "库销比", desc: "总库存 / 近 30 天销量，超过 6x 进入高风险观察。" },
    { title: "滞销风险", desc: "30 天销量为 0 或销量显著低于安全阈值。" },
    { title: "到货延迟", desc: "头程预计到仓日期晚于安全到货窗口 7 天以上。" },
  ];
  return (
    <section className="method-grid">
      {methods.slice(0, 8).map((item) => (
        <article key={item.title}>
          <ClipboardList size={28} />
          <h3>{item.title}</h3>
          <p>{item.desc}</p>
        </article>
      ))}
    </section>
  );
}

function DetailDrawer({ item, onClose }) {
  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="detail-drawer" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span>风险详情</span>
            <h2>{item.type || item.risk || "维度风险"}</h2>
          </div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </header>
        <dl>
          <div><dt>对象</dt><dd>{item.object || item.name || item.sku || item.batch || item.warehouse || "-"}</dd></div>
          <div><dt>描述</dt><dd>{item.desc || item.reason || item.status || item.action || "按当前维度聚合后的风险明细"}</dd></div>
          <div><dt>涉及 SKU</dt><dd>{item.sku || "-"}</dd></div>
          <div><dt>涉及库存</dt><dd>{item.inventory || item.qty || item.available || "-"}</dd></div>
        </dl>
        <button className="drawer-primary" type="button" onClick={onClose}>
          <Eye size={16} />
          已查看，返回看板
        </button>
      </aside>
    </div>
  );
}

function SkuWorkbench({ item, onClose }) {
  const [activeTab, setActiveTab] = useState("detail");
  const [forecastReview, setForecastReview] = useState(null);
  const [firstLeg, setFirstLeg] = useState(null);
  const [shippingCost, setShippingCost] = useState(null);
  const [diagnosis, setDiagnosis] = useState(null);
  const [contextLoading, setContextLoading] = useState(true);
  const [diagnosisLoading, setDiagnosisLoading] = useState(false);
  const [chatSending, setChatSending] = useState(false);
  const [contextError, setContextError] = useState("");
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState([
    { role: "assistant", text: `已载入 ${item.material_code || item.msku || item.fnsku || "SKU"} 的库存上下文，可以问断货原因、冗余依据、补货建议或生成全链路诊断。` },
  ]);
  const [recordInput, setRecordInput] = useState("");
  const [records, setRecords] = useState([{ time: "当前", title: "Agent 识别风险", content: item.warning_type || riskTypeMeta[riskKeyForItem(item)]?.label || "正常" }]);

  useEffect(() => {
    let cancelled = false;
    setActiveTab("detail");
    setContextLoading(true);
    setContextError("");
    setForecastReview(null);
    setFirstLeg(null);
    setShippingCost(null);
    setDiagnosis(null);
    Promise.allSettled([
      fetchMonthlyForecastReview(item),
      fetchFirstLegShipments(item),
      fetchSkuShippingCost(item),
    ]).then((results) => {
      if (cancelled) return;
      if (results[0].status === "fulfilled") setForecastReview(results[0].value);
      if (results[1].status === "fulfilled") setFirstLeg(results[1].value);
      if (results[2].status === "fulfilled") setShippingCost(results[2].value);
      const failures = results.filter((result) => result.status === "rejected").map((result) => result.reason?.message || "上下文读取失败");
      setContextError(failures.join("；"));
    }).finally(() => {
      if (!cancelled) setContextLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, [item.material_code, item.msku, item.fnsku, item.asin, item.store_name, item.country_code]);

  async function runDiagnosis(question = "生成 SKU 全链路诊断") {
    setDiagnosisLoading(true);
    try {
      const payload = await fetchSkuDiagnosis(item, question, forecastReview, firstLeg?.shipments || []);
      setDiagnosis(payload);
      setActiveTab("diagnosis");
      return payload;
    } finally {
      setDiagnosisLoading(false);
    }
  }

  async function sendChat() {
    const text = chatInput.trim();
    if (!text || chatSending) return;
    setChatMessages((messages) => [...messages, { role: "user", text }]);
    setChatInput("");
    setChatSending(true);
    try {
      let reply = "";
      if (/全链路|诊断|库存情况|售卖情况|补救|断货原因|冗余/.test(text)) {
        const payload = await runDiagnosis(text);
        reply = formatSkuDiagnosisReply(payload);
      } else {
        reply = await askSkuAssistant(item, text, forecastReview, firstLeg?.shipments || []);
      }
      setChatMessages((messages) => [...messages, { role: "assistant", text: reply }]);
    } catch (err) {
      setChatMessages((messages) => [...messages, { role: "assistant", text: localSkuReply(item, text, err) }]);
    } finally {
      setChatSending(false);
    }
  }

  function addRecord() {
    const text = recordInput.trim();
    if (!text) return;
    setRecords((current) => [{ time: new Date().toLocaleString("zh-CN", { hour12: false }), title: "人工备注", content: text }, ...current]);
    setRecordInput("");
  }

  return (
    <div className="drawer-backdrop" onMouseDown={onClose}>
      <aside className="detail-drawer sku-workbench" onMouseDown={(event) => event.stopPropagation()}>
        <header>
          <div>
            <span>FNSKU 工作台</span>
            <h2>{item.material_code || item.msku || item.fnsku || "-"}</h2>
            <p>{[item.store_name, item.country_code, item.fnsku].filter(Boolean).join(" / ") || item.sku_name || "-"}</p>
          </div>
          <button type="button" onClick={onClose}><X size={18} /></button>
        </header>
        <div className="drawer-tabs">
          {[
            ["detail", "详情", PackageSearch],
            ["diagnosis", "诊断", Bot],
            ["ai", "AI 对话", MessageSquare],
            ["records", "处理记录", ClipboardList],
          ].map(([key, label, Icon]) => (
            <button key={key} type="button" className={activeTab === key ? "active" : ""} onClick={() => setActiveTab(key)}>
              <Icon size={15} />
              {label}
            </button>
          ))}
        </div>
        <div className="sku-workbench-body">
          {contextLoading ? <p className="sku-status"><Loader2 size={15} /> 正在读取预测复盘、头程和运费上下文...</p> : null}
          {contextError ? <p className="sku-status error">{contextError}</p> : null}
          {activeTab === "detail" ? (
            <SkuDetailTab item={item} forecastReview={forecastReview} firstLeg={firstLeg} shippingCost={shippingCost} />
          ) : null}
          {activeTab === "diagnosis" ? (
            <SkuDiagnosisTab diagnosis={diagnosis} loading={diagnosisLoading} onRun={() => runDiagnosis()} />
          ) : null}
          {activeTab === "ai" ? (
            <SkuChatTab messages={chatMessages} input={chatInput} sending={chatSending} onInput={setChatInput} onSend={sendChat} />
          ) : null}
          {activeTab === "records" ? (
            <SkuRecordsTab records={records} input={recordInput} onInput={setRecordInput} onAdd={addRecord} />
          ) : null}
        </div>
      </aside>
    </div>
  );
}

function SkuDetailTab({ item, forecastReview, firstLeg, shippingCost }) {
  const estimate = shippingCost?.shipping_cost_estimate || shippingCost;
  const shipments = Array.isArray(firstLeg?.shipments) ? firstLeg.shipments : [];
  return (
    <>
      <div className="detail-kpi-grid">
        <MetricTile label="风险等级" value={riskLevelLabel[item.risk_level] || item.risk_level || "-"} tone={item.risk_level === "critical" || item.risk_level === "high" ? "red" : "blue"} />
        <MetricTile label="总库存" value={formatNumber(item.total_inventory)} />
        <MetricTile label="FBA 可售" value={formatNumber(item.fba_sellable)} />
        <MetricTile label="区间销量" value={formatNumber(item.daily_sales_volume)} />
      </div>
      <DetailBlock title="基础信息" rows={[
        ["SKU", item.material_code],
        ["MSKU", item.msku],
        ["FNSKU", item.fnsku],
        ["ASIN", item.asin],
        ["店铺/国家", [item.store_name, item.country_code, item.shipments_country].filter(Boolean).join(" / ")],
        ["销售部门", item.sales_department],
        ["销售员", item.salesman],
        ["产品经理", item.product_manager],
        ["销售属性", item.sales_property],
        ["产品属性", item.product_property],
        ["季节属性", item.seasonality],
        ["MSKU 状态", item.msku_status],
      ]} />
      <DetailBlock title="风险判断" rows={[
        ["风险类型", item.warning_type || riskTypeMeta[riskKeyForItem(item)]?.label],
        ["断货等级", riskLevelLabel[item.stockout_risk_level] || item.stockout_risk_level],
        ["冗余等级", riskLevelLabel[item.overstock_risk_level] || item.overstock_risk_level],
        ["断货提示", item.stockout_warning],
        ["冗余提示", item.overstock_warning],
        ["建议动作", item.suggested_action],
      ]} />
      <DetailBlock title="库存与需求" rows={[
        ["FBA 库存", formatNumber(item.fba_inventory)],
        ["海外仓", formatNumber(item.overseas_inventory)],
        ["本地仓", formatNumber(item.local_inventory)],
        ["在途合计", formatNumber(item.inbound_total)],
        ["30天需求", formatNumber(item.demand_30d)],
        ["预计7天", formatNumber(item.projected_7d)],
        ["FBA 覆盖", item.sellable_days ? `${formatNumber(item.sellable_days)} 天` : "-"],
        ["长库龄", formatNumber(item.long_age_inventory)],
      ]} />
      <DetailBlock title="月度预测复盘" rows={[
        ["结果", forecastReview?.result_label],
        ["预测月份", forecastReview?.target_month],
        ["预测量", formatNumber(forecastReview?.forecast_quantity)],
        ["实际销量", formatNumber(forecastReview?.actual_sales)],
        ["差异", formatSignedNumber(forecastReview?.difference)],
        ["差异比例", formatPercent(forecastReview?.variance_percent)],
      ]} />
      <DetailBlock title="头程批次" rows={[
        ["批次数", formatNumber(firstLeg?.row_count ?? shipments.length)],
        ["查询口径", firstLeg?.query?.latest_only ? "最新批次" : "全部批次"],
        ["最近批次", shipments[0]?.ship_id || shipments[0]?.batch_no || shipments[0]?.shipment_id],
        ["最近状态", shipments[0]?.status || shipments[0]?.shipment_status],
      ]} />
      <DetailBlock title="补货成本" rows={[
        ["估算状态", estimate?.status || shippingCost?.status],
        ["推荐渠道", estimate?.recommended_channel || estimate?.channel],
        ["单件成本", formatMoney(estimate?.unit_shipping_cost_cny)],
        ["备注", estimate?.recommendation || estimate?.summary],
      ]} />
    </>
  );
}

function SkuDiagnosisTab({ diagnosis, loading, onRun }) {
  return (
    <div className="diagnosis-panel">
      <button className="drawer-primary" type="button" onClick={onRun} disabled={loading}>
        {loading ? <Loader2 size={16} /> : <Bot size={16} />}
        {loading ? "诊断中" : "生成 SKU 全链路诊断"}
      </button>
      {diagnosis ? (
        <div className="diagnosis-result">
          <h3>{diagnosis.overall_status || diagnosis.summary || "SKU 全链路诊断"}</h3>
          <p>{formatSkuDiagnosisReply(diagnosis)}</p>
        </div>
      ) : (
        <p className="empty-detail">点击按钮后会调用旧控制塔的 `/control-tower/sku-diagnosis/analyze`。</p>
      )}
    </div>
  );
}

function SkuChatTab({ messages, input, sending, onInput, onSend }) {
  return (
    <div className="chat-panel">
      <div className="chat-messages">
        {messages.map((message, index) => (
          <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}>
            <span>{message.role === "user" ? "你" : "AI"}</span>
            <p>{message.text}</p>
          </div>
        ))}
      </div>
      <div className="chat-input-row">
        <input value={input} placeholder="问断货原因、冗余依据、补货建议..." onChange={(event) => onInput(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") onSend(); }} />
        <button type="button" onClick={onSend} disabled={sending}>
          {sending ? <Loader2 size={15} /> : <Send size={15} />}
        </button>
      </div>
    </div>
  );
}

function SkuRecordsTab({ records, input, onInput, onAdd }) {
  return (
    <div className="records-panel">
      <div className="record-input-row">
        <input value={input} placeholder="记录处理结论、责任人或下一步动作" onChange={(event) => onInput(event.target.value)} />
        <button type="button" onClick={onAdd}>添加</button>
      </div>
      {records.map((record, index) => (
        <article key={`${record.time}-${index}`}>
          <span>{record.time}</span>
          <strong>{record.title}</strong>
          <p>{record.content}</p>
        </article>
      ))}
    </div>
  );
}

function MetricTile({ label, value, tone = "blue" }) {
  return (
    <article className={`metric-tile ${tone}`}>
      <span>{label}</span>
      <strong>{value || "-"}</strong>
    </article>
  );
}

function DetailBlock({ title, rows }) {
  return (
    <section className="detail-block">
      <h3>{title}</h3>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value === null || value === undefined || value === "" ? "-" : value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function buildAlerts(items) {
  const groups = new Map();
  items.forEach((item) => {
    const key = `${riskKeyForItem(item)}|${item.country_code || item.store_name || "全部"}`;
    const riskKey = riskKeyForItem(item);
    const meta = riskTypeMeta[riskKey] || riskTypeMeta.normal;
    const current = groups.get(key) || {
      type: meta.label,
      object: item.country_code || item.store_name || "-",
      desc: item.stockout_warning || item.overstock_warning || item.warning_type || item.suggested_action || `${riskLevelLabel[item.risk_level] || "风险"} SKU`,
      sku: 0,
      inventoryValue: 0,
      tone: item.risk_level === "critical" || item.risk_level === "high" ? "red" : meta.tone,
    };
    current.sku += 1;
    current.inventoryValue += number(item.total_inventory);
    groups.set(key, current);
  });
  const rows = Array.from(groups.values())
    .sort((a, b) => b.sku - a.sku || b.inventoryValue - a.inventoryValue)
    .slice(0, 5)
    .map((row) => ({ ...row, inventory: formatNumber(row.inventoryValue) }));
  return rows.length ? rows : fallbackAlerts;
}

function buildSkuRows(items) {
  const rows = items.slice(0, 20).map((item) => ({
    sku: item.material_code || item.msku || item.fnsku || "-",
    site: [item.country_code, item.store_name].filter(Boolean).join(" / ") || "-",
    risk: item.warning_type || riskTypeMeta[riskKeyForItem(item)]?.label || "-",
    inventory: formatNumber(item.total_inventory),
    sales: formatNumber(item.daily_sales_volume || item.demand_30d),
    owner: item.product_manager || item.salesman || "-",
    action: item.suggested_action || item.stockout_warning || item.overstock_warning || "-",
    raw: item,
  }));
  return rows.length ? rows : fallbackSkuRows;
}

function buildWarehouseRows(rows = []) {
  const mapped = rows.slice(0, 20).map((row) => ({
    warehouse: row.display_name || row.warehouse_name || row.warehouse_code || "-",
    type: row.country_code || row.country_name || "-",
    available: formatNumber(row.product_valid_num),
    transit: formatNumber(row.product_onway),
    reserved: formatNumber(row.product_lock_num),
    risk: formatPartPercent(row.product_valid_num, row.product_total),
    owner: row.warehouse_code || "-",
    stage: warehouseStageForRow(row),
  }));
  return mapped.length ? mapped : fallbackWarehouseRows;
}

function buildTransitRows(items) {
  const rows = items
    .filter((item) => number(item.inbound_total) > 0)
    .slice(0, 12)
    .map((item) => ({
      batch: item.material_code || item.msku || item.fnsku || "-",
      route: [item.shipments_country, item.country_code].filter(Boolean).join(" -> ") || "-",
      eta: item.stockout_warning || "按头程在途汇总",
      sku: 1,
      qty: formatNumber(item.inbound_total),
      status: item.suggested_action || item.warning_type || "-",
      raw: item,
    }));
  return rows.length ? rows : fallbackTransitRows;
}

function buildReplenishRows(items) {
  const rows = items
    .filter((item) => item.suggested_action || item.stockout_warning || item.overstock_warning)
    .slice(0, 12)
    .map((item) => ({
      sku: item.material_code || item.msku || item.fnsku || "-",
      site: [item.country_code, item.store_name].filter(Boolean).join(" / ") || "-",
      suggestion: item.suggested_action || item.stockout_warning || item.overstock_warning || "-",
      reason: item.warning_type || riskTypeMeta[riskKeyForItem(item)]?.label || "-",
      priority: riskLevelLabel[item.risk_level] || item.risk_level || "-",
    }));
  return rows.length ? rows : fallbackReplenishRows;
}

function warehouseStageForRow(row = {}) {
  const text = [row.display_name, row.warehouse_name, row.warehouse_code, row.country_name, row.country_code].filter(Boolean).join(" ").toLowerCase();
  if (number(row.product_onway) > 0) return "transit";
  if (/fba|amazon|海外|oversea|us|uk|jp|de|ca|fr/.test(text)) return "overseas";
  if (/计划|预留|planned|reserve/.test(text)) return "planned";
  return "local";
}

function filterWarehouseStageRows(rows = [], stage = "local") {
  const filtered = rows.filter((row) => row.stage === stage);
  return filtered.length ? filtered : rows;
}

function buildFieldRows(fields = [], notes = []) {
  const fieldRows = fields.slice(0, 8).map((field) => ({
    title: field.label || field.field || "字段口径",
    desc: field.decision || field.description || field.source || field.field || "-",
  }));
  if (fieldRows.length) return fieldRows;
  return notes.map((note, index) => ({ title: `口径 ${index + 1}`, desc: note }));
}

function distributionFromMap(map = {}, metaMap = {}, fallback = []) {
  const entries = Object.entries(map || {})
    .filter(([, value]) => number(value) > 0)
    .map(([key, value], index) => {
      const meta = metaMap[key] || {};
      return {
        label: meta.label || key,
        value: number(value),
        color: meta.color || fallback[index % fallback.length]?.color || "#5e8cff",
      };
    });
  return withPercent(entries.length ? entries : fallback);
}

function distributionFromDimensions(rows = [], fallback = []) {
  const palette = ["#2368e8", "#4d8fff", "#65a6ff", "#31bec8", "#ffc32a", "#ff8b21"];
  const entries = (rows || [])
    .filter((row) => number(row.risk_count) > 0)
    .slice(0, 6)
    .map((row, index) => ({
      label: row.label || row.key || "-",
      value: number(row.risk_count),
      color: palette[index % palette.length],
    }));
  return withPercent(entries.length ? entries : fallback);
}

function rankingRows(rows = [], fallback = [], filterKey = "") {
  const source = (rows || []).filter((row) => number(row.risk_count) > 0).slice(0, 5);
  if (!source.length) return fallback;
  const maxRate = Math.max(...source.map((row) => number(row.risk_rate)), 0.01);
  return source.map((row) => ({
    name: row.label || row.key || "-",
    filterKey,
    filterValue: row.key || row.label || "",
    high: formatNumber(number(row.critical_count) + number(row.high_count)),
    risk: formatNumber(row.risk_count),
    share: formatRatioPercent(row.risk_rate, 1),
    width: Math.max(10, Math.min(100, (number(row.risk_rate) / maxRate) * 100)),
  }));
}

function riskKeyForItem(item) {
  if (isActiveRisk(item.stockout_risk_level)) return "stockout";
  if (isActiveRisk(item.overstock_risk_level)) return "overstock";
  return item.risk_type || "normal";
}

function isActiveRisk(level) {
  return Boolean(level && !["normal", "none", ""].includes(String(level).toLowerCase()));
}

function withPercent(entries) {
  const total = entries.reduce((sum, item) => sum + number(item.value), 0);
  return entries.map((item) => ({
    ...item,
    pct: total > 0 ? `${((number(item.value) / total) * 100).toFixed(1)}%` : "0.0%",
  }));
}

function withDefault(label, values = []) {
  return [label, ...uniqueValues(values).filter((item) => item !== label)];
}

function uniqueValues(values = []) {
  return Array.from(new Set((values || []).filter((item) => item !== null && item !== undefined && String(item).trim() !== "").map(String)));
}

function fieldLabel(key, defs) {
  return defs.find((item) => item.key === key)?.label || key;
}

function checkboxLabel(value) {
  return typeof value === "boolean" ? (value ? "已开启" : "未开启") : value;
}

function authDisplayName(auth) {
  const user = auth?.user || {};
  return user.name || user.en_name || user.email || user.open_id || "PM";
}

function authInitials(auth) {
  const name = authDisplayName(auth);
  const letters = String(name || "PM").match(/[A-Za-z0-9]/g);
  if (letters?.length) return letters.slice(0, 2).join("").toUpperCase();
  return String(name || "PM").slice(0, 2).toUpperCase();
}

function appendParam(params, key, value, defaultValue) {
  if (!value || value === defaultValue) return;
  params.append(key, value);
}

function normalizeCountry(value) {
  if (!value || value === "全部") return "";
  return countryNameMap[value] || value;
}

function salesRange(option) {
  const today = new Date();
  const end = new Date(today);
  end.setDate(today.getDate() - 1);
  if (option === "昨日") return { start: formatIsoDate(end), end: formatIsoDate(end) };
  if (option === "近7天") return rangeByDays(end, 7);
  if (option === "本月") {
    const start = new Date(end.getFullYear(), end.getMonth(), 1);
    return { start: formatIsoDate(start), end: formatIsoDate(end) };
  }
  return rangeByDays(end, 30);
}

function rangeByDays(end, days) {
  const start = new Date(end);
  start.setDate(end.getDate() - Math.max(days - 1, 0));
  return { start: formatIsoDate(start), end: formatIsoDate(end) };
}

function formatIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function formatNumber(value, digits = 0) {
  const n = number(value);
  if (!Number.isFinite(n)) return "-";
  return nf.format(Number(n.toFixed(digits)));
}

function number(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function formatRatioPercent(value, digits = 1) {
  return `${(number(value) * 100).toFixed(digits)}%`;
}

function formatPartPercent(numerator, denominator) {
  const denominatorValue = number(denominator);
  if (denominatorValue <= 0) return "0.0%";
  return `${((number(numerator) / denominatorValue) * 100).toFixed(1)}%`;
}

function formatInventorySalesRatio(inventory, demand30d) {
  const denominator = number(demand30d);
  if (denominator <= 0) return "-";
  return `${(number(inventory) / denominator).toFixed(1)}x`;
}

function formatSignedNumber(value) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${formatNumber(n)}`;
}

function formatPercent(value) {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}%`;
}

function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "-";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

async function fetchMonthlyForecastReview(item, options = {}) {
  const params = new URLSearchParams();
  params.set("month_offset", "2");
  if (options.refresh) params.set("refresh", "true");
  appendIdentityParams(params, item);
  const response = await apiFetch(`${API_BASE_URL}/control-tower/monthly-forecast-review?${params.toString()}`);
  if (!response.ok) throw new Error(`月度预测复盘失败 ${response.status}`);
  return response.json();
}

async function fetchSkuShippingCost(item) {
  const response = await apiFetch(`${API_BASE_URL}/control-tower/sku-shipping-cost`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item }),
  });
  if (!response.ok) throw new Error(`补货成本估算失败 ${response.status}`);
  return response.json();
}

async function fetchSkuDiagnosis(item, question = "生成 SKU 全链路诊断", forecastReview = null, firstLegShipments = []) {
  const response = await apiFetch(`${API_BASE_URL}/control-tower/sku-diagnosis/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      item: {
        ...item,
        ...(forecastReview ? { forecast_review: forecastReview, monthly_forecast_review: forecastReview } : {}),
        ...(firstLegShipments?.length ? { first_leg_shipments: firstLegShipments, shipments: firstLegShipments } : {}),
      },
      question,
    }),
  });
  if (!response.ok) throw new Error(`诊断失败 ${response.status}`);
  return response.json();
}

async function fetchFirstLegShipments(item) {
  const code = String(item?.fnsku || item?.material_code || item?.msku || item?.asin || "").trim();
  if (!code) return { query: { material_codes: [] }, row_count: 0, shipments: [] };
  const params = new URLSearchParams();
  if (item?.fnsku) params.set("fnsku", item.fnsku);
  else if (item?.material_code) params.set("material_code", item.material_code);
  else if (item?.msku) params.set("msku", item.msku);
  else if (item?.asin) params.set("asin", item.asin);
  params.set("latest_only", "true");
  params.set("limit", "200");
  const endpoint = `/control-tower/first-leg-shipments?${params.toString()}`;
  const bases = Array.from(new Set([API_BASE_URL, "http://127.0.0.1:8016", "http://127.0.0.1:8015"]));
  const errors = [];
  for (const base of bases) {
    try {
      const response = await fetchWithTimeout(`${base}${endpoint}`, {}, 8000);
      if (!response.ok) {
        errors.push(`${base} ${response.status}`);
        continue;
      }
      return response.json();
    } catch (err) {
      errors.push(`${base} ${err instanceof Error ? err.message : "请求失败"}`);
    }
  }
  throw new Error(`头程批次查询失败：${errors.join("；")}`);
}

async function askSkuAssistant(item, question, forecastReview = null, firstLegShipments = []) {
  const response = await apiFetch(`${API_BASE_URL}/agent/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: [
        `请基于库存控制塔上下文回答 SKU 问题。`,
        `SKU: ${item.material_code || "-"}；MSKU: ${item.msku || "-"}；FNSKU: ${item.fnsku || "-"}`,
        `国家/店铺: ${[item.country_code, item.store_name].filter(Boolean).join(" / ") || "-"}`,
        `风险: ${item.warning_type || riskTypeMeta[riskKeyForItem(item)]?.label || "-"}`,
        `库存: 总库存 ${formatNumber(item.total_inventory)}，FBA可售 ${formatNumber(item.fba_sellable)}，在途 ${formatNumber(item.inbound_total)}，30天需求 ${formatNumber(item.demand_30d)}。`,
        forecastReview ? `月度复盘: ${forecastReview.result_label || "-"}，预测 ${formatNumber(forecastReview.forecast_quantity)}，实际 ${formatNumber(forecastReview.actual_sales)}。` : "",
        firstLegShipments?.length ? `头程批次: ${firstLegShipments.length} 批。` : "",
        `用户问题: ${question}`,
      ].filter(Boolean).join("\n"),
    }),
  });
  if (!response.ok) throw new Error(`AI ${response.status}`);
  const payload = await response.json();
  return extractAgentReply(payload) || localSkuReply(item, question);
}

function appendIdentityParams(params, item = {}) {
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

function extractAgentReply(payload) {
  if (!payload || typeof payload !== "object") return "";
  return payload.final_answer || payload.answer || payload.output || payload.result?.final_answer || payload.result?.answer || "";
}

function formatSkuDiagnosisReply(diagnosis = {}) {
  if (diagnosis.ai_reply) return String(diagnosis.ai_reply);
  const lines = [
    `整体状态：${diagnosis.overall_status || "-"}；风险等级：${riskLevelLabel[diagnosis.risk_level] || diagnosis.risk_level || "-"}`,
    formatFindingGroup("库存情况", diagnosis.inventory?.findings),
    formatFindingGroup("售卖情况", diagnosis.sales?.findings),
    formatFindingGroup("断货风险", diagnosis.stockout?.findings),
    formatFindingGroup("冗余风险", diagnosis.overstock?.findings),
    formatFindingGroup("归因", diagnosis.attribution || diagnosis.root_cause_analysis),
    formatFindingGroup("处理逻辑", diagnosis.handling_logic),
    formatFindingGroup("补救措施", diagnosis.remedies),
  ].filter(Boolean);
  return lines.join("\n\n");
}

function formatFindingGroup(title, values) {
  const rows = Array.isArray(values) ? values : values ? [values] : [];
  if (!rows.length) return "";
  return `${title}\n${rows.map((row, index) => `${index + 1}. ${formatFinding(row)}`).join("\n")}`;
}

function formatFinding(value) {
  if (typeof value === "string") return value;
  if (!value || typeof value !== "object") return String(value || "-");
  return value.summary || value.finding || value.cause || value.recommendation || value.evidence || JSON.stringify(value);
}

function localSkuReply(item, question, err) {
  const reason = err instanceof Error ? `接口暂不可用：${err.message}` : "接口暂不可用";
  return `${reason}。当前可见信息：${item.material_code || item.msku || item.fnsku || "该 SKU"} 风险为 ${item.warning_type || riskTypeMeta[riskKeyForItem(item)]?.label || "-"}，总库存 ${formatNumber(item.total_inventory)}，FBA 可售 ${formatNumber(item.fba_sellable)}，在途 ${formatNumber(item.inbound_total)}，区间销量 ${formatNumber(item.daily_sales_volume)}。问题：${question}`;
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
