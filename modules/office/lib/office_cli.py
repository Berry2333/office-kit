#!/usr/bin/env python3
"""office-kit office 模块 CLI。

子命令：convert / render / recalc / info / create
错误码：参数错误 2、运行时错误 1、缺依赖 3。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path
from typing import Any

import office_common as oc
import office_create
import office_info

VERSION = oc.VERSION
JSON_MODE = False

PROG = "office-kit office"

DESCRIPTION = """\
Word / Excel / PowerPoint 的转换、渲染、公式重算、结构摘要与生成。

子命令:
  convert   把 doc/docx/odt/xls/xlsx/ods/ppt/pptx/odp 转为 PDF
  render    渲染为 PNG（docx/xlsx/pptx/... 以及 pdf）
  recalc    刷新 xlsx / ods / xls 的公式缓存
  info      读取 docx/xlsx/pptx/pdf 的结构摘要
  create    按 JSON plan 生成 docx/xlsx/pptx

示例:
  office-kit office convert --input 报告.docx --output 报告.pdf --json
  office-kit office render --input 报告.docx --output-dir 预览 --pages 1-3 --dpi 144 --json
  office-kit office recalc --input 预算.xlsx --output 预算-已重算.xlsx --json
  office-kit office info --input 报告.pptx --json
  office-kit office create --type docx --output 报告.docx --plan plan.json --json
"""

CONVERT_EPILOG = """\
说明:
  --output 必须是 .pdf；若指向已存在的目录，则自动写入 <输入文件名>.pdf。
  引擎为离线 LibreOffice WASM，无需系统安装 LibreOffice。
"""

RENDER_EPILOG = """\
说明:
  --pages 支持 1,3,5 与 1-3,5 两种写法（1-based）；省略表示全部页。
  xlsx 按工作表渲染，请用 --sheet/--range，不能用 --pages。
  输出文件名为 page-001.png、page-002.png...，并生成 manifest.json。
"""

INFO_EPILOG = """\
说明:
  原生解析 docx/xlsx/pptx/pdf；doc/odt/xls/ods/ppt/odp 会先转成临时 PDF 再摘要。
"""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Any:  # noqa: D401
        raise oc.usage_error(message)


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="输出单个 JSON 对象")


def _add_engine_flags(
    parser: argparse.ArgumentParser, *, timeout: bool = True
) -> None:
    parser.add_argument(
        "--font-dir",
        action="append",
        default=[],
        metavar="DIR",
        help="追加字体目录（可重复），透传给 LibreOffice 引擎",
    )
    if timeout:
        parser.add_argument(
            "--timeout-ms",
            type=int,
            default=oc.DEFAULT_TIMEOUT_MS,
            metavar="N",
            help=f"引擎单次处理超时毫秒数（默认 {oc.DEFAULT_TIMEOUT_MS}）",
        )


def build_parser() -> Parser:
    parser = Parser(
        prog=PROG,
        description=DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=True,
    )
    parser.add_argument(
        "--version", action="version", version=f"office-kit office {VERSION}"
    )
    subparsers = parser.add_subparsers(dest="command", metavar="子命令", required=True)

    convert = subparsers.add_parser(
        "convert",
        help="Office/WPS 文件转 PDF（含 wps/et/dps）",
        description="把 Office 文件转换为 PDF。",
        epilog=CONVERT_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    convert.add_argument("--input", required=True, metavar="F", help="输入 Office/WPS 文件（doc/docx/odt/wps/et/dps/...）")
    convert.add_argument("--output", required=True, metavar="F", help="输出 PDF 文件")
    _add_json_flag(convert)
    _add_engine_flags(convert)

    render = subparsers.add_parser(
        "render",
        help="文档渲染为 PNG（含 WPS 的 wps/et/dps）",
        description="把文档逐页渲染为 PNG（PDF 使用 pdfium，Office 使用 LibreOffice）。",
        epilog=RENDER_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    render.add_argument("--input", required=True, metavar="F", help="输入文件")
    render.add_argument(
        "--output-dir", required=True, metavar="D", help="输出 PNG 的目录"
    )
    render.add_argument(
        "--pages", metavar="SPEC", help="页码，如 1,3 或 1-3,5；省略表示全部"
    )
    render.add_argument("--dpi", type=int, default=144, metavar="N", help="渲染 DPI（默认 144）")
    render.add_argument("--sheet", metavar="NAME", help="xlsx 工作表名（精确匹配）")
    render.add_argument("--range", metavar="A1:D20", help="xlsx 区域，需配合 --sheet")
    render.add_argument(
        "--max-pages", type=int, default=None, metavar="N", help="本次最多渲染页数（默认 100）"
    )
    _add_json_flag(render)
    _add_engine_flags(render)

    recalc = subparsers.add_parser(
        "recalc",
        help="刷新公式缓存（含 WPS 的 et）",
        description="用 LibreOffice 重新计算公式并保存缓存值（保留公式）。",
    )
    recalc.add_argument("--input", required=True, metavar="F", help="xls/xlsx/ods 或 WPS et 文件")
    recalc.add_argument("--output", required=True, metavar="F", help="输出 xlsx/ods 文件")
    _add_json_flag(recalc)
    _add_engine_flags(recalc)

    info = subparsers.add_parser(
        "info",
        help="结构摘要（含 WPS 的 wps/et/dps）",
        description="读取文档结构摘要（段落 / 工作表 / 幻灯片 / PDF 页数与元数据）。",
        epilog=INFO_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    info.add_argument("--input", required=True, metavar="F", help="输入文件")
    _add_json_flag(info)

    create = subparsers.add_parser(
        "create",
        help="按 plan 生成文档",
        description="按 JSON plan 生成 docx / xlsx / pptx。plan 传 - 表示从 stdin 读取。",
    )
    create.add_argument(
        "--type", required=True, choices=["docx", "xlsx", "pptx"], help="输出类型"
    )
    create.add_argument("--output", required=True, metavar="F", help="输出文件")
    create.add_argument(
        "--plan", required=True, metavar="FILE|-", help="plan JSON 路径，或 - 表示 stdin"
    )
    _add_json_flag(create)
    return parser


# ---------------------------------------------------------------------------
# 参数辅助
# ---------------------------------------------------------------------------


def _font_args(args: argparse.Namespace) -> list[str]:
    result: list[str] = []
    for raw in getattr(args, "font_dir", None) or []:
        directory = oc.resolve_user_path(raw)
        if not directory.is_dir():
            raise oc.usage_error(f"--font-dir 不是可读目录：{directory}")
        result.extend(["--font-directory", str(directory)])
    return result


def _timeout(args: argparse.Namespace) -> int:
    value = int(getattr(args, "timeout_ms", oc.DEFAULT_TIMEOUT_MS) or 0)
    if value < 1000 or value > 3_600_000:
        raise oc.usage_error("--timeout-ms 必须在 1000 ~ 3600000 之间")
    return value


def _pdf_output(raw: str, source: Path) -> Path:
    output = oc.resolve_user_path(raw)
    if raw.endswith(os.sep) or raw.endswith("/") or (output.exists() and output.is_dir()):
        output = output / f"{source.stem}.pdf"
    if not output.suffix:
        output = output.with_name(output.name + ".pdf")
    elif output.suffix.lower() != ".pdf":
        raise oc.usage_error(f"--output 必须是 .pdf 文件，实际是 {output.name!r}")
    return output


def _parse_pages(spec: str | None, max_pages: int | None) -> list[int] | None:
    if spec is None:
        return None
    text = spec.strip()
    if not text:
        raise oc.usage_error("--pages 不能为空")
    if text.lower() == "all":
        return None
    pages: list[int] = []
    for part in re.split(r"[,，]", text):
        part = part.strip()
        if not part:
            continue
        match = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            if start < 1 or end < start:
                raise oc.usage_error(f"--pages 区间不合法：{part!r}（页码从 1 开始且递增）")
            pages.extend(range(start, end + 1))
        elif part.isdigit():
            page = int(part)
            if page < 1:
                raise oc.usage_error(f"--pages 页码必须从 1 开始：{part!r}")
            pages.append(page)
        else:
            raise oc.usage_error(
                f"--pages 无法解析：{part!r}（示例：1,3 或 1-3,5）"
            )
    if not pages:
        raise oc.usage_error("--pages 未包含任何页码")
    unique: list[int] = []
    seen: set[int] = set()
    for page in pages:
        if page not in seen:
            seen.add(page)
            unique.append(page)
    limit = max_pages or 100
    if len(unique) > limit:
        raise oc.usage_error(
            f"选择了 {len(unique)} 页，超过上限 {limit}；可减少页数或用 --max-pages 提高"
        )
    return unique


def _formula_count(path: Path) -> int | None:
    try:
        import openpyxl  # type: ignore

        workbook = openpyxl.load_workbook(str(path), read_only=True, data_only=False)
        try:
            count = 0
            for worksheet in workbook.worksheets:
                for row in worksheet.iter_rows():
                    for cell in row:
                        if isinstance(cell.value, str) and cell.value.startswith("="):
                            count += 1
            return count
        finally:
            workbook.close()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


def cmd_convert(args: argparse.Namespace) -> None:
    started = time.monotonic()
    user_input = oc.resolve_input(args.input)
    prep = oc.prepare_document(user_input)
    source = prep.path
    ext = prep.ext
    if ext not in oc.OFFICE_EXTS:
        raise oc.usage_error(
            f"convert 不支持 .{ext or '?'}；支持 doc/docx/odt、xls/xlsx/ods、ppt/pptx/odp，"
            "以及 WPS 的 wps/wpt、et/ett、dps/dpt"
        )
    output = _pdf_output(args.output, user_input)
    if output == source:
        raise oc.usage_error("--output 不能与 --input 相同")
    oc.ensure_dir(output.parent)
    temp_dir = oc.make_temp_dir(output.parent, ".office-convert-")
    engine_output = temp_dir / "output.pdf"
    try:
        if prep.native:
            oc.convert_with_soffice(user_input, engine_output, timeout_ms=_timeout(args))
            result = {"backend": "native-libreoffice"}
        else:
            result = oc.run_engine(
                "convert",
                ["--input", str(source), "--output", str(engine_output), *_font_args(args)],
                timeout_ms=_timeout(args),
            )
        if not engine_output.is_file():
            raise oc.runtime_error("LibreOffice 引擎未生成 PDF 输出")
        os.replace(engine_output, output)
        oc.chmod_public(output)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    size = output.stat().st_size
    page_count = oc.pdf_page_count(output)
    missing = [str(f) for f in result.get("missingFonts") or []]
    payload = {
        "format": "pdf",
        "input": str(source),
        "output": str(output),
        "bytes": size,
        "pageCount": page_count,
        "backend": result.get("backend"),
        "sourceFormat": prep.source_ext,
        "missingFonts": missing,
        "elapsedMs": int((time.monotonic() - started) * 1000),
    }
    if JSON_MODE:
        oc.emit_json(payload)
    else:
        pages = f"，{page_count} 页" if page_count is not None else ""
        print(f"已转换: {output}（{oc.human_size(size)}{pages}）")
        if result.get("backend"):
            print(f"引擎: {result['backend']}")
    oc.warn_missing_fonts(missing)


def cmd_render(args: argparse.Namespace) -> None:
    started = time.monotonic()
    user_input = oc.resolve_input(args.input)
    prep = oc.prepare_document(user_input)
    source = prep.path
    ext = prep.ext
    if ext not in oc.IMAGE_EXTS:
        raise oc.usage_error(
            f"render 不支持 .{ext or '?'}；支持 Office 格式（含 WPS 的 wps/et/dps）与 pdf"
        )
    output_dir = oc.resolve_user_path(args.output_dir)
    if output_dir.exists() and not output_dir.is_dir():
        raise oc.runtime_error(f"--output-dir 已被文件占用：{output_dir}")
    if not 24 <= args.dpi <= 600:
        raise oc.usage_error("--dpi 必须在 24 ~ 600 之间")

    max_pages = args.max_pages
    if max_pages is not None and not 1 <= max_pages <= 10000:
        raise oc.usage_error("--max-pages 必须在 1 ~ 10000 之间")
    pages = _parse_pages(args.pages, max_pages)

    is_calc = ext in oc.CALC_EXTS
    if is_calc and pages is not None:
        raise oc.usage_error(
            "xlsx/xls/ods 按工作表渲染：请使用 --sheet（可配合 --range），不要传 --pages"
        )
    if not is_calc and (args.sheet or args.range):
        raise oc.usage_error("--sheet / --range 仅用于 xlsx/xls/ods 输入")
    if args.range and not args.sheet:
        raise oc.usage_error("--range 必须配合 --sheet 使用")

    oc.ensure_dir(output_dir.parent)
    temp_dir = oc.make_temp_dir(output_dir.parent, ".office-render-")
    raw_dir = temp_dir / "raw"
    engine_args = [
        "--input",
        str(source),
        "--output-dir",
        str(raw_dir),
        "--dpi",
        str(args.dpi),
        *_font_args(args),
    ]
    if pages:
        engine_args.extend(["--pages", ",".join(str(p) for p in pages)])
    if args.sheet:
        engine_args.extend(["--sheet", args.sheet])
    if args.range:
        engine_args.extend(["--range", args.range])
    if max_pages is not None:
        engine_args.extend(["--max-pages", str(max_pages)])

    try:
        result = oc.run_engine("render", engine_args, timeout_ms=_timeout(args))
        images = result.get("images") or []
        if not isinstance(images, list) or not images:
            raise oc.runtime_error("LibreOffice 引擎未返回任何页面图像")
        oc.ensure_dir(output_dir)
        try:
            os.chmod(output_dir, 0o755)
        except OSError:
            pass
        normalized_pages: list[dict[str, Any]] = []
        keep: set[str] = set()
        for image in images:
            index = int(image.get("index") or len(normalized_pages) + 1)
            filename = f"page-{index:03d}.png"
            destination = output_dir / filename
            source_png = Path(str(image.get("path", "")))
            if not source_png.is_file():
                raise oc.runtime_error(f"引擎输出 PNG 不存在：{source_png}")
            os.replace(source_png, destination)
            oc.chmod_public(destination)
            keep.add(filename)
            entry: dict[str, Any] = {
                "index": index,
                "file": filename,
                "path": str(destination),
                "width": int(image.get("width") or 0),
                "height": int(image.get("height") or 0),
                "byteLength": int(
                    image.get("byteLength") or destination.stat().st_size
                ),
            }
            if "page" in image:
                entry["page"] = image["page"]
            if "sheet" in image:
                entry["sheet"] = image["sheet"]
                entry["range"] = image.get("range")
                entry["rtl"] = image.get("rtl")
            normalized_pages.append(entry)
        # 清理上一次遗留的多余页，避免旧页污染结果。
        for stale in output_dir.glob("page-*.png"):
            if re.fullmatch(r"page-\d+\.png", stale.name) and stale.name not in keep:
                try:
                    stale.unlink()
                except OSError:
                    pass
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    missing = [str(f) for f in result.get("missingFonts") or []]
    payload = {
        "format": "png",
        "input": str(source),
        "outputDir": str(output_dir),
        "dpi": args.dpi,
        "pageCount": result.get("pageCount"),
        "pages": normalized_pages,
        "missingFonts": missing,
        "backend": result.get("backend"),
        "rasterEngine": result.get("rasterEngine"),
        "elapsedMs": int((time.monotonic() - started) * 1000),
    }
    oc.write_json_file(output_dir / "manifest.json", payload)
    if JSON_MODE:
        oc.emit_json(payload)
    else:
        print(f"已渲染 {len(normalized_pages)} 页到: {output_dir}")
        for entry in normalized_pages:
            page_info = f"第 {entry['page']} 页" if "page" in entry else (
                f"工作表 {entry['sheet']}" if "sheet" in entry else ""
            )
            print(
                f"  {entry['file']}  {entry['width']}x{entry['height']}  "
                f"{oc.human_size(entry['byteLength'])}  {page_info}".rstrip()
            )
    oc.warn_missing_fonts(missing)


def cmd_recalc(args: argparse.Namespace) -> None:
    started = time.monotonic()
    user_input = oc.resolve_input(args.input)
    prep = oc.prepare_document(user_input)
    source = prep.path
    ext = prep.ext
    if ext not in oc.CALC_EXTS:
        raise oc.usage_error(
            f"recalc 只支持 xls/xlsx/ods（含 WPS et/ett），实际是 .{ext or '?'}"
        )
    output = oc.resolve_user_path(args.output)
    if args.output.endswith(os.sep) or (output.exists() and output.is_dir()):
        output = output / f"{source.stem}.xlsx"
    if not output.suffix:
        output = output.with_name(output.name + ".xlsx")
    output_ext = output.suffix.lower().lstrip(".")
    if output_ext not in {"xlsx", "ods"}:
        raise oc.usage_error("recalc 的输出必须是 .xlsx 或 .ods")
    if output == source:
        raise oc.usage_error("--output 不能与 --input 相同")
    oc.ensure_dir(output.parent)
    temp_dir = oc.make_temp_dir(output.parent, ".office-recalc-")
    engine_output = temp_dir / f"output.{output_ext}"
    try:
        result = oc.run_engine(
            "recalculate",
            ["--input", str(source), "--output", str(engine_output), *_font_args(args)],
            timeout_ms=_timeout(args),
        )
        if not engine_output.is_file():
            raise oc.runtime_error("LibreOffice 引擎未生成重算后的工作簿")
        os.replace(engine_output, output)
        oc.chmod_public(output)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    size = output.stat().st_size
    formulas = _formula_count(output)
    missing = [str(f) for f in result.get("missingFonts") or []]
    payload = {
        "format": output_ext,
        "input": str(source),
        "output": str(output),
        "bytes": size,
        "formulaCount": formulas,
        "backend": result.get("backend"),
        "missingFonts": missing,
        "elapsedMs": int((time.monotonic() - started) * 1000),
    }
    if JSON_MODE:
        oc.emit_json(payload)
    else:
        formula_text = f"，{formulas} 个公式" if formulas is not None else ""
        print(f"公式缓存已刷新: {output}（{oc.human_size(size)}{formula_text}）")
    oc.warn_missing_fonts(missing)


def cmd_info(args: argparse.Namespace) -> None:
    user_input = oc.resolve_input(args.input)
    prep = oc.prepare_document(user_input)
    source = prep.path
    ext = prep.ext
    if ext == "docx":
        summary = office_info.docx_summary(source)
        human_ext = ext
    elif ext == "xlsx":
        summary = office_info.xlsx_summary(source)
        human_ext = ext
    elif ext == "pptx":
        summary = office_info.pptx_summary(source)
        human_ext = ext
    elif ext == "pdf":
        summary = office_info.pdf_summary(source)
        human_ext = ext
    elif ext in oc.OFFICE_EXTS:
        temp_dir = oc.make_temp_dir(oc.data_tmp_dir(), ".office-info-")
        engine_output = temp_dir / "converted.pdf"
        try:
            if prep.native:
                oc.convert_with_soffice(user_input, engine_output)
                result = {"backend": "native-libreoffice"}
            else:
                result = oc.run_engine(
                    "convert",
                    ["--input", str(source), "--output", str(engine_output)],
                    timeout_ms=oc.DEFAULT_TIMEOUT_MS,
                )
            if not engine_output.is_file():
                raise oc.runtime_error("转换临时 PDF 失败，无法生成结构摘要")
            summary = office_info.pdf_summary(engine_output)
            summary["viaPdf"] = True
            summary["sourceFormat"] = ext
            summary["missingFonts"] = [
                str(f) for f in result.get("missingFonts") or []
            ]
            summary["fontCheck"] = "engine"
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
        human_ext = "pdf"
    else:
        raise oc.usage_error(
            f"info 不支持 .{ext or '?'}；支持 docx/xlsx/pptx/pdf，"
            "以及可转 PDF 的 doc/odt/xls/ods/ppt/odp 与 WPS 的 wps/et/dps"
        )

    payload = {
        "format": ext,
        "path": str(user_input),
        "sourceFormat": prep.source_ext,
        "summary": summary,
    }
    if JSON_MODE:
        oc.emit_json(payload)
    else:
        print(office_info.format_human(human_ext, source, summary))


def cmd_create(args: argparse.Namespace) -> None:
    kind = args.type
    output = oc.resolve_user_path(args.output)
    if not output.suffix:
        output = output.with_name(output.name + f".{kind}")
    elif output.suffix.lower() != f".{kind}":
        raise oc.usage_error(
            f"--type {kind} 要求 --output 以 .{kind} 结尾，实际是 {output.suffix!r}"
        )
    oc.ensure_dir(output.parent)

    if args.plan == "-":
        raw = sys.stdin.read()
        origin = "<stdin>"
    else:
        plan_path = oc.resolve_user_path(args.plan)
        if not plan_path.is_file():
            raise oc.runtime_error(f"plan 文件不存在：{plan_path}")
        try:
            raw = plan_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise oc.runtime_error(f"无法读取 plan 文件 {plan_path}：{exc}") from exc
        origin = str(plan_path)
    if not raw.strip():
        raise oc.usage_error(f"plan 为空：{origin}")
    if len(raw.encode("utf-8")) > 4 * 1024 * 1024:
        raise oc.usage_error("plan 超过 4 MB，请拆分生成")
    try:
        plan = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise oc.usage_error(
            f"plan JSON 解析失败（{origin} 第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}"
        ) from exc
    if not isinstance(plan, dict):
        raise oc.usage_error("plan 顶层必须是 JSON 对象（{...}）")

    warnings: list[str] = []
    fd, temp_name = tempfile.mkstemp(
        prefix=".office-create-", suffix=f".{kind}", dir=str(output.parent)
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        summary = office_create.build(kind, plan, temp_path, warnings)
        if not temp_path.is_file() or temp_path.stat().st_size == 0:
            raise oc.runtime_error("生成失败：输出文件为空")
        os.replace(temp_path, output)
        oc.chmod_public(output)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass

    for warning in warnings:
        print(f"提示: {warning}", file=sys.stderr)
    size = output.stat().st_size
    payload = {
        "format": kind,
        "output": str(output),
        "bytes": size,
        "summary": summary,
        "warnings": warnings,
    }
    if JSON_MODE:
        oc.emit_json(payload)
    else:
        print(f"已生成 {kind.upper()}: {output}（{oc.human_size(size)}）")
        if kind == "docx":
            print(
                "结构: 段落 {p} · 表格 {t} · 节 {s} · 字数 {w}".format(
                    p=summary.get("paragraphCount", 0),
                    t=summary.get("tableCount", 0),
                    s=summary.get("sectionCount", 0),
                    w=summary.get("wordCount", 0),
                )
            )
        elif kind == "xlsx":
            print(
                f"结构: {summary.get('sheetCount', 0)} 个工作表 · "
                f"非空单元格 {summary.get('totalNonEmptyCells', 0)} · "
                f"公式 {summary.get('totalFormulaCount', 0)}"
            )
        elif kind == "pptx":
            print(f"结构: {summary.get('slideCount', 0)} 张幻灯片")


HANDLERS = {
    "convert": cmd_convert,
    "render": cmd_render,
    "recalc": cmd_recalc,
    "info": cmd_info,
    "create": cmd_create,
}


def main(argv: list[str] | None = None) -> int:
    global JSON_MODE
    argv = list(sys.argv[1:] if argv is None else argv)
    JSON_MODE = "--json" in argv
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        handler = HANDLERS.get(args.command)
        if handler is None:
            raise oc.usage_error(f"未知子命令：{args.command}")
        handler(args)
        return 0
    except oc.OfficeError as err:
        return oc.emit_error(err, JSON_MODE)
    except KeyboardInterrupt:
        print("office: 已中断", file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 1
    except Exception:
        traceback.print_exc()
        return oc.EXIT_RUNTIME


if __name__ == "__main__":
    raise SystemExit(main())
