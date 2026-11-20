"""office-kit ocr 模块 CLI：图片 / PDF / 批量目录的文字识别。

用法（由 bin/ocr 的 bash 包装 exec 到本文件）：
  ocr image --input F [--lang chi_sim+eng] [--engine auto|rapid|tess] [--json]
  ocr pdf   --input F [--pages 1-3] [--dpi 200] [--json]
  ocr batch --input DIR [--recursive] [--json]
  ocr list-langs [--json]

输出契约见 modules/ocr/README.md；错误写 stderr，退出码 0/1/2/3。
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time

VERSION = "1.0.0"

import importlib  # noqa: E402

import ocr_engine  # noqa: E402
from ocr_util import (  # noqa: E402
    DEFAULT_DPI,
    EXIT_OK,
    EXIT_RUNTIME,
    EXIT_USAGE,
    IMAGE_EXTS,
    MAX_SIDE_DEFAULT,
    PDF_EXTS,
    SUPPORTED_EXTS,
    DependencyError,
    OcrError,
    UsageError,
    log,
    print_json,
    write_json,
    write_text,
)

SUPPORTED_HINT = "支持 .png/.jpg/.jpeg/.bmp/.webp/.tif/.tiff/.pdf"

_IO_MODULE = None


def io():
    """按需导入图像/PDF I/O 层：缺 Pillow/PyMuPDF 时给出可执行修复提示（退出码 3）。"""
    global _IO_MODULE
    if _IO_MODULE is None:
        missing = []
        if importlib.util.find_spec("PIL") is None:
            missing.append("pillow")
        if (
            importlib.util.find_spec("pymupdf") is None
            and importlib.util.find_spec("fitz") is None
        ):
            missing.append("pymupdf")
        if missing:
            raise DependencyError(
                "缺少依赖：" + "、".join(missing),
                hint='"$OFFICE_KIT_PY" -m pip install --no-cache-dir ' + " ".join(missing),
            )
        _IO_MODULE = importlib.import_module("ocr_io")
    return _IO_MODULE


EPILOG = """\
示例:
  ocr image --input 截图.png --json
  ocr image --input 发票.jpg --region 100,80,1200,600 --output-text 发票.txt
  ocr pdf --input 扫描件.pdf --pages 1-3 --json --output-json 结果.json
  ocr batch --input ./图片目录 --recursive --json
  ocr list-langs --json

说明:
  * 默认引擎 RapidOCR（ONNX，中英混排，模型随包离线可用），tesseract 为可选后备；
  * box 为原图像素（PDF 为渲染像素）的 [x1,y1,x2,y2]，便于还原版面；
  * 所有识别均在本机完成，运行期不联网。
"""


# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------


def _add_engine_args(parser):
    parser.add_argument(
        "--lang",
        default=ocr_engine.DEFAULT_LANG,
        metavar="LANG",
        help=f"语言，tesseract 风格（默认 {ocr_engine.DEFAULT_LANG}，如 chi_sim+eng、eng）",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "rapid", "tess"),
        default="auto",
        help="引擎：auto=优先 rapid 再退 tesseract（默认）；rapid=RapidOCR；tess=系统 tesseract",
    )
    parser.add_argument("--json", action="store_true", help="stdout 输出单个 JSON 对象")
    parser.add_argument(
        "--output-json", metavar="F", help="把 JSON 结果同时写入文件 F（父目录自动创建）"
    )
    parser.add_argument(
        "--output-text", metavar="F", help="把纯文本结果同时写入文件 F（UTF-8）"
    )
    parser.add_argument(
        "--rotate",
        default="0",
        choices=("auto", "0", "90", "180", "270"),
        help="方向矫正：auto 用 tesseract OSD（无则用 RapidOCR cls 判 0/180）",
    )
    parser.add_argument(
        "--region",
        metavar="x1,y1,x2,y2",
        help="只识别指定矩形区域（原图像素，先按 --rotate 摆正后裁切；PDF 对每页生效）",
    )
    parser.add_argument(
        "--max-side",
        type=int,
        default=MAX_SIDE_DEFAULT,
        metavar="N",
        help=f"超大图长边缩放到 N 像素再识别，0=不缩放（默认 {MAX_SIDE_DEFAULT}）",
    )
    parser.add_argument("--quiet", action="store_true", help="不输出人类可读结果")


def _add_pdf_args(parser):
    parser.add_argument("--pages", metavar="SPEC", help='页码，如 "1-3,5"、"3-"；默认全部')
    parser.add_argument(
        "--dpi",
        type=int,
        default=DEFAULT_DPI,
        help=f"PDF 渲染 DPI（默认 {DEFAULT_DPI}；扫描件可试 300）",
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ocr",
        description="离线 OCR：图片 / PDF 扫描件 / 批量目录的文字识别（RapidOCR + 可选 tesseract）",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version", action="version", version=f"ocr (office-kit) {VERSION}"
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p_image = sub.add_parser(
        "image",
        help="识别单张图片",
        description="识别单张图片，输出带坐标的文字行。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p_image.add_argument("--input", required=True, metavar="F", help="图片路径（支持中文/空格）")
    _add_engine_args(p_image)

    p_pdf = sub.add_parser(
        "pdf",
        help="识别 PDF（逐页渲染）",
        description="用内置 PyMuPDF 逐页渲染（默认 200dpi）后识别，不依赖系统 poppler。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p_pdf.add_argument("--input", required=True, metavar="F", help="PDF 路径")
    _add_pdf_args(p_pdf)
    _add_engine_args(p_pdf)

    p_batch = sub.add_parser(
        "batch",
        help="批量识别目录中的图片/PDF",
        description="批量识别目录中的图片/PDF；单个文件失败不中断，失败项写 failures。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p_batch.add_argument("--input", required=True, metavar="DIR", help="目录路径")
    p_batch.add_argument("--recursive", action="store_true", help="递归子目录")
    p_batch.add_argument(
        "--output-dir",
        metavar="D",
        help="为每个文件另存 <名字>.json / <名字>.txt 到目录 D",
    )
    _add_pdf_args(p_batch)
    _add_engine_args(p_batch)

    p_langs = sub.add_parser(
        "list-langs",
        help="列出可用引擎与语言",
        description="列出可用 OCR 引擎、版本、语言与模型来源。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    p_langs.add_argument("--json", action="store_true", help="输出 JSON")

    return parser


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------


def _validate_input(path, expected):
    """命令行先校验输入，避免白载引擎；不存在/类型不符按用法错误退出。"""
    if not path:
        raise UsageError("缺少 --input")
    if not os.path.exists(path):
        raise UsageError(f"输入不存在：{path}")
    if os.path.isdir(path):
        raise UsageError(f"--input 需要文件而不是目录：{path}（批量请用 ocr batch）")
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise UsageError(f"不支持的文件类型：{path}（{ext or '无扩展名'}）；{SUPPORTED_HINT}")
    kind = "pdf" if ext in PDF_EXTS else "image"
    if kind != expected:
        if expected == "image":
            raise UsageError("PDF 请用 ocr pdf 子命令（或 ocr batch 自动分派）")
        raise UsageError("图片请用 ocr image 子命令（或 ocr batch 自动分派）")
    return kind


def _file_kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in PDF_EXTS:
        return "pdf"
    raise UsageError(
        f"不支持的文件类型：{path}（{ext or '无扩展名'}）；{SUPPORTED_HINT}"
    )


def _number(value):
    """坐标输出：整数就不带小数点，否则保留 1 位。"""
    rounded = round(float(value), 1)
    as_int = int(rounded)
    return as_int if abs(rounded - as_int) < 1e-9 else rounded


def _finish_lines(raw_lines, transform, page_no, width, height):
    lines = []
    for item in raw_lines:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        box = transform.box(item["box"])
        x1 = min(max(box[0], 0.0), float(width))
        y1 = min(max(box[1], 0.0), float(height))
        x2 = min(max(box[2], 0.0), float(width))
        y2 = min(max(box[3], 0.0), float(height))
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        lines.append(
            {
                "text": text,
                "box": [_number(x1), _number(y1), _number(x2), _number(y2)],
                "score": round(float(item.get("score") or 0.0), 4),
                "page": page_no,
            }
        )
    return lines


def _page_text(lines):
    return "\n".join(line["text"] for line in lines)


def _rotation_engine(engine, mode):
    """--rotate auto 时，只有 rapid 引擎能提供 180° 兜底判断。"""
    if engine is None:
        return None
    if getattr(engine, "name", "") == "rapid" and str(mode).lower() == "auto":
        return engine
    return None


def _recognize_image(image, engine, args, page_no=1):
    """对一张图执行 方向矫正 -> 裁切/缩放 -> 识别 -> 坐标反算。"""
    image, rotation = io().rotate_image(
        image, args.rotate, rapid_engine=_rotation_engine(engine, args.rotate)
    )
    width, height = image.size
    work, transform, notes = io().prepare_image(image, args.max_side, args.region)
    for note in notes:
        log(note)
    start = time.time()
    raw_lines = engine.run(work)
    elapsed = time.time() - start
    lines = _finish_lines(raw_lines, transform, page_no, width, height)
    page = {
        "page": page_no,
        "width": width,
        "height": height,
        "text": _page_text(lines),
        "lines": lines,
    }
    if rotation:
        page["rotation"] = rotation
    return page, elapsed


def _stats(pages):
    return {
        "pages": len(pages),
        "lines": sum(len(page["lines"]) for page in pages),
        "chars": sum(len(page["text"]) for page in pages),
    }


def _process_image(path, args, engine, langs_text):
    image = io().load_image(path)
    page, elapsed = _recognize_image(image, engine, args)
    result = {
        "engine": engine.name,
        "input": path,
        "lang": langs_text,
        "pages": [page],
        "text": page["text"],
        "stats": _stats([page]),
        "elapsed": round(elapsed, 3),
    }
    if page.get("rotation"):
        result["rotation"] = page["rotation"]
    return result


def _process_pdf(path, args, engine, langs_text):
    doc = io().open_pdf(path)
    try:
        total = doc.page_count
        numbers = io().parse_pages(args.pages, total)
        log(f"PDF 共 {total} 页，本次识别第 {'、'.join(str(n) for n in numbers)} 页")
        rendered = io().render_pdf_pages(doc, numbers, dpi=args.dpi)
        pages = []
        elapsed = 0.0
        for index, (number, image, dpi, pixels_per_point) in enumerate(rendered, 1):
            log(f"第 {number}/{total} 页渲染完成 {image.width}x{image.height}px，开始识别")
            page, cost = _recognize_image(image, engine, args, page_no=number)
            page["dpi"] = dpi
            page["pixels_per_point"] = round(pixels_per_point, 4)
            pages.append(page)
            elapsed += cost
            del image
            if index < len(numbers):
                log(f"进度 {index}/{len(numbers)}")
    finally:
        doc.close()

    text = "\n\n".join(page["text"] for page in pages)
    result = {
        "engine": engine.name,
        "input": path,
        "lang": langs_text,
        "pages": pages,
        "text": text,
        "page_count": total,
        "dpi": args.dpi,
        "pixels_per_point": round(args.dpi / 72.0, 4),
        "stats": _stats(pages),
        "elapsed": round(elapsed, 3),
    }
    return result


def _collect_files(root, recursive):
    files = []
    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                    files.append(os.path.join(dirpath, name))
    else:
        for name in sorted(os.listdir(root)):
            path = os.path.join(root, name)
            if not os.path.isfile(path) or name.startswith("."):
                continue
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTS:
                files.append(path)
    return files


def _safe_stem(path, root):
    rel = os.path.relpath(path, root)
    stem = os.path.splitext(rel)[0]
    return "".join(ch if ch.isalnum() or ch in "-_. " else "_" for ch in stem)


def _process_batch(args, engine, langs_text):
    root = os.path.abspath(args.input)
    if not os.path.isdir(root):
        raise UsageError(f"--input 需要目录：{root}")
    files = _collect_files(root, args.recursive)
    if not files:
        raise UsageError(f"目录下没有可识别文件（{SUPPORTED_HINT}）：{root}")
    if args.output_dir:
        os.makedirs(args.output_dir, exist_ok=True)

    items = []
    failures = []
    started = time.time()
    for index, path in enumerate(files, 1):
        name = os.path.relpath(path, root)
        log(f"[{index}/{len(files)}] {name}")
        try:
            kind = _file_kind(path)
            if kind == "pdf":
                result = _process_pdf(path, args, engine, langs_text)
            else:
                result = _process_image(path, args, engine, langs_text)
            items.append(result)
            if args.output_dir:
                stem = _safe_stem(path, root)
                write_json(os.path.join(args.output_dir, stem + ".json"), result)
                write_text(os.path.join(args.output_dir, stem + ".txt"), result["text"] + "\n")
        except OcrError as exc:
            failures.append({"input": path, "error": exc.message, "code": exc.code})
            log(f"失败：{name}：{exc.message}")
            if exc.hint:
                log(f"提示：{exc.hint}")
        except Exception as exc:  # noqa: BLE001 - 单文件失败不中断批处理
            failures.append({"input": path, "error": str(exc), "code": EXIT_RUNTIME})
            log(f"失败：{name}：{exc}")

    result = {
        "engine": engine.name,
        "input": root,
        "items": items,
        "failures": failures,
        "stats": {
            "files": len(files),
            "ok": len(items),
            "failed": len(failures),
            "pages": sum(len(item["pages"]) for item in items),
            "chars": sum(len(item["text"]) for item in items),
        },
        "elapsed": round(time.time() - started, 3),
    }
    return result


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------


def _rule(width=64):
    return "─" * width


def _print_human(result, args):
    if "items" in result:
        stats = result["stats"]
        print(f"引擎: {result['engine']}    目录: {result['input']}")
        print(
            f"文件 {stats['files']} 个：成功 {stats['ok']}，失败 {stats['failed']}"
            f"，共 {stats['pages']} 页 / {stats['chars']} 字"
        )
        for item in result["items"]:
            print()
            print(_rule())
            name = os.path.basename(item["input"])
            page = item["pages"][0] if item["pages"] else {"width": 0, "height": 0, "lines": []}
            print(
                f"{name}   {page['width']}x{page['height']}px"
                f"   页数 {len(item['pages'])}   行数 {item['stats']['lines']}"
            )
            print(_rule())
            print(item["text"] or "(未识别到文字)")
        if result["failures"]:
            print()
            print("失败列表:")
            for failure in result["failures"]:
                print(f"  {os.path.basename(failure['input'])}: {failure['error']}")
        return

    engine_label = ocr_engine.RapidEngine.label if result["engine"] == "rapid" else "tesseract"
    print(
        f"引擎: {result['engine']}（{engine_label}）    "
        f"文件: {result['input']}    语言: {result.get('lang', '')}"
    )
    if "page_count" in result:
        print(
            f"共 {result['page_count']} 页，识别 {len(result['pages'])} 页，"
            f"渲染 {result.get('dpi')}dpi（{result.get('pixels_per_point')} px/pt）"
        )
    else:
        page = result["pages"][0]
        print(f"尺寸: {page['width']}x{page['height']}px")
    print(f"行数: {result['stats']['lines']}    字数: {result['stats']['chars']}")
    for page in result["pages"]:
        print()
        print(_rule())
        suffix = ""
        if page.get("rotation"):
            suffix = f"   已旋转 {page['rotation']['angle']}°"
        print(f"第 {page['page']} 页   {page['width']}x{page['height']}px{suffix}")
        print(_rule())
        print(page["text"] or "(未识别到文字)")


def _emit(result, args):
    if getattr(args, "output_json", None):
        write_json(args.output_json, result)
        log(f"JSON 已写入 {args.output_json}")
    if getattr(args, "output_text", None):
        real = result
        if "items" in real:
            chunks = []
            for item in real["items"]:
                chunks.append(f"===== {os.path.basename(item['input'])} =====\n{item['text']}")
            text = "\n\n".join(chunks)
        else:
            text = real["text"]
        write_text(args.output_text, text + "\n")
        log(f"文本已写入 {args.output_text}")
    if getattr(args, "json", False):
        print_json(result)
    elif not getattr(args, "quiet", False):
        _print_human(result, args)


def _print_langs(result):
    default = result["default"]
    print("OCR 引擎：")
    for key, engine in result["engines"].items():
        name = "rapid" if key == "rapid" else "tess"
        label = "RapidOCR" if key == "rapid" else "tesseract"
        if engine["available"]:
            version = engine.get("version") or "未知版本"
            langs = "、".join(engine.get("languages") or []) or "无"
            if key == "rapid":
                extra = f"模型: {engine.get('model_dir') or 'wheel'}（离线）"
            else:
                extra = f"tessdata: {engine.get('tessdata_dir') or '默认'}"
            print(f"  {name:<6} 可用   {label} {version}   {extra}")
            print(f"        语言: {langs}")
        else:
            print(f"  {name:<6} 不可用  {engine.get('error') or ''}")
    print()
    print(f"默认: --engine {default['engine']} --lang {default['lang']}")
    print("可选语言（engines 列表示支持该语言的引擎）：")
    for item in result["languages"]:
        print(f"  {item['code']:<8} {item['name']:<8} {'/'.join(item['engines'])}")


def _list_langs(args):
    engines = ocr_engine.detect_engines()
    names = (
        ("chi_sim", "简体中文"),
        ("chi_tra", "繁体中文"),
        ("eng", "英文"),
        ("japan", "日文"),
        ("korean", "韩文"),
        ("rus", "俄文"),
        ("fra", "法文"),
        ("deu", "德文"),
        ("spa", "西班牙文"),
    )
    languages = []
    for code, name in names:
        supported = []
        if code in engines["rapid"]["languages"]:
            supported.append("rapid")
        if code in engines["tess"]["languages"]:
            supported.append("tess")
        if supported:
            languages.append({"code": code, "name": name, "engines": supported})
    known = {code for code, _ in names} | {"osd"}
    for code in engines["tess"]["languages"]:
        if code not in known:
            languages.append({"code": code, "name": code, "engines": ["tess"]})

    result = {
        "default": {"engine": ocr_engine.DEFAULT_ENGINE, "lang": ocr_engine.DEFAULT_LANG},
        "engines": engines,
        "languages": languages,
    }
    if args.json:
        print_json(result)
    else:
        _print_langs(result)
    return EXIT_OK


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _prepare(args):
    langs = ocr_engine.normalize_langs(args.lang)
    langs_text = "+".join(langs)
    if args.max_side < 0:
        raise UsageError(f"--max-side 不能为负数：{args.max_side}")
    if getattr(args, "dpi", None) is not None and not (36 <= args.dpi <= 1200):
        raise UsageError(f"--dpi 应在 36~1200 之间，收到 {args.dpi}")
    engine = ocr_engine.make_engine(args.engine, langs)
    return engine, langs_text


def run(args):
    if args.command == "list-langs":
        return _list_langs(args)

    if args.command in ("image", "pdf"):
        _validate_input(args.input, args.command)
    elif args.command == "batch":
        if not os.path.isdir(args.input):
            raise UsageError(f"--input 需要目录：{os.path.abspath(args.input)}")

    engine, langs_text = _prepare(args)
    log(f"引擎 {engine.name}（{engine.label}），语言 {langs_text}")

    if args.command == "image":
        result = _process_image(args.input, args, engine, langs_text)
        _emit(result, args)
        return EXIT_OK

    if args.command == "pdf":
        result = _process_pdf(args.input, args, engine, langs_text)
        _emit(result, args)
        return EXIT_OK

    if args.command == "batch":
        result = _process_batch(args, engine, langs_text)
        _emit(result, args)
        if not result["items"] and result["failures"]:
            return EXIT_RUNTIME
        return EXIT_OK

    raise UsageError(f"未知子命令：{args.command}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    try:
        return run(args)
    except OcrError as exc:
        log(f"错误：{exc.message}")
        if exc.hint:
            log(f"修复：{exc.hint}")
        return exc.code
    except KeyboardInterrupt:
        log("已中断")
        return 130
    except BrokenPipeError:
        return EXIT_OK
    except Exception as exc:  # noqa: BLE001 - 兜底，避免裸 traceback 干扰调用方
        if os.environ.get("OCR_DEBUG"):
            raise
        log(f"内部错误：{exc}")
        return EXIT_RUNTIME


if __name__ == "__main__":
    sys.exit(main())
