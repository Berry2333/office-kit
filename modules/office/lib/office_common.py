#!/usr/bin/env python3
"""office 模块共享工具：路径解析、错误模型、LibreOffice WASM 引擎调用、字体探测。

本文件只依赖 Python 标准库；第三方 Python 依赖在真正用到时才导入。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable, Sequence

VERSION = "1.0.0"

EXIT_USAGE = 2
EXIT_RUNTIME = 1
EXIT_DEPENDENCY = 3

_LIB_DIR = Path(__file__).resolve().parent
_MODULE_DIR = _LIB_DIR.parent
_KIT_DIR = _MODULE_DIR.parent.parent


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    return Path(os.path.expanduser(raw)) if raw else default


# 独立运行时（直接执行 modules/office/bin/office）也能工作的回退逻辑。
RUNTIME_DIR = _env_path("OFFICE_KIT_RUNTIME", _KIT_DIR / "runtime")
_DATA_DEFAULT = Path(
    os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
) / "office-kit"
DATA_DIR = _env_path("OFFICE_KIT_DATA", _DATA_DEFAULT)
CACHE_DIR = _env_path("OFFICE_KIT_CACHE", DATA_DIR / "cache")
LOGS_DIR = _env_path("OFFICE_KIT_LOGS", DATA_DIR / "logs")
PYTHON = _env_path("OFFICE_KIT_PY", RUNTIME_DIR / "python" / "bin" / "python3")
NODE = _env_path("OFFICE_KIT_NODE", RUNTIME_DIR / "node" / "bin" / "node")
NODE_MODULES = _env_path(
    "OFFICE_KIT_NODE_MODULES", RUNTIME_DIR / "node" / "lib" / "node_modules"
)
ENGINE_CLI = NODE_MODULES / "@deepseek-ai" / "libreoffice-kit" / "lib" / "cli.js"

# 模块自带的小型纯 Python 依赖（pypdf，BSD-3-Clause），不污染 runtime/。
VENDOR_DIR = _LIB_DIR / "vendor"
if VENDOR_DIR.is_dir() and str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

# WPS Office 自有扩展名：内容多为 Word/Excel/PPT 兼容的 OLE 复合文档
WPS_WRITER_EXTS = {"wps", "wpt"}
WPS_CALC_EXTS = {"et", "ett"}
WPS_SHOW_EXTS = {"dps", "dpt"}
WPS_EXTS = WPS_WRITER_EXTS | WPS_CALC_EXTS | WPS_SHOW_EXTS
OFFICE_EXTS = {
    "doc", "docx", "odt", "xls", "xlsx", "ods", "ppt", "pptx", "odp",
} | WPS_EXTS
CALC_EXTS = {"xls", "xlsx", "ods"} | WPS_CALC_EXTS
IMAGE_EXTS = OFFICE_EXTS | {"pdf"}
NATIVE_INFO_EXTS = {"docx", "xlsx", "pptx", "pdf"}

DEFAULT_TIMEOUT_MS = 180_000


class OfficeError(Exception):
    """带退出码语义的用户可见错误。"""

    def __init__(
        self,
        message: str,
        kind: str = "runtime",
        *,
        hint: str | None = None,
        diagnostics: Sequence[str] | None = None,
        engine_code: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.kind = kind
        self.exit_code = {
            "usage": EXIT_USAGE,
            "runtime": EXIT_RUNTIME,
            "dependency": EXIT_DEPENDENCY,
        }.get(kind, EXIT_RUNTIME)
        self.hint = hint
        self.diagnostics = list(diagnostics or [])
        self.engine_code = engine_code
        self.extra = dict(extra or {})


def usage_error(message: str, *, hint: str | None = None) -> OfficeError:
    return OfficeError(message, "usage", hint=hint)


def dependency_error(message: str, *, hint: str | None = None) -> OfficeError:
    return OfficeError(message, "dependency", hint=hint)


def runtime_error(message: str, *, hint: str | None = None) -> OfficeError:
    return OfficeError(message, "runtime", hint=hint)


def ensure_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise runtime_error(f"无法创建目录 {path}：{exc}") from exc
    return path


def data_tmp_dir() -> Path:
    return ensure_dir(DATA_DIR / "tmp")


def resolve_user_path(raw: str) -> Path:
    """把用户输入解析为绝对路径（不要求存在）。"""
    return Path(os.path.abspath(os.path.expanduser(raw)))


def resolve_input(raw: str, what: str = "输入文件") -> Path:
    path = resolve_user_path(raw)
    if not path.exists():
        raise runtime_error(f"{what}不存在：{path}")
    if not path.is_file():
        raise runtime_error(f"{what}不是普通文件：{path}")
    return path


def file_ext(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


# ---------------------------------------------------------------------------
# WPS 文档预处理：.wps/.et/.dps 本质上是 Word/Excel/PPT 兼容的 OLE 复合文档，
# LibreOffice 引擎按后缀选过滤器，所以先嗅探真实容器再以正确后缀交给引擎。
# ---------------------------------------------------------------------------

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


class PreparedDocument:
    """预处理后的输入：稳定路径 + 引擎可识别的扩展名。"""

    def __init__(self, path: Path, ext: str, source_ext: str | None = None, native: bool = False):
        self.path = path
        self.ext = ext
        self.source_ext = source_ext or ext
        self.native = native

    @property
    def normalized(self) -> bool:
        return self.path.suffix.lower().lstrip(".") != self.source_ext


def sniff_document(path: Path) -> str | None:
    """根据文件内容判断 LibreOffice 可用的真实格式后缀。"""
    try:
        with path.open("rb") as fh:
            head = fh.read(8)
            fh.seek(0)
            sample = fh.read(4096)
    except OSError:
        return None
    if head[:4] == b"PK\x03\x04":
        import zipfile

        try:
            with zipfile.ZipFile(path) as archive:
                data = archive.read("[Content_Types].xml").decode("utf-8", "replace")
        except (KeyError, OSError, ValueError, zipfile.BadZipFile):
            return None
        if "wordprocessingml" in data:
            return "docx"
        if "spreadsheetml" in data:
            return "xlsx"
        if "presentationml" in data:
            return "pptx"
        return None
    if head.startswith(OLE_MAGIC):
        try:
            blob = path.read_bytes()
        except OSError:
            return None
        if "WordDocument".encode("utf-16-le") in blob:
            return "doc"
        if "Workbook".encode("utf-16-le") in blob or "Book".encode("utf-16-le") in blob:
            return "xls"
        if "PowerPoint Document".encode("utf-16-le") in blob:
            return "ppt"
        return None
    lowered = sample.lower()
    if lowered.startswith(b"{\\rtf"):
        return "rtf"
    if b"<html" in lowered or b"<!doctype html" in lowered:
        return "html"
    return "txt"


def find_soffice() -> str | None:
    """可选的原生 LibreOffice（用户自己装了就用它兜底）。"""
    import shutil

    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    for candidate in (
        "/usr/lib/libreoffice/program/soffice",
        "/opt/libreoffice/program/soffice",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def convert_with_soffice(src: Path, dst: Path, timeout_ms: int = 120000) -> None:
    """用原生 LibreOffice 转换（仅当用户自装了 soffice 且内置引擎无法识别时有意义）。"""
    soffice = find_soffice()
    if not soffice:
        raise dependency_error(
            "需要原生 LibreOffice（soffice）才能处理该文件，但系统中未找到",
            hint="安装 libreoffice 后重试，或用 WPS Office 另存为 docx/xlsx/pptx。",
        )
    ensure_dir(dst.parent)
    proc = subprocess.run(
        [
            soffice, "--headless", "--nologo", "--nofirststartwizard",
            "--convert-to", "pdf", "--outdir", str(dst.parent), str(src),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(120.0, timeout_ms / 1000.0 + 60.0),
    )
    produced = dst.parent / f"{src.stem}.pdf"
    if proc.returncode != 0 or not produced.is_file():
        raise OfficeError(
            f"原生 LibreOffice 转换失败（退出码 {proc.returncode}）",
            "runtime",
            diagnostics=_tail_lines(proc.stderr),
        )
    if produced != dst:
        os.replace(produced, dst)


def prepare_document(path: Path) -> PreparedDocument:
    """把 WPS 系后缀转换为引擎可识别的后缀（缓存复用）。

    * Word/Excel/PPT 兼容的 .wps/.et/.dps：嗅探后复制为 .doc/.xls/.ppt；
    * 旧版 WPS 2000 等无法嗅探的格式：若有原生 LibreOffice 则标记 native 兜底；
    * 其余格式原样返回。
    """
    ext = file_ext(path)
    if ext not in WPS_EXTS:
        return PreparedDocument(path, ext)
    target = sniff_document(path)
    if target is None:
        if find_soffice():
            return PreparedDocument(path, ext, native=True)
        raise runtime_error(
            f"无法识别 .{ext} 内部格式（不是 Word/Excel/PPT 兼容的复合文档）",
            hint=(
                "该文件可能是旧版 WPS 2000 专用格式。请用 WPS Office 另存为 .docx/.xlsx，"
                "或在目标机安装原生 LibreOffice（soffice）后重试。"
            ),
        )
    ensure_dir(CACHE_DIR / "office" / "normalized")
    try:
        stat = path.stat()
        stamp = f"{stat.st_size}-{int(stat.st_mtime)}"
    except OSError:
        stamp = "0"
    digest = hashlib.sha1(f"{path.resolve()}|{stamp}".encode("utf-8")).hexdigest()[:12]
    dest = CACHE_DIR / "office" / "normalized" / f"{path.stem}-{digest}.{target}"
    if not dest.is_file() or dest.stat().st_size == 0:
        import shutil

        shutil.copyfile(path, dest)
    return PreparedDocument(dest, target, source_ext=ext)


def human_size(num: int | float) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def emit_json(payload: Any) -> None:
    """输出单个 UTF-8 JSON 对象，中文不转义。"""
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def emit_error(err: OfficeError, json_mode: bool) -> int:
    if err.diagnostics:
        print("--- LibreOffice 诊断（stderr 最后 20 行）---", file=sys.stderr)
        for line in err.diagnostics[-20:]:
            print(line, file=sys.stderr)
        print("--- 诊断结束 ---", file=sys.stderr)
    if json_mode:
        payload: dict[str, Any] = {
            "ok": False,
            "code": err.kind,
            "error": err.message,
        }
        if err.engine_code:
            payload["engineCode"] = err.engine_code
        if err.hint:
            payload["hint"] = err.hint
        if err.diagnostics:
            payload["diagnostics"] = err.diagnostics[-20:]
        payload.update(err.extra)
        sys.stderr.write(json.dumps(payload, ensure_ascii=False) + "\n")
    else:
        print(f"office: {err.message}", file=sys.stderr)
        if err.hint:
            print(f"提示: {err.hint}", file=sys.stderr)
    sys.stderr.flush()
    return err.exit_code


# ---------------------------------------------------------------------------
# LibreOffice WASM 引擎（Node CLI）调用
# ---------------------------------------------------------------------------


def check_engine() -> None:
    if not NODE.is_file():
        raise dependency_error(
            f"运行时缺少 Node：{NODE}",
            hint="确认 office-kit 运行时完整（runtime/node/bin/node），或设置 OFFICE_KIT_NODE。",
        )
    if not ENGINE_CLI.is_file():
        raise dependency_error(
            f"运行时缺少 LibreOffice WASM 引擎：{ENGINE_CLI}",
            hint=(
                "确认 runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit 完整；"
                "该引擎离线运行，无需系统安装 LibreOffice。"
            ),
        )


def _engine_env() -> dict[str, str]:
    env = dict(os.environ)
    # 引擎自带的字体元数据缓存固定写入 office-kit 数据目录，避免污染 ~/.cache。
    ensure_dir(CACHE_DIR)
    env["XDG_CACHE_HOME"] = str(CACHE_DIR)
    # 引擎临时目录同样收敛到数据目录（可用 OFFICE_KIT_DATA 整体迁移）。
    env["TMPDIR"] = str(data_tmp_dir())
    env.setdefault("LANG", "zh_CN.UTF-8")
    env["NO_COLOR"] = "1"
    return env


_ENGINE_CODE_MESSAGES = {
    "input-too-large": "输入文件超过 LibreOffice 引擎的大小限制",
    "output-too-large": "输出超过 LibreOffice 引擎的大小限制（可减少页数或降低 DPI）",
    "invalid-document": "无法解析文档（文件损坏、加密或实际格式与后缀不符）",
    "unsupported-format": "LibreOffice 引擎不支持该文件格式",
    "invalid-output": "输出文件未通过引擎校验",
    "timeout": "LibreOffice 处理超时",
    "unavailable": "LibreOffice 引擎不可用（WASM 资源缺失或字体目录不可访问）",
    "failed": "LibreOffice 处理失败",
}


def run_engine(
    command: str,
    args: Iterable[str],
    *,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> dict[str, Any]:
    """调用 libreoffice-kit CLI，返回其 stdout 上的 JSON 结果。

    引擎的 stderr 诊断只保留最后 20 行随错误抛出，由 CLI 统一打印。
    """
    check_engine()
    if timeout_ms < 1000:
        raise usage_error("--timeout-ms 必须大于等于 1000")
    cmd = [
        str(NODE),
        str(ENGINE_CLI),
        command,
        *[str(a) for a in args],
        "--timeout-ms",
        str(int(timeout_ms)),
    ]
    overall = max(120.0, timeout_ms / 1000.0 + 120.0)
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_engine_env(),
            timeout=overall,
        )
    except subprocess.TimeoutExpired as exc:
        raise OfficeError(
            f"LibreOffice 引擎进程超时（>{overall:.0f} 秒）",
            "runtime",
            hint="可用 --timeout-ms 提高超时，或拆分/精简文档后重试。",
            diagnostics=_tail_lines(exc.stderr),
        ) from exc
    except OSError as exc:
        raise dependency_error(f"无法启动 LibreOffice 引擎：{exc}") from exc

    stderr_lines = (proc.stderr or "").strip().splitlines()
    stdout_text = (proc.stdout or "").strip()
    payload: dict[str, Any] | None = None
    for line in reversed(stdout_text.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            payload = parsed
            break

    if proc.returncode == 0:
        if payload is None:
            raise OfficeError(
                "LibreOffice 引擎未返回可解析的 JSON 结果",
                "runtime",
                diagnostics=stderr_lines[-20:],
            )
        return payload

    code: str | None = None
    engine_message: str | None = None
    for line in reversed(stderr_lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "error" in parsed:
            code = parsed.get("code") if isinstance(parsed.get("code"), str) else None
            engine_message = str(parsed.get("error") or "")
            break

    mapped = _ENGINE_CODE_MESSAGES.get(code or "", "LibreOffice 引擎处理失败")
    message = mapped
    if engine_message:
        message = f"{mapped}（引擎信息：{engine_message}）"
    hint = None
    kind = "runtime"
    if code == "unavailable":
        kind = "dependency"
        hint = (
            "确认 runtime/node/lib/node_modules/@deepseek-ai/libreoffice-kit 完整；"
            "若指定了 --font-dir，请检查目录是否存在且可读。"
        )
    elif code == "timeout":
        hint = "可用 --timeout-ms 提高超时（例如 --timeout-ms 600000），或减少页数。"
    elif code == "output-too-large":
        hint = "尝试减少渲染页数、降低 --dpi，或拆分输入文档。"
    elif code == "input-too-large":
        hint = "文件过大；请拆分后分别处理。"
    elif code == "unsupported-format":
        hint = "convert 支持 doc/docx/odt、xls/xlsx/ods、ppt/pptx/odp；render 另外支持 pdf。"

    raise OfficeError(
        message,
        kind,
        hint=hint,
        diagnostics=stderr_lines[-20:],
        engine_code=code,
    )


def _tail_lines(value: Any, limit: int = 20) -> list[str]:
    if value is None:
        return []
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return str(value).strip().splitlines()[-limit:]


def pdf_page_count(path: Path) -> int | None:
    """用轻量 pypdf 读取页数，失败时返回 None（不阻塞主流程）。"""
    try:
        from pypdf import PdfReader  # type: ignore

        return len(PdfReader(str(path)).pages)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 字体探测：把文档声明的字体族与系统已安装字体族对比
# ---------------------------------------------------------------------------


def _fontconfig_families() -> set[str] | None:
    fc_list = shutil.which("fc-list")
    if not fc_list:
        return None
    try:
        proc = subprocess.run(
            [fc_list, "--format", "%{family}\n"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    families: set[str] = set()
    for line in proc.stdout.splitlines():
        for part in line.split(","):
            name = part.strip()
            if name:
                families.add(name)
    return families or None


_RFONTS_TAG_RE = re.compile(r"<w:rFonts\b[^>]*>")
_RFONTS_ATTR_RE = re.compile(r'w:(?:ascii|hAnsi|eastAsia|cs)="([^"]+)"')
_THEME_FONT_TAG_RE = re.compile(r"<a:(?:latin|ea|cs)\b[^>]*>")
_THEME_FONT_ATTR_RE = re.compile(r'typeface="([^"]+)"')
_LOCALE_RE = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")


def declared_fonts(path: Path, ext: str) -> list[str]:
    """从 OOXML 包中读取文档声明的字体族（docx / pptx）。"""
    names: set[str] = set()
    if ext == "docx":
        # 只统计正文/样式/页眉页脚真正引用到的字体，避免把主题默认字体
        # （Calibri/Cambria 等）全部当成“缺失”报给用户。
        members = ("word/document.xml", "word/styles.xml", "word/numbering.xml")
    elif ext == "pptx":
        members = ("ppt/presentation.xml",)
    else:
        return []
    try:
        with zipfile.ZipFile(path) as archive:
            available = set(archive.namelist())
            if ext == "docx":
                extra = sorted(
                    n
                    for n in available
                    if n.startswith(("word/header", "word/footer"))
                    and n.endswith(".xml")
                )
                members = tuple(list(members) + extra)
            elif ext == "pptx":
                theme_members = sorted(
                    n for n in available if n.startswith("ppt/theme/") and n.endswith(".xml")
                )
                slide_members = sorted(
                    n for n in available if n.startswith("ppt/slides/") and n.endswith(".xml")
                )
                members = tuple(theme_members + slide_members + list(members))
            for member in members:
                if member not in available:
                    continue
                try:
                    text = archive.read(member).decode("utf-8", "replace")
                except (KeyError, OSError):
                    continue
                if ext == "docx":
                    for tag in _RFONTS_TAG_RE.findall(text):
                        names.update(_RFONTS_ATTR_RE.findall(tag))
                for tag in _THEME_FONT_TAG_RE.findall(text):
                    names.update(_THEME_FONT_ATTR_RE.findall(tag))
    except (OSError, zipfile.BadZipFile):
        return []
    cleaned: list[str] = []
    for name in names:
        name = name.strip()
        if not name or name.startswith("+") or name.lower() in {"none", "null"}:
            continue
        # 排除 w:lang/@w:eastAsia="en-US" 这类语言标记被误当作字体名。
        if _LOCALE_RE.fullmatch(name) and name.lower() not in {"arial", "calibri"}:
            continue
        if name not in cleaned:
            cleaned.append(name)
    return sorted(cleaned)


def font_report(path: Path, ext: str) -> tuple[list[str], list[str], str]:
    """返回 (声明字体, 缺失字体, 检测方式)。"""
    declared = declared_fonts(path, ext)
    if not declared:
        return [], [], "none-declared"
    installed = _fontconfig_families()
    if installed is None:
        return declared, [], "unavailable"
    lowered = {name.lower() for name in installed}
    missing = [name for name in declared if name.lower() not in lowered]
    return declared, missing, "fontconfig"


def font_report_from_names(declared: list[str]) -> tuple[list[str], list[str], str]:
    """对调用方已经收集好的字体名做与 font_report 相同的可用性对比。"""
    cleaned: list[str] = []
    for name in declared:
        text = (name or "").strip()
        if not text or text.startswith("+"):
            continue
        if _LOCALE_RE.fullmatch(text) and text.lower() not in {"arial", "calibri"}:
            continue
        if text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return [], [], "none-declared"
    installed = _fontconfig_families()
    if installed is None:
        return cleaned, [], "unavailable"
    lowered = {name.lower() for name in installed}
    missing = [name for name in cleaned if name.lower() not in lowered]
    return cleaned, missing, "fontconfig"


def warn_missing_fonts(missing: Sequence[str]) -> None:
    if missing:
        print(
            "提示: 缺失字体 "
            + "、".join(missing)
            + "，渲染时将由替代字体回退（可用 --font-dir 追加字体目录）。",
            file=sys.stderr,
        )


def write_json_file(path: Path, payload: Any) -> None:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    except OSError as exc:
        raise runtime_error(f"无法写入 {path}：{exc}") from exc
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def chmod_public(path: Path) -> None:
    """引擎输出为 0600，交付给用户时放宽到 0644（失败不致命）。"""
    try:
        os.chmod(path, 0o644)
    except OSError:
        pass


def make_temp_dir(parent: Path, prefix: str = ".office-") -> Path:
    ensure_dir(parent)
    try:
        return Path(tempfile.mkdtemp(prefix=prefix, dir=str(parent)))
    except OSError as exc:
        raise runtime_error(f"无法在 {parent} 创建临时目录：{exc}") from exc
