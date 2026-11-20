#!/usr/bin/env python3
"""从 JSON plan 生成 docx / xlsx / pptx。

plan schema 见 skills/office-docs/SKILL.md；本模块只负责校验与落盘。
"""

from __future__ import annotations

import importlib
import math
import re
from pathlib import Path
from typing import Any, Iterable

import office_info
import office_common as oc


class PlanError(oc.OfficeError):
    def __init__(self, message: str, hint: str | None = None) -> None:
        super().__init__(f"plan 校验失败：{message}", "usage", hint=hint)


def _import(module_name: str, pip_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        raise oc.dependency_error(
            f"缺少 Python 依赖 {pip_name}：{exc}",
            hint=(
                f"运行时异常，请由维护者补齐：{oc.PYTHON} -m pip install {pip_name}；"
                "离线目标机应随 office-kit 一起分发该依赖。"
            ),
        ) from exc


def _dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanError(f"{path} 必须是对象（{{...}}），实际是 {type(value).__name__}")
    return value


def _list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise PlanError(f"{path} 必须是数组（[...]），实际是 {type(value).__name__}")
    return value


def _str(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PlanError(f"{path} 必须是字符串，实际是 {type(value).__name__}")
    if not allow_empty and not value.strip():
        raise PlanError(f"{path} 不能为空字符串")
    return value


def _bool(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        raise PlanError(f"{path} 必须是 true / false")
    return value


def _number(
    value: Any, path: str, *, minimum: float = -math.inf, maximum: float = math.inf
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PlanError(f"{path} 必须是数字")
    number = float(value)
    if not math.isfinite(number) or number < minimum or number > maximum:
        raise PlanError(f"{path} 必须在 {minimum} ~ {maximum} 之间，实际是 {value}")
    return number


def _color(value: Any, path: str) -> str:
    text = _str(value, path).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        raise PlanError(f"{path} 必须是 6 位十六进制颜色（如 \"FF0000\"）")
    return text.upper()


def _check_keys(
    obj: dict[str, Any],
    allowed: Iterable[str],
    path: str,
    warnings: list[str],
    *,
    label: str = "字段",
) -> None:
    allowed_set = set(allowed)
    for key in obj:
        if key in allowed_set or key.startswith("$") or key in ("description", "comment"):
            continue
        where = f"{path}.{key}" if path else key
        warnings.append(f"{where} 不是已知{label}，已忽略")


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (dict, list)):
        return ""
    return str(value)


# ===========================================================================
# docx
# ===========================================================================

_DOCX_KEYS = {
    "title",
    "subtitle",
    "author",
    "subject",
    "keywords",
    "font",
    "headings",
    "paragraphs",
    "tables",
    "blocks",
}
_PARA_KEYS = {"text", "style", "bold", "italic", "size", "align", "color", "bullet"}
_TABLE_KEYS = {"headers", "rows", "style", "widths", "headerBold"}
_HEADING_KEYS = {"text", "level"}
_BLOCK_TYPES = {"title", "heading", "paragraph", "table", "bullets", "pageBreak"}
_ALIGN_MAP = {
    "left": "LEFT",
    "center": "CENTER",
    "right": "RIGHT",
    "justify": "JUSTIFY",
}


def _parse_paragraph(spec: Any, path: str, warnings: list[str]) -> dict[str, Any]:
    if isinstance(spec, str):
        return {"text": _str(spec, path)}
    obj = _dict(spec, path)
    _check_keys(obj, _PARA_KEYS, path, warnings)
    text = _str(obj.get("text", ""), f"{path}.text", allow_empty=True)
    result: dict[str, Any] = {"text": text}
    if obj.get("style") is not None:
        result["style"] = _str(obj["style"], f"{path}.style")
    for key in ("bold", "italic", "bullet"):
        if obj.get(key) is not None:
            result[key] = _bool(obj[key], f"{path}.{key}")
    if obj.get("size") is not None:
        result["size"] = _number(obj["size"], f"{path}.size", minimum=1, maximum=200)
    if obj.get("align") is not None:
        align = _str(obj["align"], f"{path}.align").lower()
        if align not in _ALIGN_MAP:
            raise PlanError(
                f"{path}.align 只能是 left/center/right/justify，实际是 {align!r}"
            )
        result["align"] = align
    if obj.get("color") is not None:
        result["color"] = _color(obj["color"], f"{path}.color")
    return result


def _parse_heading(spec: Any, path: str, warnings: list[str]) -> dict[str, Any]:
    if isinstance(spec, str):
        return {"text": _str(spec, path), "level": 1}
    obj = _dict(spec, path)
    _check_keys(obj, _HEADING_KEYS, path, warnings)
    text = _str(obj.get("text"), f"{path}.text")
    level = obj.get("level")
    if level is None:
        level = 1
    level_num = _number(level, f"{path}.level", minimum=1, maximum=9)
    if not level_num.is_integer():
        raise PlanError(f"{path}.level 必须是 1~9 的整数")
    return {"text": text, "level": int(level_num)}


def _parse_table(spec: Any, path: str, warnings: list[str]) -> dict[str, Any]:
    obj = _dict(spec, path)
    _check_keys(obj, _TABLE_KEYS, path, warnings)
    headers = obj.get("headers")
    if headers is not None:
        headers = _list(headers, f"{path}.headers")
        headers = [_cell_text(item) for item in headers]
    rows = obj.get("rows")
    if rows is None:
        rows = []
    rows = _list(rows, f"{path}.rows")
    parsed_rows: list[list[str]] = []
    for index, row in enumerate(rows):
        row_list = _list(row, f"{path}.rows[{index}]")
        parsed_rows.append([_cell_text(item) for item in row_list])
    if not headers and not parsed_rows:
        raise PlanError(f"{path} 至少要提供 headers 或 rows")
    widths = None
    if obj.get("widths") is not None:
        raw_widths = _list(obj["widths"], f"{path}.widths")
        widths = [
            _number(w, f"{path}.widths[{i}]", minimum=0.5, maximum=50)
            for i, w in enumerate(raw_widths)
        ]
    style_value = obj.get("style")
    result = {
        "headers": headers,
        "rows": parsed_rows,
        "style": _str(style_value, f"{path}.style") if style_value is not None else "Table Grid",
        "widths": widths,
        "headerBold": _bool(obj["headerBold"], f"{path}.headerBold")
        if obj.get("headerBold") is not None
        else True,
    }
    total_columns = max(
        [len(result["headers"]) if result["headers"] else 0]
        + [len(row) for row in parsed_rows]
        + [0]
    )
    if total_columns > 64:
        raise PlanError(f"{path} 列数 {total_columns} 超过上限 64")
    return result


def _parse_bullets(spec: Any, path: str, warnings: list[str]) -> list[dict[str, Any]]:
    items = _list(spec, path)
    parsed: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        item_path = f"{path}[{index}]"
        if isinstance(item, str):
            parsed.append({"text": _str(item, item_path), "level": 0})
            continue
        obj = _dict(item, item_path)
        _check_keys(obj, {"text", "level"}, item_path, warnings)
        level_value = obj.get("level")
        if level_value is None:
            level_value = 0
        level = _number(level_value, f"{item_path}.level", minimum=0, maximum=2)
        if not level.is_integer():
            raise PlanError(f"{item_path}.level 必须是 0~2 的整数")
        parsed.append(
            {"text": _str(obj.get("text"), f"{item_path}.text"), "level": int(level)}
        )
    return parsed


def _apply_font_to_styles(docx_module: Any, document: Any, font: str) -> None:
    qn = docx_module.oxml.ns.qn
    names = {"Normal", "Title", "Subtitle"} | {f"Heading {i}" for i in range(1, 10)}
    for style in document.styles:
        try:
            style_name = style.name
        except Exception:
            continue
        if style_name not in names:
            continue
        try:
            style.font.name = font
            rpr = style.element.get_or_add_rPr()
            rfonts = rpr.get_or_add_rFonts()
            for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
                rfonts.set(qn(attr), font)
        except Exception:
            continue


def _add_docx_paragraph(
    docx_module: Any,
    document: Any,
    spec: dict[str, Any],
    *,
    style: str | None = None,
    warnings: list[str] | None = None,
    path: str = "paragraph",
    bullet_level: int = 0,
) -> Any:
    from docx.enum.text import WD_ALIGN_PARAGRAPH  # type: ignore
    from docx.shared import Cm  # type: ignore

    chosen_style = style or spec.get("style")
    is_bullet = bool(spec.get("bullet"))
    if is_bullet:
        # 不依赖模板里的 List Bullet 编号定义（部分模板不渲染项目符号），
        # 直接用项目符号 + 悬挂缩进，保证 LibreOffice/Word 中外观一致。
        chosen_style = spec.get("style")
    paragraph = None
    if chosen_style:
        try:
            paragraph = document.add_paragraph(style=chosen_style)
        except KeyError:
            if warnings is not None:
                warnings.append(f"{path}.style 未找到样式 {chosen_style!r}，已改用普通段落")
            paragraph = document.add_paragraph()
    else:
        paragraph = document.add_paragraph()
    text = spec.get("text", "")
    if is_bullet:
        prefix = {0: "• ", 1: "◦ ", 2: "▪ "}.get(bullet_level, "• ")
        text = prefix + text
        paragraph.paragraph_format.left_indent = Cm(0.75 * (bullet_level + 1))
        paragraph.paragraph_format.first_line_indent = Cm(-0.55)
    run = paragraph.add_run(text)
    if spec.get("bold"):
        run.bold = True
    if spec.get("italic"):
        run.italic = True
    if spec.get("size") is not None:
        from docx.shared import Pt  # type: ignore

        run.font.size = Pt(spec["size"])
    if spec.get("color"):
        from docx.shared import RGBColor  # type: ignore

        run.font.color.rgb = RGBColor.from_string(spec["color"])
    if spec.get("align"):
        paragraph.alignment = getattr(WD_ALIGN_PARAGRAPH, _ALIGN_MAP[spec["align"]])
    return paragraph


def _add_docx_table(
    docx_module: Any,
    document: Any,
    spec: dict[str, Any],
    *,
    warnings: list[str],
    path: str,
) -> Any:
    from docx.shared import Cm  # type: ignore

    headers = spec.get("headers") or []
    rows = list(spec.get("rows") or [])
    all_rows = ([headers] if headers else []) + rows
    columns = max(len(row) for row in all_rows)
    table = document.add_table(rows=len(all_rows), cols=columns)
    style = spec.get("style")
    if style:
        try:
            table.style = style
        except KeyError:
            warnings.append(f"{path}.style 未找到表格样式 {style!r}，已使用默认样式")
    for row_index, row in enumerate(all_rows):
        for col_index in range(columns):
            value = row[col_index] if col_index < len(row) else ""
            cell = table.cell(row_index, col_index)
            cell.text = value
            if row_index == 0 and headers and spec.get("headerBold"):
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.bold = True
    widths = spec.get("widths")
    if widths:
        for col_index, width in enumerate(widths[:columns]):
            for row in table.rows:
                row.cells[col_index].width = Cm(width)
    return table


def build_docx(plan: dict[str, Any], output: Path, warnings: list[str]) -> dict[str, Any]:
    docx_module = _import("docx", "python-docx")
    _check_keys(plan, _DOCX_KEYS, "", warnings)

    title = plan.get("title")
    if title is not None:
        title = _str(title, "title", allow_empty=True) or None
    subtitle = plan.get("subtitle")
    if subtitle is not None:
        subtitle = _str(subtitle, "subtitle", allow_empty=True) or None
    font = plan.get("font")
    if font is not None:
        font = _str(font, "font", allow_empty=True) or None

    document = docx_module.Document()
    if font:
        _apply_font_to_styles(docx_module, document, font)
    props = document.core_properties
    if title:
        props.title = title
    for key in ("author", "subject", "keywords"):
        value = plan.get(key)
        if value is not None and value != "":
            setattr(props, key, _str(value, key))

    content_blocks: list[dict[str, Any]] = []
    raw_blocks = plan.get("blocks")
    if raw_blocks is not None:
        raw_blocks = _list(raw_blocks, "blocks")
        if raw_blocks and any(
            plan.get(key) for key in ("headings", "paragraphs", "tables")
        ):
            warnings.append(
                "同时提供了 blocks 与 headings/paragraphs/tables；已按 blocks 顺序渲染，后者被忽略"
            )
        elif not raw_blocks and any(
            plan.get(key) for key in ("headings", "paragraphs", "tables")
        ):
            warnings.append("blocks 为空数组，已改用 headings/paragraphs/tables")
        for index, block in enumerate(raw_blocks):
            block_path = f"blocks[{index}]"
            obj = _dict(block, block_path)
            block_type = _str(obj.get("type"), f"{block_path}.type")
            if block_type not in _BLOCK_TYPES:
                raise PlanError(
                    f"{block_path}.type 只能是 {sorted(_BLOCK_TYPES)}，实际是 {block_type!r}"
                )
            content_blocks.append({"type": block_type, "spec": obj, "path": block_path})
    if not raw_blocks:
        # 这里只保留原始 spec，统一在下面的渲染循环里解析一次，避免二次解析
        # 已解析的 dict（例如 widths=None）再次触发 _list 校验。
        headings = plan.get("headings")
        headings = _list(headings, "headings") if headings is not None else []
        paragraphs = plan.get("paragraphs")
        paragraphs = _list(paragraphs, "paragraphs") if paragraphs is not None else []
        tables = plan.get("tables")
        tables = _list(tables, "tables") if tables is not None else []
        for heading in headings:
            content_blocks.append(
                {"type": "heading", "spec": heading, "path": "headings"}
            )
        for paragraph in paragraphs:
            content_blocks.append(
                {"type": "paragraph", "spec": paragraph, "path": "paragraphs"}
            )
        for table in tables:
            content_blocks.append({"type": "table", "spec": table, "path": "tables"})

    if title:
        document.add_heading(title, level=0)
    if subtitle:
        try:
            document.add_paragraph(subtitle, style="Subtitle")
        except KeyError:
            document.add_paragraph(subtitle)

    for block in content_blocks:
        block_type = block["type"]
        spec = block["spec"]
        path = block["path"]
        if block_type == "paragraph" and isinstance(spec, str):
            payload: Any = {"text": spec}
        elif isinstance(spec, dict):
            payload = {k: v for k, v in spec.items() if k != "type"}
        else:
            payload = spec
        if block_type == "title":
            text = _str(payload.get("text"), f"{path}.text")
            document.add_heading(text, level=0)
        elif block_type == "heading":
            parsed = _parse_heading(payload, path, warnings)
            document.add_heading(parsed["text"], level=parsed["level"])
        elif block_type == "paragraph":
            parsed = _parse_paragraph(payload, path, warnings)
            _add_docx_paragraph(
                docx_module, document, parsed, warnings=warnings, path=path
            )
        elif block_type == "bullets":
            items = _parse_bullets(payload.get("items", payload.get("bullets")), f"{path}.items", warnings)
            for item in items:
                _add_docx_paragraph(
                    docx_module,
                    document,
                    {"text": item["text"], "bullet": True},
                    warnings=warnings,
                    path=path,
                    bullet_level=item["level"],
                )
        elif block_type == "table":
            parsed = _parse_table(payload, path, warnings)
            _add_docx_table(
                docx_module, document, parsed, warnings=warnings, path=path
            )
        elif block_type == "pageBreak":
            document.add_page_break()

    try:
        document.save(str(output))
    except OSError as exc:
        raise oc.runtime_error(f"无法写入 docx {output}：{exc}") from exc

    return {
        "paragraphCount": len(document.paragraphs),
        "tableCount": len(document.tables),
        "sectionCount": len(document.sections),
        "wordCount": office_info.count_words(
            "\n".join(p.text for p in document.paragraphs)
        ),
    }


# ===========================================================================
# xlsx
# ===========================================================================

_XLSX_KEYS = {"sheets"}
_SHEET_KEYS = {
    "name",
    "rows",
    "formulas",
    "widths",
    "styles",
    "freeze",
    "autofilter",
}
_STYLE_KEYS = {
    "bold",
    "italic",
    "size",
    "color",
    "fill",
    "align",
    "valign",
    "wrap",
    "numberFormat",
}
_ALIGN_X = {"left", "center", "right", "justify", "general"}
_ALIGN_Y = {"top", "center", "bottom"}
_INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")
_CELL_REF_RE = re.compile(r"\$?([A-Za-z]{1,3})\$?([1-9]\d{0,6})")


def _validate_sheet_name(name: Any, path: str) -> str:
    text = _str(name, path)
    if len(text) > 31:
        raise PlanError(f"{path} 长度不能超过 31 个字符（Excel 限制）")
    if _INVALID_SHEET_CHARS.search(text):
        raise PlanError(f"{path} 不能包含 [ ] : * ? / \\ 等字符")
    if text.startswith("'") or text.endswith("'"):
        raise PlanError(f"{path} 不能以单引号开头或结尾")
    return text


def _parse_cell_style(
    spec: Any, path: str, warnings: list[str]
) -> dict[str, Any]:
    obj = _dict(spec, path)
    _check_keys(obj, _STYLE_KEYS, path, warnings)
    result: dict[str, Any] = {}
    for key in ("bold", "italic", "wrap"):
        if key in obj:
            result[key] = _bool(obj[key], f"{path}.{key}")
    if "size" in obj:
        result["size"] = _number(obj["size"], f"{path}.size", minimum=1, maximum=200)
    if "color" in obj:
        result["color"] = _color(obj["color"], f"{path}.color")
    if "fill" in obj:
        result["fill"] = _color(obj["fill"], f"{path}.fill")
    if "align" in obj:
        align = _str(obj["align"], f"{path}.align").lower()
        if align not in _ALIGN_X:
            raise PlanError(f"{path}.align 只能是 {sorted(_ALIGN_X)}")
        result["align"] = align
    if "valign" in obj:
        valign = _str(obj["valign"], f"{path}.valign").lower()
        if valign not in _ALIGN_Y:
            raise PlanError(f"{path}.valign 只能是 {sorted(_ALIGN_Y)}")
        result["valign"] = valign
    if "numberFormat" in obj:
        result["numberFormat"] = _str(obj["numberFormat"], f"{path}.numberFormat")
    return result


def _apply_xlsx_style(cell: Any, spec: dict[str, Any], styles_module: Any) -> None:
    Font = styles_module.Font
    PatternFill = styles_module.PatternFill
    Alignment = styles_module.Alignment

    font_kwargs: dict[str, Any] = {}
    if spec.get("bold"):
        font_kwargs["bold"] = True
    if spec.get("italic"):
        font_kwargs["italic"] = True
    if spec.get("size") is not None:
        font_kwargs["size"] = spec["size"]
    if spec.get("color"):
        font_kwargs["color"] = spec["color"]
    if font_kwargs:
        cell.font = Font(**font_kwargs)
    if spec.get("fill"):
        color = spec["fill"]
        cell.fill = PatternFill(fill_type="solid", start_color=color, end_color=color)
    align_kwargs: dict[str, Any] = {}
    if spec.get("align"):
        align_kwargs["horizontal"] = spec["align"]
    if spec.get("valign"):
        align_kwargs["vertical"] = spec["valign"]
    if "wrap" in spec:
        align_kwargs["wrap_text"] = spec["wrap"]
    if align_kwargs:
        cell.alignment = Alignment(**align_kwargs)
    if spec.get("numberFormat"):
        cell.number_format = spec["numberFormat"]


def _normalize_cell_value(value: Any, path: str) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise PlanError(f"{path} 不能是 NaN / Infinity")
        return value
    raise PlanError(f"{path} 只能是字符串 / 数字 / 布尔 / null")


def build_xlsx(plan: dict[str, Any], output: Path, warnings: list[str]) -> dict[str, Any]:
    openpyxl = _import("openpyxl", "openpyxl")
    styles_module = _import("openpyxl.styles", "openpyxl")
    utils = _import("openpyxl.utils", "openpyxl")
    _check_keys(plan, _XLSX_KEYS, "", warnings)

    raw_sheets = plan.get("sheets")
    if raw_sheets is None:
        raw_sheets = [{"name": "Sheet1", "rows": []}]
    raw_sheets = _list(raw_sheets, "sheets")
    if not raw_sheets:
        raise PlanError("sheets 至少需要一个工作表")

    workbook = openpyxl.Workbook()
    default_sheet = workbook.active
    seen_names: set[str] = set()
    sheet_summaries: list[dict[str, Any]] = []
    total_cells = 0
    total_formulas = 0

    for sheet_index, raw_sheet in enumerate(raw_sheets):
        sheet_path = f"sheets[{sheet_index}]"
        sheet = _dict(raw_sheet, sheet_path)
        _check_keys(sheet, _SHEET_KEYS, sheet_path, warnings)
        default_name = "Sheet1" if sheet_index == 0 else f"Sheet{sheet_index + 1}"
        name_value = sheet.get("name")
        if name_value is None:
            name_value = default_name
        name = _validate_sheet_name(name_value, f"{sheet_path}.name")
        if name.lower() in seen_names:
            raise PlanError(f"{sheet_path}.name 工作表名重复：{name!r}")
        seen_names.add(name.lower())
        if sheet_index == 0:
            worksheet = default_sheet
            worksheet.title = name
        else:
            worksheet = workbook.create_sheet(title=name)

        rows = sheet.get("rows")
        rows = _list(rows, f"{sheet_path}.rows") if rows is not None else []
        formula_cells: set[tuple[int, int]] = set()
        used_cells: set[tuple[int, int]] = set()
        column_count = 0
        non_empty_rows = 0
        for row_index, raw_row in enumerate(rows, start=1):
            row = _list(raw_row, f"{sheet_path}.rows[{row_index - 1}]")
            if len(row) > 16384:
                raise PlanError(f"{sheet_path}.rows[{row_index - 1}] 列数超过 16384")
            if len(row) > column_count:
                column_count = len(row)
            row_has_value = False
            for col_index, value in enumerate(row, start=1):
                value = _normalize_cell_value(
                    value, f"{sheet_path}.rows[{row_index - 1}][{col_index - 1}]"
                )
                if value is None:
                    continue
                if isinstance(value, str) and value == "":
                    continue
                row_has_value = True
                if (row_index, col_index) not in used_cells:
                    used_cells.add((row_index, col_index))
                    total_cells += 1
                    if total_cells > 300_000:
                        raise PlanError("plan 单元格总数超过 300000，请拆分生成")
                if isinstance(value, str) and value.startswith("="):
                    formula_cells.add((row_index, col_index))
                worksheet.cell(row=row_index, column=col_index, value=value)
            if row_has_value:
                non_empty_rows += 1

        formulas = sheet.get("formulas")
        formulas = _dict(formulas, f"{sheet_path}.formulas") if formulas is not None else {}
        for cell_ref, formula in formulas.items():
            ref_path = f"{sheet_path}.formulas.{cell_ref}"
            normalized_ref = str(cell_ref).replace("$", "").upper()
            match = _CELL_REF_RE.fullmatch(normalized_ref)
            if not match:
                raise PlanError(f"{ref_path} 不是合法的 A1 单元格引用")
            formula_text = _str(formula, ref_path)
            if not formula_text.startswith("="):
                raise PlanError(f"{ref_path} 必须以 = 开头（例如 \"=SUM(A1:A3)\"）")
            worksheet[normalized_ref] = formula_text
            ref_row = int(match.group(2))
            ref_col = utils.column_index_from_string(match.group(1))
            formula_cells.add((ref_row, ref_col))
            if (ref_row, ref_col) not in used_cells:
                used_cells.add((ref_row, ref_col))
                total_cells += 1
                if total_cells > 300_000:
                    raise PlanError("plan 单元格总数超过 300000，请拆分生成")

        widths = sheet.get("widths")
        widths = _dict(widths, f"{sheet_path}.widths") if widths is not None else {}
        for column, width in widths.items():
            col_path = f"{sheet_path}.widths.{column}"
            if not re.fullmatch(r"[A-Za-z]{1,3}", str(column)):
                raise PlanError(f"{col_path} 的列名必须是 A、B、AA 这样的字母")
            column_width = _number(width, col_path, minimum=0.1, maximum=255)
            worksheet.column_dimensions[str(column).upper()].width = column_width

        styles = sheet.get("styles")
        styles = _dict(styles, f"{sheet_path}.styles") if styles is not None else {}
        for ref, style_spec in styles.items():
            style_path = f"{sheet_path}.styles.{ref}"
            try:
                bounds = utils.range_boundaries(str(ref).upper())
            except ValueError as exc:
                raise PlanError(f"{style_path} 不是合法的区域（如 A1 或 A1:C3）") from exc
            if None in bounds:
                raise PlanError(f"{style_path} 必须写明完整区域（如 A1:C3）")
            min_col, min_row, max_col, max_row = bounds
            area = (max_row - min_row + 1) * (max_col - min_col + 1)
            if area > 300_000:
                raise PlanError(
                    f"{style_path} 覆盖 {area} 个单元格，超过 300000 上限"
                )
            parsed_style = _parse_cell_style(style_spec, style_path, warnings)
            for row in worksheet.iter_rows(
                min_row=min_row, max_row=max_row, min_col=min_col, max_col=max_col
            ):
                for cell in row:
                    _apply_xlsx_style(cell, parsed_style, styles_module)

        freeze = sheet.get("freeze")
        if freeze is not None:
            freeze_text = _str(freeze, f"{sheet_path}.freeze").upper()
            if not re.fullmatch(r"[A-Z]{1,3}[1-9]\d*", freeze_text):
                raise PlanError(f"{sheet_path}.freeze 必须是单元格引用（如 A2）")
            worksheet.freeze_panes = freeze_text

        autofilter = sheet.get("autofilter")
        if autofilter is not None:
            filter_text = _str(autofilter, f"{sheet_path}.autofilter").upper()
            try:
                utils.range_boundaries(filter_text)
            except ValueError as exc:
                raise PlanError(
                    f"{sheet_path}.autofilter 必须是区域（如 A1:D10）"
                ) from exc
            worksheet.auto_filter.ref = filter_text

        formula_count = len(formula_cells)
        sheet_cells = len(used_cells)
        sheet_summaries.append(
            {
                "name": name,
                "rows": non_empty_rows,
                "columns": column_count,
                "nonEmptyCells": sheet_cells,
                "formulaCount": formula_count,
            }
        )
        total_formulas += formula_count

    try:
        workbook.save(str(output))
    except OSError as exc:
        raise oc.runtime_error(f"无法写入 xlsx {output}：{exc}") from exc
    finally:
        try:
            workbook.close()
        except Exception:
            pass

    return {
        "sheetCount": len(sheet_summaries),
        "sheets": sheet_summaries,
        "totalNonEmptyCells": total_cells,
        "totalFormulaCount": total_formulas,
    }


# ===========================================================================
# pptx
# ===========================================================================

_PPTX_KEYS = {
    "title",
    "author",
    "subject",
    "font",
    "slideSize",
    "cover",
    "slides",
}
_SLIDE_KEYS = {"title", "bullets", "notes", "table"}
_COVER_KEYS = {"title", "subtitle"}
_PPT_TABLE_KEYS = {"headers", "rows", "widths", "headerBold"}


def _parse_ppt_table(spec: Any, path: str, warnings: list[str]) -> dict[str, Any]:
    obj = _dict(spec, path)
    _check_keys(obj, _PPT_TABLE_KEYS, path, warnings)
    headers = obj.get("headers")
    if headers is not None:
        headers = [_cell_text(item) for item in _list(headers, f"{path}.headers")]
    rows = obj.get("rows", [])
    rows = _list(rows, f"{path}.rows")
    parsed_rows: list[list[str]] = []
    for index, row in enumerate(rows):
        parsed_rows.append(
            [_cell_text(item) for item in _list(row, f"{path}.rows[{index}]")]
        )
    if not headers and not parsed_rows:
        raise PlanError(f"{path} 至少要提供 headers 或 rows")
    widths = None
    if obj.get("widths") is not None:
        widths = [
            _number(w, f"{path}.widths[{i}]", minimum=0.2, maximum=13)
            for i, w in enumerate(_list(obj["widths"], f"{path}.widths"))
        ]
    columns = max(
        [len(headers) if headers else 0] + [len(r) for r in parsed_rows] + [0]
    )
    if columns > 20:
        raise PlanError(f"{path} 列数 {columns} 超过上限 20")
    return {
        "headers": headers,
        "rows": parsed_rows,
        "widths": widths,
        "headerBold": _bool(obj["headerBold"], f"{path}.headerBold")
        if obj.get("headerBold") is not None
        else True,
    }


def _pptx_set_font(run: Any, font: str) -> None:
    """设置拉丁字体，并尽力设置东亚字体（a:ea）。"""
    try:
        run.font.name = font
    except Exception:
        return
    try:
        rpr = run._r.get_or_add_rPr()
        ea = rpr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}ea")
        if ea is None:
            from pptx.oxml.ns import qn  # type: ignore

            ea = rpr.makeelement(qn("a:ea"), {})
            # a:ea 必须排在 a:cs 之前；没有 a:cs 时追加到末尾即可。
            cs = rpr.find(qn("a:cs"))
            if cs is not None:
                cs.addprevious(ea)
            else:
                rpr.append(ea)
        ea.set("typeface", font)
    except Exception:
        return


def _fill_pptx_bullets(
    text_frame: Any,
    bullets: list[dict[str, Any]],
    font: str | None,
    *,
    manual_bullets: bool = False,
) -> None:
    text_frame.clear()
    text_frame.word_wrap = True
    glyphs = {0: "• ", 1: "– ", 2: "· "}
    for index, item in enumerate(bullets):
        paragraph = text_frame.paragraphs[0] if index == 0 else text_frame.add_paragraph()
        text = item["text"]
        if manual_bullets:
            text = glyphs.get(item["level"], "• ") + text
        paragraph.text = text
        paragraph.level = min(8, max(0, item["level"]))
        if font:
            for run in paragraph.runs:
                _pptx_set_font(run, font)


def build_pptx(plan: dict[str, Any], output: Path, warnings: list[str]) -> dict[str, Any]:
    pptx = _import("pptx", "python-pptx")
    _check_keys(plan, _PPTX_KEYS, "", warnings)

    title = plan.get("title")
    if title is not None:
        title = _str(title, "title", allow_empty=True) or None
    font = plan.get("font")
    if font is not None:
        font = _str(font, "font", allow_empty=True) or None
    slide_size_value = plan.get("slideSize")
    if slide_size_value is None:
        slide_size_value = "16:9"
    slide_size = _str(slide_size_value, "slideSize")
    if slide_size not in ("16:9", "4:3"):
        raise PlanError("slideSize 只能是 \"16:9\" 或 \"4:3\"")

    cover_spec = plan.get("cover")
    if cover_spec is not None:
        cover_spec = _dict(cover_spec, "cover")
        _check_keys(cover_spec, _COVER_KEYS, "cover", warnings)
        cover_title = _str(cover_spec.get("title"), "cover.title")
        cover_subtitle = cover_spec.get("subtitle")
        if cover_subtitle is not None:
            cover_subtitle = _str(cover_subtitle, "cover.subtitle", allow_empty=True) or None
    else:
        cover_title = None
        cover_subtitle = None

    raw_slides = plan.get("slides")
    if raw_slides is None:
        raw_slides = []
    raw_slides = _list(raw_slides, "slides")
    if not raw_slides and not cover_title:
        raise PlanError("slides 不能为空（或至少提供 cover.title）")

    presentation = pptx.Presentation()
    from pptx.util import Inches  # type: ignore

    if slide_size == "16:9":
        presentation.slide_width = Inches(13.333)
        presentation.slide_height = Inches(7.5)
        content_width_in = 12.1
    else:
        presentation.slide_width = Inches(10)
        presentation.slide_height = Inches(7.5)
        content_width_in = 8.8

    props = presentation.core_properties
    if title:
        props.title = title
    for key in ("author", "subject"):
        value = plan.get(key)
        if value is not None:
            setattr(props, key, _str(value, key))

    if cover_title:
        layout = presentation.slide_layouts[0]
        slide = presentation.slides.add_slide(layout)
        try:
            slide.shapes.title.text = cover_title
            if cover_subtitle is not None and len(slide.placeholders) > 1:
                slide.placeholders[1].text = cover_subtitle
        except Exception:
            warnings.append("封面占位符不可用，已跳过部分封面文本")
        if font:
            for shape in slide.shapes:
                if not getattr(shape, "has_text_frame", False):
                    continue
                for paragraph in shape.text_frame.paragraphs:
                    for run in paragraph.runs:
                        _pptx_set_font(run, font)

    slide_summaries: list[dict[str, Any]] = []
    if cover_title:
        slide_summaries.append(
            {
                "index": 1,
                "title": cover_title,
                "bulletCount": 0,
                "tableCount": 0,
                "hasNotes": False,
                "cover": True,
            }
        )
    for index, raw_slide in enumerate(raw_slides):
        slide_path = f"slides[{index}]"
        slide_spec = _dict(raw_slide, slide_path)
        _check_keys(slide_spec, _SLIDE_KEYS, slide_path, warnings)
        slide_title = slide_spec.get("title")
        if slide_title is not None:
            slide_title = _str(slide_title, f"{slide_path}.title")
        bullets: list[dict[str, Any]] = []
        if slide_spec.get("bullets") is not None:
            bullets = _parse_bullets(
                slide_spec["bullets"], f"{slide_path}.bullets", warnings
            )
        notes = slide_spec.get("notes")
        if notes is not None:
            notes = _str(notes, f"{slide_path}.notes", allow_empty=True)
        table_spec = None
        if slide_spec.get("table") is not None:
            table_spec = _parse_ppt_table(
                slide_spec["table"], f"{slide_path}.table", warnings
            )

        use_table = table_spec is not None
        layout = presentation.slide_layouts[5] if use_table else presentation.slide_layouts[1]
        if not bullets and not use_table:
            layout = presentation.slide_layouts[5]
        slide = presentation.slides.add_slide(layout)
        if slide_title is not None:
            try:
                slide.shapes.title.text = slide_title
            except Exception:
                # 极少数模板没有标题占位符：补一个文本框。
                box = slide.shapes.add_textbox(
                    Inches(0.5), Inches(0.3), Inches(12.3), Inches(0.9)
                )
                box.text_frame.text = slide_title

        if bullets and not use_table:
            body = None
            try:
                body = slide.placeholders[1]
            except (KeyError, IndexError):
                body = None
            if body is not None:
                _fill_pptx_bullets(body.text_frame, bullets, font)
            else:
                box = slide.shapes.add_textbox(
                    Inches(0.6), Inches(1.4), Inches(content_width_in), Inches(5.6)
                )
                _fill_pptx_bullets(box.text_frame, bullets, font, manual_bullets=True)
        elif bullets and use_table:
            box = slide.shapes.add_textbox(
                Inches(0.6), Inches(1.25), Inches(content_width_in), Inches(1.9)
            )
            _fill_pptx_bullets(box.text_frame, bullets, font, manual_bullets=True)

        if table_spec is not None:
            all_rows = ([table_spec["headers"]] if table_spec["headers"] else []) + table_spec["rows"]
            row_total = len(all_rows)
            columns = max(len(row) for row in all_rows)
            top_in = 3.35 if bullets else 1.45
            available = 7.2 - top_in
            height_in = min(available, 0.42 * row_total + 0.2)
            if table_spec["widths"]:
                width_sum = sum(table_spec["widths"][:columns])
                if width_sum > content_width_in + 0.01:
                    warnings.append(
                        f"{slide_path}.table.widths 合计 {width_sum:g} 英寸，"
                        f"超过当前页面可用宽度 {content_width_in:g} 英寸，表格可能溢出"
                    )
            shape = slide.shapes.add_table(
                row_total,
                columns,
                Inches(0.6),
                Inches(top_in),
                Inches(content_width_in),
                Inches(max(0.6, height_in)),
            )
            table = shape.table
            for row_index, row in enumerate(all_rows):
                for col_index in range(columns):
                    value = row[col_index] if col_index < len(row) else ""
                    cell = table.cell(row_index, col_index)
                    cell.text = value
                    if font:
                        for paragraph in cell.text_frame.paragraphs:
                            for run in paragraph.runs:
                                _pptx_set_font(run, font)
                    if row_index == 0 and table_spec["headers"] and table_spec["headerBold"]:
                        for paragraph in cell.text_frame.paragraphs:
                            for run in paragraph.runs:
                                run.font.bold = True
            if table_spec["widths"]:
                for col_index, width in enumerate(table_spec["widths"][:columns]):
                    table.columns[col_index].width = Inches(width)

        if font and slide_title is not None:
            try:
                for paragraph in slide.shapes.title.text_frame.paragraphs:
                    for run in paragraph.runs:
                        _pptx_set_font(run, font)
            except Exception:
                pass

        if notes and notes.strip():
            try:
                slide.notes_slide.notes_text_frame.text = notes
            except Exception:
                warnings.append(f"{slide_path}.notes 无法写入备注，已忽略")

        slide_summaries.append(
            {
                "index": len(slide_summaries) + 1,
                "title": slide_title or "",
                "bulletCount": len(bullets),
                "tableCount": 1 if table_spec else 0,
                "hasNotes": bool(notes and notes.strip()),
            }
        )

    try:
        presentation.save(str(output))
    except OSError as exc:
        raise oc.runtime_error(f"无法写入 pptx {output}：{exc}") from exc

    return {
        "slideCount": len(slide_summaries),
        "slides": slide_summaries,
        "cover": bool(cover_title),
    }


# ===========================================================================
# 统一入口
# ===========================================================================


def build(kind: str, plan: dict[str, Any], output: Path, warnings: list[str]) -> dict[str, Any]:
    if kind == "docx":
        return build_docx(plan, output, warnings)
    if kind == "xlsx":
        return build_xlsx(plan, output, warnings)
    if kind == "pptx":
        return build_pptx(plan, output, warnings)
    raise oc.usage_error(f"不支持的 --type：{kind}（可选 docx / xlsx / pptx）")
