# 大模型继续任务工作标准

本文档用于约束后续由大模型或开发人员继续推进 PMC 库存供应链智能体项目时的工作方式。目标是保证每次改动都可理解、可测试、可追踪、可回滚。

## 1. 基本原则

- 先读上下文，再动代码：优先阅读 `README.md`、`docs/architecture.md`、`docs/requirements_extracted.md` 和相关源码。
- 不做无关重构：每次改动只围绕当前任务，避免顺手大改。
- 不覆盖用户已有改动：如果工作区已有变化，必须先理解，再在此基础上继续。
- 业务计算必须可复算：库存数量、采购量、发货量、日期、金额等结果必须由规则工具计算，不能由大模型直接生成。
- 高风险动作必须人工确认：采购单创建、发货单调整、库存或订单写回、规则变更等动作不能自动执行。

## 2. 模块边界

当前项目主要模块如下：

- `planning`：意图识别结果承接、计划生成。
- `model`：大模型客户端、结构化意图识别、后续 tool-calling 接口。
- `tools`：库存健康、控制塔、断货追因、发货验证、采购验证、周度计划、异常 Case、知识库工具。
- `connectors`：ERP、FBA、WMS、数据仓库、Excel 规则表等外部数据连接。
- `orchestrator`：Agent 主流程，串联请求、计划、工具、验证、结果。
- `verifier`：验证输出是否完整、是否需要人工确认、是否存在假设。
- `cli` / `api`：命令行与 HTTP 接口入口。

新增功能时，必须先判断属于哪个模块；跨模块改动需要说明接口变化。

## 3. 测试标准

每个模块都需要独立测试。不能只依赖端到端示例。

### 3.1 模块级测试

- `planning`：测试不同模型意图输出能生成正确计划。
- `model`：测试模型响应解析、异常响应、缺少字段、非法 `task_type`。
- `tools`：每个业务工具都要有独立测试，包括正常场景、边界场景、缺数据场景。
- `connectors`：测试字段映射、空数据、异常数据、连接失败。
- `orchestrator`：测试完整流程、工具调用顺序、artifact 输出、人工确认提示。
- `verifier`：测试决策输出、artifact 输出、无数据输出、含假设输出。
- `cli` / `api`：测试参数解析、环境变量加载、错误提示。

### 3.2 测试命名

测试文件建议按模块命名：

```text
tests/test_planning.py
tests/test_model.py
tests/test_tools_inventory.py
tests/test_tools_purchase.py
tests/test_connectors.py
tests/test_orchestrator.py
tests/test_verifier.py
tests/test_env_and_logging.py
```

### 3.3 最低测试要求

每次新增或修改模块时，必须满足：

- 至少新增或更新一个对应模块测试。
- 涉及业务计算时，必须测试输入、输出和关键中间证据。
- 涉及异常处理时，必须测试失败路径。
- 涉及权限或人工确认时，必须测试不会自动执行高风险动作。
- 所有测试必须能通过：

```powershell
$env:PYTHONPATH='src'; python -m unittest discover -s tests
```

## 4. 日志标准

每个模块都需要输出对应日志，日志必须分级。日志用于定位问题、审计流程和解释 Agent 决策，不用于泄露密钥或敏感数据。

当前框架已提供统一日志入口：`src/pmc_agent/app_logging.py`。新增模块应通过 `get_logger(__name__)` 获取日志器，并通过 `log_extra(...)` 填充结构化字段。

状态流转必须和日志绑定。当前框架通过 `src/pmc_agent/state.py` 管理运行状态，每次流转都会输出 `state_transition` 日志。

测试阶段，所有模型交互输入输出必须落盘。当前路径规范为：

```text
logs/model_interactions/<interaction_type>/<time_id>.txt
```

其中 `<interaction_type>` 表示模型交互类型，例如 `intent_recognition`；`<time_id>` 由当前时间生成，用于关联本次运行日志和模型交互记录。

### 4.1 日志级别

统一使用以下级别：

- `DEBUG`：开发调试信息，例如工具入参摘要、候选计划、字段映射细节。
- `INFO`：正常业务流程信息，例如任务开始、意图识别完成、工具调用完成、计划生成完成。
- `WARNING`：可恢复异常或业务风险，例如缺少部分字段、使用默认值、存在人工确认假设。
- `ERROR`：当前步骤失败但系统仍可返回错误信息，例如连接失败、模型响应格式错误、规则计算失败。
- `CRITICAL`：系统不可继续或存在高风险操作，例如权限绕过、关键数据源不可用且无替代路径。

### 4.2 各模块日志要求

- `planning`
  - `INFO`：记录意图类型、置信度、计划步骤数量。
  - `WARNING`：记录低置信度、上下文不足、需要人工澄清。

- `model`
  - `INFO`：记录模型名称、请求类型、结构化解析成功。
  - `WARNING`：记录模型返回低置信度或需要澄清。
  - `ERROR`：记录 API 调用失败、超时、JSON 解析失败。

- `tools`
  - `INFO`：记录工具名称、处理对象、输出结果数量。
  - `WARNING`：记录缺字段、缺数据、规则兜底、需要人工确认。
  - `ERROR`：记录计算失败、非法输入、规则冲突。

- `connectors`
  - `INFO`：记录数据源名称、查询对象、返回记录数。
  - `WARNING`：记录空结果、字段缺失、数据延迟。
  - `ERROR`：记录连接失败、认证失败、查询失败。

- `orchestrator`
  - `INFO`：记录任务开始、计划完成、工具调用完成、验证完成。
  - `WARNING`：记录工具预算接近上限、计划存在假设、需要人工确认。
  - `ERROR`：记录流程中断和失败步骤。

- `verifier`
  - `INFO`：记录验证通过项。
  - `WARNING`：记录残余风险、假设、人工复核点。
  - `ERROR`：记录输出缺失、证据不足、不可解释结果。

### 4.3 日志格式

建议使用结构化日志字段：

```text
timestamp | level | module | event | request_id | task_type | message | extra
```

示例：

```text
2026-05-20T10:30:00Z | INFO | orchestrator | task_started | req-001 | shortage_trace | request received | {"material_code":"A100"}
2026-05-20T10:30:02Z | WARNING | tools.purchase | manual_confirmation_required | req-001 | purchase_verification | purchase advice generated as draft only | {"material_code":"A100"}
2026-05-20T10:30:03Z | ERROR | model.intent | response_parse_failed | req-001 | unknown | model response missing task_type | {}
```

### 4.4 日志安全

- 禁止记录 API Key、数据库密码、Cookie、Token。
- 禁止记录完整个人敏感信息。
- 业务数据日志只记录必要摘要，例如 SKU、数量、风险等级、数据源名称。
- 大模型请求和响应如果需要落盘，必须脱敏，并明确用途。

## 5. 交付标准

每次任务完成时，必须说明：

- 改了哪些文件。
- 新增或修改了哪些模块。
- 对应测试是什么。
- 运行了哪些验证命令。
- 是否还有未解决风险或需要人工确认的点。

如果无法运行测试，必须说明原因，不能假装已验证。

## 6. 大模型接手任务流程

推荐流程：

```text
读取需求和架构文档
  -> 确认涉及模块
  -> 查看现有测试
  -> 做最小实现
  -> 为对应模块补测试
  -> 为对应模块补日志
  -> 运行测试
  -> 总结改动、验证和风险
```

## 7. 禁止事项

- 禁止用关键词规则替代模型意图识别。
- 禁止让大模型直接编造库存、采购、发货、金额、日期等结果。
- 禁止没有测试就修改业务计算逻辑。
- 禁止没有日志就新增工具或连接器。
- 禁止自动执行采购单创建、订单修改、库存写回、发货单调整等高风险动作。
- 禁止吞掉异常后返回“成功”。
