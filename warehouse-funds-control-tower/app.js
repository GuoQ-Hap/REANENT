let capitalRows = [];
let lossRows = [];
let metadata = {};

const state = {
  view: "overview",
  basis: "cost",
  chartFilter: null,
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

const compactMoney = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});

const number = new Intl.NumberFormat("en-US");

const colors = ["#2563eb", "#12805c", "#c78613", "#8b5cf6", "#d94f45"];
const sourceColors = ["#2563eb", "#0f766e", "#7c3aed", "#c78613", "#64748b", "#d94f45"];
const riskColors = ["#d94f45", "#c78613", "#8b5cf6", "#475569", "#0f766e", "#2563eb"];
const statusColors = {
  "正常周转": "#12805c",
  "风险占用": "#d94f45",
  "在途资金": "#c78613",
  "成本缺失": "#7c3aed",
  "其他占用": "#2563eb",
  "预计仓储费": "#0ea5e9",
  "损耗净额": "#be123c",
};

function unique(values) {
  return [...new Set(values)].filter(Boolean).sort();
}

function setupControls() {
  ["dateFilter", "warehouseTypeFilter", "countryFilter", "searchInput"].forEach((id) => {
    document.getElementById(id).addEventListener("input", render);
  });

  document.querySelectorAll(".segmented button").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".segmented button").forEach((item) => item.classList.remove("is-selected"));
      button.classList.add("is-selected");
      state.basis = button.dataset.basis;
      render();
    });
  });

  document.querySelector(".route-board").addEventListener("click", (event) => {
    const target = event.target.closest("[data-filter-kind][data-filter-value]");
    if (!target) return;
    setChartFilter({
      kind: target.dataset.filterKind,
      value: target.dataset.filterValue,
      label: target.dataset.filterLabel || target.dataset.filterValue,
    });
  });

  document.getElementById("clearChartFilter").addEventListener("click", clearChartFilter);

  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => {
      state.view = button.dataset.view;
      document.querySelectorAll(".nav-item").forEach((item) => {
        item.classList.toggle("is-active", item.dataset.view === state.view);
      });
      document.querySelectorAll(".view-panel").forEach((panel) => {
        panel.classList.toggle("is-active", panel.dataset.panel === state.view);
      });
    });
  });

  document.getElementById("refreshBtn").addEventListener("click", loadData);
  document.getElementById("exportBtn").addEventListener("click", exportCsv);
}

async function loadData() {
  setLoading(true);
  try {
    const response = await fetch("./api/funds?limit=320", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    if (!payload.ok) {
      throw new Error(payload.error || "database query failed");
    }
    capitalRows = Array.isArray(payload.capitalRows) ? payload.capitalRows : [];
    lossRows = Array.isArray(payload.lossRows) ? payload.lossRows : [];
    metadata = payload.metadata || {};
    refreshFilterOptions();
    render();
    setStatus(
      `真实数据：库存 ${metadata.inventoryDate || "-"}，FBA ${metadata.fbaDate || "-"}，台账 ${metadata.ledgerDate || "-"}`
    );
  } catch (error) {
    capitalRows = [];
    lossRows = [];
    metadata = {};
    refreshFilterOptions();
    render();
    setStatus(`数据库读取失败：${error.message}`);
  } finally {
    setLoading(false);
  }
}

function refreshFilterOptions() {
  const dateSelect = document.getElementById("dateFilter");
  const countrySelect = document.getElementById("countryFilter");
  const previousDate = dateSelect.value || "all";
  const previousCountry = countrySelect.value || "all";
  const dates = unique([...capitalRows, ...lossRows].map((row) => row.date));
  const countries = unique([...capitalRows, ...lossRows].map((row) => row.country));
  fillSelect(dateSelect, ["all", ...dates], "全部日期", previousDate);
  fillSelect(countrySelect, ["all", ...countries], "全部国家", previousCountry);
}

function fillSelect(select, values, allLabel, previousValue) {
  select.innerHTML = "";
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value === "all" ? allLabel : value;
    select.appendChild(option);
  });
  select.value = values.includes(previousValue) ? previousValue : "all";
}

function filters() {
  return {
    date: document.getElementById("dateFilter").value || "all",
    type: document.getElementById("warehouseTypeFilter").value || "all",
    country: document.getElementById("countryFilter").value || "all",
    query: document.getElementById("searchInput").value.trim().toLowerCase(),
  };
}

function setChartFilter(filter) {
  const sameFilter =
    state.chartFilter && state.chartFilter.kind === filter.kind && state.chartFilter.value === filter.value;
  state.chartFilter = sameFilter ? null : filter;
  render();
}

function clearChartFilter() {
  state.chartFilter = null;
  render();
}

function updateChartFilterBar() {
  const bar = document.getElementById("chartFilterBar");
  const text = document.getElementById("chartFilterText");
  if (!state.chartFilter) {
    bar.hidden = true;
    text.textContent = "当前钻取：全部";
    return;
  }
  const kindLabels = {
    source: "来源",
    status: "状态",
    risk: "关注",
    attention: "处置",
  };
  bar.hidden = false;
  text.textContent = `当前钻取：${kindLabels[state.chartFilter.kind] || "条件"} / ${state.chartFilter.label}`;
}

function matches(row, active) {
  if (active.date !== "all" && row.date !== active.date) return false;
  if (active.type !== "all" && row.type !== active.type) return false;
  if (active.country !== "all" && row.country !== active.country) return false;
  if (!active.query) return true;
  return [row.sku, row.fnsku, row.warehouse].some((value) => String(value || "").toLowerCase().includes(active.query));
}

function matchesChartFilter(row, domain) {
  const filter = state.chartFilter;
  if (!filter) return true;
  if (filter.kind === "source") return row.type === filter.value;
  if (domain === "loss") return filter.kind === "attention" && filter.value === "损耗净额";
  if (filter.kind === "status") return capitalFlowLabel(row) === filter.value;
  if (filter.kind === "risk") return capitalRiskLabel(row) === filter.value;
  if (filter.kind === "attention" && filter.value === "预计仓储费") return Number(row.storageNext30 || 0) > 0;
  if (filter.kind === "attention" && filter.value === "成本缺失") return isMissingCost(row);
  return false;
}

function isChartFilterActive(kind, value) {
  return Boolean(state.chartFilter && state.chartFilter.kind === kind && state.chartFilter.value === value);
}

function currentCapital() {
  const active = filters();
  return capitalRows.filter((row) => matches(row, active) && matchesChartFilter(row, "capital"));
}

function currentLosses() {
  const active = filters();
  return lossRows.filter((row) => matches(row, active) && matchesChartFilter(row, "loss"));
}

function lossAmount(row) {
  const stockLoss = Number(row.stockLoss ?? row.qty * row.unitCost ?? 0);
  const handlingFee = Number(row.handlingFee || 0);
  const recovery = Number(row.recovery || 0);
  return stockLoss + handlingFee - (state.basis === "recovery" ? recovery : 0);
}

function render() {
  const capital = currentCapital();
  const losses = currentLosses();
  const capitalTotal = sum(capital, "amount");
  const healthyRows = capital.filter((row) => capitalFlowLabel(row) === "正常周转");
  const riskRows = capital.filter((row) => capitalFlowLabel(row) === "风险占用" || capitalFlowLabel(row) === "成本缺失");
  const transitRows = capital.filter((row) => capitalFlowLabel(row) === "在途资金");
  const missingCostRows = capital.filter((row) => capitalFlowLabel(row) === "成本缺失");
  const healthyTotal = sum(healthyRows, "amount");
  const riskCapitalTotal = sum(riskRows, "amount");
  const transitTotal = sum(transitRows, "amount");
  const lossTotal = losses.reduce((total, row) => total + lossAmount(row), 0);
  const storageTotal = sum(capital, "storageNext30");

  setText("metricCapital", money.format(capitalTotal));
  setText("metricCapitalMeta", `${capital.length} 条明细`);
  setText("metricHealthy", money.format(healthyTotal));
  setText("metricHealthyMeta", `${healthyRows.length} 条正常周转`);
  setText("metricRiskCapital", money.format(riskCapitalTotal));
  setText("metricRiskCapitalMeta", `${riskRows.length} 条风险占用`);
  setText("metricTransit", money.format(transitTotal));
  setText("metricTransitMeta", `${transitRows.length} 条在途/入库`);
  setText("metricStorage", money.format(storageTotal));
  setText("metricLoss", money.format(lossTotal));
  setText("metricLossMeta", `${losses.length} 项损耗 · ${missingCostRows.length} 行成本缺失`);

  updateChartFilterBar();
  renderRouteDashboard(capital, losses);
  renderChart(capital);
  renderStructure(capital, losses);
  renderQueue(losses);
  renderCapitalTable(capital);
  renderLossTable(losses);
}

function renderRouteDashboard(capital, losses) {
  const total = sum(capital, "amount");
  const sourceGroups = topDonutSlices(groupAmount(capital, (row) => row.type || "其他", sourceColors), 5, "#64748b");
  const statusGroups = statusBreakdown(capital);
  const riskRows = capital.filter((row) => !isHealthyCapital(row));
  const riskTotal = sum(riskRows, "amount");
  const riskGroups = topDonutSlices(groupAmount(riskRows, capitalRiskLabel, riskColors), 5, "#64748b");
  const lossTotal = losses.reduce((value, row) => value + lossAmount(row), 0);
  const storageRows = capital.filter((row) => Number(row.storageNext30 || 0) > 0);
  const missingRows = capital.filter(isMissingCost);
  const storageTotal = sum(storageRows, "storageNext30");
  const missingTotal = sum(missingRows, "amount");

  setText("routeMeta", `${capital.length} 条占用明细 · ${losses.length} 条损耗明细`);
  setText("routeBasis", state.basis === "recovery" ? "回款口径" : "成本口径");
  renderRouteFlow({
    total,
    sourceGroups,
    statusGroups,
    storageTotal,
    storageCount: storageRows.length,
    lossTotal,
    lossCount: losses.length,
    missingTotal,
    missingCount: missingRows.length,
  });

  renderDonut("capital", {
    slices: statusGroups,
    total,
    meta: `${capital.length} 条明细`,
    filterKind: "status",
  });

  renderDonut("warehouse", {
    slices: sourceGroups,
    total,
    meta: `${unique(capital.map((row) => row.type)).length} 类仓库`,
    filterKind: "source",
  });

  renderDonut("risk", {
    slices: riskGroups,
    total: riskTotal,
    meta: `${unique(riskRows.map(capitalRiskLabel)).length} 类口径`,
    filterKind: "risk",
  });
}

function statusBreakdown(capital) {
  return ["正常周转", "风险占用", "在途资金", "成本缺失", "其他占用"]
    .map((label) => {
      const rows = capital.filter((row) => capitalFlowLabel(row) === label);
      return {
        label,
        value: sum(rows, "amount"),
        count: rows.length,
        color: statusColors[label],
        detail: `${rows.length} 条`,
      };
    })
    .filter((item) => Number(item.value || 0) > 0 || Number(item.count || 0) > 0);
}

function capitalFlowLabel(row) {
  if (isMissingCost(row)) return "成本缺失";
  if (isRiskCapital(row)) return "风险占用";
  if (isTransitCapital(row)) return "在途资金";
  if (isHealthyCapital(row)) return "正常周转";
  return "其他占用";
}

function renderRouteFlow({
  total,
  sourceGroups,
  statusGroups,
  storageTotal,
  storageCount,
  lossTotal,
  lossCount,
  missingTotal,
  missingCount,
}) {
  const route = document.getElementById("routeFlow");
  const attentionGroups = [
    {
      label: "预计仓储费",
      value: storageTotal,
      count: storageCount,
      color: statusColors["预计仓储费"],
      detail: `${storageCount} 条FBA分摊`,
    },
    {
      label: "损耗净额",
      value: lossTotal,
      count: lossCount,
      color: statusColors["损耗净额"],
      detail: state.basis === "recovery" ? `${lossCount} 项 · 扣减预计回款` : `${lossCount} 项 · 库存成本口径`,
    },
    {
      label: "成本缺失",
      value: missingTotal,
      count: missingCount,
      color: statusColors["成本缺失"],
      detail: `${missingCount} 行需补单位成本`,
    },
  ].filter((item) => Number(item.value || 0) > 0 || Number(item.count || 0) > 0);
  const columns = [
    { title: "来源口径", total, items: sourceGroups, filterKind: "source" },
    { title: "状态分流", total, items: statusGroups, filterKind: "status" },
    { title: "处置关注", total: Math.max(total, storageTotal, lossTotal, missingTotal), items: attentionGroups, filterKind: "attention" },
  ];
  route.innerHTML = columns
    .map(
      (column) => `
        <article class="route-column">
          <div class="route-column-head">
            <span>${escapeHtml(column.title)}</span>
            <strong>${money.format(column.items.reduce((value, item) => value + Number(item.value || 0), 0))}</strong>
          </div>
          <div class="route-node-list">
            ${
              column.items.length
                ? column.items
                    .map((item) => {
                      const width = Math.max(Math.min((Number(item.value || 0) / Math.max(column.total, 1)) * 100, 100), item.value ? 4 : 0);
                      const filterValue = item.filterValue || item.label;
                      const selected = isChartFilterActive(column.filterKind, filterValue);
                      return `
                        <button class="route-node${selected ? " is-selected" : ""}" type="button" ${chartFilterAttributes(
                          column.filterKind,
                          filterValue,
                          item.filterLabel || item.label
                        )} aria-pressed="${selected ? "true" : "false"}">
                          <div class="route-node-main">
                            <span><i style="background:${item.color}; color:${item.color}"></i>${escapeHtml(item.label)}</span>
                            <strong>${money.format(item.value)}</strong>
                          </div>
                          <div class="route-node-track"><span style="width:${width}%; background:${item.color}"></span></div>
                          ${item.detail ? `<small>${escapeHtml(item.detail)}</small>` : ""}
                        </button>
                      `;
                    })
                    .join("")
                : '<div class="route-node is-empty">暂无真实数据</div>'
            }
          </div>
        </article>
      `
    )
    .join("");
}

function renderDonut(prefix, config) {
  const slices = (config.slices || []).filter((item) => Number(item.value || 0) > 0 || Number(item.count || 0) > 0);
  const total = Number(config.total || 0);
  const ring = document.getElementById(`${prefix}DonutRing`);
  const legend = document.getElementById(`${prefix}DonutLegend`);
  const center = document.getElementById(`${prefix}DonutCenter`);
  const meta = document.getElementById(`${prefix}DonutMeta`);
  const gradient = donutGradient(slices, total);

  ring.style.setProperty("--donut-bg", gradient);
  center.textContent = compactMoney.format(total);
  meta.textContent = config.meta || "0";
  legend.innerHTML = slices.length
    ? slices
        .map((item) => {
          const percent = formatPercent(item.value, total);
          const filterValue = item.filterValue || item.label;
          const selected = config.filterKind && isChartFilterActive(config.filterKind, filterValue);
          return `
            <button class="route-legend-row${selected ? " is-selected" : ""}" type="button" ${chartFilterAttributes(
              config.filterKind,
              filterValue,
              item.filterLabel || item.label
            )} aria-pressed="${selected ? "true" : "false"}">
              <span><i style="background:${item.color}; color:${item.color}"></i>${escapeHtml(item.label)}</span>
              <strong>${money.format(item.value)}</strong>
              <small>${percent}</small>
              ${item.detail ? `<em>${escapeHtml(item.detail)}</em>` : ""}
            </button>
          `;
        })
        .join("")
    : '<div class="route-empty">暂无真实数据</div>';
}

function chartFilterAttributes(kind, value, label) {
  return `data-filter-kind="${escapeHtml(kind)}" data-filter-value="${escapeHtml(value)}" data-filter-label="${escapeHtml(label)}"`;
}

function donutGradient(slices, total) {
  if (!slices.length || total <= 0) {
    return "conic-gradient(#153745 0% 100%)";
  }
  let cursor = 0;
  const stops = slices.map((item) => {
    const start = cursor;
    cursor += (Number(item.value || 0) / total) * 100;
    return `${item.color} ${start}% ${cursor}%`;
  });
  return `conic-gradient(${stops.join(", ")})`;
}

function groupAmount(rows, labelFn, palette = sourceColors) {
  const groups = new Map();
  rows.forEach((row) => {
    const label = labelFn(row);
    const group = groups.get(label) || { value: 0, count: 0 };
    group.value += Number(row.amount || 0);
    group.count += 1;
    groups.set(label, group);
  });
  return [...groups.entries()]
    .map(([label, group], index) => ({
      label,
      value: group.value,
      count: group.count,
      color: palette[index % palette.length],
    }))
    .sort((a, b) => b.value - a.value);
}

function topDonutSlices(slices, limit, otherColor = "#64748b") {
  if (slices.length <= limit) return slices;
  const visible = slices.slice(0, limit - 1);
  const rest = slices.slice(limit - 1);
  visible.push({
    label: "其他",
    value: rest.reduce((total, item) => total + Number(item.value || 0), 0),
    count: rest.reduce((total, item) => total + Number(item.count || 0), 0),
    color: otherColor,
  });
  return visible;
}

function formatPercent(value, total) {
  if (!total) return "0%";
  return `${Math.round((Number(value || 0) / total) * 100)}%`;
}

function renderChart(rows) {
  const groups = rows.reduce((map, row) => {
    map[row.type] = (map[row.type] || 0) + Number(row.amount || 0);
    return map;
  }, {});
  const entries = Object.entries(groups).sort((a, b) => b[1] - a[1]);
  const max = Math.max(...entries.map((entry) => entry[1]), 1);
  const total = entries.reduce((value, entry) => value + entry[1], 0);
  setText("chartTotal", money.format(total));
  const chart = document.getElementById("barChart");
  chart.innerHTML = "";
  entries.forEach(([name, value], index) => {
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span class="bar-name">${escapeHtml(name)}</span>
      <span class="bar-track"><span class="bar-fill" style="width:${(value / max) * 100}%; background:${colors[index % colors.length]}"></span></span>
      <span class="bar-value">${money.format(value)}</span>
    `;
    chart.appendChild(row);
  });
  if (!entries.length) {
    chart.innerHTML = '<div class="empty">暂无真实数据</div>';
  }
}

function renderStructure(capital, losses) {
  const capitalTotal = Math.max(sum(capital, "amount"), 1);
  const groups = [
    {
      key: "healthy",
      label: "正常周转",
      amount: sum(capital.filter((row) => capitalFlowLabel(row) === "正常周转"), "amount"),
      count: capital.filter((row) => capitalFlowLabel(row) === "正常周转").length,
      hint: "FBA可售 / 仓库可用",
    },
    {
      key: "risk",
      label: "风险占用",
      amount: sum(capital.filter((row) => capitalFlowLabel(row) === "风险占用"), "amount"),
      count: capital.filter((row) => capitalFlowLabel(row) === "风险占用").length,
      hint: "不可售 / 锁定 / 次品 / 长库龄",
    },
    {
      key: "transit",
      label: "在途资金",
      amount: sum(capital.filter((row) => capitalFlowLabel(row) === "在途资金"), "amount"),
      count: capital.filter((row) => capitalFlowLabel(row) === "在途资金").length,
      hint: "在途 / 入库中 / 计划入库",
    },
    {
      key: "missing",
      label: "成本缺失",
      amount: sum(capital.filter((row) => capitalFlowLabel(row) === "成本缺失"), "amount"),
      count: capital.filter((row) => capitalFlowLabel(row) === "成本缺失").length,
      hint: "单位成本为 0 的明细",
    },
    {
      key: "loss",
      label: "损耗净额",
      amount: losses.reduce((total, row) => total + lossAmount(row), 0),
      count: losses.length,
      hint: state.basis === "cost" ? "按库存成本" : "扣减预计回款",
    },
  ];
  setText("structureMeta", `${capital.length} 条占用明细 · ${losses.length} 条损耗明细`);
  const grid = document.getElementById("structureGrid");
  grid.innerHTML = groups
    .map((item) => {
      const width = Math.min(Math.max((Math.abs(item.amount) / capitalTotal) * 100, item.amount ? 3 : 0), 100);
      return `
        <article class="structure-card ${item.key}">
          <div>
            <span>${escapeHtml(item.label)}</span>
            <strong>${money.format(item.amount)}</strong>
            <small>${number.format(item.count)} 条 · ${escapeHtml(item.hint)}</small>
          </div>
          <div class="structure-track"><span style="width:${width}%"></span></div>
        </article>
      `;
    })
    .join("");
}

function renderQueue(rows) {
  const queue = document.getElementById("actionQueue");
  const ordered = [...rows].sort((a, b) => lossAmount(b) - lossAmount(a)).slice(0, 8);
  setText("queueCount", `${ordered.length} 项`);
  queue.innerHTML = "";
  ordered.forEach((row) => {
    const amount = lossAmount(row);
    const item = document.createElement("article");
    item.className = "queue-item";
    item.innerHTML = `
      <strong>${escapeHtml(row.sku)} · ${escapeHtml(row.kind)}</strong>
      <span class="badge ${riskClass(amount)}">${money.format(amount)}</span>
      <small>${escapeHtml(row.warehouse)} / ${escapeHtml(row.country)} / ${escapeHtml(row.action)}</small>
    `;
    queue.appendChild(item);
  });
  if (!ordered.length) {
    queue.innerHTML = '<div class="empty">暂无真实数据</div>';
  }
}

function renderCapitalTable(rows) {
  setText("capitalRows", `${rows.length} 行`);
  const tbody = document.getElementById("capitalTable");
  tbody.innerHTML = rows
    .map(
      (row) => `
      <tr>
        <td>${escapeHtml(row.date)}</td>
        <td>${escapeHtml(row.warehouse)}</td>
        <td>${escapeHtml(row.type)}</td>
        <td>${escapeHtml(row.sku)}</td>
        <td>${escapeHtml(row.fnsku)}</td>
        <td>${statusDot(row.status)}${escapeHtml(row.status)}</td>
        <td class="num">${number.format(Number(row.qty || 0))}</td>
        <td class="num">${money.format(Number(row.unitCost || 0))}</td>
        <td class="num">${money.format(Number(row.amount || 0))}</td>
        <td class="num">${number.format(Number(row.ageDays || 0))} 天</td>
        <td><span class="badge ${capitalRiskClass(row)}">${escapeHtml(capitalRiskLabel(row))}</span></td>
        <td class="num">${money.format(Number(row.storageNext30 || 0))}</td>
      </tr>
    `
    )
    .join("");
}

function renderLossTable(rows) {
  setText("lossRows", `${rows.length} 行`);
  const tbody = document.getElementById("lossTable");
  tbody.innerHTML = rows
    .map((row) => {
      const stockLoss = Number(row.stockLoss ?? row.qty * row.unitCost ?? 0);
      const net = lossAmount(row);
      return `
        <tr>
          <td>${escapeHtml(row.date)}</td>
          <td>${escapeHtml(row.warehouse)}</td>
          <td>${escapeHtml(row.sku)}</td>
          <td>${escapeHtml(row.kind)}</td>
          <td class="num">${number.format(Number(row.qty || 0))}</td>
          <td class="num">${money.format(stockLoss)}</td>
          <td class="num">${money.format(Number(row.handlingFee || 0))}</td>
          <td class="num">${money.format(Number(row.recovery || 0))}</td>
          <td class="num">${money.format(net)}</td>
          <td><span class="badge ${riskClass(net)}">${escapeHtml(row.action)}</span></td>
        </tr>
      `;
    })
    .join("");
}

function statusDot(status) {
  const text = String(status || "");
  if (text.includes("不可售") || text.includes("次品") || text.includes("损")) return '<span class="status-dot danger"></span>';
  if (text.includes("锁定") || text.includes("预留") || text.includes("在途")) return '<span class="status-dot warn"></span>';
  return '<span class="status-dot"></span>';
}

function isMissingCost(row) {
  return Number(row.qty || 0) > 0 && Number(row.unitCost || 0) <= 0 && Number(row.amount || 0) <= 0;
}

function isTransitCapital(row) {
  const status = String(row.status || "");
  return ["在途", "入库", "计划", "待调仓", "调仓"].some((keyword) => status.includes(keyword));
}

function isRiskCapital(row) {
  const status = String(row.status || "");
  if (isMissingCost(row)) return true;
  if (Number(row.ageDays || 0) >= 181) return true;
  return ["不可售", "次品", "待检", "锁定", "预留", "调查", "待发货"].some((keyword) => status.includes(keyword));
}

function isHealthyCapital(row) {
  const status = String(row.status || "");
  if (isRiskCapital(row) || isTransitCapital(row)) return false;
  return ["可售", "可用"].some((keyword) => status.includes(keyword));
}

function capitalRiskLabel(row) {
  const status = String(row.status || "");
  if (isMissingCost(row)) return "成本缺失";
  if (Number(row.ageDays || 0) >= 365) return "365天+";
  if (Number(row.ageDays || 0) >= 181) return "181天+";
  if (["不可售", "次品", "待检"].some((keyword) => status.includes(keyword))) return "不可售风险";
  if (["锁定", "预留", "调查", "待发货"].some((keyword) => status.includes(keyword))) return "冻结占用";
  if (isTransitCapital(row)) return "在途资金";
  return "正常周转";
}

function capitalRiskClass(row) {
  const label = capitalRiskLabel(row);
  if (label.includes("缺失") || label.includes("365") || label.includes("不可售")) return "high";
  if (label.includes("181") || label.includes("冻结") || label.includes("在途")) return "medium";
  return "low";
}

function riskClass(value) {
  if (value >= 450) return "high";
  if (value >= 180) return "medium";
  return "low";
}

function exportCsv() {
  const rows = [
    ["date", "warehouse", "type", "country", "sku", "fnsku", "status", "quantity", "unit_cost", "amount"],
    ...currentCapital().map((row) => [
      row.date,
      row.warehouse,
      row.type,
      row.country,
      row.sku,
      row.fnsku,
      row.status,
      row.qty,
      row.unitCost,
      row.amount,
    ]),
  ];
  const csv = rows.map((row) => row.map(csvCell).join(",")).join("\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "warehouse-capital-detail.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function csvCell(value) {
  const text = String(value ?? "");
  return `"${text.replaceAll('"', '""')}"`;
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + Number(row[key] || 0), 0);
}

function setText(id, value) {
  document.getElementById(id).textContent = value;
}

function setStatus(text) {
  const node = document.querySelector(".topbar p");
  node.textContent = text;
}

function setLoading(isLoading) {
  document.getElementById("refreshBtn").disabled = isLoading;
  if (isLoading) setStatus("正在读取 STI 数据库...");
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

setupControls();
refreshFilterOptions();
render();
loadData();
