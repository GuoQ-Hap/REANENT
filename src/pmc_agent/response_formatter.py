from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any
import re

from pmc_agent.domain import AgentRunResult, ControlDecision, TaskType


FIELD_MEANINGS = {
    "material_code": "查询对象，通常为 SKU/MSKU/FNSKU",
    "risk_level": "规则工具计算出的风险级别",
    "category": "本次结果所属业务场景",
    "on_hand": "FBA、海外仓、本地仓等库存合计",
    "allocated": "已占用或已分配的数量",
    "available": "当前总库存扣除已分配后的数量",
    "inbound": "接收中、处理中、在途和计划量合计",
    "demand_next_7d": "近 7 天销量或 7 天需求口径",
    "demand_next_30d": "未来预测或近 30 天需求口径",
    "projected_7d": "按库存、在途和 7 天需求推算的库存余额",
    "days_of_cover": "预计库存可支撑销售的天数",
    "safety_stock": "规则表或宽表给出的安全库存口径",
    "lead_time_days": "供应或物流交付所需天数",
    "shortage_qty": "按需求、可用库存和在途计算出的缺口",
    "suggested_purchase_qty": "结合缺口和 MOQ 后的采购草稿量",
    "moq": "供应商或规则约束的最小起订量",
    "base_shipment_qty": "按需求和可用库存得到的基础发货量",
    "shipment_correction_qty": "扣除在途后仍需修正的发货量",
}


CALCULATION_LOGIC = {
    "inventory_health": [
        "可用库存 = 当前总库存 - 已分配数量。",
        "预计 7 天后库存 = 可用库存 + 在途/计划入库合计 - 未来/近 7 天需求。",
        "库存可覆盖天数 = max(预计 7 天后库存, 0) / max(未来/近 30 天日均需求, 默认日需求)。",
        "风险等级按覆盖天数判断：<=3 天为严重风险，<=7 天为高风险，<=14 天为中风险，否则为低风险。",
    ],
    "shortage_trace": [
        "断货追因基于库存、需求、在途、采购和发货窗口形成原因链。",
        "预计 7 天后库存低于 0 时按严重风险处理，否则按中风险提示继续复核。",
    ],
    "shipment_verification": [
        "可用库存 = 当前总库存 - 已分配数量。",
        "基础发货量 = max(未来/近 7 天需求 - 可用库存, 0)。",
        "发货修正量 = max(基础发货量 - 在途/计划入库合计, 0)。",
    ],
    "purchase_verification": [
        "可用库存 = 当前总库存 - 已分配数量。",
        "采购缺口数量 = max(未来/近 30 天需求 - 可用库存 - 在途/计划入库合计, 0)。",
        "建议采购数量 = max(采购缺口数量, MOQ)。当前输出仍是草稿，必须人工确认 MOQ、箱规、供应商和合并采购规则。",
    ],
}


def format_agent_reply(result: AgentRunResult) -> str:
    failure = _format_failure(result)
    if failure:
        return failure

    chat_reply = result.artifacts.get("chat_reply")
    if isinstance(chat_reply, dict) and chat_reply.get("reply"):
        return str(chat_reply["reply"])

    sections: list[str] = []
    if result.decisions:
        sections.append("**查询结果**")
        sections.append(_decision_table(result.decisions))
        sections.append("**计算逻辑**")
        sections.append(_calculation_logic(result.decisions, result.plan.task_type))
        sections.append("**建议动作**")
        sections.append(_action_table(result.decisions))

    visible_artifacts = {key: value for key, value in result.artifacts.items() if key not in {"chat_reply", "attachments"}}
    if visible_artifacts:
        sections.append("**已生成草稿 / 产物**")
        sections.append(_artifact_table(visible_artifacts))

    attachments = result.artifacts.get("attachments")
    if isinstance(attachments, list) and attachments:
        sections.append("**附件**")
        sections.extend(_format_attachment(item) for item in attachments if isinstance(item, dict))

    if result.plan.assumptions:
        sections.append("**提示**")
        sections.append("未识别到具体物料，当前按整体库存范围处理。")

    if not sections:
        return "我还没有拿到足够的信息。可以补充物料编码，比如 A100，或说明你要看库存、采购还是发货。"
    return "\n\n".join(item for item in sections if item)


def wants_excel_attachment(text: str) -> bool:
    lowered = text.lower()
    terms = ("excel", "xlsx", "附件", "导出", "下载", "表格文件", "回传")
    return any(term in lowered for term in terms)


def rows_for_export(result: AgentRunResult) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    query_rows: list[dict[str, Any]] = []
    logic_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    for decision in result.decisions:
        query_rows.append(_decision_row(decision))
        for index, logic in enumerate(_logic_items(decision.category, result.plan.task_type), start=1):
            logic_rows.append({"物料编码": decision.material_code, "步骤": index, "计算逻辑": logic})
        for action in decision.recommended_actions:
            action_rows.append({"物料编码": decision.material_code, "风险等级": _risk_label(_value(decision.risk_level)), "建议动作": action})
    return query_rows, logic_rows, action_rows


def build_agent_result_ui(result: AgentRunResult) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    calculations: list[str] = []
    if result.decisions:
        decision_columns = _decision_columns()
        tables.append(
            {
                "id": "query_result",
                "title": "查询结果",
                "description": "按固定字段展示本轮查询与规则计算结果。",
                "columns": [_ui_column(key, label) for key, label in decision_columns],
                "rows": [_ui_row(_decision_row(decision), decision_columns) for decision in result.decisions],
            }
        )
        action_columns = [("material_code", "物料编码"), ("risk_level", "风险等级"), ("actions", "建议动作")]
        tables.append(
            {
                "id": "recommended_actions",
                "title": "建议动作",
                "description": "系统给出的动作建议，执行前仍需结合业务口径复核。",
                "columns": [_ui_column(key, label) for key, label in action_columns],
                "rows": [_ui_row(row, action_columns) for row in _action_rows(result.decisions)],
            }
        )
        calculations = _calculation_items(result.decisions, result.plan.task_type)

    visible_artifacts = {key: value for key, value in result.artifacts.items() if key not in {"chat_reply", "attachments"}}
    if visible_artifacts:
        artifact_columns = [("name", "产物名称"), ("meaning", "含义"), ("size", "数量")]
        tables.append(
            {
                "id": "artifacts",
                "title": "已生成草稿 / 产物",
                "description": "草稿类产物需要人工复核后再执行。",
                "columns": [_ui_column(key, label) for key, label in artifact_columns],
                "rows": [_ui_row(row, artifact_columns) for row in _artifact_rows(visible_artifacts)],
            }
        )
    return {"tables": tables, "calculations": calculations}


def build_agentic_result_ui(result: Any) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    observation_rows = _agentic_rows_from_observations(result)
    if observation_rows:
        keys = _ordered_keys(observation_rows)
        tables.append(
            {
                "id": "agentic_observation_result",
                "title": "查询结果",
                "description": "来自本轮工具 observation 的结构化结果。",
                "columns": [_ui_column(key, key) for key in keys],
                "rows": [{key: row.get(key) for key in keys} for row in observation_rows],
            }
        )
    for index, table in enumerate(_extract_markdown_tables(str(getattr(result, "reply", "") or "")), start=1):
        columns = [{"key": key, "label": key, "meaning": FIELD_MEANINGS.get(key, key), "align": _column_align(key)} for key in table["headers"]]
        tables.append(
            {
                "id": f"model_table_{index}",
                "title": "查询结果" if index == 1 and not observation_rows else f"结果表 {index}",
                "description": "模型按固定表格组件展示的本轮结果。",
                "columns": columns,
                "rows": table["rows"],
            }
        )
    return {"tables": tables, "calculations": _extract_calculation_items(str(getattr(result, "reply", "") or ""))}


def strip_markdown_tables(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    table_block: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            table_block.append(line)
            continue
        if table_block:
            table_block = []
        kept.append(line)
    return _compact_blank_lines("\n".join(kept)).strip()


def _decision_table(decisions: list[ControlDecision]) -> str:
    headers = _decision_columns()
    rows = [_decision_row(decision) for decision in decisions]
    return _markdown_table(headers, rows)


def _action_table(decisions: list[ControlDecision]) -> str:
    rows = _action_rows(decisions)
    return _markdown_table(
        [("material_code", "物料编码"), ("risk_level", "风险等级"), ("actions", "建议动作")],
        rows,
    )


def _artifact_table(artifacts: dict[str, Any]) -> str:
    return _markdown_table([("name", "产物名称"), ("meaning", "含义"), ("size", "数量")], _artifact_rows(artifacts))


def _artifact_rows(artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for name, value in artifacts.items():
        size = f"{len(value)} 条" if isinstance(value, list) else f"{len(value)} 项" if isinstance(value, dict) else "1 项"
        rows.append({"name": name, "meaning": "草稿或辅助产物，需要人工复核", "size": size})
    return rows


def _calculation_logic(decisions: list[ControlDecision], task_type: TaskType) -> str:
    return "\n".join(f"{index}. {item}" for index, item in enumerate(_calculation_items(decisions, task_type), start=1))


def _calculation_items(decisions: list[ControlDecision], task_type: TaskType) -> list[str]:
    seen: list[str] = []
    for decision in decisions:
        for item in _logic_items(decision.category, task_type):
            if item not in seen:
                seen.append(item)
    return seen


def _logic_items(category: str, task_type: TaskType) -> list[str]:
    if category in CALCULATION_LOGIC:
        return CALCULATION_LOGIC[category]
    if task_type == TaskType.INVENTORY_RISK:
        return CALCULATION_LOGIC["inventory_health"]
    return ["该结果来自规则工具输出；数量、风险和建议均基于工具返回的 evidence，草稿类产物需要人工复核。"]


def _decision_row(decision: ControlDecision) -> dict[str, Any]:
    evidence = decision.evidence or {}
    on_hand = _number(evidence.get("on_hand"))
    allocated = _number(evidence.get("allocated"))
    inbound = _number(evidence.get("inbound"))
    demand_7d = _number(evidence.get("demand_next_7d"))
    demand_30d = _number(evidence.get("demand_next_30d"))
    available = None if on_hand is None or allocated is None else on_hand - allocated
    projected_7d = None if available is None or inbound is None or demand_7d is None else available + inbound - demand_7d
    row = {
        "material_code": decision.material_code,
        "risk_level": _risk_label(_value(decision.risk_level)),
        "category": decision.category,
        "on_hand": on_hand,
        "allocated": allocated,
        "available": available,
        "inbound": inbound,
        "demand_next_7d": demand_7d,
        "demand_next_30d": demand_30d,
        "projected_7d": projected_7d,
    }
    for key in ("shortage_qty", "suggested_purchase_qty", "moq", "base_shipment_qty", "shipment_correction_qty"):
        if key in evidence:
            row[key] = evidence[key]
    return row


def _decision_columns() -> list[tuple[str, str]]:
    return [
        ("material_code", "物料编码"),
        ("risk_level", "风险等级"),
        ("on_hand", "当前总库存"),
        ("available", "可用库存"),
        ("inbound", "在途/计划入库合计"),
        ("demand_next_7d", "未来/近 7 天需求"),
        ("demand_next_30d", "未来/近 30 天需求"),
        ("projected_7d", "预计 7 天后库存"),
        ("category", "业务类型"),
    ]


def _action_rows(decisions: list[ControlDecision]) -> list[dict[str, Any]]:
    rows = []
    for decision in decisions:
        rows.append(
            {
                "material_code": decision.material_code,
                "risk_level": _risk_label(_value(decision.risk_level)),
                "actions": "；".join(decision.recommended_actions) or "-",
            }
        )
    return rows


def _ui_column(key: str, label: str) -> dict[str, str]:
    return {
        "key": key,
        "label": label,
        "meaning": FIELD_MEANINGS.get(key, label),
        "align": _column_align(key),
    }


def _ui_row(row: dict[str, Any], columns: list[tuple[str, str]]) -> dict[str, Any]:
    return {key: _value(row.get(key)) for key, _ in columns}


def _column_align(key: str) -> str:
    return "right" if re.search(r"qty|stock|days|demand|hand|available|inbound|projected|sales|库存|销量|数量|天数", key, re.I) else "left"


def _agentic_rows_from_observations(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in getattr(result, "steps", []) or []:
        observation = getattr(step, "observation", {}) or {}
        rows.extend(_flatten_agentic_rows("snapshot", observation.get("snapshots")))
        rows.extend(_flatten_agentic_rows("decision", observation.get("decisions")))
        subtasks = observation.get("subtasks")
        if isinstance(subtasks, list):
            for subtask in subtasks:
                if not isinstance(subtask, dict):
                    continue
                source = str(subtask.get("action") or subtask.get("kind") or "subtask")
                rows.extend(_flatten_agentic_rows(source, subtask.get("snapshots")))
                rows.extend(_flatten_agentic_rows(source, subtask.get("decisions")))
    return rows


def _flatten_agentic_rows(source: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row: dict[str, Any] = {"来源": source}
        for key, raw in item.items():
            if isinstance(raw, dict):
                for child_key, child_value in raw.items():
                    if not isinstance(child_value, (dict, list)):
                        row[f"{key}.{child_key}"] = _value(child_value)
            elif isinstance(raw, list):
                row[key] = "；".join(str(part) for part in raw[:5])
            else:
                row[key] = _value(raw)
        rows.append(row)
    return rows


def _ordered_keys(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "来源",
        "material_code",
        "sku",
        "msku",
        "warehouse",
        "country",
        "risk_level",
        "on_hand",
        "available",
        "inbound",
        "sales_7d",
        "demand_next_7d",
        "demand_next_30d",
        "projected_7d",
        "recommended_actions",
    ]
    keys = [key for key in preferred if any(key in row for row in rows)]
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    return keys


def _extract_markdown_tables(text: str) -> list[dict[str, Any]]:
    tables: list[dict[str, Any]] = []
    block: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            block.append(stripped)
            continue
        if block:
            parsed = _parse_markdown_table(block)
            if parsed:
                tables.append(parsed)
            block = []
    if block:
        parsed = _parse_markdown_table(block)
        if parsed:
            tables.append(parsed)
    return tables


def _parse_markdown_table(lines: list[str]) -> dict[str, Any] | None:
    if len(lines) < 2:
        return None
    headers = [_clean_markdown_cell(cell) for cell in lines[0].strip("|").split("|")]
    if not headers or not _is_separator(lines[1]):
        return None
    rows = []
    for line in lines[2:]:
        values = [_clean_markdown_cell(cell) for cell in line.strip("|").split("|")]
        if not any(values):
            continue
        rows.append({headers[index]: values[index] if index < len(values) else "" for index in range(len(headers))})
    return {"headers": headers, "rows": rows}


def _clean_markdown_cell(value: str) -> str:
    return value.strip().replace("`", "")


def _is_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _extract_calculation_items(text: str) -> list[str]:
    marker_index = text.find("计算逻辑")
    if marker_index < 0:
        return []
    tail = text[marker_index:].splitlines()[1:]
    items: list[str] = []
    for line in tail:
        stripped = line.strip()
        if not stripped:
            if items:
                break
            continue
        match = re.match(r"^(?:[-*]|\d+[.、])\s*(.+)$", stripped)
        if match:
            items.append(match.group(1).strip())
    return items


def _compact_blank_lines(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text)


def _markdown_table(headers: list[tuple[str, str]], rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "暂无数据。"
    header_text = [f"{label}（{FIELD_MEANINGS.get(key, label)}）" for key, label in headers]
    lines = [
        "| " + " | ".join(header_text) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_cell(row.get(key)) for key, _ in headers) + " |")
    return "\n".join(lines)


def _format_failure(result: AgentRunResult) -> str:
    failure_decision = result.artifacts.get("failure_decision")
    if not failure_decision:
        return ""
    if isinstance(failure_decision, dict):
        message = str(failure_decision.get("user_message") or "当前查询失败，模型已生成处理建议。")
        suggested = failure_decision.get("suggested_inputs") or []
    else:
        message = str(getattr(failure_decision, "user_message", "当前查询失败，模型已生成处理建议。"))
        suggested = getattr(failure_decision, "suggested_inputs", [])
    if suggested:
        return message + "\n\n可补充：" + "；".join(str(item) for item in suggested)
    return message


def _format_attachment(item: dict[str, Any]) -> str:
    label = str(item.get("name") or "附件")
    url = str(item.get("url") or item.get("path") or "")
    if url:
        return f"[{label}]({url})"
    return label


def _risk_label(value: str) -> str:
    return {
        "critical": "严重风险",
        "high": "高风险",
        "medium": "中风险",
        "low": "低风险",
    }.get(value, value)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cell(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.2f}".rstrip("0").rstrip(".")
    text = str(_value(value))
    return text.replace("|", "\\|").replace("\n", " ")


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return asdict(value)
    return value
