# PMC Inventory Supply Chain Control Agent

This repository is a first-pass framework for a PMC supply chain control agent. It is intentionally small: the core loop is separated from model providers, ERP/MES/WMS connectors, and UI layers so each part can be replaced safely.

## What This Framework Covers

- Task classification for PMC control requests from the project proposal.
- Lightweight planning with explicit execution steps.
- Tool registry for inventory health, control tower, shortage tracing, shipment verification, purchase verification, weekly shipment plan, exception cases, and knowledge lookup.
- A deterministic inventory-control baseline for early validation.
- CLI entry point for local smoke tests.
- Optional FastAPI entry point for integration later.

## Architecture

```text
User / System Trigger
  -> Classifier
  -> Planner
  -> Orchestrator
  -> Tool Registry
  -> Domain Decision Engine
  -> Verifier
  -> Response
```

## Suggested Next Integrations

- Data warehouse: `ads_lingxing_all_warehouse_new_v1`, `dim_inventory_forecast_v1`, `dim_inventory_forecast_v1_fh`, sales daily, FBA inventory, domestic warehouse inventory.
- Rule Excel files: stocking rules, reorder quantity, carton size, supplier data, logistics rules.
- Business workflows: PMC confirmation, purchase confirmation, logistics confirmation, operations impact review.
- LLM provider: the intent recognizer is already model-backed; next, extend model use into multi-step tool-calling orchestration.

See [docs/requirements_extracted.md](docs/requirements_extracted.md) for the extracted project requirements from the rendered PDF.
See [docs/llm_working_standard.md](docs/llm_working_standard.md) for the working standard used by future LLM-assisted development.

## Startup Commands

Run commands from the repository root: `D:\R_TO_AG`.

Start the local test console, which can run module tests and business scenarios without a real model key:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.test_server
```

Then open:

```text
http://127.0.0.1:8765
```

Simple chat window:

```text
http://127.0.0.1:8765/chat.html
```

Run the CLI agent with a real model-backed intent recognizer:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.cli "检查 A100 是否有缺料风险"
```

Run the goal loop with user feedback applied to the next iteration:

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.cli "验证 A100 采购建议" --feedback "请按 MOQ 和人工确认边界重新检查"
```

Model routing is handled by `pmc_agent.model_router`. You can inspect it in the test console under 模型调试 -> 模型调度.

Run all unit tests:

```powershell
$env:PYTHONPATH="src"; python -m unittest discover -s tests
```

Optional FastAPI entry point, after installing the `api` extra:

```powershell
$env:PYTHONPATH="src"; uvicorn pmc_agent.api:app --reload
```

## Run

The default CLI uses a model-backed intent recognizer. Copy `.env.example` to `.env`, then fill in your key and API URL:

```powershell
Copy-Item .env.example .env
```

`.env`:

```dotenv
OPENAI_API_KEY=your_api_key
PMC_AGENT_INTENT_MODEL=gpt-5.4-mini
PMC_AGENT_MODEL_DEFAULT=gpt-5.4-mini
PMC_AGENT_MODEL_INTENT_RECOGNITION=gpt-5.4-mini
PMC_AGENT_MODEL_GOAL_REPAIR=gpt-5.4
PMC_AGENT_MODEL_TOOL_ORCHESTRATION=gpt-5.4
PMC_AGENT_MODEL_FAILURE_HANDLING=gpt-5.4
PMC_AGENT_MODEL_BUSINESS_EXPLANATION=gpt-5.4
PMC_AGENT_MODEL_SUMMARY=gpt-5.4-mini
PMC_AGENT_MODEL_HIGH_RISK=gpt-5.4
PMC_AGENT_MODEL_LONG_CONTEXT_THRESHOLD=4000
OPENAI_BASE_URL=https://api.openai.com/v1
PMC_AGENT_HTTP_TIMEOUT=30
PMC_AGENT_LOG_LEVEL=INFO
STI_DB_ENABLED=false
STI_DB_HOST=
STI_DB_PORT=9030
STI_DB_USER=
STI_DB_PASSWORD=
STI_DB_NAME=dw_leang
STI_DB_CHARSET=utf8mb4
```

Use the CLI commands from [Startup Commands](#startup-commands) after `.env` is configured.

The `--feedback` option turns on a lightweight goal loop. The first iteration runs the original goal; each feedback item is merged with the previous observation and executed as the next iteration.

## Database Connector

Set `STI_DB_ENABLED=true` in `.env` to use the read-only STI data warehouse connector. The current implementation reads inventory snapshots from `ads_lingxing_all_warehouse_new_v1`.

When the database connector is enabled, query failures and empty results are treated as real failures and returned to the caller. Demo data is used only when the database connector is disabled.

The connector only performs `SELECT` queries. Control advice and exception handling remain draft outputs inside the agent and are not written back to the database.

## Model Routing

Model names are centralized in [src/pmc_agent/model_router.py](src/pmc_agent/model_router.py). Business modules should pass an action type, content, and metadata to the router instead of hard-coding model names.

Current action routes:

- `intent_recognition`: understand the user's request and classify task type.
- `goal_repair`: revise the goal after user feedback.
- `tool_orchestration`: choose or sequence tool calls in future dynamic loops.
- `failure_handling`: decide how to respond when a real tool or database query fails.
- `business_explanation`: produce higher-stakes business explanations.
- `summary`: compress observations and execution output.

High-risk content such as purchase confirmation, exception handling, approval, or explicit high-risk metadata is routed to `PMC_AGENT_MODEL_HIGH_RISK`.

## Model-Driven Chat Loop

The chat frontend uses two modes:

- Local demo mode: deterministic heuristic intent recognition for quick UI checks without a model key.
- Real model mode: `pmc_agent.agentic_loop.AgenticPmcLoop` sends the user request, table pool summary, and available tool list to the model first. The model chooses an action, the program executes only that whitelisted action, then returns the observation to the model. The loop continues until the model returns `final_answer` or asks the user for missing input.
- The loop runs up to 20 tool-decision iterations. If the limit is reached, the collected decisions and observations are sent back to the model once more so it must summarize directly with `final_answer`.

Current whitelisted model actions:

- `query_inventory_snapshot`: read inventory snapshots from the read-only STI connector.
- `evaluate_inventory_risk`: calculate risk from the latest returned snapshots.
- `ask_user`: ask for missing code, scope, or confirmation.
- `final_answer`: return the final answer to the user.

This means real model mode is not "local code classifies first"; the model controls the next step while code enforces read-only tools and schema boundaries.

## Test

Use the unit-test command from [Startup Commands](#startup-commands).

## Test Frontend

The local test console runs without a real model key. It injects scenario intent results so module tests and agent scenarios can be checked quickly:

Use the test-console command from [Startup Commands](#startup-commands), then open `http://127.0.0.1:8765`.

For a simple conversation UI, open `http://127.0.0.1:8765/chat.html`.

## Runtime Records

- 状态流转会进入标准日志，事件名为 `state_transition`。
- 模型交互会按类型和时间 ID 落盘：`logs/model_interactions/<interaction_type>/<time_id>.txt`。
- `logs/` 已加入 `.gitignore`，用于本地测试和审计，不进入代码仓库。
