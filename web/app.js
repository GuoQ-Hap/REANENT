const testList = document.querySelector("#testList");
const scenarioList = document.querySelector("#scenarioList");
const contractList = document.querySelector("#contractList");
const llmModuleList = document.querySelector("#llmModuleList");
const output = document.querySelector("#output");
const stateFlow = document.querySelector("#stateFlow");
const stateCheck = document.querySelector("#stateCheck");
const statusLabel = document.querySelector("#statusLabel");
const subLabel = document.querySelector("#subLabel");
const runAll = document.querySelector("#runAll");
const useRealModel = document.querySelector("#useRealModel");
const modelSelect = document.querySelector("#modelSelect");
const customModel = document.querySelector("#customModel");

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  return response.json();
}

function setBusy(title, sub) {
  statusLabel.textContent = title;
  subLabel.textContent = sub;
  output.innerHTML = "";
  stateFlow.innerHTML = "";
  stateCheck.innerHTML = "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function rawBlock(data) {
  return `<details class="raw"><summary>查看原始数据</summary><pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre></details>`;
}

function metric(label, value, className = "") {
  return `<div class="metric"><div class="metric-label">${escapeHtml(label)}</div><div class="metric-value ${className}">${escapeHtml(value)}</div></div>`;
}

function selectedModel() {
  return (customModel.value || modelSelect.value || "").trim();
}

function list(items, emptyText = "暂无") {
  if (!items || !items.length) {
    return `<ul class="soft-list"><li>${escapeHtml(emptyText)}</li></ul>`;
  }
  return `<ul class="soft-list">${items.map((item) => `<li>${item}</li>`).join("")}</ul>`;
}

function parseRanCount(text = "") {
  const match = text.match(/Ran\s+(\d+)\s+tests?/);
  return match ? match[1] : "-";
}

function parseFailureLine(text = "") {
  const failed = text.match(/FAILED\s+\(([^)]+)\)/);
  if (failed) return failed[1];
  if (text.includes("OK")) return "0";
  return "-";
}

function renderTestResult(data) {
  const combined = `${data.stdout || ""}\n${data.stderr || ""}`;
  const ran = parseRanCount(combined);
  const failed = parseFailureLine(combined);
  const status = data.ok ? "通过" : "失败";
  const statusClass = data.ok ? "ok" : "fail";
  output.innerHTML = `
    <div class="summary-grid">
      ${metric("测试结果", status, statusClass)}
      ${metric("测试数量", ran)}
      ${metric("失败/错误", failed, data.ok ? "ok" : "fail")}
      ${metric("真实模型", data.uses_real_model ? "已调用" : "未调用")}
    </div>
    <div class="section">
      <h3>模型调用说明</h3>
      <ul class="soft-list"><li>${escapeHtml(data.model_mode || "模块单元测试默认不调用真实模型。")}</li></ul>
    </div>
    <div class="section">
      <h3>执行命令</h3>
      <ul class="soft-list"><li><code>${escapeHtml(data.command || "-")}</code></li></ul>
    </div>
    <div class="section">
      <h3>控制台输出</h3>
      <pre class="console">${escapeHtml(combined.trim() || "无输出")}</pre>
    </div>
    ${rawBlock(data)}
  `;
}

function renderScenarioResult(data) {
  if (!data.ok) {
    output.innerHTML = `
      <div class="summary-grid">
        ${metric("场景结果", "失败", "fail")}
        ${metric("模式", data.mode || "-")}
      </div>
      <div class="section">
        <h3>失败原因</h3>
        <pre class="console">${escapeHtml(data.error || "-")}</pre>
      </div>
      <div class="section">
        <h3>排查提示</h3>
        ${list([
          escapeHtml(data.hint || "请检查后端日志和模型交互记录。"),
          escapeHtml(data.model_record_hint || "如果使用测试模型，则不会生成真实模型交互记录。"),
        ])}
      </div>
      ${rawBlock(data)}
    `;
    return;
  }

  const result = data.result || {};
  if (data.mode === "agentic_model") {
    const steps = result.steps || [];
    const stepItems = steps.map((step) => {
      const action = step.decision?.action || "-";
      const args = JSON.stringify(step.decision?.arguments || {});
      const observation = JSON.stringify(step.observation || {});
      return `<strong>${escapeHtml(String(step.iteration || "-"))}. ${escapeHtml(action)}</strong><br><span>arguments: ${escapeHtml(args)}</span><br><span>observation: ${escapeHtml(observation)}</span>`;
    });
    output.innerHTML = `
      <div class="summary-grid">
        ${metric("任务类型", data.scenario?.task_type || "-")}
        ${metric("模式", "模型驱动循环")}
        ${metric("真实模型", "已调用")}
        ${metric("模型", data.model || "-")}
      </div>
      <div class="section">
        <h3>最终回答</h3>
        <pre class="standard-input">${escapeHtml(data.reply || result.reply || "-")}</pre>
      </div>
      <div class="section">
        <h3>模型动作与 Observation</h3>
        ${list(stepItems, "暂无执行步骤。")}
      </div>
      <div class="section">
        <h3>模型记录</h3>
        <ul class="soft-list"><li>${escapeHtml(data.model_record_hint || "logs/model_interactions/agentic_orchestration/<request_id>.txt")}</li></ul>
      </div>
      ${rawBlock(data)}
    `;
    return;
  }

  const plan = result.plan || {};
  const decisions = result.decisions || [];
  const artifacts = result.artifacts || {};
  const verification = result.verification || [];
  const requestId = result.request?.metadata?.request_id || "-";

  const planItems = (plan.steps || []).map((step) => {
    const tool = step.tool ? ` <span class="tag">${escapeHtml(step.tool)}</span>` : "";
    return `<strong>${escapeHtml(step.name)}</strong>${tool}<br><span>${escapeHtml(step.purpose)}</span>`;
  });

  const decisionItems = decisions.map((decision) => {
    const actions = (decision.recommended_actions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
    return `
      <strong>${escapeHtml(decision.material_code)} · ${escapeHtml(decision.risk_level)}</strong>
      <br>${escapeHtml(decision.summary)}
      <ul>${actions}</ul>
    `;
  });

  const artifactItems = Object.entries(artifacts).map(([name, value]) => {
    const size = Array.isArray(value) ? `${value.length} 条` : typeof value === "object" && value ? `${Object.keys(value).length} 项` : "1 项";
    return `<strong>${escapeHtml(name)}</strong><br><span>${escapeHtml(size)}</span>`;
  });

  output.innerHTML = `
    <div class="summary-grid">
      ${metric("任务类型", plan.task_type || data.scenario?.task_type || "-")}
      ${metric("置信度", plan.confidence ?? "-")}
      ${metric("请求 ID", requestId)}
      ${metric("真实模型", data.mode === "real_model" || data.mode === "agentic_model" ? "已调用" : "未调用")}
      ${metric("模型", data.model || "-")}
    </div>
    <div class="section">
      <h3>节点校验</h3>
      ${list((data.state_check?.expected || []).map((node) => {
        const ok = !(data.state_check?.missing || []).includes(node);
        return `<span class="tag ${ok ? "" : "fail"}">${ok ? "已出现" : "缺失"}</span> ${escapeHtml(node)}`;
      }), "暂无节点校验。")}
    </div>
    <div class="section">
      <h3>执行计划</h3>
      ${list(planItems)}
    </div>
    <div class="section">
      <h3>业务决策</h3>
      ${list(decisionItems, "这个场景没有产生决策，可能产生的是草稿或知识产物。")}
    </div>
    <div class="section">
      <h3>产物</h3>
      ${list(artifactItems, "暂无 artifact。")}
    </div>
    <div class="section">
      <h3>验证提示</h3>
      ${list(verification.map((item) => escapeHtml(item)))}
    </div>
    <div class="section">
      <h3>模型记录</h3>
      <ul class="soft-list"><li>${data.model_record_hint ? escapeHtml(data.model_record_hint) : "当前使用测试模型，不会生成真实模型交互记录。"}</li></ul>
    </div>
    ${rawBlock(data)}
  `;
}

function renderLlmModule(module) {
  const standard = JSON.stringify(module.standard_input || {}, null, 2);
  output.innerHTML = `
      <div class="summary-grid">
        ${metric("模块", module.name || module.id)}
        ${metric("真实模型", "待调用")}
        ${metric("模型", selectedModel() || "-")}
        ${metric("记录", "运行后生成")}
      </div>
    <div class="llm-debug-grid">
      <div class="section">
        <h3>标准输入</h3>
        <pre class="standard-input">${escapeHtml(standard)}</pre>
      </div>
      <div class="section">
        <h3>调试输入</h3>
        <textarea id="llmDebugInput" class="debug-input">${escapeHtml(standard)}</textarea>
        <div class="debug-actions">
          <button id="resetLlmInput">恢复标准输入</button>
          <button id="runLlmModule" class="primary">调用真实模型</button>
        </div>
      </div>
    </div>
    <div class="section">
      <h3>输入说明</h3>
      ${list(Object.entries(module.input_schema || {}).map(([key, value]) => `<strong>${escapeHtml(key)}</strong><br><span>${escapeHtml(value)}</span>`))}
    </div>
    <div class="section">
      <h3>期望输出</h3>
      <pre class="standard-input">${escapeHtml(JSON.stringify(module.expected_output || {}, null, 2))}</pre>
    </div>
  `;
  renderState([]);
  renderStateCheck(null);
  document.querySelector("#resetLlmInput").addEventListener("click", () => {
    document.querySelector("#llmDebugInput").value = standard;
  });
  document.querySelector("#runLlmModule").addEventListener("click", () => runLlmModule(module));
}

function renderLlmResult(data) {
  if (!data.ok) {
    output.innerHTML = `
      <div class="summary-grid">
        ${metric("调用结果", "失败", "fail")}
        ${metric("真实模型", "已尝试")}
        ${metric("模型", data.model || "-")}
        ${metric("记录", data.record_path || "-")}
      </div>
      <div class="section">
        <h3>失败原因</h3>
        <pre class="console">${escapeHtml(data.error || "-")}</pre>
      </div>
      ${rawBlock(data)}
    `;
    return;
  }

  const outputItems = Object.entries(data.output || {}).map(([key, value]) => {
    return `<strong>${escapeHtml(key)}</strong><br><span>${escapeHtml(JSON.stringify(value))}</span>`;
  });
  output.innerHTML = `
    <div class="summary-grid">
      ${metric("调用结果", "成功", "ok")}
      ${metric("真实模型", "已调用")}
      ${metric("模型", data.model || "-")}
      ${metric("记录", data.record_path || "-")}
    </div>
    <div class="section">
      <h3>调试输入</h3>
      <pre class="standard-input">${escapeHtml(JSON.stringify({ request: data.request, recent_context: data.recent_context }, null, 2))}</pre>
    </div>
    <div class="section">
      <h3>模型输出</h3>
      ${list(outputItems)}
    </div>
    ${rawBlock(data)}
  `;
}

function renderState(history = []) {
  stateFlow.innerHTML = "";
  if (!history.length) {
    stateFlow.innerHTML = '<div class="state-item"><strong>暂无状态流转</strong><span>测试输出没有 state_history。</span></div>';
    return;
  }
  for (const item of history) {
    const node = document.createElement("div");
    node.className = "state-item";
    node.innerHTML = `<strong>${item.from_status} -> ${item.to_status}</strong><span>${item.event} · ${item.timestamp}</span>`;
    stateFlow.appendChild(node);
  }
}

function renderStateCheck(check) {
  if (!check) {
    stateCheck.innerHTML = '<span class="tag warn">未进行节点校验</span><div class="sub">模块测试看输入输出合同和 unittest；业务场景会校验状态流转。</div>';
    return;
  }
  const tag = check.ok ? '<span class="tag">节点校验通过</span>' : '<span class="tag fail">节点缺失</span>';
  const missing = check.missing?.length ? `缺失：${check.missing.join(", ")}` : "期望节点均已出现";
  stateCheck.innerHTML = `${tag}<div class="sub">${escapeHtml(missing)}</div>`;
}

function makeButton(item, onClick) {
  const button = document.createElement("button");
  button.className = "item-button";
  button.innerHTML = `<span class="item-name">${item.name}</span><span class="item-desc">${item.description || item.text}</span>`;
  button.addEventListener("click", onClick);
  return button;
}

async function runTest(id, name) {
  setBusy(`运行测试：${name}`, "正在调用 unittest，请稍等。");
  const data = await api("/api/tests/run", {
    method: "POST",
    body: JSON.stringify({ id }),
  });
  statusLabel.innerHTML = data.ok ? `<span class="ok">测试通过：${name}</span>` : `<span class="fail">测试失败：${name}</span>`;
  subLabel.textContent = data.command || "";
  renderTestResult(data);
  renderState([]);
  renderStateCheck(null);
}

async function runScenario(id, name) {
  const mode = useRealModel.checked ? "真实模型" : "测试模型";
  setBusy(`运行场景：${name}`, `正在使用${mode}执行 agent 场景并收集状态流转。`);
  const data = await api("/api/scenarios/run", {
    method: "POST",
    body: JSON.stringify({ id, use_real_model: useRealModel.checked, model: selectedModel() }),
  });
  statusLabel.innerHTML = data.ok ? `<span class="ok">场景完成：${name}</span>` : `<span class="fail">场景失败：${name}</span>`;
  subLabel.textContent = data.scenario ? `任务类型：${data.scenario.task_type} · 模式：${data.mode || mode}` : "";
  renderScenarioResult(data);
  renderState(data.result?.state_history || []);
  renderStateCheck(data.state_check);
}

async function runLlmModule(module) {
  let input;
  try {
    input = JSON.parse(document.querySelector("#llmDebugInput").value || "{}");
  } catch (error) {
    output.insertAdjacentHTML(
      "afterbegin",
      `<div class="section"><pre class="console">调试输入不是合法 JSON：${escapeHtml(error.message)}</pre></div>`,
    );
    return;
  }
  setBusy(`调试模型：${module.name}`, "正在调用真实大模型并记录输入输出。");
  const data = await api("/api/llm/run", {
    method: "POST",
    body: JSON.stringify({ id: module.id, input, model: selectedModel() }),
  });
  statusLabel.innerHTML = data.ok ? `<span class="ok">模型调用成功：${module.name}</span>` : `<span class="fail">模型调用失败：${module.name}</span>`;
  subLabel.textContent = data.record_path || "";
  renderLlmResult(data);
  renderState([]);
  renderStateCheck(null);
}

async function boot() {
  const [tests, scenarios, contracts, llmModules, modelOptions] = await Promise.all([
    api("/api/tests"),
    api("/api/scenarios"),
    api("/api/contracts"),
    api("/api/llm/modules"),
    api("/api/model-options"),
  ]);
  testList.innerHTML = "";
  scenarioList.innerHTML = "";
  contractList.innerHTML = "";
  llmModuleList.innerHTML = "";
  modelSelect.innerHTML = "";

  for (const model of modelOptions.options || []) {
    const option = document.createElement("option");
    option.value = model;
    option.textContent = model === modelOptions.default_model ? `${model}（默认）` : model;
    modelSelect.appendChild(option);
  }
  modelSelect.value = modelOptions.default_model || modelSelect.value;

  for (const item of contracts.contracts) {
    const node = document.createElement("div");
    node.className = "contract";
    node.innerHTML = `
      <strong>${escapeHtml(item.module)}</strong>
      <span>输入：${escapeHtml(item.input)}</span>
      <span>输出：${escapeHtml(item.expected_output)}</span>
      <span>节点：${escapeHtml((item.expected_nodes || []).join(" -> "))}</span>
    `;
    contractList.appendChild(node);
  }

  for (const item of tests.tests) {
    testList.appendChild(makeButton(item, () => runTest(item.id, item.name)));
  }

  for (const item of scenarios.scenarios) {
    scenarioList.appendChild(makeButton(item, () => runScenario(item.id, item.name)));
  }

  for (const item of llmModules.modules) {
    llmModuleList.appendChild(makeButton(item, () => {
      statusLabel.textContent = `模型调试：${item.name}`;
      subLabel.textContent = item.description || "";
      renderLlmModule(item);
    }));
  }
}

runAll.addEventListener("click", () => runTest("all", "全部测试"));
boot().catch((error) => {
  statusLabel.innerHTML = '<span class="fail">前端初始化失败</span>';
  output.textContent = String(error);
});
