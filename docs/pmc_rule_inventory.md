# PMC 前端规则盘点

来源文件：`D:\laydown\ric-train-master\frontend\src\pages\InventoryLKA.tsx`

本文档用于盘点当前写在 LKA 库存前端页面里的业务规则，并把这些规则映射到后续应该承接它们的后端智能体模块。

## 迁移目标

把确定性的 PMC 业务规则从 React 页面迁移到可审计、可测试、可复用的后端工具中。

- 前端负责传入筛选条件、上传规则文件、触发用户动作。
- 后端负责查询数据、计算数量、生成验证结果和结构化输出。
- 大模型负责理解问题、追问缺失条件、选择工具和解释结果，但不能编造库存、销量、采购、发货数量。

## 已发现的规则范围

| 规则范围 | 当前前端行为 | 建议后端归属 | 优先级 |
| --- | --- | --- | --- |
| 库存健康预警 | 把行数据识别为断货预警、冗余库存、库存异常或正常。 | `InventoryHealthTool` / `ControlTowerTool` | P0 |
| 跨表数据校验 | 用日粒度预测、实际销量、在途、FBA 明细校验主库存宽表。 | `InventoryDataValidationTool` | P0 |
| 发货验证 | 复算发货 T0/T1/T2/T3、M3、基础发货量、发货修正量、发货参考量。 | `ShipmentVerificationTool` | P1 |
| 采购验证 | 复算采购 T0/T1/T2/T3、M3、基础采购量、采购修正量、采购参考量。 | `PurchaseVerificationTool` | P1 |
| MOQ 与整箱取整 | 处理整箱、半箱、滞销/平销/爆旺款取整，以及起订量门槛。 | `MoqRuleEngine` | P1 |
| 可拼采购 | 按供应商、款式、颜色、门幅等维度处理可拼采购组合。 | `PurchaseMixRuleEngine` | P2 |
| 周度发货计划 | 生成发货计划明细、三周需求拆分、仓库分配、库存校验、货件合并。 | `WeeklyShipmentPlanTool` | P2 |
| Excel 导入 | 在浏览器中读取《备货规则》和《起订量要求》文件。 | 后端上传/解析能力 | P1 |
| Excel 导出 | 生成发货验证表、采购验证表、周度发货计划。 | `excel_attachment` 能力 | P1 |

## 数据来源

| 数据源 | 前端中的用途 |
| --- | --- |
| `ads_lingxing_all_warehouse_new` | 主库存宽表，包含库存、需求、销售、时效、采购、发货、风险等字段。 |
| `temp_lingxing_stocking_rules` | 发货频率、补货频率、可超卖比例、安全天数、下次交付天数。 |
| `temp_fnsku_boxing` | 单箱数量和供应商 ID。 |
| `dim_lingxing_local_inventory_product_info` | 供应商报价、产品名称、材质、供应商代码候选。 |
| `temp_lingxing_pici_sale` | 批次销量差异字段，例如 `chazhi_0_7` 到 `chazhi_0_98`。 |
| `dim_lingxing_sales_estimates_everyday_incr` | 未来 30 天日粒度销量预测，用于预测校验。 |
| `ads_lingxing_sc_sales_daily_new` | 近 7 天、近 30 天实际销量、广告花费、促销销量。 |
| `in_transit_shipment` | 在途数量、预计上架日期、延误天数、物流异常。 |
| `dwd_lingxing_fba_warehouse_detail` | FBA 明细库存，用于 FBA 可售校验。 |
| `dim_inventory_forecast_v1` | 采购侧未来库存预测和期末库存。 |
| `dim_inventory_forecast_v1_fh` | 发货侧未来库存预测和期末库存。 |
| `dwd_lingxing_inventory_details` | 国内仓库存明细。 |
| `dwd_lingxing_sc_warehouse` | 仓库名称和仓库元数据。 |
| `dim_lingxing_warehouse_mapping` | 仓库业务类型映射。 |
| `ods_lingxing_inventory_details` | 待配货锁定库存。 |
| `dwd_lingxing_inbound_shipment_list_incr` | 从 `relate_list` 解析待配货/待到货数量。 |

## 库存健康规则

当前前端输出字段：

- `warning_type`：`断货预警`、`冗余库存`、`库存异常`、`正常`
- `risk_level`：`高`、`中`、`低`、`正常`
- `sellable_days`
- `total_inventory`
- `lead_time_days`
- `validation_status`
- `validation_notes`
- `suggested_action`

当前规则：

| 规则项 | 公式或条件 |
| --- | --- |
| 日均需求 | `forecast_30d_sales_checked / 30`；缺失时回退到 `sale_quantity_30 / 30`。 |
| 总库存 | `fba_warehouse_quantity + overseas_warehouse_quantity + local_warehouse_quantity + stock_up_num`。 |
| FBA 可售天数 | `afn_fulfillable_quantity / daily_demand`。 |
| 提前期 | `order_duration + production_duration + max(local_to_FBA_time, overseas_to_FBA_time, local_to_overseas_warehouse_time) + fba_safety_days_fn`。 |
| 长库龄库存 | `inv_age_181_to_270_days + inv_age_271_to_330_days + inv_age_331_to_365_days + inv_age_365_plus_days`。 |
| 断货预警 | `daily_demand > 0` 且 `sellable_days <= max(lead_time, 7)`。 |
| 冗余库存 | `forecast30 > 0` 且 `total_inventory > forecast30 * 2.5` 且 `long_age > max(20, total_inventory * 0.15)`。 |
| FBA 异常 | FBA 明细库存差异大于 `max(10, fba_sellable * 0.08)`。 |
| 销量突变 | 近 7 天实际销量大于 `max(10, 7天基线销量 * 2.2)`。 |
| 物流异常 | `max_delay_days > 3` 或存在物流异常标记。 |
| 高风险 | 命中断货预警且 `sellable_days <= 7`。 |
| 中风险 | 命中断货预警或库存异常。 |
| 低风险 | 命中冗余库存。 |

建议动作：

- 断货：建议立即补货，目标覆盖 `ceil(lead_time + safety_stock_days_sales)` 天需求。
- 冗余：建议核查未发货批次，优先截停或延后本地仓/海外仓补货。
- 异常：建议复核销量、广告活动、FBA 库存和在途状态。
- 正常：继续监控。

## 发货验证规则

输入：

- 如有上传《备货规则》，优先使用上传文件。
- 未上传或未匹配时，使用 `temp_lingxing_stocking_rules` 中的数据库字段。
- 发货预测表：`dim_inventory_forecast_v1_fh`。
- M3 期末库存按 `FNSKU + store_name + 发货 T3 - 1 天` 匹配。

核心规则：

| 规则项 | 规则 |
| --- | --- |
| 发货频率 | 优先使用上传备货规则中的 `发货频率`；其次使用 `temp_lingxing_stocking_rules.shipments_frequency`；最终回退为 `30`。 |
| T0 | 若补货倒计时 >= 发货频率，则为空；否则为验证日期 + `max(补货倒计时, 0)`。 |
| T1 | 若 T0 存在，则 T1 = 验证日期 + 发货频率。 |
| T2/T3 来源 | 使用主宽表 `start_dates0` 和 `end_dates0`；不使用验证日期兜底。 |
| M3 | 使用 `dim_inventory_forecast_v1_fh.ending_inventory`，日期为 `end_dates0 - 1 天`。 |
| 基础发货量 | 汇总 T2 含当天到 T3 不含当天之间的 `expected_sales`。 |
| 安全销量 | `next_logistics_safety_days * daily_sales`。 |
| 发货修正量 | `T1~T3 预计销量 * oversell_rate + 安全销量 - M3`。 |
| 发货参考量 | `max(基础发货量 + 发货修正量, 0)`。 |
| 对比字段 | `basic_fh_quantity`、`fhxiuzhenliang`、`jyfahuo_quantity`。 |
| 校验口径 | 差异 = 复算值 - 底表值；容差为 `0.05`。 |

需要保留的说明：

- 如果底表发货窗口缺失，基础量、M3、修正量按 0 校验。
- 如果 T3 存在但 M3 缺失，发货修正量和参考量无法完整复算。
- 结果必须包含数据来源说明和精确差异字段。

## 采购验证规则

输入：

- 如有上传《备货规则》，优先使用上传文件。
- 采购预测表：`dim_inventory_forecast_v1`。
- M3 期末库存按 `FNSKU + store_name + 采购 T3 - 1 天` 匹配。

核心规则：

| 规则项 | 规则 |
| --- | --- |
| 采购频率 | 优先使用上传备货规则中的 `补货频率`；其次使用 `restocking_frequency`；再回退到发货频率；最终回退为 `30`。 |
| 采购 T0 | 若补货倒计时 6 >= 采购频率，则为空；否则为验证日期 + `max(补货倒计时, 0)`。 |
| 采购 T1 | 若采购 T0 存在，则采购 T1 = 验证日期 + 采购频率。 |
| 采购 T2/T3 来源 | 使用主宽表 `start_dates` 和 `end_dates`；不使用验证日期兜底。 |
| M3 | 使用 `dim_inventory_forecast_v1.ending_inventory`，日期为 `end_dates - 1 天`。 |
| 基础采购量 | 汇总 T2 含当天到 T3 不含当天之间的 `expected_sales`。 |
| 安全销量 | `next_logistics_safety_days * daily_sales`。 |
| 采购修正量 | `T1~T3' 预计销量 * oversell_rate + 安全销量 - M3`。 |
| 采购参考量 | `max(基础采购量 + 采购修正量, 0)`。 |
| 对比字段 | `basic_purchase_quantity`、`xiuzhenliang`、`jypurchase_quantity`。 |
| 校验口径 | 差异 = 复算值 - 底表值；容差为 `0.05`。 |

## MOQ 与整箱规则

当前解析的《起订量要求》字段：

- `SKU`
- `供应商`
- `备注`
- `单个起订量`
- `大机器起订量`
- `单件尺寸`

匹配顺序：

1. 供应商 + SKU。
2. 从产品资料中解析出的供应商候选 + SKU。
3. 仅 SKU。

取整规则：

| 条件 | 规则 |
| --- | --- |
| 无单箱数量 | 保持计划数量不变。 |
| 备注包含 `半箱起订` | 按 `0.5 * 单箱数量` 向上取整。 |
| 销售属性包含 `滞` | 尾箱占比大于 `70%` 才补整箱，否则舍去尾箱。 |
| 销售属性包含 `平` | 尾箱占比大于等于 `50%` 时补整箱，否则舍去尾箱。 |
| 销售属性包含 `爆` 或 `旺` | 向上取整到整箱。 |
| 其他情况 | 向上取整到整箱。 |

起订量规则：

- 备注包含 `大机器` 时，使用 `大机器起订量`。
- 否则使用 `单个起订量`。
- 如果整箱数量低于起订量，只有当未来 180 天销量达到起订量的 `80%` 时，才提升到起订量。
- 如果整箱数量低于起订量且未来需求不足，计划采购量置为 `0`。
- 如果整箱采购数量小于 `10` 且折算箱数小于 `3`，计划采购量置为 `0`，备注 `需求过低`。
- 如果季节属性包含 `节日款`，计划采购量置为 `0`。
- 如果起订量备注包含 `统一备货`，计划采购量置为 `0`。

## 可拼采购规则

适用条件：

- 起订量备注包含 `可拼`。
- 起订量备注不包含 `不可拼`。
- 存在 `单件尺寸`。
- 能从备注中解析出平方数门槛。

分组维度：

- 供应商代码始终参与分组。
- `同款` 增加款式维度。
- `同色` 或 `单色` 增加颜色维度。
- `同门幅` 增加门幅维度。
- 如果没有款式、颜色、门幅限制，则仅按供应商分组。

处理逻辑：

- 如果组内采购平方数已经达到门槛，各 SKU 保持自己的整箱采购数量，并增加可拼备注。
- 如果未达到门槛，则按整箱或半箱步长补量，上限为未来 180 天销量。
- 如果补到上限后仍未达到门槛，则保留尽力补足结果，并标记未达标。

## 周度发货计划规则

主要输出：

- 周度发货计划明细 sheet。
- 货件合并汇总 sheet。
- 国内库存明细 sheet。
- 规则说明 sheet。

核心规则：

| 规则项 | 规则 |
| --- | --- |
| 计划来源 | 读取 `ads_lingxing_all_warehouse_new` 全量行；无建议发货量的行也保留，发货列按 0 输出。 |
| 计划发货时间 | 使用 `start_dates0`；不使用验证日期兜底。 |
| 计划发货量 | 使用 `jyfahuo_quantity`。 |
| 前三周发货日 | 选择日期之后最近的周五，以及后续两个周五。 |
| 周需求窗口 | 到货日 + 1 到到货日 + 7。 |
| 周需求来源 | 汇总 `dim_inventory_forecast_v1_fh.expected_sales`。 |
| 建单太晚 | 如果发货 T0 在当周，当周需求置 0，且不并入下周。 |
| T0 不在当周 | 从 T0 发货周开始，按单箱数拆分三周需求，并标记超出需求。 |
| 补缺量分配 | 补缺量小于 100 时放入第一个可发周；大于等于 100 时按完整箱数分摊到可发周。 |
| 渠道拆分 | 快船展示为 `美森`；慢船展示为 `慢船`。 |
| 覆盖截止日建议量 | 如果覆盖截止日期的期末库存为负，按缺口并结合整箱/半箱步长向上取整；如果缺失期末库存，则回退为覆盖期销量 - 当前 FBA 可售。 |
| 库存过高取消 | 如果可售天数 >= 90 且为滞销或季节类，规则建议发货量置为 0。 |
| 断货风险改渠道 | 如果存在断货风险且当前渠道为慢船，建议改为 `美森`。 |
| 库存不足限制 | 如果发货量超过国内总库存或可用 + 在途库存，发货量限制为当前可支持数量。 |
| 退回货件重建 | 如果存在退回数量，标记需要单独重建发货计划。 |

国内库存规则：

- 国内总库存 = `local_warehouse_quantity + local_afn_inbound_shipped_quantity`。
- 国内可用库存 = `local_warehouse_quantity`。
- 国内在途库存 = `local_afn_inbound_shipped_quantity`。
- 待配货 = `ods_lingxing_inventory_details.product_lock_num` + 待到货货件 `relate_list[].num`。
- 仓库优先级：中转仓优先，其次供应商仓，再其他本地仓。

库存校验状态：

| 状态 | 条件 |
| --- | --- |
| `超发` | 整箱发货量 > 国内总库存。 |
| `库存充足` | 国内可用库存 >= 整箱发货量。 |
| `可用不足在途覆盖` | 国内可用库存不足，但可用 + 在途可以覆盖。 |
| `可用不足` | 可用 + 在途也无法覆盖。 |

货件合并分组：

- 同一店铺。
- 同一计划发货时间。
- 相同尺寸类型。
- 相同透明计划状态。
- 同一仓库或供应商。

## 后端迁移计划

### P0：库存健康与数据校验

1. 扩展 `schema_catalog.py`，加入库存健康页面使用到的字段包。
2. 增加日粒度预测、实际销量、在途、FBA 库存校验的 connector 方法。
3. 实现 `InventoryHealthTool` 和 `InventoryDataValidationTool`。
4. 使用固定行样例补充单元测试，确保与前端规则一致。

### P1：发货验证与采购验证

1. 实现发货和采购共用的日期窗口辅助函数。
2. 增加 `dim_inventory_forecast_v1` 和 `dim_inventory_forecast_v1_fh` 的 M3 查询辅助函数。
3. 实现结构化结果行、差异字段和校验结论。
4. 通过现有 `excel_attachment` 能力生成 Excel 附件。

### P2：周度发货计划

1. 实现 MOQ 解析和整箱取整引擎。
2. 实现可拼采购分组。
3. 实现国内仓分配和库存限制后的发货数量。
4. 生成明细、货件合并汇总、国内库存、规则说明等 sheet。

## 迁移后的前端改造

- 用后端接口或智能体工具替代前端原始 SQL 调用。
- 保留筛选条件、上传控件、结果表格、下载按钮。
- 展示后端返回的计算解释、验证说明和差异字段。
- 等一致性测试通过后，从 React 页面移除确定性业务公式。

## 必需的一致性测试

- 断货、冗余库存、库存异常分类一致。
- 发货基础量、修正量、参考量一致。
- 采购基础量、修正量、参考量一致。
- 爆旺、平销、滞销、半箱起订的 MOQ 与整箱取整一致。
- 三周需求拆分和建单太晚顺延一致。
- 国内库存校验状态一致。
- 货件合并分组一致。
