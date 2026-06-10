# PMC SKU 事项闭环目标

## 业务目标

构建一个由 Agent 驱动的 SKU 异常事项闭环系统。Agent 负责识别问题、判定归属、发起 PMC 初审、分派处理人、跟踪反馈、超时提醒、落表和生成日/周总结；飞书只作为通知、审核和反馈入口，核心状态由系统自己的业务状态机维护。

## 主业务链路

1. Agent 每日或实时识别 SKU 状态
   - 冗余
   - 断货
   - 风险预警
   - 异常发货、采购、销售问题

2. Agent 判定问题归属
   - 销售处理
   - 采购处理
   - 发货/物流处理
   - PMC 处理
   - 多部门共同处理

3. PMC 真人先审核
   - 确认 Agent 判断是否正确
   - 可以修改处理人
   - 可以修改处理部门
   - 可以补充说明
   - 可以驳回或关闭

4. PMC 确认后，按 SKU 分派到具体人
   - SKU A -> 销售张三
   - SKU B -> 采购李四
   - SKU C -> 发货王五

5. 对应人反馈处理方式
   - 加急发货
   - 补采购
   - 销售控销
   - 促销清库存
   - 暂不处理
   - 需要上级决策
   - 数据有误

6. Agent 落表
   - SKU
   - 问题类型
   - 责任部门
   - 处理人
   - 反馈动作
   - 反馈时间
   - 当前状态

7. Agent 监控超时
   - 3 小时未反馈，再提醒
   - 可多次提醒
   - 超过提醒次数后升级给主管或 PMC

8. Agent 汇总
   - 日总结
   - 周总结
   - 未闭环清单
   - 高风险 SKU 清单
   - 部门响应效率

## 建议状态机

```text
agent_detected
-> pmc_review_pending
-> owner_feedback_pending
-> owner_feedback_reminded
-> recorded
-> closed
```

异常分支：

```text
pmc_review_pending -> pmc_rejected / closed
owner_feedback_pending -> escalated
owner_feedback_reminded -> escalated
```

## 最小落表字段

| 字段 | 含义 |
| --- | --- |
| issue_id | SKU 事项唯一 ID |
| sku | 物料/SKU 编码 |
| issue_type | 问题类型：冗余、断货、风险预警、异常发货/采购/销售 |
| risk_level | 风险等级 |
| summary | Agent 识别出的事项摘要 |
| suggested_department | Agent 建议责任部门 |
| suggested_owner | Agent 建议处理人 |
| pmc_reviewer | PMC 审核人 |
| final_department | PMC 确认后的责任部门 |
| final_owner | PMC 确认后的处理人 |
| feedback_action | 处理人反馈动作 |
| feedback_comment | 处理人反馈说明 |
| feedback_at | 反馈时间 |
| reminder_count | 已提醒次数 |
| status | 当前状态 |
| created_at | 事项生成时间 |
| updated_at | 最近更新时间 |

## 飞书使用边界

飞书不作为主状态存储。飞书用于：

- 给 PMC 发起初审通知/审核入口
- 给销售、采购、发货/物流处理人发送反馈卡片
- 接收按钮或表单回调
- 触发系统状态机推进

系统内部负责：

- 事项状态机
- 处理人和部门分派记录
- 超时提醒判断
- 落表
- 日总结和周总结
- 未闭环和高风险清单统计

## 当前实现方向

当前应优先实现 Agent 自己维护的 `SKU 事项表 + 状态机`，再逐步接入真实飞书回调。

优先级：

1. SKU 事项识别和落表
2. PMC 初审和修改处理人
3. 处理人反馈卡片
4. 3 小时未反馈提醒
5. 升级给主管或 PMC
6. 日总结、周总结和效率统计
