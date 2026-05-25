from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape
import re
import zipfile

from pmc_agent.domain import AgentRunResult
from pmc_agent.model_io import generate_time_id
from pmc_agent.response_formatter import rows_for_export


@dataclass(frozen=True)
class Attachment:
    name: str
    path: str
    url: str
    mime_type: str


def create_result_excel_attachment(result: AgentRunResult, output_root: Path, url_root: str = "/generated") -> Attachment | None:
    query_rows, logic_rows, action_rows = rows_for_export(result)
    if not query_rows and not logic_rows and not action_rows:
        return None

    request_id = str(result.request.metadata.get("request_id") or generate_time_id())
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", request_id)
    filename = f"pmc_result_{safe_id}.xlsx"
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / filename

    sheets = [
        ("查询结果", _sheet_rows(query_rows)),
        ("计算逻辑", _sheet_rows(logic_rows)),
        ("建议动作", _sheet_rows(action_rows)),
    ]
    _write_xlsx(path, sheets)
    return Attachment(
        name=filename,
        path=str(path),
        url=f"{url_root.rstrip('/')}/{filename}",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def create_agentic_excel_attachment(result: Any, output_root: Path, request_id: str, url_root: str = "/generated") -> Attachment | None:
    query_rows, logic_rows, action_rows = _rows_from_agentic_result(result)
    if not query_rows and not logic_rows and not action_rows:
        return None

    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", request_id)
    filename = f"pmc_agentic_result_{safe_id}.xlsx"
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / filename
    sheets = [
        ("查询结果", _sheet_rows(query_rows)),
        ("计算逻辑", _sheet_rows(logic_rows)),
        ("建议动作", _sheet_rows(action_rows)),
    ]
    _write_xlsx(path, sheets)
    return Attachment(
        name=filename,
        path=str(path),
        url=f"{url_root.rstrip('/')}/{filename}",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _rows_from_agentic_result(result: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    query_rows: list[dict[str, Any]] = []
    logic_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    for step in getattr(result, "steps", []) or []:
        observation = getattr(step, "observation", {}) or {}
        query_rows.extend(_flatten_rows("snapshot", observation.get("snapshots")))
        query_rows.extend(_flatten_rows("decision", observation.get("decisions")))
        for subtask in observation.get("subtasks", []) if isinstance(observation.get("subtasks"), list) else []:
            if isinstance(subtask, dict):
                query_rows.extend(_flatten_rows(str(subtask.get("action") or subtask.get("kind") or "subtask"), subtask.get("snapshots")))
                query_rows.extend(_flatten_rows(str(subtask.get("action") or subtask.get("kind") or "subtask"), subtask.get("decisions")))
    if not query_rows:
        query_rows.extend(_rows_from_markdown_tables(str(getattr(result, "reply", "") or "")))
    if query_rows:
        logic_rows = [
            {"步骤": 1, "计算逻辑": "查询结果来自模型选择的受控工具 observation。"},
            {"步骤": 2, "计算逻辑": "若包含风险判断，风险由后端规则工具基于库存、在途、需求和覆盖天数计算。"},
            {"步骤": 3, "计算逻辑": "Excel 为按用户要求生成的附件，仅汇总本轮工具返回的数据和建议。"},
        ]
    for row in query_rows:
        actions = row.get("recommended_actions")
        if isinstance(actions, list):
            for action in actions:
                action_rows.append({"物料编码": row.get("material_code") or row.get("sku") or "-", "建议动作": action})
    return query_rows, logic_rows, action_rows


def _rows_from_markdown_tables(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    table_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if line.startswith("|") and line.endswith("|"):
            table_lines.append(line)
            continue
        if table_lines:
            rows.extend(_parse_markdown_table(table_lines))
            table_lines = []
    if table_lines:
        rows.extend(_parse_markdown_table(table_lines))
    return rows


def _parse_markdown_table(lines: list[str]) -> list[dict[str, Any]]:
    if len(lines) < 2:
        return []
    header = [_clean_markdown_cell(cell) for cell in lines[0].strip("|").split("|")]
    if not header or not _is_markdown_separator(lines[1]):
        return []
    parsed_rows: list[dict[str, Any]] = []
    for line in lines[2:]:
        values = [_clean_markdown_cell(cell) for cell in line.strip("|").split("|")]
        if not any(values):
            continue
        parsed_rows.append({header[index]: values[index] if index < len(values) else "" for index in range(len(header))})
    return parsed_rows


def _clean_markdown_cell(value: str) -> str:
    return value.strip().replace("`", "")


def _is_markdown_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell or "") for cell in cells)


def _flatten_rows(source: str, value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row = {"来源": source}
        for key, raw in item.items():
            if isinstance(raw, dict):
                for child_key, child_value in raw.items():
                    if not isinstance(child_value, (dict, list)):
                        row[f"{key}.{child_key}"] = child_value
            elif isinstance(raw, list):
                row[key] = "；".join(str(part) for part in raw[:5])
            else:
                row[key] = raw
        rows.append(row)
    return rows


def _sheet_rows(rows: list[dict[str, Any]]) -> list[list[Any]]:
    if not rows:
        return [["说明"], ["暂无数据"]]
    headers = list(rows[0].keys())
    return [headers, *[[row.get(header) for header in headers] for row in rows]]


def _write_xlsx(path: Path, sheets: list[tuple[str, list[list[Any]]]]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _content_types(len(sheets)))
        archive.writestr("_rels/.rels", _root_rels())
        archive.writestr("xl/workbook.xml", _workbook_xml(sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", _workbook_rels(len(sheets)))
        archive.writestr("xl/styles.xml", _styles_xml())
        for index, (_, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", _worksheet_xml(rows))


def _worksheet_xml(rows: list[list[Any]]) -> str:
    row_xml = []
    max_cols = max((len(row) for row in rows), default=1)
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{_column_name(col_index)}{row_index}"
            style = 1 if row_index == 1 else 0
            cells.append(_cell_xml(ref, value, style))
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    cols = "".join(f'<col min="{i}" max="{i}" width="22" customWidth="1"/>' for i in range(1, max_cols + 1))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<cols>{cols}</cols>"
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _cell_xml(ref: str, value: Any, style: int) -> str:
    style_attr = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style_attr}><v>{1 if value else 0}</v></c>'
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = escape("" if value is None else str(value))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types(sheet_count: int) -> str:
    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        f"{sheet_overrides}"
        "</Types>"
    )


def _root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheets: list[tuple[str, list[list[Any]]]]) -> str:
    sheet_xml = "".join(
        f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, (name, _) in enumerate(sheets, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheet_xml}</sheets>"
        "</workbook>"
    )


def _workbook_rels(sheet_count: int) -> str:
    rels = "".join(
        f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    rels += f'<Relationship Id="rId{sheet_count + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{rels}"
        "</Relationships>"
    )


def _styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="1" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
        "</styleSheet>"
    )
