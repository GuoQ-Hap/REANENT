# Extracted Requirements From Project Proposal

Source PDF rendered with Poppler `pdftoppm` from:

`D:/desktop/PMC库存供应链智能体暂行立项书第一版5月20日.pdf`

## Project Positioning

- Project name: 凌昂科技 PMC 库存供应链智能体项目.
- Suggested product name: PMC库存计划官 / 小昂库存计划官.
- Target: build a trustworthy, explainable, recalculable, closed-loop inventory planning agent for cross-border e-commerce PMC work.
- Method: structured data + deterministic rule engine + agent orchestration + human confirmation.

## First-Phase Scope

- Inventory control tower.
- Risk list with risk level, PMC, shop, country, MSKU, and FNSKU filters.
- Single SKU/FNSKU shortage tracing.
- Shipment verification.
- Purchase verification.
- Weekly shipment plan draft.
- Agent Q&A around inventory, shipment, purchase, and rule logic.
- Knowledge base for field definitions, SOPs, stocking rules, shipment/purchase calculation rules.
- Feedback records for suggested purchases, manual edits, abnormal causes, and handling results.

## Explicitly Out Of Initial Scope

- Automatically creating formal purchase orders.
- Automatically modifying ERP, OMS, or WMS inventory/orders.
- Automatically adjusting formal shipment orders.
- Automatically changing safety stock rules.
- Full supplier collaboration platform.
- Finance-level cash-flow optimization.
- Complex multi-level inventory optimization.

## Data Base

- `ads_lingxing_all_warehouse_new`: inventory control tower bottom table.
- `dim_inventory_forecast_v1`: purchase-side future inventory forecast.
- `dim_inventory_forecast_v1_fh`: shipment-side future inventory forecast.
- `ads_lingxing_sc_sales_daily_new`: sales daily report, actual sales, ads, promotion data.
- `dwd_lingxing_fba_warehouse_detail`: FBA inventory details.
- `dwd_lingxing_inventory_details`: domestic warehouse inventory details.
- `temp_lingxing_stocking_rules`: stocking rules.
- Supplementary Excel rules: stocking rules, reorder quantity, carton size, suppliers.

## Rule Engine Tools

- Inventory health calculation: shortage warning, redundant stock, inventory abnormality.
- Sellable-days calculation: FBA sellable and sales forecast.
- Lead-time calculation: orders, production, domestic warehouse, overseas warehouse, FBA delivery, safety days.
- Shipment recalculation: base shipment quantity, shipment correction quantity, shipment reference quantity.
- Purchase recalculation: base purchase quantity, purchase correction quantity, purchase reference quantity.
- Inventory reconciliation: sufficient stock, over-shipment, available + in-transit coverage, insufficient stock.
- MOQ/carton calculation: full cartons, half-carton ordering, combined purchase, demand-too-low cases.
- Logistics advice: slow boat, Mason service, shipment suspension, delay, in-transit attention.

## Agent Split

- Inventory health agent.
- Shortage tracing agent.
- Shipment verification agent.
- Purchase verification agent.
- Weekly plan agent.
- Exception case agent.

## Governance

- Role boundaries: PMC, purchase, logistics, operations, management.
- Data boundaries by shop, country, sales department, and owner.
- High-risk actions require human confirmation.
- Preserve audit records for suggestion generation, manual edits, export, confirmation, and closure.
- Preserve versions of stocking rules, shipment plans, and purchase suggestions.

## Milestones

- P0, weeks 1-2: demand and rule sorting; field paths, rule documents, existing frontend calculation logic.
- P1, weeks 3-5: backend rule tools; inventory health, shipment recalculation, purchase recalculation, inventory reconciliation.
- P2, weeks 6-8: agent prototype; single SKU trace, risk summary, shipment/purchase explanation.
- P3, weeks 9-11: control tower and cases; inventory control tower, risk list, exception case process.
- P4, weeks 12-14: weekly plan loop; draft, export, human confirmation, feedback records.
- P5, weeks 15-16: evaluation and optimization; adoption rate, hit rate, recalculation consistency, forecast deviation.

## Acceptance Criteria

- Show inventory control tower.
- Trace shortage cause by FNSKU.
- Generate shipment verification table and explain differences.
- Generate purchase verification table and explain differences.
- Generate weekly shipment plan draft.
- Answer rule and suggestion questions through the agent.
- Record human confirmation and handling results.
- Explain shipment and purchase recalculation differences against bottom-table fields.
- Detect and alert on missing M3, forecast, and FBA details.
- Clearly distinguish inventory paths: FBA, overseas warehouse, local warehouse, in-transit, pending allocation.

## Main Risks And Responses

- Inconsistent data paths: define primary paths; every answer shows data source and path.
- High rule complexity: solidify high-frequency rules first; low-frequency rules enter human confirmation.
- LLM hallucination: quantities, dates, and amounts are calculated only by deterministic tools.
- Business distrust: every suggestion shows reason chain, data source, and calculation basis.
- Automation risk: first phase only generates drafts; key actions require human confirmation.
- Forecast deviation: establish forecast-deviation review and manual correction entry.
- Heavy system coupling: extract and reuse existing frontend calculation logic first, then backendize gradually.
