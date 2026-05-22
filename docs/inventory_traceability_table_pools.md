# 库存全链路溯源表池规划

来源：
- `D:\laydown\ric-train-master\LDA\data\schema_index.json`
- `D:\laydown\ric-train-master\LDA\data\schema_raw.json`
- 真实库探测：`dw_leang` 中关键表存在性和字段数量。

## 结论

- 主要表池: 8 张
- 用得到表池: 113 张
- 可能有用表池: 175 张
- 首期基本用不到表池: 65 张

`ads_lingxing_all_warehouse_new_v1` 是主查询宽表，用户说明其更新逻辑为一月一更；因此它应作为月度基准快照和主入口，不应单独承担实时库存变动、采购在途、发货在途的全量追踪。实时/过程性追踪需要结合 DWD/ODS 明细、预测表、采购订单、发货/物流表。

注意：两个 schema 文件未完整覆盖真实库中确认存在的 `ads_lingxing_all_warehouse_new_v1`、`dim_inventory_forecast_v1`、`dim_inventory_forecast_v1_fh`，本规划已根据真实库探测强制纳入主要表池。

## 主要表池

首期最核心的查询入口和复算依据。

| 表 | 描述 | 分类 | 放入原因 |
| --- | --- | --- | --- |
| `ads_lingxing_all_warehouse_new_v1` | 领星ERP全部仓库/仓储主宽表 v1，真实库已确认存在。 | 库存管理 | 库存全链路溯源主查询宽表；用户说明为一月一更，适合做月度基准快照和主入口。注意它不适合单独承担实时库存变动追踪。 |
| `ads_lingxing_sc_sales_daily_new` | 领星ERP - 销售 - 日度 - (new版本) | 销售分析 | 销售日报；用于真实销量、近 7/30 天需求和预测偏差核对。 |
| `ads_lingxing_stocking_rules` | 领星ERP - 补货/备货 - 规则 | 库存管理 | ADS 层备货规则；作为规则宽表或 temp 表口径的对照。 |
| `dim_inventory_forecast_v1` | 采购侧库存预测 v1。 | 库存管理, 数据预测 | 采购侧未来库存预测；用于采购验证、缺口测算和未来库存曲线，真实库已确认存在。 |
| `dim_inventory_forecast_v1_fh` | 发货侧库存预测 v1。 | 库存管理, 数据预测 | 发货侧未来库存预测；用于发货验证和发货窗口复算，真实库已确认存在。 |
| `dwd_lingxing_fba_warehouse_detail` | 领星ERP - 亚马逊FBA物流 - 仓库/仓储 - 明细 | 库存管理 | FBA 库存明细；用于 FBA 可售、不可售、预留、在途状态核对。 |
| `dwd_lingxing_inventory_details` | 领星ERP - 库存 | 库存管理 | 国内仓库存明细；用于本地仓可用、锁定、在途、质检和不良品库存。 |
| `temp_lingxing_stocking_rules` | 临时 - 领星ERP - 补货/备货 - 规则 | 库存管理 | 临时/现行备货规则；用于安全库存、时效、补货频率等规则口径。 |

## 用得到表池

建议进入首期 connector 的候选白名单，按问题类型分批接入。

| 表 | 描述 | 分类 | 放入原因 |
| --- | --- | --- | --- |
| `ads_lingxing_all_warehouse_new` | 领星ERP - 全部 - 仓库/仓储 - (new版本) | 库存管理 | 主宽表历史/new 版本，可用于和 v1 比较字段口径。 |
| `ads_lingxing_all_warehouse_new_sh` | 领星ERP - 全部 - 仓库/仓储 - (new版本) | 库存管理 | 主宽表 SH 版本，可用于区域或上海口径核对。 |
| `ads_lingxing_all_warehouse_new_sh_v1` | 领星ERP - 全部 - 仓库/仓储 - (new版本) - (v1版本) | 库存管理 | 主宽表 SH v1 版本，可用于区域或上海口径核对。 |
| `ads_lingxing_flz` | 领星ERP | 其他 | FBA 库存/库存流水 ADS 表。 |
| `ads_lingxing_sc_sales_daily` | 领星ERP - 销售 - 日度 | 销售分析 | 销售日报旧表，可用于口径回溯。 |
| `ads_lingxing_sc_sales_daily2` | 领星ERP - 销售 | 销售分析 | 销售日报旧/中间表。 |
| `ads_logistics_monitoring` | 物流 | 物流管理 | 物流监控。 |
| `ads_logistics_monitoring_sj` | 物流 | 物流管理 | 物流监控时间/事件口径。 |
| `ads_m_firstleg_shipping` | 物流运输 | 物流管理 | 头程发货 ADS。 |
| `ads_rpt_inventory_sales_health_weekly` | 库存 - 销售 - 健康度 - 周度 | 销售分析, 库存管理 | 库存销售健康周报，可用于风险等级和周度趋势对照。 |
| `all_warehouse_mv` | 全部 - 仓库/仓储 | 库存管理 | 库存宽表物化视图/汇总视图，可用于性能优化或宽表口径核对。 |
| `dim_caigoujihua_weekly` | 周度 | 采购管理 | 周度采购计划。 |
| `dim_fahuojihua_weekly` | 周度 | 其他 | 周度发货计划。 |
| `dim_inventory_forecast` | 库存 - 预测 | 库存管理, 数据预测 | 库存预测老版本，可用于追溯口径变化。 |
| `dim_inventory_forecast2` | 库存 | 库存管理, 数据预测 | 库存预测中间/旧版本，可用于追溯口径变化。 |
| `dim_inventory_forecast_bd` | 库存 - 预测 | 库存管理, 数据预测 | BD 口径预测表，可用于特殊渠道或 BD 口径核对。 |
| `dim_lingxing_account_mapping` | 领星ERP - 账号 - 映射关系 | 店铺管理 | 账号/店铺映射。 |
| `dim_lingxing_daily_sales_estimates` | 领星ERP - 日度 - 销售 | 销售分析, 数据预测 | 日销量预测。 |
| `dim_lingxing_kucun_num` | 领星ERP - 数量 | 库存管理 | 库存数量维表/汇总表。 |
| `dim_lingxing_lot_tracking_new` | 领星ERP - 追踪 - (new版本) | 物流管理 | 批次跟踪。 |
| `dim_lingxing_planned_shipment_quantity_new` | 领星ERP - 发货/物流 - 数量 - (new版本) | 物流管理 | 计划发货量。 |
| `dim_lingxing_product` | 领星ERP - 产品 | 产品管理 | 产品维表。 |
| `dim_lingxing_product_info` | 领星ERP - 产品 - 信息 | 产品管理 | 产品信息维表。 |
| `dim_lingxing_sales_estimates` | 领星ERP - 销售 | 销售分析, 数据预测 | 销量预测维表。 |
| `dim_lingxing_sales_estimates_everyday_v1_incr` | 领星ERP - 销售 - (v1版本) - 增量 | 销售分析, 数据预测 | 每日销量预测 v1 增量。 |
| `dim_lingxing_sales_estimates_v1` | 领星ERP - 销售 - (v1版本) | 销售分析, 数据预测 | 销量预测 v1。 |
| `dim_lingxing_stocking_rules` | 领星ERP - 补货/备货 - 规则 | 库存管理 | 领星备货规则维表。 |
| `dim_lingxing_stocking_rules2` | 领星ERP - 补货/备货 | 库存管理 | 领星备货规则版本表。 |
| `dim_lingxing_stocking_rules_v1` | 领星ERP - 补货/备货 - 规则 - (v1版本) | 库存管理 | 领星备货规则 v1。 |
| `dim_lingxing_store` | 领星ERP - 店铺 | 店铺管理 | 店铺维表。 |
| `dim_lingxing_warehouse_analysis` | 领星ERP - 仓库/仓储 - 分析 | 库存管理 | 仓库分析维表。 |
| `dim_lingxing_warehouse_mapping` | 领星ERP - 仓库/仓储 - 映射关系 | 库存管理 | 仓库映射表。 |
| `dim_msku_dimension_detailed` | MSKU(商户SKU) | 产品管理 | MSKU 维度明细。 |
| `dim_platform_store` | 店铺 | 店铺管理 | 平台店铺维表。 |
| `dwd_lingxing_awd_inbound_plan_list_incr` | 领星ERP - 亚马逊AWD仓储 - 入库 - 计划 - 列表 - 增量 | 物流管理 | AWD 入库计划 DWD。 |
| `dwd_lingxing_awd_warehouse_detail` | 领星ERP - 亚马逊AWD仓储 - 仓库/仓储 - 明细 | 库存管理 | AWD 仓库存明细。 |
| `dwd_lingxing_fba_report_shipment_detail_incr` | 领星ERP - 亚马逊FBA物流 - 报告 - 发货/物流 - 明细 - 增量 | 物流管理 | FBA 发货报告明细 DWD。 |
| `dwd_lingxing_fba_report_shipment_list_incr` | 领星ERP - 亚马逊FBA物流 - 报告 - 发货/物流 - 列表 - 增量 | 物流管理 | FBA 发货报告主表 DWD。 |
| `dwd_lingxing_fba_shipment_plan_lists_incr` | 领星ERP - 亚马逊FBA物流 - 发货/物流 - 计划 - 增量 | 物流管理 | FBA 发货计划 DWD。 |
| `dwd_lingxing_inbound_shipment_boxes_incr` | 领星ERP - 入库 - 发货/物流 - 增量 | 物流管理 | 入库箱规/箱明细 DWD。 |
| `dwd_lingxing_inbound_shipment_detail_incr` | 领星ERP - 入库 - 发货/物流 - 明细 - 增量 | 物流管理 | 入库/货件明细 DWD。 |
| `dwd_lingxing_inbound_shipment_list_incr` | 领星ERP - 入库 - 发货/物流 - 列表 - 增量 | 物流管理 | 入库/货件主表 DWD。 |
| `dwd_lingxing_inventory_ledger_summary_incr` | 领星ERP - 库存 - 台账 - 统计/汇总 - 增量 | 库存管理 | 库存流水/台账汇总，用于库存变动追溯。 |
| `dwd_lingxing_inventory_turnover_incr` | 领星ERP - 库存 - 周转 - 增量 | 库存管理 | 库存周转明细/指标，用于滞销和周转分析。 |
| `dwd_lingxing_local_inventory_product_list_incr` | 领星ERP - 本地仓 - 库存 - 产品 - 列表 - 增量 | 库存管理, 产品管理 | 本地库存商品列表 DWD。 |
| `dwd_lingxing_owms_inbound_list_incr` | 领星ERP - 入库 - 列表 - 增量 | 物流管理 | 海外仓入库 DWD。 |
| `dwd_lingxing_purchase_order_item_list_incr` | 领星ERP - 采购 - 订单 - 列表 - 增量 | 销售分析, 采购管理 | 采购订单明细 DWD，用于采购在途和交期追溯。 |
| `dwd_lingxing_purchase_order_list_incr` | 领星ERP - 采购 - 订单 - 列表 - 增量 | 销售分析, 采购管理 | 采购订单主表 DWD。 |
| `dwd_lingxing_purchase_plans_incr` | 领星ERP - 采购 - 增量 | 采购管理 | 采购计划 DWD。 |
| `dwd_lingxing_purchase_receipt_order_incr` | 领星ERP - 采购 - 订单 - 增量 | 销售分析, 采购管理 | 采购收货 DWD。 |
| `dwd_lingxing_sc_warehouse` | 领星ERP - 仓库/仓储 | 库存管理 | 仓库信息 DWD。 |
| `dwd_lingxing_sta_inbound_plan_detail_incr` | 领星ERP - 入库 - 计划 - 明细 - 增量 | 物流管理 | STA 入库计划明细 DWD。 |
| `dwd_lingxing_sta_inbound_plan_list_incr` | 领星ERP - 入库 - 计划 - 列表 - 增量 | 物流管理 | STA 入库计划主表 DWD。 |
| `dws_purchase_allocation` | 采购 - 分配 | 采购管理 | 采购分配 DWS。 |
| `dws_purchase_attribution_detailed` | 采购 - 归因 | 采购管理 | 采购归因明细。 |
| `dws_shipment_attribution_detailed` | 发货/物流 - 归因 | 物流管理 | 发货归因明细。 |
| `fba_shipment_report` | 亚马逊FBA物流 - 发货/物流 - 报告 | 物流管理 | FBA 发货报告汇总。 |
| `fba_warehouse_qty_ratio` | 亚马逊FBA物流 - 仓库/仓储 | 库存管理 | FBA 仓库数量比例。 |
| `fba_warehouse_summary` | 亚马逊FBA物流 - 仓库/仓储 - 统计/汇总 | 库存管理 | FBA 仓库汇总。 |
| `fba_warehouse_to_sales_ratio` | 亚马逊FBA物流 - 仓库/仓储 - 销售 | 销售分析, 库存管理 | FBA 库存销量比。 |
| `feishu_first_leg_shipment_records` | 飞书 - 发货/物流 | 物流管理 | 飞书头程发货记录。 |
| `feishu_first_leg_tracking_records` | 飞书 - 追踪 | 物流管理 | 飞书头程跟踪记录。 |
| `forecast_snapshot` | 预测 | 数据预测 | 预测快照。 |
| `in_transit_shipment` | 发货/物流 | 物流管理 | 在途发货。 |
| `in_transit_shipment_records` | 发货/物流 | 物流管理 | 在途发货记录。 |
| `in_transit_shipment_tmp` | 发货/物流 - 临时 | 物流管理 | 在途发货临时表。 |
| `leang_lst_asin_mapping` | 乐昂(公司) - ASIN(亚马逊产品编号) - 映射关系 | 产品管理 | ASIN 映射。 |
| `leang_product_info` | 乐昂(公司) - 产品 - 信息 | 产品管理 | 产品信息补充表。 |
| `leang_western_sku_mapping` | 乐昂(公司) - SKU(库存单位) - 映射关系 | 产品管理 | SKU 映射。 |
| `local_inventory_details` | 本地仓 - 库存 | 库存管理 | 本地库存明细补充表。 |
| `ods_lingxing_awd_inbound_plan_list` | 领星ERP - 亚马逊AWD仓储 - 入库 - 计划 - 列表 | 物流管理 | AWD 入库计划 ODS。 |
| `ods_lingxing_awd_warehouse_detail` | 领星ERP - 亚马逊AWD仓储 - 仓库/仓储 - 明细 | 库存管理 | AWD 仓库存 ODS。 |
| `ods_lingxing_fba_report_shipment_detail` | 领星ERP - 亚马逊FBA物流 - 报告 - 发货/物流 - 明细 | 物流管理 | FBA 发货报告明细 ODS。 |
| `ods_lingxing_fba_report_shipment_list` | 领星ERP - 亚马逊FBA物流 - 报告 - 发货/物流 - 列表 | 物流管理 | FBA 发货报告主表 ODS。 |
| `ods_lingxing_fba_shipment_plan_lists` | 领星ERP - 亚马逊FBA物流 - 发货/物流 - 计划 | 物流管理 | FBA 发货计划 ODS。 |
| `ods_lingxing_fba_warehouse_detail` | 领星ERP - 亚马逊FBA物流 - 仓库/仓储 - 明细 | 库存管理 | FBA 库存 ODS 原始表。 |
| `ods_lingxing_inbound_shipment_boxes` | 领星ERP - 入库 - 发货/物流 | 物流管理 | 入库箱明细 ODS。 |
| `ods_lingxing_inbound_shipment_detail` | 领星ERP - 入库 - 发货/物流 - 明细 | 物流管理 | 入库/货件明细 ODS。 |
| `ods_lingxing_inbound_shipment_list` | 领星ERP - 入库 - 发货/物流 - 列表 | 物流管理 | 入库/货件主表 ODS。 |
| `ods_lingxing_inventory_details` | 领星ERP - 库存 | 库存管理 | 国内仓库存 ODS 原始表。 |
| `ods_lingxing_inventory_ledger_summary` | 领星ERP - 库存 - 台账 - 统计/汇总 | 库存管理 | 库存台账 ODS。 |
| `ods_lingxing_inventory_turnover` | 领星ERP - 库存 - 周转 | 库存管理 | 库存周转 ODS。 |
| `ods_lingxing_local_inventory_product_list` | 领星ERP - 本地仓 - 库存 - 产品 - 列表 | 库存管理, 产品管理 | 本地库存商品列表 ODS。 |
| `ods_lingxing_lot_tracking` | 领星ERP - 追踪 | 物流管理 | 批次跟踪 ODS。 |
| `ods_lingxing_owms_inbound_list` | 领星ERP - 入库 - 列表 | 物流管理 | 海外仓入库 ODS。 |
| `ods_lingxing_planned_shipment_quantity` | 领星ERP - 发货/物流 - 数量 | 物流管理 | 计划发货量 ODS。 |
| `ods_lingxing_purchase_order_item_list` | 领星ERP - 采购 - 订单 - 列表 | 销售分析, 采购管理 | 采购订单明细 ODS。 |
| `ods_lingxing_purchase_order_list` | 领星ERP - 采购 - 订单 - 列表 | 销售分析, 采购管理 | 采购订单主表 ODS。 |
| `ods_lingxing_purchase_plans` | 领星ERP - 采购 | 采购管理 | 采购计划 ODS。 |
| `ods_lingxing_purchase_receipt_order` | 领星ERP - 采购 - 订单 | 销售分析, 采购管理 | 采购收货 ODS。 |
| `ods_lingxing_sales_estimates_v1` | 领星ERP - 销售 - (v1版本) | 销售分析, 数据预测 | 销量预测 ODS v1。 |
| `ods_lingxing_sc_store` | 领星ERP - 店铺 | 店铺管理 | 店铺 ODS。 |
| `ods_lingxing_sc_warehouse` | 领星ERP - 仓库/仓储 | 库存管理 | 仓库信息 ODS。 |
| `ods_lingxing_stocking_rules` | 领星ERP - 补货/备货 - 规则 | 库存管理 | 备货规则 ODS 原始表。 |
| `ods_lingxing_stocking_rules_v1` | 领星ERP - 补货/备货 - 规则 - (v1版本) | 库存管理 | 备货规则 ODS v1 原始表。 |
| `stock_monitor_new` | 库存 - 监控 - (new版本) | 库存管理 | 库存监控新表。 |
| `stock_monitor_tmp` | 库存 - 监控 - 临时 | 库存管理 | 库存监控临时表。 |
| `tem_lingxing_stocking_rules` | 领星ERP - 补货/备货 - 规则 | 库存管理 | 备货规则临时表，可能是 temp_lingxing_stocking_rules 的历史拼写。 |
| `temp_batch_kucun` | 临时 | 库存管理 | 批次库存临时表。 |
| `temp_caigoushiji` | 临时 | 采购管理 | 采购实际/临时表。 |
| `temp_current_inventory` | 临时 - 库存 | 库存管理 | 当前库存临时表。 |
| `temp_fahuojihua_weekly` | 临时 - 周度 | 其他 | 周度发货计划临时表。 |
| `temp_fahuoshiji` | 临时 | 其他 | 发货实际临时表。 |
| `temp_kucun_fnsku_zgb` | 临时 - FNSKU(亚马逊配送网络SKU) | 库存管理, 产品管理 | FNSKU 库存临时/中间表。 |
| `temp_kucun_sku_zgb` | 临时 - SKU(库存单位) | 库存管理, 产品管理 | SKU 库存临时/中间表。 |
| `temp_kucunlinshi_a` | 临时 | 库存管理 | 库存临时表。 |
| `temp_lingxing_flz` | 临时 - 领星ERP | 其他 | FBA 库存/库存流水相关临时表。 |
| `temp_lingxing_fnsku_sales_forecast` | 临时 - 领星ERP - FNSKU(亚马逊配送网络SKU) - 销售 - 预测 | 销售分析, 产品管理, 数据预测 | FNSKU 销量预测临时表。 |
| `temp_lingxing_kucun_num` | 临时 - 领星ERP - 数量 | 库存管理 | 库存数量临时表。 |
| `temp_purchase_quantity_temp_v1` | 临时 - 采购 - 数量 - 临时 - (v1版本) | 采购管理 | 采购数量临时结果。 |
| `temp_purchase_quantity_temptwo` | 临时 - 采购 - 数量 | 采购管理 | 采购数量临时结果。 |
| `temp_status_fahuo` | 临时 - 状态 | 其他 | 发货状态临时表。 |
| `vw_purchase_decision_support` | 采购 | 采购管理 | 采购决策支持视图。 |

## 可能有用表池

暂不作为首期必查表，但在产品、店铺、退货、利润、预测版本、日历/活动等问题时可能需要。完整清单见 JSON。

| 表 | 描述 | 分类 | 放入原因 |
| --- | --- | --- | --- |
| `ads_lingxing_return_analysis` | 领星ERP - 退货/退款 - 分析 | 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_lingxing_return_analysis_pr` | 领星ERP - 退货/退款 - 分析 | 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_multichannel_fc` | ads_multichannel_fc | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_return_notes` | 退货/退款 | 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_return_notes1` | 退货/退款 | 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_rpt_weekly_sales_checkls` | 周度 - 销售 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_status_juhe` | 状态 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_temp_base_dates` | 临时 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_week_huojians` | ads_week_huojians | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_xiyou_last_mile_summary_temp` | 西邮物流 - 统计/汇总 - 临时 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ads_xiyou_logistics_claim_expenses_temp` | 西邮物流 - 物流 - 索赔 - 临时 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ads_xiyou_logistics_supplement_temp` | 西邮物流 - 物流 - 临时 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ads_xiyou_return_logistics_temp` | 西邮物流 - 退货/退款 - 物流 - 临时 | 物流管理, 退货退款 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ads_xiyou_return_order_detail_temp` | 西邮物流 - 退货/退款 - 订单 - 明细 - 临时 | 销售分析, 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_xiyou_self_delivery_orders_temp` | 西邮物流 - 临时 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ads_xiyou_shipment_order_details_temp` | 西邮物流 - 发货/物流 - 订单 - 临时 | 销售分析, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ads_xiyou_warehouse_claim_temp` | 西邮物流 - 仓库/仓储 - 索赔 - 临时 | 库存管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dim_BI_ASIN_demo` | ASIN(亚马逊产品编号) | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_Quality_reference` | 质量 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_Quality_reference_with_supplier` | 质量 - 供应商 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_Quality_reference_with_supplier2` | 质量 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_activity_schedule` | 活动 - 排期 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_calendar_table` | 日历 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_fs_specialorder` | dim_fs_specialorder | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_headway_bill_incr_a` | 增量 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_high_return_rate_tag` | 退货/退款 - 汇率/比率 | 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_high_return_rate_tag_new` | 退货/退款 - 汇率/比率 - (new版本) | 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_daily_sales_estimates_tmp` | 领星ERP - 日度 - 销售 - 临时 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_fnsku_quantity` | 领星ERP - FNSKU(亚马逊配送网络SKU) - 数量 | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_local_inventory_product_info` | 领星ERP - 本地仓 - 库存 - 产品 - 信息 | 库存管理, 产品管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dim_lingxing_mp_seller_list` | 领星ERP - 卖家 - 列表 | 店铺管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_product_info_monthly` | 领星ERP - 产品 - 信息 - 月度 | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_product_sale_date` | 领星ERP - 产品 - 销售 - 日期 | 销售分析, 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_everyday_incr` | 领星ERP - 销售 - 增量 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_everyday_incr2` | 领星ERP - 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_everyday_incr3` | 领星ERP - 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_monthly` | 领星ERP - 销售 - 月度 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_monthly_v1` | 领星ERP - 销售 - 月度 - (v1版本) | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_tmp` | 领星ERP - 销售 - 临时 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sales_estimates_tmp1` | 领星ERP - 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_lingxing_sc_market` | 领星ERP - 市场/站点 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_pub_china_region` | 区域 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_pub_date` | 日期 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_redundant_list` | 冗余/滞销 - 列表 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_redundant_list_new` | 冗余/滞销 - 列表 - (new版本) | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_xiyou_logistics_claim_expenses` | 西邮物流 - 物流 - 索赔 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dim_xiyou_logistics_supplement` | 西邮物流 - 物流 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dim_xiyou_return_logistics` | 西邮物流 - 退货/退款 - 物流 | 物流管理, 退货退款 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dim_xiyou_return_order_detail` | 西邮物流 - 退货/退款 - 订单 - 明细 | 销售分析, 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_xiyou_self_delivery_orders` | 西邮物流 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dim_xiyou_shipment_order_details` | 西邮物流 - 发货/物流 - 订单 | 销售分析, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dim_xiyou_warehouse_claim` | 西邮物流 - 仓库/仓储 - 索赔 | 库存管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dwd_leang_first_leg_shipping_cost` | 乐昂(公司) - 物流运输 - 成本 | 物流管理, 利润报告 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dwd_lingxing_fba_report_shipment_list_tmp` | 领星ERP - 亚马逊FBA物流 - 报告 - 发货/物流 - 列表 - 临时 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dwd_lingxing_inbound_shipment_detail_tmp` | 领星ERP - 入库 - 发货/物流 - 明细 - 临时 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dwd_lingxing_mp_order_list_incr` | 领星ERP - 订单 - 列表 - 增量 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_multi_channel_order_detail_with_logistics_incr` | 领星ERP - 订单 - 明细 - 物流 - 增量 | 销售分析, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `dwd_lingxing_multi_channel_order_detail_with_transaction_incr` | 领星ERP - 订单 - 明细 - 交易 - 增量 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_multi_channel_order_list_incr` | 领星ERP - 订单 - 列表 - 增量 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_refund_orders_incr` | 领星ERP - 退款 - 增量 | 销售分析, 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_sc_listing_incr` | 领星ERP - 产品链接/Listing - 增量 | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_sc_order_detail_incr` | 领星ERP - 订单 - 明细 - 增量 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_sc_order_incr` | 领星ERP - 订单 - 增量 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_sc_profit_report_order_incr` | 领星ERP - 利润 - 报告 - 订单 - 增量 | 销售分析, 利润报告 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_sc_rate` | 领星ERP - 汇率/比率 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_statistics_sale_stat_incr` | 领星ERP - 统计/汇总 - 销售 - 统计/汇总 - 增量 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_lingxing_storage_fee_month_incr` | 领星ERP - 增量 | 利润报告, 仓储费用 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_original_sales_estimates` | 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_tmp_order_profit_daily` | 临时 - 订单 - 利润 - 日度 | 销售分析, 利润报告 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `dwd_xiao_liang_yu_gu` | dwd_xiao_liang_yu_gu | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `leang_last_mile_order` | 乐昂(公司) - 订单 | 销售分析, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `leang_last_mile_order_no` | 乐昂(公司) - 订单 | 销售分析, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `leang_local_warehouse_holding_profit_report` | 乐昂(公司) - 本地仓 - 仓库/仓储 - 利润 - 报告 | 库存管理, 利润报告 | 名称或分类有非库存特征，但也与库存/采购/物流相关，暂放可能有用池。 |
| `leang_sales_estimates` | 乐昂(公司) - 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `leang_sales_estimates_tmp` | 乐昂(公司) - 销售 - 临时 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `leang_shipment_order_detail` | 乐昂(公司) - 发货/物流 - 订单 - 明细 | 销售分析, 物流管理 | 名称或分类有非库存特征，但也与库存/采购/物流相关，暂放可能有用池。 |
| `monthly_first_leg_cost_price` | 月度 - 成本 - 价格 | 物流管理, 利润报告 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `monthly_store_clearance` | 月度 - 店铺 - 清仓 | 店铺管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `mv_6` | mv_6 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_local_inventory_product_info` | 领星ERP - 本地仓 - 库存 - 产品 - 信息 | 库存管理, 产品管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ods_lingxing_mp_order_list` | 领星ERP - 订单 - 列表 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_mp_seller_list` | 领星ERP - 卖家 - 列表 | 店铺管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_multi_channel_order_detail_with_logistics` | 领星ERP - 订单 - 明细 - 物流 | 销售分析, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ods_lingxing_multi_channel_order_detail_with_transaction` | 领星ERP - 订单 - 明细 - 交易 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_multi_channel_order_list` | 领星ERP - 订单 - 列表 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_product_info` | 领星ERP - 产品 - 信息 | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_refund_orders` | 领星ERP - 退款 | 销售分析, 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sales_estimates` | 领星ERP - 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sales_estimates_monthly` | 领星ERP - 销售 - 月度 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sales_estimates_monthly_v1` | 领星ERP - 销售 - 月度 - (v1版本) | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sales_estimates_stash` | 领星ERP - 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sales_estimates_v2` | 领星ERP - 销售 - (v2版本) | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sc_listing` | 领星ERP - 产品链接/Listing | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sc_market` | 领星ERP - 市场/站点 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sc_order_delta` | 领星ERP - 订单 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sc_order_detail` | 领星ERP - 订单 - 明细 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sc_profit_report_order` | 领星ERP - 利润 - 报告 - 订单 | 销售分析, 利润报告 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sc_rate` | 领星ERP - 汇率/比率 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_sta_inbound_plan_detail` | 领星ERP - 入库 - 计划 - 明细 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ods_lingxing_sta_inbound_plan_list` | 领星ERP - 入库 - 计划 - 列表 | 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `ods_lingxing_statistics_sale_stat` | 领星ERP - 统计/汇总 - 销售 - 统计/汇总 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_lingxing_storage_fee_month` | 领星ERP | 利润报告, 仓储费用 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_original_sales_estimates` | 销售 | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `ods_original_sales_estimates_v1` | 销售 - (v1版本) | 销售分析, 数据预测 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `overseas_warehouse_dropshipping` | 海外仓 - 仓库/仓储 | 库存管理, 物流管理 | schema 分类与库存/采购/物流相关，但暂未进入首期直接查询链路。 |
| `product_sales_quantity` | 产品 - 销售 - 数量 | 销售分析, 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `return_orders` | 退货/退款 | 销售分析, 退货退款 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_AFCE_2` | 临时 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_BI_ASIN_demo_temp` | 临时 - ASIN(亚马逊产品编号) - 临时 | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_base_data` | 临时 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_buhuo_fnsku_zjg` | 临时 - FNSKU(亚马逊配送网络SKU) | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_buhuo_sku_zjg` | 临时 - SKU(库存单位) | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_daily_arrivals` | 临时 - 日度 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_daily_arrivals2` | 临时 - 日度 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_daily_sales` | 临时 - 日度 - 销售 | 销售分析 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_data_weekly` | 临时 - 周度 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_date_series` | 临时 - 日期 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_date_series_bd` | 临时 - 日期 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_duptm` | 临时 | 其他 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| `temp_dwd_lingxing_sc_listing_incr_1` | 临时 - 领星ERP - 产品链接/Listing - 增量 | 产品管理 | 产品、店铺、预测、退货、利润或日历等补充维度，按问题可能需要。 |
| ... | 其余 55 张见 `docs/inventory_traceability_table_pools.json` | - | - |

## 首期基本用不到表池

主要是广告投放、评论评价、人员组织、目标考核、与库存溯源链路关系弱的临时或分析表。完整清单见 JSON。

| 表 | 描述 | 分类 | 放入原因 |
| --- | --- | --- | --- |
| `ads_dpt_mubiao` | ads_dpt_mubiao | 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_mws_reviews_incr` | 领星ERP - 增量 | 评论评价 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_product_profit` | 领星ERP - 产品 - 利润 | 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_sc_sales_daily_tmp1` | 领星ERP - 销售 - 日度 | 销售分析 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_sc_sales_daily_tmp2` | 领星ERP - 销售 - 日度 | 销售分析 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_search_term_cost` | 领星ERP - 成本 | 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_sp_asin_reports_incr` | 领星ERP - SP广告(Sponsored Products) - ASIN(亚马逊产品编号) - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_sp_product_ad_reports_incr` | 领星ERP - SP广告(Sponsored Products) - 产品 - 广告 - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_lingxing_sp_word_reports_incr` | 领星ERP - SP广告(Sponsored Products) - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_m_completion_rate` | 完成率 - 汇率/比率 | 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_m_completion_rate_test` | 完成率 - 汇率/比率 | 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_sales_target_daily` | 销售 - 目标 - 日度 | 销售分析, 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ads_week_completion_rate` | 完成率 - 汇率/比率 | 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dim_lingxing_adv_account` | 领星ERP - 广告 - 账号 | 广告投放, 店铺管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_mws_reviews_incr` | 领星ERP - 增量 | 评论评价 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_newad_portfolios_incr` | 领星ERP - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sb_word_reports_incr` | 领星ERP - SB广告(Sponsored Brands) - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_newad_aba_report_incr` | 领星ERP - 报告 - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_product_performance` | 领星ERP - 产品 - 业绩/表现 | 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_product_performance_asin` | 领星ERP - 产品 - 业绩/表现 - ASIN(亚马逊产品编号) | 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_product_performance_msku` | 领星ERP - 产品 - 业绩/表现 - MSKU(商户SKU) | 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_profit_report_msku_incr` | 领星ERP - 利润 - 报告 - MSKU(商户SKU) - 增量 | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_profit_report_msku_incr_tmp` | 领星ERP - 利润 - 报告 - MSKU(商户SKU) - 增量 - 临时 | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_profit_report_sku_incr` | 领星ERP - 利润 - 报告 - SKU(库存单位) - 增量 | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_profit_report_store_incr` | 领星ERP - 利润 - 报告 - 店铺 - 增量 | 利润报告, 店铺管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sc_profit_statistics_msku_incr` | 领星ERP - 利润 - 统计/汇总 - MSKU(商户SKU) - 增量 | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_ad_groups_incr` | 领星ERP - SP广告(Sponsored Products) - 广告 - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_asin_reports_incr` | 领星ERP - SP广告(Sponsored Products) - ASIN(亚马逊产品编号) - 增量 | 广告投放, 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_campaigns_incr` | 领星ERP - SP广告(Sponsored Products) - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_key_word_reports_incr` | 领星ERP - SP广告(Sponsored Products) - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_product_ad_reports_incr` | 领星ERP - SP广告(Sponsored Products) - 产品 - 广告 - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_transaction_detail_incr` | 领星ERP - SP广告(Sponsored Products) - 交易 - 明细 - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `dwd_lingxing_sp_word_reports_incr` | 领星ERP - SP广告(Sponsored Products) - 增量 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `feishu_amz_bi_upload` | 飞书 | 其他 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `feishu_multi_platform_bi_upload` | 飞书 | 其他 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `leang_oper_staff_org_offline` | 乐昂(公司) - 员工/人员 | 人员组织 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `leang_sales_dep_leader_evaluations` | 乐昂(公司) - 销售 - 组长/负责人 | 销售分析, 人员组织, 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `leang_sales_staff_performance_evaluations` | 乐昂(公司) - 销售 - 员工/人员 - 业绩/表现 | 销售分析, 人员组织, 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `leang_sales_team_leader_evaluations` | 乐昂(公司) - 销售 - 团队 - 组长/负责人 | 销售分析, 人员组织, 目标考核 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `leang_staff_org` | 乐昂(公司) - 员工/人员 | 人员组织 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `mid_final_result` | mid_final_result | 其他 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_mws_reviews` | 领星ERP | 评论评价 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_newad_portfolios` | 领星ERP | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sb_word_reports` | 领星ERP - SB广告(Sponsored Brands) | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_adv_list` | 领星ERP - 广告 - 列表 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_newad_aba_report` | 领星ERP - 报告 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_product_performance` | 领星ERP - 产品 - 业绩/表现 | 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_product_performance_asin` | 领星ERP - 产品 - 业绩/表现 - ASIN(亚马逊产品编号) | 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_product_performance_msku` | 领星ERP - 产品 - 业绩/表现 - MSKU(商户SKU) | 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_profit_report_msku` | 领星ERP - 利润 - 报告 - MSKU(商户SKU) | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_profit_report_sku` | 领星ERP - 利润 - 报告 - SKU(库存单位) | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_profit_report_store` | 领星ERP - 利润 - 报告 - 店铺 | 利润报告, 店铺管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sc_profit_statistics_msku` | 领星ERP - 利润 - 统计/汇总 - MSKU(商户SKU) | 产品管理, 利润报告 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_ad_groups` | 领星ERP - SP广告(Sponsored Products) - 广告 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_asin_reports` | 领星ERP - SP广告(Sponsored Products) - ASIN(亚马逊产品编号) | 广告投放, 产品管理 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_campaigns` | 领星ERP - SP广告(Sponsored Products) | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_key_word_reports` | 领星ERP - SP广告(Sponsored Products) | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_product_ad_reports` | 领星ERP - SP广告(Sponsored Products) - 产品 - 广告 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_transaction_detail` | 领星ERP - SP广告(Sponsored Products) - 交易 - 明细 | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `ods_lingxing_sp_word_reports` | 领星ERP - SP广告(Sponsored Products) | 广告投放 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |
| `temp_pici_awd` | 临时 - 亚马逊AWD仓储 | 其他 | 与库存、采购、发货、物流、销售预测链路关联弱，首期不纳入。 |
| `temp_pici_cgzt` | 临时 | 其他 | 与库存、采购、发货、物流、销售预测链路关联弱，首期不纳入。 |
| `temp_pici_dfh` | 临时 | 其他 | 与库存、采购、发货、物流、销售预测链路关联弱，首期不纳入。 |
| `tmp_current_time` | 临时 | 其他 | 与库存、采购、发货、物流、销售预测链路关联弱，首期不纳入。 |
| `tmp_t_source` | 临时 | 其他 | 广告、评价、人员、目标考核或销售绩效类，库存全链路溯源首期基本不需要。 |

## 首期建议接入顺序

1. 主查询宽表：`ads_lingxing_all_warehouse_new_v1`。
2. 预测表：`dim_inventory_forecast_v1`、`dim_inventory_forecast_v1_fh`。
3. 库存明细：`dwd_lingxing_fba_warehouse_detail`、`dwd_lingxing_inventory_details`。
4. 需求来源：`ads_lingxing_sc_sales_daily_new`。
5. 规则表：`temp_lingxing_stocking_rules`、`ads_lingxing_stocking_rules`。
6. 过程追踪：采购订单、采购计划、发货计划、FBA shipment、inbound shipment、物流监控、在途发货。

## connector 设计建议

- 首期默认只查 `main` 和 `directly_used`，避免 Agent 在 300 多张表里盲查。
- `possibly_useful` 只在用户明确问到产品、店铺、退货、利润、活动、日历、预测版本时启用。
- `not_needed` 首期禁止自动查询，除非人工把表提升到其他池。
- 由于主宽表一月一更，涉及“今天库存/最新在途/最新发货”的问题必须落到 DWD/ODS 明细或实时快照表复核。