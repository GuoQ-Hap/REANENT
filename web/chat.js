const form = document.querySelector("#chatForm");
const input = document.querySelector("#chatInput");
const messages = document.querySelector("#messages");
const useRealModel = document.querySelector("#useRealModel");
const modelSelect = document.querySelector("#modelSelect");
const runtimeSummary = document.querySelector("#runtimeSummary");
const runtimeBadge = document.querySelector("#runtimeBadge");
const routeStrip = document.querySelector("#routeStrip");
const recentContext = [];
let activePoll = null;

function addMessage(role, text) {
  const item = document.createElement("article");
  item.className = `message ${role}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  item.appendChild(bubble);
  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
  return bubble;
}

function renderAttachments(bubble, result) {
  const attachments = result?.artifacts?.attachments || result?.result?.artifacts?.attachments || [];
  if (!attachments.length) return;
  const list = document.createElement("div");
  list.className = "attachment-list";
  for (const item of attachments) {
    const link = document.createElement("a");
    link.href = item.url || item.path || "#";
    link.textContent = item.name || "附件";
    link.target = "_blank";
    link.rel = "noopener";
    list.appendChild(link);
  }
  bubble.appendChild(list);
}

function renderAssistantResult(bubble, result, reply) {
  bubble.textContent = "";
  const ui = result?.ui || {};
  const hasStructured = Boolean(ui.tables?.length || ui.calculations?.length);
  const displayText = hasStructured ? cleanReplyText(reply || "") : reply || "";
  if (displayText) {
    const textBlock = document.createElement("div");
    textBlock.className = "reply-text";
    renderTextLines(textBlock, displayText);
    bubble.appendChild(textBlock);
  }
  if (ui.tables?.length) {
    const stack = document.createElement("div");
    stack.className = "structured-stack";
    for (const table of ui.tables) {
      stack.appendChild(createStructuredTable(table));
    }
    bubble.appendChild(stack);
  }
  if (ui.calculations?.length) {
    bubble.appendChild(createCalculationBlock(ui.calculations));
  }
  renderAttachments(bubble, result);
  if (!bubble.textContent.trim() && !bubble.querySelector("table")) {
    bubble.textContent = "（空回复）";
  }
}

function renderTextLines(container, text) {
  const lines = text.split(/\n{2,}/).map((line) => line.trim()).filter(Boolean);
  for (const line of lines) {
    const paragraph = document.createElement("p");
    paragraph.textContent = stripMarkdownMarks(line);
    container.appendChild(paragraph);
  }
}

function cleanReplyText(text) {
  const lines = [];
  let inTable = false;
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (line.startsWith("|") && line.endsWith("|")) {
      inTable = true;
      continue;
    }
    if (inTable) inTable = false;
    if (/^\*\*(查询结果|建议动作|附件)\*\*$/.test(line)) continue;
    lines.push(rawLine);
  }
  return lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

function stripMarkdownMarks(text) {
  return text.replace(/\*\*/g, "").replace(/`/g, "");
}

function createStructuredTable(table) {
  const section = document.createElement("section");
  section.className = "structured-table-card";

  const header = document.createElement("div");
  header.className = "structured-table-header";
  const title = document.createElement("strong");
  title.textContent = table.title || "结果表";
  header.appendChild(title);
  if (table.description) {
    const desc = document.createElement("span");
    desc.textContent = table.description;
    header.appendChild(desc);
  }

  const wrap = document.createElement("div");
  wrap.className = "structured-table-wrap";
  const grid = document.createElement("table");
  grid.className = "structured-table";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const column of table.columns || []) {
    const th = document.createElement("th");
    const label = document.createElement("span");
    label.className = "column-label";
    label.textContent = column.label || column.key;
    th.appendChild(label);
    if (column.meaning && column.meaning !== column.label) {
      const meaning = document.createElement("small");
      meaning.textContent = column.meaning;
      th.appendChild(meaning);
    }
    if (column.align === "right") th.className = "numeric";
    headRow.appendChild(th);
  }
  thead.appendChild(headRow);

  const tbody = document.createElement("tbody");
  for (const row of table.rows || []) {
    const tr = document.createElement("tr");
    for (const column of table.columns || []) {
      const td = document.createElement("td");
      if (column.align === "right") td.className = "numeric";
      td.textContent = formatCell(row?.[column.key]);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  if (!table.rows?.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = Math.max((table.columns || []).length, 1);
    td.textContent = "暂无数据";
    tr.appendChild(td);
    tbody.appendChild(tr);
  }

  grid.append(thead, tbody);
  wrap.appendChild(grid);
  section.append(header, wrap);
  return section;
}

function createCalculationBlock(items) {
  const section = document.createElement("section");
  section.className = "calculation-block";
  const title = document.createElement("strong");
  title.textContent = "计算逻辑";
  const list = document.createElement("ol");
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    list.appendChild(li);
  }
  section.append(title, list);
  return section;
}

function formatCell(value) {
  if (value == null || value === "") return "-";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : String(Number(value.toFixed(4)));
  if (Array.isArray(value)) return value.join("；");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

async function startMessage(text) {
  const response = await fetch("/api/chat/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      use_real_model: useRealModel.checked,
      model: modelSelect.value,
      recent_context: recentContext.slice(-8),
    }),
  });
  return parseJsonResponse(response);
}

async function loadRunStatus(runId) {
  const response = await fetch(`/api/chat/status?run_id=${encodeURIComponent(runId)}`);
  return parseJsonResponse(response);
}

async function parseJsonResponse(response) {
  const raw = await response.text();
  try {
    return JSON.parse(raw);
  } catch (error) {
    const looksLikeHtml = raw.trim().startsWith("<!doctype") || raw.trim().startsWith("<html");
    return {
      ok: false,
      error: looksLikeHtml ? "后端没有返回 JSON，可能还在运行旧服务或接口地址未命中。" : `响应不是合法 JSON：${error.message}`,
      hint: "请停止当前服务后重新运行：$env:PYTHONPATH=\"src\"; python -m pmc_agent.test_server，然后刷新 chat.html。",
    };
  }
}

function setRuntimeStatus(status, summary) {
  runtimeBadge.className = `runtime-badge ${status || "idle"}`;
  runtimeBadge.textContent = status === "completed" ? "Done" : status === "failed" ? "Failed" : status === "running" ? "Running" : "Idle";
  runtimeSummary.textContent = summary || "等待请求";
}

function resetRuntime() {
  setRuntimeStatus("running", "正在构建路线");
  routeStrip.innerHTML = "";
}

function routeLetter(index) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
  if (index <= alphabet.length) return alphabet[index - 1];
  return `N${index}`;
}

function normalizeRouteNodes(events) {
  const nodes = [];
  const routeNodes = new Map();
  const seenFinal = new Set();
  const hasRouteNodes = (events || []).some((event) => isRouteEvent(event));

  for (const event of events || []) {
    if (!isFlowEvent(event)) continue;
    if (shouldSkipFlowEvent(event, hasRouteNodes)) continue;
    if (event.event === "final_returned") {
      const key = `${event.event}:${event.detail || event.label}`;
      if (seenFinal.has(key)) continue;
      seenFinal.add(key);
    }

    if (isRouteEvent(event)) {
      const key = `route:${event.route_index}`;
      let node = routeNodes.get(key);
      if (!node) {
        node = {
          index: nodes.length + 1,
          label: routeLetter(event.route_index),
          title: event.action || event.behavior || event.label,
          detail: event.detail || "",
          status: event.status || statusForEvent(event),
          input: inputForEvent(event),
          output: outputForEvent(event),
          parallel: [],
          shape: event.event?.startsWith("parallel_group") ? "parallel" : "serial",
        };
        routeNodes.set(key, node);
        nodes.push(node);
      }
      node.title = event.action || event.behavior || event.label || node.title;
      node.detail = event.detail || node.detail;
      node.status = event.status || node.status;
      if (event.event?.endsWith("_started")) node.input = inputForEvent(event);
      if (event.event?.endsWith("_completed")) node.output = outputForEvent(event);
      if (event.event?.startsWith("parallel_group")) {
        node.shape = "parallel";
        node.title = event.label || "并行组";
        node.parallel = collectParallel(events, event.route_index);
        node.output = outputForParallel(event, node.parallel);
      }
      continue;
    }

    const shape = shapeForEvent(event);
    nodes.push({
      index: nodes.length + 1,
      label: Number.isInteger(event.route_index) ? routeLetter(event.route_index) : String(nodes.length + 1),
      title: event.action || event.behavior || event.label,
      detail: event.detail || "",
      status: event.status || statusForEvent(event),
      input: inputForEvent(event),
      output: outputForEvent(event),
      parallel: shape === "parallel" ? collectParallel(events, event.route_index) : [],
      shape,
    });
  }
  return nodes;
}

function shouldSkipFlowEvent(event, hasRouteNodes = false) {
  if (hasRouteNodes && (event.event === "run_started" || event.event === "route_started")) return true;
  if (event.event === "observation_returned" && event.action === "run_serial_space") return true;
  if (event.event === "model_returned" && event.action === "run_serial_space") return true;
  if (event.event === "action_running" && event.action === "run_serial_space") return true;
  if (event.event === "model_returned" && event.action === "final_answer") return true;
  return false;
}

function isRouteEvent(event) {
  if (!Number.isInteger(event.route_index)) return false;
  return ["route_node_started", "route_node_completed", "parallel_group_started", "parallel_group_completed"].includes(event.event);
}

function isFlowEvent(event) {
  if (!event) return false;
  if (Number.isInteger(event.parallel_index) && !event.event?.startsWith("parallel_group")) return false;
  if (event.event?.startsWith("parallel_group")) return true;
  if (Number.isInteger(event.route_index)) return true;
  const text = `${event.event || ""} ${event.label || ""} ${event.action || ""} ${event.detail || ""}`;
  return /queued|run_started|model_thinking|model_returned|action_running|observation_returned|self_review_failed|final_returned|run_failed|排队|开始|判断|思考|路线|调用|返回|最终|失败/.test(text);
}

function shapeForEvent(event) {
  const text = `${event.event || ""} ${event.label || ""} ${event.action || ""} ${event.detail || ""}`;
  if (event.event === "queued") return "start";
  if (event.event === "final_returned" || event.event === "run_failed" || /最终|失败/.test(text)) return "end";
  if (event.event?.startsWith("parallel_group")) return "parallel";
  if (event.event === "model_thinking" || event.label === "模型思考中" || /模型思考中/.test(text)) return "thinking";
  if (event.event === "self_review_failed" || /判断|审核/.test(text)) return "decision";
  if (event.event === "observation_returned" || /返回/.test(text)) return "data";
  return "process";
}

function statusForEvent(event) {
  if (event.event === "queued") return "queued";
  if (event.event === "run_failed") return "failed";
  if (event.event === "final_returned") return "completed";
  return "running";
}

function collectParallel(events, routeIndex) {
  return events
    .filter((event) => event.route_index === routeIndex && Number.isInteger(event.parallel_index))
    .map((event) => ({
      index: event.parallel_index,
      label: event.behavior || event.label,
      status: event.status || "running",
      detail: event.detail || "",
    }));
}

function inputForEvent(event) {
  if (event.arguments) return compactFlowValue(event.arguments);
  if (event.event === "queued") return event.detail || "用户请求已进入运行队列。";
  if (event.event === "run_started") return event.mode ? `运行模式：${event.mode}` : event.detail || "";
  if (event.event === "model_thinking") return `轮次：${event.iteration || "-"}；上下文：当前对话与历史 observation。`;
  if (event.event === "route_node_started" || event.event === "parallel_group_started") return event.detail || event.action || event.label || "";
  return event.action ? `动作：${event.action}` : event.detail || "";
}

function outputForEvent(event) {
  if (event.observation) return compactFlowValue(event.observation);
  if (event.reasoning_summary) return compactFlowValue(event.reasoning_summary);
  if (event.event === "model_returned") return event.action ? `选择动作：${event.action}` : event.detail || "";
  if (event.event === "final_returned") return event.detail || "最终结果已返回。";
  if (event.event === "run_failed") return event.detail || "运行失败。";
  if (event.event?.endsWith("_completed")) return event.detail || "节点已完成。";
  return "";
}

function outputForParallel(event, branches) {
  if (event.event === "parallel_group_completed") {
    const branchText = branches.map((branch) => `${branch.index}. ${branch.label || "子行为"}：${statusLabel(branch.status)}`).join("\n");
    return [event.detail, branchText].filter(Boolean).join("\n");
  }
  return event.detail || "并行子行为执行中。";
}

function compactFlowValue(value) {
  if (value == null || value === "") return "";
  if (typeof value === "string") return value.length > 260 ? `${value.slice(0, 260)}...` : value;
  if (Array.isArray(value)) return value.slice(0, 6).map((item, index) => `${index + 1}. ${compactFlowValue(item)}`).join("\n");
  if (typeof value === "object") {
    return Object.entries(value)
      .slice(0, 10)
      .map(([key, item]) => `${key}: ${compactFlowScalar(item)}`)
      .join("\n");
  }
  return String(value);
}

function compactFlowScalar(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.length > 120 ? `${value.slice(0, 120)}...` : value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return `[${value.length}项]`;
  if (typeof value === "object") return `{${Object.keys(value).slice(0, 5).join(", ")}}`;
  return String(value);
}

function renderRoute(events) {
  const nodes = normalizeRouteNodes(events);
  routeStrip.innerHTML = "";
  if (!nodes.length) {
    const empty = document.createElement("div");
    empty.className = "flow-empty";
    empty.textContent = "等待构建执行路线";
    routeStrip.appendChild(empty);
    return;
  }
  const stepbar = document.createElement("div");
  stepbar.className = "flow-stepbar";
  nodes.forEach((node) => {
    const step = document.createElement("div");
    step.className = `flow-step ${node.status || "running"}`;
    step.textContent = node.index;
    step.title = node.title || "";
    stepbar.appendChild(step);
  });
  const column = document.createElement("div");
  column.className = "flow-column";
  nodes.forEach((node, index) => {
    if (index > 0) {
      const join = document.createElement("div");
      join.className = "flow-arrow";
      column.appendChild(join);
    }
    column.appendChild(createFlowNode(node));
  });
  routeStrip.append(stepbar, column);
}

function createFlowNode(node) {
  const item = document.createElement("section");
  const shape = node.parallel?.length ? "parallel" : node.shape || "process";
  item.className = `flow-node ${shape} ${node.status || "running"} ${node.parallel?.length ? "parallel" : ""}`;
  item.title = node.title || "";
  item.tabIndex = 0;

  const kicker = document.createElement("div");
  kicker.className = "flow-kicker";
  const code = document.createElement("span");
  code.textContent = node.parallel?.length ? `${node.index} 并行` : `${shapeLabel(shape)} ${node.index}`;
  const status = document.createElement("span");
  status.className = "flow-status";
  status.textContent = statusLabel(node.status);
  kicker.append(code, status);

  const title = document.createElement("div");
  title.className = "flow-title";
  title.textContent = node.title || node.label;

  const detail = document.createElement("div");
  detail.className = "flow-detail";
  detail.textContent = node.detail || "";

  item.append(kicker, title, detail);
  item.appendChild(createIoBubble(node));
  if (node.parallel?.length) {
    const branches = document.createElement("div");
    branches.className = "flow-branches";
    for (const branch of node.parallel) {
      const branchEl = document.createElement("div");
      branchEl.className = `flow-branch ${branch.status || "running"}`;
      const branchTitle = document.createElement("strong");
      branchTitle.textContent = `${node.label}.${branch.index} ${branch.label || "子行为"}`;
      const branchStatus = document.createElement("span");
      branchStatus.textContent = statusLabel(branch.status);
      const branchDetail = document.createElement("small");
      branchDetail.textContent = branch.detail || "";
      branchEl.append(branchTitle, branchStatus, branchDetail);
      branches.appendChild(branchEl);
    }
    item.appendChild(branches);
  }
  return item;
}

function createIoBubble(node) {
  const bubble = document.createElement("aside");
  bubble.className = "flow-io-bubble";
  const input = document.createElement("div");
  const inputTitle = document.createElement("strong");
  inputTitle.textContent = "输入";
  const inputBody = document.createElement("p");
  inputBody.textContent = node.input || "无显式输入";
  input.append(inputTitle, inputBody);

  const output = document.createElement("div");
  const outputTitle = document.createElement("strong");
  outputTitle.textContent = "输出";
  const outputBody = document.createElement("p");
  outputBody.textContent = node.output || (node.status === "running" ? "等待返回" : "无显式输出");
  output.append(outputTitle, outputBody);

  bubble.append(input, output);
  return bubble;
}

function statusLabel(status) {
  if (status === "completed") return "完成";
  if (status === "failed") return "失败";
  if (status === "queued") return "排队";
  return "执行中";
}

function shapeLabel(shape) {
  if (shape === "start") return "开始";
  if (shape === "end") return "结束";
  if (shape === "decision") return "判断";
  if (shape === "thinking") return "思考";
  if (shape === "data") return "返回";
  if (shape === "parallel") return "并行";
  if (shape === "serial") return "串行";
  return "执行";
}

function renderRunStatus(data) {
  const events = data.events || [];
  const last = events[events.length - 1];
  setRuntimeStatus(data.status, last?.label || (data.status === "completed" ? "执行完成" : "运行中"));
  renderRoute(events);
}

async function pollRun(runId, loading) {
  while (true) {
    const data = await loadRunStatus(runId);
    if (!data.ok) throw new Error(data.error || "运行状态读取失败");
    renderRunStatus(data);
    if (data.status === "completed" || data.status === "failed") {
      const result = data.result || {};
      const reply = result.ok ? result.reply : `${result.error || "请求失败"}\n${result.hint || ""}`.trim();
      renderAssistantResult(loading, result, reply || "（空回复）");
      recentContext.push({ role: "assistant", content: reply || "（空回复）" });
      rememberResult(result);
      return result;
    }
    await new Promise((resolve) => {
      activePoll = window.setTimeout(resolve, 450);
    });
  }
}

function rememberResult(data) {
  if (data.result?.steps?.length) {
    const lastObservation = data.result.steps[data.result.steps.length - 1]?.observation || {};
    const firstObservation = data.result.steps.find((step) => step.observation?.query_material_code || step.observation?.snapshots)?.observation;
    const memory = {
      role: "system_memory",
      content: JSON.stringify(
        {
          query_material_code: firstObservation?.query_material_code,
          resolved_aliases: firstObservation?.resolved_aliases,
          row_count: firstObservation?.row_count,
          last_action: data.result.steps[data.result.steps.length - 1]?.decision?.action,
          last_observation: lastObservation,
        },
        null,
        0,
      ),
    };
    recentContext.push(memory);
  }
}

async function loadModelOptions() {
  try {
    const response = await fetch("/api/model-options");
    const data = await response.json();
    const options = data.options || [];
    const preferred = options.includes("gpt-5.1") ? "gpt-5.1" : data.default_model;
    modelSelect.innerHTML = "";
    for (const model of options) {
      const option = document.createElement("option");
      option.value = model;
      option.textContent = model;
      option.selected = model === preferred;
      modelSelect.appendChild(option);
    }
  } catch (error) {
    addMessage("assistant", `模型列表加载失败：${error.message}`);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  addMessage("user", text);
  recentContext.push({ role: "user", content: text });
  input.value = "";
  const loading = addMessage("assistant", "正在处理...");
  const button = form.querySelector("button");
  button.disabled = true;
  resetRuntime();
  if (activePoll) window.clearTimeout(activePoll);

  try {
    const started = await startMessage(text);
    if (!started.ok) throw new Error(started.error || "启动失败");
    await pollRun(started.run_id, loading);
  } catch (error) {
    loading.textContent = `请求失败：${error.message}`;
    setRuntimeStatus("failed", "请求失败");
  } finally {
    button.disabled = false;
    input.focus();
  }
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

loadModelOptions();
