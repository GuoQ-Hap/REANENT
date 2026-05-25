# PMC Frontend Rule Inventory

Source file: `D:\laydown\ric-train-master\frontend\src\pages\InventoryLKA.tsx`

This document inventories the business rules currently embedded in the LKA inventory frontend and maps them to backend agent modules that should own them.

## Migration Goal

Move deterministic PMC rules out of the React page and into audited backend tools.

- The frontend should send filters, uploaded rule files, and user actions.
- The backend should query data, calculate quantities, generate validation artifacts, and return structured results.
- The model should explain, ask follow-up questions, and choose tools, but should not invent quantities.

## Rule Areas Found

| Area | Current frontend behavior | Target backend owner | Priority |
| --- | --- | --- | --- |
| Inventory health warning | Classifies rows as shortage warning, redundant stock, inventory anomaly, or normal. | `InventoryHealthTool` / `ControlTowerTool` | P0 |
| Cross-table validation | Checks daily forecast, actual sales, transit, and FBA detail against the inventory base table. | `InventoryDataValidationTool` | P0 |
| Shipment verification | Recalculates shipment T0/T1/T2/T3, M3, base shipment quantity, correction quantity, and reference quantity. | `ShipmentVerificationTool` | P1 |
| Purchase verification | Recalculates purchase T0/T1/T2/T3, M3, base purchase quantity, correction quantity, and reference quantity. | `PurchaseVerificationTool` | P1 |
| MOQ and carton rounding | Applies full-box, half-box, slow/normal/hot item rounding, and MOQ thresholds. | `MoqRuleEngine` | P1 |
| Purchase mix rules | Handles "can combine purchase" groups by supplier, style, color, and width thresholds. | `PurchaseMixRuleEngine` | P2 |
| Weekly shipment plan | Builds shipment plan rows, three-week demand split, warehouse allocation, stock checks, and merge groups. | `WeeklyShipmentPlanTool` | P2 |
| Excel import | Reads stocking rules and MOQ requirement files in the browser. | Backend upload/parser capability | P1 |
| Excel export | Writes shipment validation, purchase validation, and weekly shipment plan workbooks. | `excel_attachment` capability | P1 |

## Data Sources

| Source | Purpose in frontend |
| --- | --- |
| `ads_lingxing_all_warehouse_new_v1` | Main inventory, demand, sales, stock, timing, purchase, shipment, and risk fields. |
| `temp_lingxing_stocking_rules` | Shipment frequency, restocking frequency, oversell ratio, safety days, next delivery days. |
| `temp_fnsku_boxing` | Carton quantity and supplier ID. |
| `dim_lingxing_local_inventory_product_info` | Supplier quote, product name, material, supplier code candidates. |
| `temp_lingxing_pici_sale` | Batch sales difference fields such as `chazhi_0_7` through `chazhi_0_98`. |
| `dim_lingxing_sales_estimates_everyday_incr` | Daily forecast sales for 30-day validation. |
| `ads_lingxing_sc_sales_daily_new` | Actual 7-day and 30-day sales, ad spend, promotion volume. |
| `in_transit_shipment` | In-transit quantity, estimated shelf date, delay days, logistics exception. |
| `dwd_lingxing_fba_warehouse_detail` | FBA detail stock validation. |
| `dim_inventory_forecast_v1` | Purchase-side forecast and ending inventory. |
| `dim_inventory_forecast_v1_fh` | Shipment-side forecast and ending inventory. |
| `dwd_lingxing_inventory_details` | Domestic warehouse stock detail. |
| `dwd_lingxing_sc_warehouse` | Warehouse name and warehouse metadata. |
| `dim_lingxing_warehouse_mapping` | Warehouse business type mapping. |
| `ods_lingxing_inventory_details` | Locked inventory for pending allocation. |
| `dwd_lingxing_inbound_shipment_list_incr` | Pending inbound/shipment allocation from `relate_list`. |

## Inventory Health Rules

Current frontend output fields:

- `warning_type`: `断货预警`, `冗余库存`, `库存异常`, `正常`
- `risk_level`: `高`, `中`, `低`, `正常`
- `sellable_days`
- `total_inventory`
- `lead_time_days`
- `validation_status`
- `validation_notes`
- `suggested_action`

Current rules:

| Rule | Formula / condition |
| --- | --- |
| Daily demand | `forecast_30d_sales_checked / 30`; fallback to `sale_quantity_30 / 30`. |
| Total inventory | `fba_warehouse_quantity + overseas_warehouse_quantity + local_warehouse_quantity + stock_up_num`. |
| FBA sellable days | `afn_fulfillable_quantity / daily_demand`. |
| Lead time | `order_duration + production_duration + max(local_to_FBA_time, overseas_to_FBA_time, local_to_overseas_warehouse_time) + fba_safety_days_fn`. |
| Long-age stock | `inv_age_181_to_270_days + inv_age_271_to_330_days + inv_age_331_to_365_days + inv_age_365_plus_days`. |
| Shortage warning | `daily_demand > 0` and `sellable_days <= max(lead_time, 7)`. |
| Redundant stock | `forecast30 > 0` and `total_inventory > forecast30 * 2.5` and `long_age > max(20, total_inventory * 0.15)`. |
| FBA anomaly | FBA detail difference greater than `max(10, fba_sellable * 0.08)`. |
| Sales spike | Actual 7-day sales greater than `max(10, 7-day baseline * 2.2)`. |
| Logistics anomaly | `max_delay_days > 3` or logistics exception exists. |
| Risk level high | Shortage and `sellable_days <= 7`. |
| Risk level medium | Shortage or anomaly. |
| Risk level low | Redundant stock. |

Suggested actions:

- Shortage: replenish immediately and target coverage of `ceil(lead_time + safety_stock_days_sales)` days.
- Redundant stock: check unshipped batches and delay or stop local/overseas replenishment.
- Anomaly: review sales, ads, FBA stock, and transit status.
- Normal: continue monitoring.

## Shipment Verification Rules

Inputs:

- Stocking rule file if uploaded.
- Otherwise database fields from `temp_lingxing_stocking_rules`.
- Shipment forecast table: `dim_inventory_forecast_v1_fh`.
- M3 ending inventory by `FNSKU + store_name + shipment T3 - 1 day`.

Core rules:

| Item | Rule |
| --- | --- |
| Shipment frequency | Uploaded stocking rule `发货频率`; fallback to `temp_lingxing_stocking_rules.shipments_frequency`; fallback `30`. |
| T0 | Empty if countdown >= frequency. Otherwise validation date + max(countdown, 0). |
| T1 | If T0 exists, validation date + frequency. |
| T2/T3 source | Uses base table `start_dates0` and `end_dates0`; no validation-date fallback. |
| M3 | `dim_inventory_forecast_v1_fh.ending_inventory` on `end_dates0 - 1 day`. |
| Base shipment quantity | Sum `expected_sales` from T2 inclusive to T3 exclusive. |
| Safety quantity | `next_logistics_safety_days * daily_sales`. |
| Correction quantity | `T1~T3 expected sales * oversell_rate + safety_quantity - M3`. |
| Reference quantity | `max(base_shipment_quantity + correction_quantity, 0)`. |
| Comparison fields | `basic_fh_quantity`, `fhxiuzhenliang`, `jyfahuo_quantity`. |
| Validation | Difference = recalculated value - base table value; tolerance is `0.05`. |

Notes to preserve:

- If base shipment window is missing, base quantity, M3, and correction are checked as zero.
- If M3 is missing while T3 exists, correction and reference cannot be fully recalculated.
- The result must include data-source notes and exact diff fields.

## Purchase Verification Rules

Inputs:

- Stocking rule file if uploaded.
- Purchase forecast table: `dim_inventory_forecast_v1`.
- M3 ending inventory by `FNSKU + store_name + purchase T3 - 1 day`.

Core rules:

| Item | Rule |
| --- | --- |
| Purchase frequency | Uploaded stocking rule `补货频率`; fallback to `restocking_frequency`; fallback to shipment frequency; fallback `30`. |
| Purchase T0 | Empty if countdown 6 >= purchase frequency. Otherwise validation date + max(countdown, 0). |
| Purchase T1 | If purchase T0 exists, validation date + purchase frequency. |
| Purchase T2/T3 source | Uses base table `start_dates` and `end_dates`; no validation-date fallback. |
| M3 | `dim_inventory_forecast_v1.ending_inventory` on `end_dates - 1 day`. |
| Base purchase quantity | Sum `expected_sales` from T2 inclusive to T3 exclusive. |
| Safety quantity | `next_logistics_safety_days * daily_sales`. |
| Correction quantity | `T1~T3' expected sales * oversell_rate + safety_quantity - M3`. |
| Reference quantity | `max(base_purchase_quantity + correction_quantity, 0)`. |
| Comparison fields | `basic_purchase_quantity`, `xiuzhenliang`, `jypurchase_quantity`. |
| Validation | Difference = recalculated value - base table value; tolerance is `0.05`. |

## MOQ And Carton Rules

Rule file fields currently parsed:

- `SKU`
- `供应商`
- `备注`
- `单个起订量`
- `大机器起订量`
- `单件尺寸`

Matching order:

1. Supplier + SKU.
2. Parsed supplier candidates + SKU.
3. SKU only.

Rounding behavior:

| Condition | Rule |
| --- | --- |
| No carton quantity | Quantity remains as planned. |
| Remark includes `半箱起订` | Round up by `0.5 * carton_qty`. |
| Sales property includes `滞` | Tail box ratio greater than `70%` rounds up; otherwise rounds down. |
| Sales property includes `平` | Tail box ratio greater than or equal to `50%` rounds up; otherwise rounds down. |
| Sales property includes `爆` or `旺` | Round up to full carton. |
| Other | Round up to full carton. |

MOQ behavior:

- Remark includes `大机器`: use `大机器起订量`.
- Otherwise use `单个起订量`.
- If whole-box quantity is below MOQ, only raise to MOQ when future 180-day sales reach at least `80%` of MOQ.
- If whole-box quantity is below MOQ and future demand is insufficient, planned purchase quantity becomes `0`.
- If whole-box purchase quantity is less than `10` and box count is less than `3`, planned purchase quantity becomes `0` with remark `需求过低`.
- If seasonality includes `节日款`, planned purchase quantity becomes `0`.
- If MOQ remark includes `统一备货`, planned purchase quantity becomes `0`.

## Purchase Mix Rules

Applicable when:

- MOQ remark includes `可拼`.
- MOQ remark does not include `不可拼`.
- `单件尺寸` is available.
- A square-meter threshold can be parsed from the remark.

Grouping dimensions:

- Supplier code is always included.
- `同款` adds style.
- `同色` or `单色` adds color.
- `同门幅` adds width.
- If no style/color/width restriction exists, group by supplier only.

Behavior:

- If group square meters already reach the threshold, keep each SKU's own whole-box purchase quantity and add mix remark.
- If not reached, raise quantities by carton or half-carton step up to future 180-day sales cap.
- If still below threshold, keep best effort and mark as not reached.

## Weekly Shipment Plan Rules

Main outputs:

- Weekly shipment plan detail sheet.
- Shipment merge summary sheet.
- Domestic stock detail sheet.
- Rule explanation sheet.

Core rules:

| Item | Rule |
| --- | --- |
| Plan source | Reads all rows from `ads_lingxing_all_warehouse_new_v1`; rows without suggested shipment quantity are retained with zero shipment output. |
| Plan shipment date | Uses `start_dates0`; no validation-date fallback. |
| Planned shipment quantity | Uses `jyfahuo_quantity`. |
| First three shipment weeks | Nearest Friday on or after selected date, then the following two Fridays. |
| Weekly demand window | Arrival date + 1 through arrival date + 7. |
| Weekly demand source | Sum `dim_inventory_forecast_v1_fh.expected_sales`. |
| Late order handling | If shipment T0 is in current week, current-week demand becomes zero and is not moved to next week. |
| T0 outside current week | Distribute three-week demand from T0 shipment week by carton quantity and mark over-demand. |
| Shipment gap | If gap is below 100, put it into first available week. If at least 100, distribute by full cartons across available weeks. |
| Channel split | Fast ship maps to `美森`; slow ship maps to `慢船`. |
| Coverage-end suggestion | If ending inventory on coverage end is negative, round shortage up by carton/half-carton step. If ending inventory is missing, fallback to coverage demand minus FBA sellable. |
| High inventory cancellation | If sellable days >= 90 and item is slow-moving or seasonal, suggested shipment quantity becomes 0. |
| Shortage channel upgrade | If shortage risk exists and current channel is slow ship, suggest `美森`. |
| Stock limit | If shipment exceeds domestic total or available + inbound stock, cap shipment to supportable quantity. |
| Return rebuild | If return quantity exists, mark that shipment needs separate rebuild plan. |

Domestic stock rules:

- Domestic total stock = `local_warehouse_quantity + local_afn_inbound_shipped_quantity`.
- Domestic available stock = `local_warehouse_quantity`.
- Domestic inbound stock = `local_afn_inbound_shipped_quantity`.
- Pending allocation = `ods_lingxing_inventory_details.product_lock_num` plus pending inbound shipment `relate_list[].num`.
- Warehouse role priority: transit warehouse first, supplier warehouse second, other local warehouse third.

Inventory check:

| Status | Condition |
| --- | --- |
| `超发` | Whole-box shipment quantity > domestic total stock. |
| `库存充足` | Domestic available stock >= whole-box shipment quantity. |
| `可用不足在途覆盖` | Available stock is insufficient, but available + inbound can cover. |
| `可用不足` | Available + inbound cannot cover. |

Shipment merge group:

- Same store.
- Same plan shipment date.
- Same product size class.
- Same transparent plan status.
- Same warehouse or supplier.

## Backend Migration Plan

### P0: Inventory Health And Validation

1. Extend `schema_catalog.py` with all fields used by the inventory health page.
2. Add connector methods for daily forecast, actual sales, transit, and FBA stock validation.
3. Implement `InventoryHealthTool` and `InventoryDataValidationTool`.
4. Add tests using fixed row fixtures copied from frontend rule examples.

### P1: Shipment And Purchase Verification

1. Implement date-window helpers shared by shipment and purchase tools.
2. Add M3 lookup helpers for `dim_inventory_forecast_v1` and `dim_inventory_forecast_v1_fh`.
3. Implement structured result rows and diff outputs.
4. Generate Excel attachments through the existing `excel_attachment` capability.

### P2: Weekly Shipment Plan

1. Implement MOQ parser and carton rounding engine.
2. Implement purchase mix groups.
3. Implement domestic warehouse allocation and stock-limited shipment quantities.
4. Generate detail, merge summary, domestic stock, and rule explanation sheets.

## Frontend Changes After Migration

- Replace raw SQL calls with backend endpoints or agent tools.
- Keep filters, upload controls, tables, and download buttons.
- Show backend-calculated explanations and validation notes.
- Remove deterministic business formulas from React after parity tests pass.

## Parity Tests Required

- Shortage, redundant stock, and anomaly classification parity.
- Shipment base/correction/reference quantity parity.
- Purchase base/correction/reference quantity parity.
- MOQ and carton rounding parity for hot, normal, slow, and half-box cases.
- Weekly demand split and late-order adjustment parity.
- Domestic stock status parity.
- Shipment merge group parity.
