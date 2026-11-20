#!/usr/bin/env python3
"""结构摘要：docx / xlsx / pptx / pdf。"""

from __future__ import annotations

import importlib
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import office_common as oc


def _import(module_name: str, pip_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except Exception as exc:  # 可能是 ImportError，也可能是依赖链损坏
        raise oc.dependency_error(
            f"缺少 Python 依赖 {pip_name}：{exc}",
            hint=(
                f"运行时异常，请由维护者补齐：{oc.PYTHON} -m pip install {pip_name}；"
                "离线目标机应随 office-kit 一起分发该依赖。"
            ),
        ) from exc


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\uac00-\ud7af]")
_LATIN_WORD_RE = re.compile(r"[A-Za-z0-9_]+(?:['’\-][A-Za-z0-9_]+)*")


def count_words(text: str) -> int:
    """中文按字计、拉丁按词计（与常见办公软件的口径接近）。"""
    return len(_CJK_RE.findall(text)) + len(_LATIN_WORD_RE.findall(text))


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _props(obj: Any, names: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in names:
        try:
            value = getattr(obj, name)
        except Exception:
            continue
        value = _json_value(value)
        if value not in (None, ""):
            result[name] = value
    return result


# ---------------------------------------------------------------------------
# docx
# ---------------------------------------------------------------------------


def _docx_used_fonts(document: Any) -> list[str]:
    """收集 docx 实际引用到的字体（正文/表格/页眉页脚/所用样式）。"""
    names: dict[str, None] = {}

    def add(name: Any) -> None:
        if isinstance(name, str) and name.strip():
            names.setdefault(name.strip(), None)

    def add_style(style: Any) -> None:
        depth = 0
        while style is not None and depth < 10:
            try:
                add(style.font.name)
            except Exception:
                pass
            try:
                style = style.base_style
            except Exception:
                style = None
            depth += 1

    def add_paragraphs(paragraphs: Any) -> None:
        for paragraph in paragraphs:
            try:
                add_style(paragraph.style)
            except Exception:
                pass
            for run in paragraph.runs:
                add(run.font.name)
                try:
                    add_style(run.style)
                except Exception:
                    pass

    def add_tables(tables: Any) -> None:
        for table in tables:
            for row in table.rows:
                for cell in row.cells:
                    add_paragraphs(cell.paragraphs)
                    add_tables(cell.tables)

    add_paragraphs(document.paragraphs)
    add_tables(document.tables)
    try:
        add_style(document.styles["Normal"])
    except Exception:
        pass
    for section in document.sections:
        for part in (
            section.header,
            section.footer,
            section.first_page_header,
            section.first_page_footer,
            section.even_page_header,
            section.even_page_footer,
        ):
            try:
                add_paragraphs(part.paragraphs)
                add_tables(part.tables)
            except Exception:
                continue
    return sorted(names)


def docx_summary(path: Path) -> dict[str, Any]:
    docx = _import("docx", "python-docx")
    try:
        document = docx.Document(str(path))
    except Exception as exc:
        raise oc.runtime_error(f"无法读取 docx：{exc}") from exc

    paragraphs = list(document.paragraphs)
    non_empty = [p for p in paragraphs if (p.text or "").strip()]
    all_text = "\n".join(p.text for p in non_empty)
    preview = []
    for index, para in enumerate(non_empty[:10]):
        style_name = ""
        try:
            style_name = para.style.name if para.style is not None else ""
        except Exception:
            style_name = ""
        preview.append(
            {
                "index": index,
                "style": style_name,
                "text": oc.truncate(para.text, 300),
            }
        )
    headings = []
    for para in non_empty:
        try:
            style_name = para.style.name if para.style is not None else ""
        except Exception:
            style_name = ""
        match = re.fullmatch(r"Heading\s*(\d+)", style_name or "")
        if match and len(headings) < 30:
            headings.append(
                {"level": int(match.group(1)), "text": oc.truncate(para.text, 120)}
            )

    fonts, missing, font_check = oc.font_report_from_names(_docx_used_fonts(document))
    summary: dict[str, Any] = {
        "sizeBytes": path.stat().st_size,
        "paragraphCount": len(paragraphs),
        "nonEmptyParagraphCount": len(non_empty),
        "tableCount": len(document.tables),
        "sectionCount": len(document.sections),
        "wordCount": count_words(all_text),
        "charCount": len(re.sub(r"\s+", "", all_text)),
        "headingCount": len(headings),
        "headings": headings,
        "preview": preview,
        "properties": _props(
            document.core_properties,
            ["title", "subject", "author", "keywords", "comments", "last_modified_by"],
        ),
        "fonts": fonts,
        "missingFonts": missing,
        "fontCheck": font_check,
    }
    return summary


# ---------------------------------------------------------------------------
# xlsx
# ---------------------------------------------------------------------------


def _col_letter(index: int) -> str:
    name = ""
    value = index
    while value > 0:
        value, rem = divmod(value - 1, 26)
        name = chr(65 + rem) + name
    return name


def xlsx_summary(path: Path) -> dict[str, Any]:
    openpyxl = _import("openpyxl", "openpyxl")
    util = _import("openpyxl.utils", "openpyxl")
    try:
        workbook = openpyxl.load_workbook(
            filename=str(path), read_only=True, data_only=False
        )
    except Exception as exc:
        raise oc.runtime_error(f"无法读取 xlsx：{exc}") from exc

    sheets: list[dict[str, Any]] = []
    total_cells = 0
    total_formulas = 0
    try:
        for ws in workbook.worksheets:
            non_empty = 0
            formulas = 0
            min_row = min_col = None
            max_row = max_col = 0
            try:
                rows_iter = ws.iter_rows()
                for row in rows_iter:
                    for cell in row:
                        value = cell.value
                        if value is None:
                            continue
                        if isinstance(value, str) and not value.strip():
                            continue
                        non_empty += 1
                        if isinstance(value, str) and value.startswith("="):
                            formulas += 1
                        row_idx = cell.row or 0
                        col_idx = cell.column or 0
                        if min_row is None or row_idx < min_row:
                            min_row = row_idx
                        if min_col is None or col_idx < min_col:
                            min_col = col_idx
                        if row_idx > max_row:
                            max_row = row_idx
                        if col_idx > max_col:
                            max_col = col_idx
            except Exception as exc:
                raise oc.runtime_error(
                    f"读取工作表 {getattr(ws, 'title', '?')} 失败：{exc}"
                ) from exc
            if non_empty:
                dimensions = (
                    f"{util.get_column_letter(min_col)}{min_row}:"
                    f"{util.get_column_letter(max_col)}{max_row}"
                )
            else:
                dimensions = "A1"
            sheets.append(
                {
                    "name": ws.title,
                    "index": len(sheets) + 1,
                    "state": getattr(ws, "sheet_state", "visible"),
                    "dimensions": dimensions,
                    "rows": (max_row - min_row + 1) if non_empty else 0,
                    "columns": (max_col - min_col + 1) if non_empty else 0,
                    "nonEmptyCells": non_empty,
                    "formulaCount": formulas,
                }
            )
            total_cells += non_empty
            total_formulas += formulas
    finally:
        try:
            workbook.close()
        except Exception:
            pass

    summary: dict[str, Any] = {
        "sizeBytes": path.stat().st_size,
        "sheetCount": len(sheets),
        "sheets": sheets,
        "totalNonEmptyCells": total_cells,
        "totalFormulaCount": total_formulas,
        "properties": {},
    }
    # read_only 工作簿关闭后仍可读取 document properties；失败则忽略。
    try:
        summary["properties"] = _props(
            workbook.properties, ["title", "subject", "creator", "keywords"]
        )
    except Exception:
        pass
    return summary


# ---------------------------------------------------------------------------
# pptx
# ---------------------------------------------------------------------------


def _pptx_shape_types(pptx_module: Any) -> Any:
    try:
        from pptx.enum.shapes import MSO_SHAPE_TYPE  # type: ignore

        return MSO_SHAPE_TYPE
    except Exception:
        return None


def pptx_summary(path: Path) -> dict[str, Any]:
    pptx = _import("pptx", "python-pptx")
    try:
        presentation = pptx.Presentation(str(path))
    except Exception as exc:
        raise oc.runtime_error(f"无法读取 pptx：{exc}") from exc

    shape_type = _pptx_shape_types(pptx)
    slides: list[dict[str, Any]] = []
    for index, slide in enumerate(presentation.slides, start=1):
        title = ""
        texts: list[str] = []
        tables = 0
        pictures = 0
        charts = 0
        title_shape = None
        try:
            title_shape = slide.shapes.title
        except Exception:
            title_shape = None
        for shape in slide.shapes:
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                try:
                    title = (shape.text_frame.text or "").strip().split("\n")[0]
                except Exception:
                    title = ""
                continue
            if getattr(shape, "has_text_frame", False):
                try:
                    text = (shape.text_frame.text or "").strip()
                except Exception:
                    text = ""
                if text:
                    texts.append(text)
            if getattr(shape, "has_table", False):
                tables += 1
            if getattr(shape, "has_chart", False):
                charts += 1
            try:
                if shape_type is not None and shape.shape_type == shape_type.PICTURE:
                    pictures += 1
            except Exception:
                pass
        notes_text = ""
        try:
            if slide.has_notes_slide:
                notes_text = (slide.notes_slide.notes_text_frame.text or "").strip()
        except Exception:
            notes_text = ""
        slides.append(
            {
                "index": index,
                "title": oc.truncate(title, 120),
                "text": oc.truncate(" / ".join(texts), 300),
                "tableCount": tables,
                "pictureCount": pictures,
                "chartCount": charts,
                "hasNotes": bool(notes_text),
                "notes": oc.truncate(notes_text, 300),
            }
        )

    fonts, missing, font_check = oc.font_report(path, "pptx")
    try:
        width_in = round(presentation.slide_width / 914400, 2)
        height_in = round(presentation.slide_height / 914400, 2)
    except Exception:
        width_in = height_in = None
    summary: dict[str, Any] = {
        "sizeBytes": path.stat().st_size,
        "slideCount": len(slides),
        "slides": slides,
        "slideSize": {"widthInches": width_in, "heightInches": height_in},
        "totalTables": sum(s["tableCount"] for s in slides),
        "totalPictures": sum(s["pictureCount"] for s in slides),
        "properties": _props(
            presentation.core_properties,
            ["title", "subject", "author", "keywords", "comments"],
        ),
        "fonts": fonts,
        "missingFonts": missing,
        "fontCheck": font_check,
    }
    return summary


# ---------------------------------------------------------------------------
# pdf
# ---------------------------------------------------------------------------


def pdf_summary(path: Path) -> dict[str, Any]:
    _import("pypdf", "pypdf")
    from pypdf import PdfReader  # type: ignore

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise oc.runtime_error(f"无法读取 pdf：{exc}") from exc

    encrypted = bool(getattr(reader, "is_encrypted", False))
    page_count: int | None
    try:
        page_count = len(reader.pages)
    except Exception:
        page_count = None

    metadata: dict[str, Any] = {}
    try:
        raw_meta = reader.metadata or {}
        key_map = {
            "/Title": "title",
            "/Author": "author",
            "/Subject": "subject",
            "/Creator": "creator",
            "/Producer": "producer",
            "/CreationDate": "creationDate",
            "/ModDate": "modDate",
            "/Keywords": "keywords",
        }
        for key, value in dict(raw_meta).items():
            if value in (None, ""):
                continue
            name = key_map.get(str(key), str(key).lstrip("/"))
            metadata[name] = str(value)
    except Exception:
        metadata = {}

    page_size: dict[str, Any] | None = None
    if page_count:
        try:
            box = reader.pages[0].mediabox
            page_size = {
                "width": round(float(box.width), 2),
                "height": round(float(box.height), 2),
                "unit": "pt",
            }
        except Exception:
            page_size = None

    fonts: list[str] = []
    if page_count:
        try:
            seen: set[str] = set()
            for page in reader.pages[: min(10, page_count)]:
                resources = page.get("/Resources")
                if resources is None:
                    continue
                resources = resources.get_object()
                font_dict = resources.get("/Font")
                if font_dict is None:
                    continue
                font_dict = font_dict.get_object()
                for font in font_dict.values():
                    try:
                        base = font.get_object().get("/BaseFont")
                    except Exception:
                        continue
                    if base:
                        name = str(base)
                        if name not in seen:
                            seen.add(name)
                            fonts.append(name)
            fonts.sort()
        except Exception:
            fonts = []

    version = None
    try:
        header = getattr(reader, "pdf_header", "") or ""
        match = re.search(r"%PDF-(\d+(?:\.\d+)?)", header)
        if match:
            version = match.group(1)
    except Exception:
        pass

    return {
        "sizeBytes": path.stat().st_size,
        "pageCount": page_count,
        "encrypted": encrypted,
        "pageSize": page_size,
        "metadata": metadata,
        "pdfVersion": version,
        "fonts": fonts,
    }


# ---------------------------------------------------------------------------
# 人类可读输出
# ---------------------------------------------------------------------------


def format_human(ext: str, path: Path, summary: dict[str, Any]) -> str:
    lines = [f"格式: {ext}", f"路径: {path}"]
    size = summary.get("sizeBytes")
    if size is not None:
        lines.append(f"大小: {oc.human_size(size)}")
    if "viaPdf" in summary:
        lines.append("说明: 该格式无法直接解析，摘要来自临时转换的 PDF")

    if ext == "docx":
        lines.append(
            "结构: 段落 {p}（非空 {np}） · 表格 {t} · 节 {s} · 字数 {w}".format(
                p=summary.get("paragraphCount", 0),
                np=summary.get("nonEmptyParagraphCount", 0),
                t=summary.get("tableCount", 0),
                s=summary.get("sectionCount", 0),
                w=summary.get("wordCount", 0),
            )
        )
        headings = summary.get("headings") or []
        if headings:
            lines.append("标题:")
            for item in headings[:10]:
                lines.append(f"  {'  ' * (int(item['level']) - 1)}{item['text']}")
        preview = summary.get("preview") or []
        if preview:
            lines.append("前几段:")
            for item in preview[:8]:
                style = f"[{item['style']}] " if item.get("style") else ""
                lines.append(f"  {item['index'] + 1}. {style}{item['text']}")
    elif ext == "xlsx":
        lines.append(
            f"结构: {summary.get('sheetCount', 0)} 个工作表 · "
            f"非空单元格 {summary.get('totalNonEmptyCells', 0)} · "
            f"公式 {summary.get('totalFormulaCount', 0)}"
        )
        for sheet in summary.get("sheets") or []:
            lines.append(
                "  - {name}  [{dim}] 非空 {cells}，公式 {f}".format(
                    name=sheet.get("name"),
                    dim=sheet.get("dimensions"),
                    cells=sheet.get("nonEmptyCells"),
                    f=sheet.get("formulaCount"),
                )
            )
    elif ext == "pptx":
        lines.append(f"结构: {summary.get('slideCount', 0)} 张幻灯片")
        for slide in summary.get("slides") or []:
            title = slide.get("title") or "(无标题)"
            lines.append(f"  {slide.get('index')}. {title}")
            if slide.get("text"):
                lines.append(f"     文本: {slide['text']}")
            bits = []
            if slide.get("tableCount"):
                bits.append(f"表格 {slide['tableCount']}")
            if slide.get("pictureCount"):
                bits.append(f"图片 {slide['pictureCount']}")
            if slide.get("hasNotes"):
                bits.append("含备注")
            if bits:
                lines.append("     " + " · ".join(bits))
    elif ext == "pdf":
        lines.append(
            f"结构: {summary.get('pageCount')} 页"
            + ("（已加密）" if summary.get("encrypted") else "")
        )
        size_info = summary.get("pageSize")
        if size_info:
            lines.append(
                f"首页尺寸: {size_info['width']} x {size_info['height']} pt"
            )
        meta = summary.get("metadata") or {}
        if meta:
            lines.append("元数据:")
            for key, value in meta.items():
                lines.append(f"  {key}: {oc.truncate(str(value), 160)}")
        if summary.get("fonts"):
            lines.append("字体: " + "、".join(summary["fonts"][:15]))

    missing = summary.get("missingFonts") or []
    if missing:
        lines.append("缺失字体: " + "、".join(missing) + "（渲染时会回退）")
    return "\n".join(lines)
