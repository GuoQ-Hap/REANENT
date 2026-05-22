const form = document.querySelector("#chatForm");
const input = document.querySelector("#chatInput");
const messages = document.querySelector("#messages");
const useRealModel = document.querySelector("#useRealModel");
const modelSelect = document.querySelector("#modelSelect");
const recentContext = [];

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

async function sendMessage(text) {
  const response = await fetch("/api/chat/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text,
      use_real_model: useRealModel.checked,
      model: modelSelect.value,
      recent_context: recentContext.slice(-8),
    }),
  });
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

  try {
    const data = await sendMessage(text);
    const reply = data.ok ? data.reply : `${data.error || "请求失败"}\n${data.hint || ""}`.trim();
    loading.textContent = reply;
    recentContext.push({ role: "assistant", content: reply || "（空回复）" });
    if (data.result?.steps?.length) {
      const lastObservation = data.result.steps[data.result.steps.length - 1]?.observation || {};
      const firstObservation = data.result.steps.find((step) => step.observation?.query_material_code)?.observation;
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
  } catch (error) {
    loading.textContent = `请求失败：${error.message}`;
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
