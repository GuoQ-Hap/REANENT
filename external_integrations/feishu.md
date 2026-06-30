# 飞书对接

## 1. 对接目标

飞书对接用于让 PMC 库存供应链智能体进入日常协作场景，支持用户在飞书内发起库存风险、断货追因、发货验证、采购验证、周度计划和异常 Case 等查询，并把智能体的结果回传到飞书会话或审批协作流程。

首期目标：

- 支持飞书机器人接收用户消息并转发给智能体 HTTP API。
- 支持智能体把结构化结果回传到飞书单聊、群聊或指定线程。
- 高风险动作只返回建议草稿和人工确认点，不在飞书中直接执行采购、发货或关单动作。
- 保留请求、响应、异常和人工确认记录，便于审计与复盘。

## 2. 接入边界

飞书只作为外部交互入口和通知出口，不承载 PMC 业务计算。

```text
飞书用户 / 群聊
  -> 飞书机器人事件
  -> 外部对接服务
  -> PMC Agent HTTP API
  -> 工具与数据连接层
  -> 结果摘要 / 草稿 / 人工确认点
  -> 飞书消息回传
```

职责分工：

- 飞书：身份入口、消息入口、群聊上下文、通知触达。
- 外部对接服务：验签、鉴权、消息标准化、限流、重试、错误兜底。
- PMC Agent：意图理解、工具编排、业务计算、结果解释、风险提示。
- 人工确认人：确认采购建议、发货计划、异常 Case 关闭等高风险动作。

## 3. 固定接口

当前项目参考 `D:\laydown\ric-train-master` 中的飞书实现，采用 `lark-oapi` WebSocket 长连接方式接入飞书。固定接口放在：

```text
src/pmc_agent/external_integrations/feishu.py
```

固定接口分三层：

| 层级 | 类 / 协议 | 职责 |
| --- | --- | --- |
| 配置层 | `FeishuConfig` | 从环境变量读取飞书开关、应用凭证、机器人名称、线程数和消息长度 |
| 入参层 | `FeishuInboundMessage` | 把飞书消息标准化为 Agent 可处理的固定结构 |
| 业务层 | `FeishuMessageHandler` | 业务处理协议，只接收标准消息并返回文本 |
| 默认实现 | `PmcAgentFeishuHandler` | 调用 PMC Agent 并把结果格式化为飞书可回复文本 |
| SDK 适配层 | `FeishuBot` | 只负责飞书 WebSocket、事件解析、群聊去 @、文本回复和异常兜底 |
| 审核配置 | `FeishuWorkflowConfig` | 配置卡片审核、流程审批、审批码、审核群和路由规则 |
| 审核请求 | `FeishuReviewRequest` | 统一承载卡片审核和流程审批的业务请求 |
| 审核服务 | `FeishuWorkflowService` | 按配置决定走飞书卡片审核或飞书流程审批 |
| 卡片审核协议 | `FeishuReviewClient` | 提交飞书审核卡片，并解析卡片回调 |
| 流程审批协议 | `FeishuApprovalClient` | 创建飞书审批实例，并解析审批回调 |

### 3.1 固定入参

所有飞书文本消息进入 Agent 前统一转成 `FeishuInboundMessage`：

```python
@dataclass(frozen=True)
class FeishuInboundMessage:
    message_id: str
    chat_id: str
    chat_type: str
    text: str
    open_id: str = ""
    user_id: str = ""
    tenant_key: str = ""
    event_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

其中：

- `message_id`：用于回复原始飞书消息。
- `chat_id`：用于识别单聊或群聊上下文。
- `chat_type`：用于区分 `p2p` 和 `group`。
- `text`：已经解析并去掉群聊 @ 的用户问题。
- `open_id` / `user_id`：用于用户身份映射和权限控制。
- `session_id`：由接口按群聊或用户生成，规则为 `pmc-feishu-chat-{chat_id}` 或 `pmc-feishu-user-{open_id}`。

### 3.2 固定业务协议

飞书 SDK 不直接调用业务逻辑，只调用固定协议：

```python
class FeishuMessageHandler(Protocol):
    def handle_message(self, message: FeishuInboundMessage) -> str:
        ...
```

后续审核、通知、反馈都应扩展这个协议或在协议之上新增明确方法，不把 `lark_oapi` 对象传入 Agent 层。

### 3.3 审核 / 审批可配置接口

飞书审核和飞书流程审批统一从 `FeishuWorkflowService.submit()` 进入：

```python
from pmc_agent.external_integrations.feishu import FeishuReviewRequest, FeishuWorkflowService

service = FeishuWorkflowService()
result = service.submit(
    FeishuReviewRequest(
        request_id="req_001",
        business_type="purchase_confirmation",
        title="采购建议审批",
        summary="高风险，建议采购 500 件",
        risk_level="high",
        suggested_action="提交采购确认",
        reviewer_open_ids=("ou_pmc", "ou_purchase"),
    )
)
```

路由规则：

- `FEISHU_REVIEW_MODE=card`：始终走飞书卡片审核。
- `FEISHU_REVIEW_MODE=approval`：优先走飞书流程审批。
- `FEISHU_REVIEW_MODE=card_or_approval`：按业务类型和风险等级自动选择。
- `FEISHU_APPROVAL_ENABLED=false`：即使命中审批规则，也回落到卡片审核。
- `FEISHU_APPROVAL_BUSINESS_TYPES`：配置哪些业务类型需要审批。
- `FEISHU_APPROVAL_RISK_LEVELS`：配置哪些风险等级需要审批。

当前测试版内置 `InMemoryFeishuReviewClient` 和 `InMemoryFeishuApprovalClient`，用于本地跑通接口契约。接真实飞书时，实现 `FeishuReviewClient` 和 `FeishuApprovalClient` 即可，不需要改 Agent 调用方。

回调统一解析为 `FeishuWorkflowCallback`：

```python
callback = service.parse_callback(
    {
        "source": "feishu_approval",
        "approval_id": "approval-req_001",
        "request_id": "req_001",
        "action": "approve",
        "operator_open_id": "ou_manager",
        "comment": "同意",
    }
)
```

本地测试命令：

```powershell
$env:PYTHONPATH="src"; python -m unittest tests.test_feishu_integration
```

### 3.4 启动方式

安装飞书可选依赖：

```powershell
pip install -e .[feishu]
```

配置 `.env`：

```dotenv
FEISHU_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_BOT_NAME=PMC库存智能体
FEISHU_MAX_WORKERS=4
FEISHU_MAX_MESSAGE_LENGTH=3500
```

单独启动飞书机器人：

```powershell
$env:PYTHONPATH="src"; python -m pmc_agent.feishu_app
```

如果未来要和 FastAPI 同进程启动，可以在应用启动钩子中调用：

```python
from pmc_agent.external_integrations.feishu import create_default_feishu_bot

feishu_bot = create_default_feishu_bot()
feishu_bot.start_in_thread()
```

注意：参考项目中提到 `lark_oapi.ws.client` 会缓存事件循环。如果同一进程启动多个飞书机器人，需要放到同一个线程和同一个事件循环中统一管理。

## 4. 首期功能

### 4.1 用户消息触发

支持用户在飞书中通过机器人发起自然语言请求：

```text
检查 A100 是否有缺料风险
追一下 FNSKU B0XXXX 的断货原因
复算本周美国站 SKU123 的发货建议
验证供应商 S001 的采购建议是否满足 MOQ
```

外部对接服务需要把飞书事件转换为统一请求：

```json
{
  "source": "feishu",
  "event_id": "event id from feishu",
  "tenant_key": "tenant key from feishu",
  "chat_id": "target chat id",
  "message_id": "source message id",
  "sender": {
    "open_id": "sender open id",
    "user_id": "optional user id"
  },
  "text": "用户原始消息",
  "metadata": {
    "chat_type": "p2p or group",
    "thread_id": "optional thread id"
  }
}
```

### 4.2 结果回传

智能体返回结果后，外部对接服务按消息类型回传到飞书：

- 普通查询：回传简洁文本或卡片。
- 风险摘要：回传风险等级、关键原因、建议动作、需人工确认项。
- 长结果：先回传摘要，再附带明细链接或文件。
- 异常失败：回传可理解的错误原因和下一步建议。

建议飞书消息包含：

- 结论：是否有风险、是否需要处理。
- 依据：关键库存、预测、在途、交期、规则命中。
- 建议：下一步动作草稿。
- 边界：哪些动作必须人工确认。
- 追踪信息：请求 ID、时间、数据口径或快照时间。

### 4.3 高风险动作

以下动作必须停留在草稿或确认态：

- 采购建议确认或下发。
- 发货计划确认或下发。
- 异常 Case 关闭。
- 影响库存、订单、金额、供应商或物流计划的写操作。

飞书侧可展示“确认人”“确认状态”“确认备注”，但首期不直接写回业务系统。

### 4.4 审核流程

审核流程建议分两层落地：轻量确认使用飞书消息卡片，正式审批使用飞书审批。这样既能让日常 PMC 协作足够快，也能让采购、发货、异常关闭等动作有明确留痕。

推荐流程：

```text
Agent 生成建议草稿
  -> 判断风险等级和动作类型
  -> 低风险：飞书卡片确认
  -> 高风险：创建飞书审批单
  -> 审核人处理
  -> 外部对接服务接收审批结果
  -> 更新任务状态 / 回传结果 / 记录审计
```

适合走飞书卡片确认的场景：

- 单 SKU 风险解释确认。
- 小范围发货建议复核。
- 异常 Case 补充信息确认。
- 仅影响智能体状态、不直接写业务系统的动作。

适合走飞书审批的场景：

- 采购建议确认。
- 周度发货计划确认。
- 异常 Case 关闭。
- 涉及金额、供应商、物流渠道、交期承诺或跨部门责任的动作。

飞书卡片建议包含：

- 业务对象：SKU、FNSKU、店铺、国家、供应商、仓库等。
- 建议动作：采购、发货、调拨、暂缓、建 Case、关闭 Case。
- 关键依据：库存、销量、预测、在途、MOQ、箱规、交期、风险等级。
- 按钮动作：同意、驳回、要求补充、转审批、查看明细。
- 审计字段：请求 ID、建议版本、生成时间、确认人、确认时间。

审批单字段建议：

| 字段 | 说明 |
| --- | --- |
| 审批类型 | 采购确认、发货确认、异常关闭、规则例外 |
| 业务对象 | SKU、FNSKU、店铺、国家、供应商、仓库 |
| 建议摘要 | Agent 生成的业务结论和动作草稿 |
| 关键依据 | 库存、预测、在途、交期、规则命中、风险等级 |
| 影响范围 | 数量、金额、时间窗口、责任部门 |
| 审核人 | PMC、采购、物流、运营或管理层 |
| 审核结论 | 通过、驳回、退回补充、转交 |
| 审核备注 | 人工修改原因或补充意见 |
| 追踪信息 | request_id、message_id、approval_id、建议版本 |

审核状态建议统一为：

```text
draft -> pending_review -> approved / rejected / need_more_info / cancelled
```

状态处理原则：

- `draft`：Agent 已生成草稿，尚未提交审核。
- `pending_review`：已发送飞书卡片或创建审批单，等待人工处理。
- `approved`：审核通过，可进入后续人工执行或业务系统写回队列。
- `rejected`：审核驳回，需要记录原因并停止后续动作。
- `need_more_info`：审核人要求补充信息，Agent 重新取数或追问用户。
- `cancelled`：请求被发起人或系统取消。

### 4.5 通知-反馈流程

通知-反馈流程建议以“群通知 + 线程反馈 + 状态闭环”落地。飞书群用于触达责任人，消息线程用于沉淀讨论，按钮或回复用于把反馈带回智能体。

推荐流程：

```text
定时任务 / 风险触发 / 用户查询
  -> Agent 生成风险摘要
  -> 按责任规则选择飞书群和责任人
  -> 发送飞书通知卡片
  -> 用户点击按钮或在线程回复
  -> 外部对接服务标准化反馈
  -> Agent 更新结论、补充追因或生成下一步动作
  -> 回传处理状态
```

通知类型建议：

| 通知类型 | 触发条件 | 接收人 | 反馈方式 |
| --- | --- | --- | --- |
| 高风险断货预警 | 可售天数低于阈值或预测断货 | PMC、运营、采购 | 确认风险、补充原因、生成 Case |
| 发货计划提醒 | 周度计划生成或临近发货窗口 | PMC、物流、运营 | 确认发货、调整数量、暂缓 |
| 采购建议提醒 | 采购参考量生成或 MOQ 命中 | PMC、采购 | 同意、驳回、修改数量、转审批 |
| 异常 Case 跟进 | Case 超时、状态停滞、责任人未反馈 | 责任人、负责人 | 更新状态、补充备注、关闭申请 |
| 日报 / 周报 | 定时汇总 | 管理层、PMC | 查看明细、订阅、取消订阅 |

飞书通知卡片建议包含：

- 标题：风险等级 + 业务对象 + 建议动作。
- 摘要：一句话说明为什么需要处理。
- 指标：库存、销量、预测、在途、交期、缺口、建议量。
- 责任：责任人、协同部门、截止时间。
- 动作：确认已知、生成 Case、提交审核、要求补充、查看明细。
- 状态：待处理、处理中、待审核、已关闭。

反馈入口建议同时支持三种：

- 按钮反馈：用于结构化动作，例如确认、驳回、转审批、关闭。
- 线程回复：用于补充自然语言原因，例如“供应商已确认提前 3 天交货”。
- 表单反馈：用于需要结构化字段的修改，例如采购数量、发货数量、预计到仓日。

外部对接服务需要把反馈标准化：

```json
{
  "source": "feishu",
  "feedback_type": "card_action or thread_reply or form_submit",
  "request_id": "agent request id",
  "message_id": "feishu message id",
  "approval_id": "optional approval id",
  "operator": {
    "open_id": "operator open id",
    "role": "pmc or purchase or logistics or ops"
  },
  "action": "approve or reject or need_more_info or comment or update_fields",
  "comment": "人工反馈内容",
  "fields": {
    "suggested_qty": 120,
    "expected_arrival_date": "2026-06-05"
  }
}
```

通知-反馈闭环需要满足：

- 每条通知都有唯一 `request_id`，可以追溯到 Agent 计算结果。
- 用户反馈必须关联原始消息或审批单，避免孤立备注。
- 结构化按钮优先驱动状态流转，自然语言回复进入备注和二次分析。
- 超时未反馈时自动提醒责任人，必要时升级到负责人。
- 任何人工修改都需要记录修改前后值、修改人、修改时间和修改原因。

## 5. 配置项

配置项不得写入仓库真实值，生产环境通过 `.env`、密钥管理系统或部署平台注入。

```dotenv
# 飞书对接开关。
FEISHU_ENABLED=false

# 飞书应用凭证。
FEISHU_APP_ID=
FEISHU_APP_SECRET=

# 事件回调安全配置。
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=

# 消息路由配置。
FEISHU_DEFAULT_CHAT_ID=
FEISHU_BOT_NAME=PMC库存智能体
FEISHU_MAX_WORKERS=4
FEISHU_RISK_ALERT_CHAT_ID=
FEISHU_PURCHASE_REVIEW_CHAT_ID=
FEISHU_SHIPMENT_REVIEW_CHAT_ID=
FEISHU_CASE_FOLLOWUP_CHAT_ID=

# 对接行为配置。
FEISHU_REQUEST_TIMEOUT=10
FEISHU_RETRY_MAX_ATTEMPTS=3
FEISHU_MAX_MESSAGE_LENGTH=3500

# 审核和反馈行为配置。
FEISHU_REVIEW_ENABLED=true
FEISHU_REVIEW_MODE=card_or_approval
FEISHU_APPROVAL_ENABLED=false
FEISHU_APPROVAL_BUSINESS_TYPES=purchase_confirmation,shipment_confirmation,case_close
FEISHU_APPROVAL_RISK_LEVELS=critical,high
FEISHU_APPROVAL_PURCHASE_CODE=
FEISHU_APPROVAL_SHIPMENT_CODE=
FEISHU_APPROVAL_CASE_CLOSE_CODE=
FEISHU_FEEDBACK_REMIND_INTERVAL_MINUTES=120
FEISHU_FEEDBACK_ESCALATE_AFTER_HOURS=24
```

## 6. 权限与安全

- 仅申请首期必需的机器人收发消息、读取用户基础身份、读取群聊上下文等权限。
- 回调入口必须校验来源、签名、事件 ID 和时间窗口，避免重放请求。
- 密钥不得进入代码仓库、日志、飞书消息或模型上下文。
- 用户身份需要映射到系统角色，执行数据权限过滤。
- 群聊请求默认只返回用户有权查看的数据范围。
- 日志中保留请求 ID、用户标识、群聊标识、任务类型、工具调用状态和错误信息；避免记录完整敏感业务明细。

## 7. 错误处理

常见错误与处理策略：

| 场景 | 处理方式 |
| --- | --- |
| 飞书验签失败 | 拒绝请求，记录安全日志 |
| 消息为空或无法解析 | 回传需要补充的信息 |
| 用户权限不足 | 回传无权限说明，不暴露数据 |
| Agent API 超时 | 回传处理中或失败提示，后台可重试 |
| 飞书回传失败 | 记录失败原因，按重试策略补发 |
| 结果超过长度限制 | 回传摘要，明细改为文件或链接 |

## 8. 组织架构同步

飞书组织架构同步独立放在：

```text
src/pmc_agent/external_integrations/feishu_directory.py
```

当前实现支持：

- 使用 `POST /open-apis/auth/v3/tenant_access_token/internal` 获取并缓存 `tenant_access_token`。
- 使用 `POST /open-apis/directory/v1/departments/filter` 从 `parent_department_id=0` 开始递归拉取部门树。
- 使用 `POST /open-apis/directory/v1/employees/filter` 按部门组合 `base_info.departments.department_id` 和 `work_info.staff_status=1` 拉取在职员工。
- 员工按 `employee_id/open_id/user_id` 去重，并展开员工多部门关系。
- 本批次未出现的历史员工会追加一条 `inactive_missing_from_sync` 记录，避免离职人员长期停留在在职池。
- 提供 `mget_departments()` 和 `mget_employees()`，用于后续按 ID 批量补全详情。

默认 JSONL 输出目录为：

```text
output/feishu_directory
```

输出文件对应建议的三张主数据表：

```text
sys_company_department.jsonl
sys_company_employee.jsonl
sys_company_employee_department.jsonl
sys_company_directory_sync_run.jsonl
```

手动同步命令：

```powershell
$env:PYTHONPATH="src"; python scripts/sync_feishu_directory.py --force
```

只验证接口和统计数量、不写文件：

```powershell
$env:PYTHONPATH="src"; python scripts/sync_feishu_directory.py --force --dry-run
```

需要配置：

```dotenv
FEISHU_DIRECTORY_SYNC_ENABLED=true
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_DIRECTORY_ROOT_DEPARTMENT_ID=0
FEISHU_DIRECTORY_OUTPUT_DIR=output/feishu_directory
```

## 9. 验收清单

- 飞书机器人可以在单聊和群聊中收到用户消息。
- 外部对接服务可以完成飞书事件验签与去重。
- 用户消息可以转换为 PMC Agent 的统一请求格式。
- 智能体结果可以回传到原始会话。
- 审核流程可以通过飞书卡片或飞书审批完成状态流转。
- 通知-反馈流程可以把按钮、线程回复或表单反馈回写为统一反馈事件。
- 权限不足、参数缺失、API 超时、飞书回传失败都有明确提示。
- 高风险动作不会被自动执行，只输出草稿和人工确认点。
- 日志可以按请求 ID 串联飞书事件、Agent 调用、审核结果、反馈内容和飞书回传结果。

## 10. 后续扩展

- 支持飞书消息卡片按钮，例如“查看明细”“生成 Case 草稿”“提交人工确认”。
- 支持飞书审批流，把采购或发货草稿提交给指定确认人。
- 支持异常 Case 状态同步到飞书群线程。
- 支持定时风险日报、周度发货计划提醒和高风险 SKU 推送。
- 支持把长结果导出为表格文件并上传到飞书。
