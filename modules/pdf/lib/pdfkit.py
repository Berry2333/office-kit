#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""office-kit pdf —— 基于 Stirling-PDF 的离线 PDF 工具箱。

用法::

    pdf start|stop|status
    pdf list-tools [--json]
    pdf run <tool> --input FILE... --output OUT [--option k=v ...] [--json]

实现要点：
  * 后端为 headless Stirling-PDF（Java），按需后台启动，端口写入
    ``$OFFICE_KIT_DATA/pdf/``，带 flock 并发保护、就绪等待和空闲退出。
  * 工具清单一律从运行中实例的 ``/v1/api-docs``（OpenAPI 3）生成，不硬编码。
  * ``run`` 是通用 REST 调用器：multipart 上传、表单参数、ZIP/图片/PDF/文本/JSON
    响应、错误体解析与超时。
  * 某些端点会因缺少系统外部程序被 Stirling 禁用（例如没有 LibreOffice 时的
    pdf-to-pdfa）。此时对 PDF/A 使用 Ghostscript 本地兜底，并在输出中明确标注。
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import fcntl
import http.client
import io
import json
import mimetypes
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

VERSION = "1.0.0"
USER_AGENT = "office-kit-pdf/%s" % VERSION

# ---------------------------------------------------------------------------
# 工具别名：用户友好名 -> OpenAPI operationId（真实存在，见 /v1/api-docs）
# defaults 仅在该工具未显式提供参数时补充，与 OpenAPI schema 的默认值一致或更安全。
# ---------------------------------------------------------------------------
TOOL_ALIASES = {
    "merge": {
        "op": "mergePdfs",
        "label": "合并多个 PDF/图片为一个 PDF",
        "defaults": {"sortType": "orderProvided", "removeCertSign": "true"},
    },
    "split": {
        "op": "splitPdf_2",
        "label": "按页码/范围拆分 PDF",
        "defaults": {"pageNumbers": "all"},
    },
    "split-sections": {"op": "splitPdf", "label": "按固定页数分段拆分"},
    "split-chapters": {"op": "splitPdf_1", "label": "按章节/书签拆分"},
    "split-size": {"op": "autoSplitPdf_1", "label": "按大小或页数拆分"},
    "rotate": {
        "op": "rotatePDF",
        "label": "旋转全部页面（角度 90/180/270）",
        "defaults": {},
    },
    "auto-rotate": {"op": "autoRotatePdf", "label": "自动纠正页面方向"},
    "extract-text": {
        "op": "processPdfToRTForTXT",
        "label": "抽取 PDF 文本层（txt/rtf）",
        "defaults": {"outputFormat": "txt"},
    },
    "pdf-to-text": {"op": "processPdfToRTForTXT", "label": "抽取 PDF 文本层"},
    "pdf-to-img": {
        "op": "convertToImage",
        "label": "PDF 转图片（PNG/JPEG）",
        "defaults": {
            "imageFormat": "png",
            "singleOrMultiple": "multiple",
            "colorType": "color",
            "dpi": "150",
            "pageNumbers": "all",
        },
    },
    "img-to-pdf": {
        "op": "convertToPdf",
        "label": "图片转 PDF",
        "defaults": {
            "fitOption": "maintainAspectRatio",
            "colorType": "color",
            "autoRotate": "false",
        },
    },
    "compress": {
        "op": "optimizePdf",
        "label": "压缩 PDF",
        "defaults": {
            "optimizeLevel": "5",
            "expectedOutputSize": "25KB",
            "linearize": "false",
            "normalize": "false",
            "grayscale": "false",
        },
    },
    "encrypt": {
        "op": "addPassword",
        "label": "添加打开密码/权限",
        "defaults": {"keyLength": "256"},
    },
    "decrypt": {"op": "removePassword", "label": "移除 PDF 密码"},
    "watermark": {
        "op": "addWatermark",
        "label": "添加文字/图片水印",
        "defaults": {
            "convertPDFToImage": "false",
            "alphabet": "roman",
            "fontSize": "40",
            "rotation": "45",
            "opacity": "0.3",
            "widthSpacer": "50",
            "heightSpacer": "50",
        },
    },
    "ocr": {
        "op": "processPdfWithOCR",
        "label": "扫描件 OCR（tesseract，含 chi_sim）",
        "defaults": {
            "ocrType": "skip-text",
            "ocrRenderType": "sandwich",
            "languages": "chi_sim+eng",
        },
    },
    "pdf-to-pdfa": {
        "op": "pdfToPdfA",
        "label": "转换 PDF/A（PDF/A-2b）",
        "defaults": {"outputFormat": "pdfa-2"},
    },
    "info": {"op": "getBasicInfo", "label": "PDF 基本信息（页数/版本/大小）"},
    "summary": {"op": "__summary__", "label": "PDF 摘要（基本+属性+安全+尺寸）"},
    "metadata": {"op": "metadata", "label": "修改 PDF 元数据"},
    "page-numbers": {"op": "addPageNumbers", "label": "添加页码"},
    "extract-images": {"op": "extractImages", "label": "提取内嵌图片"},
    "remove-pages": {"op": "deletePages", "label": "删除页面"},
    "rearrange": {"op": "rearrangePages", "label": "重排页面"},
    "repair": {"op": "repairPdf", "label": "修复损坏 PDF"},
    "flatten": {"op": "flatten", "label": "扁平化表单"},
    "sanitize": {"op": "sanitizePDF", "label": "清理隐藏内容"},
    "add-stamp": {"op": "addStamp", "label": "添加图章"},
    "pdf-to-word": {"op": "processPdfToWord", "label": "PDF 转 Word（需 LibreOffice）"},
    "pdf-to-html": {"op": "processPdfToHTML", "label": "PDF 转 HTML（需 LibreOffice）"},
    "pdf-to-markdown": {"op": "processPdfToMarkdown", "label": "PDF 转 Markdown"},
    "pdf-to-csv": {"op": "pdfToCsv", "label": "PDF 表格转 CSV"},
    "pdf-to-xlsx": {"op": "pdfToExcel", "label": "PDF 表格转 Excel"},
    "pdf-to-json": {"op": "convertPdfToJson", "label": "PDF 转可编辑 JSON"},
    "page-dimensions": {"op": "getPageDimensions", "label": "页面尺寸"},
    "security-info": {"op": "getSecurityInfo", "label": "文档安全信息"},
}

# 常见外部依赖缺失时被禁用的端点（仅用于友好提示，不参与调用逻辑）
DISABLED_HINTS = {
    "pdf-to-pdfa": "需要 LibreOffice（soffice）或 Ghostscript；本工具会在端点被禁用时自动使用 Ghostscript 兜底",
    "pdf-to-word": "需要 LibreOffice（soffice）",
    "pdf-to-html": "需要 LibreOffice（soffice）",
    "pdf-to-presentation": "需要 LibreOffice（soffice）",
    "pdf-to-xml": "需要 LibreOffice（soffice）",
    "file-to-pdf": "需要 LibreOffice（soffice）",
    "repair": "需要 qpdf",
    "pdf-to-epub": "需要 Calibre（ebook-convert）",
}

# 端点 key 与 OpenAPI 路径无法自动对应时的显式映射
ENDPOINT_KEY_OVERRIDES = {
    "pdfToPdfA": "pdf-to-pdfa",
    "processPdfWithOCR": "ocr-pdf",
}


class KitError(Exception):
    """带退出码与修复提示的错误。"""

    def __init__(self, message, code=1, hint=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


# ---------------------------------------------------------------------------
# 环境
# ---------------------------------------------------------------------------
class Env:
    def __init__(self):
        self._self = Path(__file__).resolve()
        self.module = Path(
            os.environ.get("OFFICE_KIT_PDF_MODULE") or self._self.parent.parent
        )
        root = os.environ.get("OFFICE_KIT_ROOT")
        if not root:
            root = str(self.module.parent.parent)
        self.root = Path(root)
        self.runtime = Path(os.environ.get("OFFICE_KIT_RUNTIME") or (self.root / "runtime"))
        data = os.environ.get("OFFICE_KIT_DATA") or os.path.join(
            os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share"),
            "office-kit",
        )
        self.data = Path(data)
        self.cache = Path(os.environ.get("OFFICE_KIT_CACHE") or (self.data / "cache"))
        self.logs = Path(os.environ.get("OFFICE_KIT_LOGS") or (self.data / "logs"))
        self.pdf = self.data / "pdf"
        self.configs = self.pdf / "configs"
        self.server_logs = self.pdf / "logs"
        self.work = self.pdf / "work"
        self.port_file = self.pdf / "port"
        self.pid_file = self.pdf / "pid"
        self.state_file = self.pdf / "state.json"
        self.tools_file = self.pdf / "tools.json"
        self.start_lock = self.pdf / "start.lock"
        self.watchdog_pid_file = self.pdf / "watchdog.pid"
        self.last_use_file = self.pdf / "last_use"
        self.console_log = self.server_logs / "console.log"
        self.jtmp = self.cache / "pdf" / "tmp"
        self.jre = self.runtime / "jre"
        self.java = Path(os.environ.get("OFFICE_KIT_JAVA") or (self.jre / "bin" / "java"))
        self.stirling = Path(os.environ.get("OFFICE_KIT_STIRLING") or (self.runtime / "stirling"))
        self.jar = self.stirling / "Stirling-PDF.jar"
        self.native = self.stirling / "native"
        self.tessdata = self.stirling / "tessdata"
        self.glibc_ld = self.runtime / "glibc" / "lib" / "ld-linux-aarch64.so.1"
        self.glibc_lib = self.runtime / "glibc" / "lib"
        self.lib = self.module / "lib"

    def _in_appimage(self):
        """当前是否从 AppImage 的 squashfs 挂载点运行。"""
        try:
            root = os.path.realpath(str(self.root))
        except OSError:
            root = str(self.root)
        return "/.mount_" in root or root.startswith("/tmp/.mount_")

    def _bind_staged(self, dest):
        self.stirling = dest / "stirling"
        self.jar = self.stirling / "Stirling-PDF.jar"
        self.native = self.stirling / "native"
        self.tessdata = self.stirling / "tessdata"
        self.jre = dest / "jre"
        self.java = self.jre / "bin" / "java"
        self.glibc_ld = dest / "glibc" / "lib" / "ld-linux-aarch64.so.1"
        self.glibc_lib = dest / "glibc" / "lib"

    def stage_if_needed(self):
        """把 PDF 引擎复制出 AppImage 挂载点。

        AppImage 进程退出后 FUSE 挂载会消失，而后台 JVM 之后仍会惰性读取 jar 里的
        class（例如 springdoc 生成 /v1/api-docs），届时会抛 NoClassDefFoundError。
        因此 AppImage 模式首次 start 时把 jar/native/tessdata/jre/glibc 解包到数据目录，
        之后都从稳定路径启动。
        """
        if os.environ.get("OFFICE_KIT_PDF_STAGE", "1") == "0":
            return
        if not self._in_appimage() or not self.jar.is_file():
            return
        dest = self.pdf / "runtime"
        marker = dest / ".staged.json"
        size = self.jar.stat().st_size
        if (dest / "stirling" / "Stirling-PDF.jar").is_file() and marker.is_file():
            try:
                if json.loads(marker.read_text(encoding="utf-8")).get("jar_size") == size:
                    self._bind_staged(dest)
                    return
            except (OSError, ValueError):
                pass
        info("首次在 AppImage 模式下解包 PDF 引擎（约 390 MB，仅一次）…")
        dest.mkdir(parents=True, exist_ok=True)
        for name in ("stirling", "jre", "glibc"):
            src = self.runtime / name
            if src.is_dir():
                shutil.copytree(src, dest / name, dirs_exist_ok=True)
        marker.write_text(
            json.dumps({"jar_size": size, "source": str(self.root)}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self._bind_staged(dest)
        info(f"PDF 引擎已解包到 {dest}")

    def ensure(self):
        for d in (
            self.pdf,
            self.configs,
            self.server_logs,
            self.work,
            self.cache / "pdf",
            self.jtmp,
            self.logs,
        ):
            d.mkdir(parents=True, exist_ok=True)


ENV = Env()


# ---------------------------------------------------------------------------
# 输出小工具
# ---------------------------------------------------------------------------
def emit_json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
    sys.stdout.flush()


def info(msg):
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json_atomic(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024.0


@contextlib.contextmanager
def file_lock(path, exclusive=True, blocking=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    flags = (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | (
        0 if blocking else fcntl.LOCK_NB
    )
    try:
        fcntl.flock(fd, flags)
    except OSError:
        os.close(fd)
        raise
    try:
        yield fd
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def tail_file(path, lines=30):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.readlines()
        return "".join(data[-lines:]).rstrip()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 后端进程管理
# ---------------------------------------------------------------------------
def _read_pid():
    try:
        return int(Path(ENV.pid_file).read_text().strip())
    except (OSError, ValueError):
        return None


def _read_port():
    try:
        return int(Path(ENV.port_file).read_text().strip())
    except (OSError, ValueError):
        return None


def _read_state():
    st = read_json(ENV.state_file, None)
    if isinstance(st, dict) and st.get("pid"):
        return st
    return None


def _proc_cmdline(pid):
    try:
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
    except (OSError, ValueError):
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace")


def _is_server_process(pid, port=None):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    cmd = _proc_cmdline(pid)
    if "Stirling-PDF.jar" not in cmd:
        return False
    if port is not None and f"server.port={port}" not in cmd:
        return False
    return True


def _is_watchdog_process(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    cmd = _proc_cmdline(pid)
    return "pdfkit.py" in cmd and "_watchdog" in cmd


def _port_free(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _pick_port(preferred=None):
    if preferred:
        return int(preferred)
    env_port = os.environ.get("OFFICE_KIT_PDF_PORT")
    if env_port and str(env_port).isdigit():
        p = int(env_port)
        if _port_free(p):
            return p
    for p in range(8091, 8200):
        if _port_free(p):
            return p
    raise KitError("8091-8199 没有空闲端口", 1, "用 --port 指定其它端口，或先释放占用端口的进程")


def _probe(port, timeout=2.0):
    if not port:
        return None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=timeout)
        conn.request("GET", "/api/v1/info/status", headers={"Accept": "application/json"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        if resp.status != 200:
            return None
        data = json.loads(body.decode("utf-8"))
        if str(data.get("status", "")).upper() != "UP":
            return None
        return data
    except (OSError, ValueError, http.client.HTTPException):
        return None


def _server_env(port):
    env = dict(os.environ)
    env["STIRLING_PDF_CONFIG_DIR"] = str(ENV.configs)
    env["STIRLING_PDF_LOG_DIR"] = str(ENV.server_logs)
    env["STIRLING_PDF_WORK_DIR"] = str(ENV.work)
    env["STIRLING_PDF_DATA_DIR"] = str(ENV.pdf)
    if ENV.tessdata.is_dir():
        env["TESSDATA_PREFIX"] = str(ENV.tessdata)
    # 模块自带的辅助外部程序（若以后打包 tesseract/gs），优先于系统 PATH
    extra_bin = ENV.lib / "bin"
    if extra_bin.is_dir():
        env["PATH"] = str(extra_bin) + os.pathsep + env.get("PATH", "")
    env.setdefault("LANG", "C.UTF-8")
    return env


def _java_command(port, xmx):
    if not ENV.jar.is_file():
        raise KitError(
            f"缺少 Stirling-PDF JAR：{ENV.jar}",
            3,
            "确认 runtime/stirling/Stirling-PDF.jar 存在；或设置 OFFICE_KIT_STIRLING 指向含 jar 的目录",
        )
    if not ENV.java.exists():
        raise KitError(
            f"缺少 Java 运行时：{ENV.java}",
            3,
            "确认 runtime/jre/bin/java 存在；或设置 OFFICE_KIT_JAVA",
        )
    args = [
        f"-Xmx{xmx}",
        "-Dfile.encoding=UTF-8",
        "-Dsun.jnu.encoding=UTF-8",
        f"-Djava.io.tmpdir={ENV.jtmp}",
        "-DBROWSER_OPEN=false",
        "-DSTIRLING_PDF_TAURI_MODE=true",
        "-Dserver.address=127.0.0.1",
        f"-Dserver.port={port}",
        "-Dsecurity.enableLogin=false",
        "-Dsecurity.csrfDisabled=true",
        "-Dserver.forward-headers-strategy=none",
        f"-Dlogging.file.path={ENV.server_logs}",
        "-Dlogging.file.name=stirling-pdf.log",
        "-jar",
        str(ENV.jar),
    ]
    extra = os.environ.get("OFFICE_KIT_PDF_JAVA_OPTS", "").strip()
    if extra:
        import shlex

        args[0:0] = shlex.split(extra)
    if ENV.native.is_dir():
        args.insert(0, f"-Djava.library.path={ENV.native}")

    # jpdfium 的 aarch64 原生库要求 glibc >= 2.35 / GLIBCXX >= 3.4.32，
    # 而 Kylin V10 为 glibc 2.31。桌面版同样用随包 glibc loader 启动后端。
    if ENV.glibc_ld.exists() and ENV.glibc_lib.is_dir():
        libpath = os.pathsep.join(
            [
                str(ENV.glibc_lib),
                str(ENV.native),
                str(ENV.jre / "lib"),
                str(ENV.jre / "lib" / "server"),
            ]
        )
        return [str(ENV.glibc_ld), "--library-path", libpath, str(ENV.java)] + args
    return [str(ENV.java)] + args


def _spawn_watchdog(idle_seconds):
    if idle_seconds <= 0:
        return None
    # 已有存活 watchdog 则复用
    try:
        old = int(Path(ENV.watchdog_pid_file).read_text().strip())
        if _is_watchdog_process(old):
            return old
    except (OSError, ValueError):
        pass
    log = open(ENV.server_logs / "watchdog.log", "a", encoding="utf-8")
    try:
        proc = subprocess.Popen(
            [
                sys.executable,
                str(ENV.module / "lib" / "pdfkit.py"),
                "_watchdog",
                "--idle",
                str(int(idle_seconds)),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=dict(os.environ),
        )
    except OSError:
        log.close()
        return None
    with contextlib.suppress(OSError):
        log.close()
    Path(ENV.watchdog_pid_file).write_text(str(proc.pid))
    return proc.pid


def _kill_pid(pid, sig):
    with contextlib.suppress(OSError):
        os.kill(int(pid), sig)


def _wait_gone(pid, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not Path(f"/proc/{int(pid)}").exists():
            return True
        time.sleep(0.25)
    return not Path(f"/proc/{int(pid)}").exists()


def _touch_last_use():
    try:
        Path(ENV.last_use_file).write_text(str(int(time.time())))
    except OSError:
        pass


_RUNNING_RE = re.compile(r"running on port:\s*(\d+)", re.I)


def _log_size(path=None):
    try:
        return os.path.getsize(str(path or ENV.console_log))
    except OSError:
        return 0


def _read_log_from(path, offset, limit=400_000):
    try:
        with open(str(path), "rb") as f:
            f.seek(int(offset))
            return f.read(limit).decode("utf-8", "replace")
    except OSError:
        return ""


def _last_running_port(text):
    found = _RUNNING_RE.findall(text or "")
    return int(found[-1]) if found else None


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _is_our_server(pid):
    """仅把本数据目录拉起的 Stirling 进程当作“我们的”，避免误杀其它实例。"""
    if not _pid_alive(pid):
        return False
    cmd = _proc_cmdline(pid)
    if "Stirling-PDF.jar" not in cmd:
        return False
    if f"-Dlogging.file.path={ENV.server_logs}" in cmd:
        return True
    # 兼容手工启动、未设置 logging.file.path 的实例；但绝不碰其它数据目录的实例
    return re.search(r"-Dlogging\.file\.path=", cmd) is None


def _cmdline_port(pid):
    m = re.search(r"-Dserver\.port=(\d+)", _proc_cmdline(pid))
    return int(m.group(1)) if m else None


def _find_our_server_pids():
    """扫描 /proc 找出属于本数据目录的 Stirling 进程（用于恢复/清理孤儿）。"""
    marker = f"-Dlogging.file.path={ENV.server_logs}"
    pids = []
    try:
        entries = os.listdir("/proc")
    except OSError:
        return pids
    for entry in entries:
        if not entry.isdigit():
            continue
        cmd = _proc_cmdline(entry)
        if "Stirling-PDF.jar" in cmd and marker in cmd:
            pids.append(int(entry))
    return pids


def _candidate_ports(pid=None, extra=()):
    ports = []

    def add(p):
        try:
            p = int(p)
        except (TypeError, ValueError):
            return
        if p > 0 and p not in ports:
            ports.append(p)

    for p in extra:
        add(p)
    add(_read_port())
    if pid:
        add(_cmdline_port(pid))
    add(_last_running_port(_read_log_from(ENV.console_log, max(0, _log_size() - 400_000))))
    return ports


def _recover_port(pid=None, extra=(), scan=False, timeout=1.0):
    candidates = _candidate_ports(pid, extra)
    for p in candidates:
        if _probe(p, timeout=timeout):
            return p
    if scan and not candidates:
        for p in range(8091, 8200):
            if p in candidates:
                continue
            if _probe(p, timeout=0.15):
                return p
    return None


def _terminate_proc(proc, grace=12):
    if proc is None:
        return
    if proc.poll() is not None:
        return
    with contextlib.suppress(OSError):
        proc.terminate()
    try:
        proc.wait(timeout=grace)
        return
    except subprocess.TimeoutExpired:
        pass
    with contextlib.suppress(OSError):
        proc.kill()
    with contextlib.suppress(Exception):
        proc.wait(timeout=5)


def _terminate_pid(pid, grace=12):
    if not _pid_alive(pid):
        return
    with contextlib.suppress(OSError):
        os.kill(int(pid), signal.SIGTERM)
    if _wait_gone(pid, grace):
        return
    with contextlib.suppress(OSError):
        os.kill(int(pid), signal.SIGKILL)
    _wait_gone(pid, 5)


def _wait_ready(proc=None, pid=None, expected=None, log_path=None, log_offset=0, timeout=180):
    """等待后端 HTTP 就绪；同时跟踪日志里的 'running on port: N'。

    返回真实端口，超时/进程退出返回 None。
    """
    deadline = time.time() + timeout
    candidates = []
    if expected:
        candidates.append(int(expected))
    if pid:
        p = _cmdline_port(pid)
        if p and p not in candidates:
            candidates.append(p)
    log_path = str(log_path or ENV.console_log)
    last_check = 0.0
    while time.time() < deadline:
        if proc is not None:
            if proc.poll() is not None:
                return None
        elif not _is_our_server(pid):
            return None
        for p in list(candidates):
            if _probe(p, timeout=1.2):
                return p
        # 日志可能显示实际端口（例如端口回退）
        if time.time() - last_check > 1.5:
            last_check = time.time()
            text = _read_log_from(log_path, log_offset)
            p = _last_running_port(text)
            if p and p not in candidates:
                candidates.append(p)
        time.sleep(1)
    return None


def _write_state(pid, port, version, idle_seconds, xmx):
    state = {
        "pid": int(pid),
        "port": int(port),
        "version": version,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "jar": str(ENV.jar),
        "idle_timeout": int(idle_seconds),
        "xmx": xmx,
    }
    write_json_atomic(ENV.state_file, state)
    Path(ENV.port_file).write_text(str(int(port)))
    return state


def _reuse_server(pid, port, timeout, idle_seconds, st):
    """复用已存活实例；必要时等待其就绪。返回 (port, version, reused)。"""
    probe = _probe(port, timeout=1.2) if port else None
    if not probe:
        info(f"检测到存活实例（pid={pid}），等待就绪…")
        real = _wait_ready(pid=pid, expected=port, timeout=timeout)
        if not real:
            # 不留下孤儿：清理后让调用方决定是否重启
            info("实例在超时内未就绪，终止残留进程…")
            _terminate_pid(pid)
            for f in (ENV.pid_file, ENV.port_file, ENV.state_file):
                with contextlib.suppress(OSError):
                    Path(f).unlink()
            raise KitError(
                "已清理未就绪的 Stirling-PDF 进程",
                1,
                f"请重试 pdf start；日志：{ENV.console_log}",
            )
        port = real
        probe = _probe(port, timeout=2) or {}
    _touch_last_use()
    st = dict(st or {})
    st.update(
        {
            "pid": int(pid),
            "port": int(port),
            "version": probe.get("version") or st.get("version"),
            "idle_timeout": int(idle_seconds),
        }
    )
    if idle_seconds > 0:
        wd = _spawn_watchdog(int(idle_seconds))
        if wd:
            st["watchdog_pid"] = wd
    else:
        try:
            old_wd = int(Path(ENV.watchdog_pid_file).read_text().strip())
            if _is_watchdog_process(old_wd):
                _kill_pid(old_wd, signal.SIGTERM)
        except (OSError, ValueError):
            pass
        with contextlib.suppress(OSError):
            Path(ENV.watchdog_pid_file).unlink()
    write_json_atomic(ENV.state_file, st)
    return int(port), st.get("version"), True


def start_server(port=None, timeout=180, idle_seconds=600, xmx="1536m", force=False):
    """启动后端；已运行则复用。返回 (port, version, reused)。

    * 端口：默认从 8091 起探测，绑定失败自动换下一个（最多 5 次）。
    * 就绪：默认等待 180s（首次启动需生成配置 + JVM 预热，实测 60-100s）。
    * 失败/超时：终止本次拉起的进程并清理 pid/port/state，不留孤儿。
    """
    ENV.ensure()
    ENV.stage_if_needed()
    with file_lock(ENV.start_lock, exclusive=True, blocking=True):
        st = _read_state() or {}
        pid = st.get("pid") or _read_pid()
        sport = st.get("port") or _read_port()
        if pid and not _is_our_server(pid):
            pid = None
        if not pid:
            # pid/state 丢失时，尝试从 /proc 找回本数据目录的实例并复用
            found = _find_our_server_pids()
            if found:
                pid = found[0]

        if pid and not force:
            return _reuse_server(
                pid, _recover_port(pid, extra=[sport], scan=False, timeout=1.0),
                timeout, idle_seconds, st,
            )
        if pid and force:
            info("--force：先停止已有实例…")
            stop_server(quiet=True, _locked=True)

        # 清理陈旧状态（没有存活进程时）
        for f in (ENV.pid_file, ENV.port_file, ENV.state_file):
            with contextlib.suppress(OSError):
                Path(f).unlink()

        if port and not _port_free(port):
            raise KitError(
                f"端口 {port} 已被占用",
                1,
                "换一个端口（--port），或结束占用进程后重试",
            )

        log_path = ENV.console_log
        attempts = 1 if port else 5
        last_tail = ""
        for attempt in range(1, attempts + 1):
            try:
                used_port = _pick_port(port)
            except KitError:
                raise
            cmd = _java_command(used_port, xmx)
            env = _server_env(used_port)
            log_offset = _log_size(log_path)
            console = open(log_path, "a", encoding="utf-8")
            console.write(
                f"\n===== pdf start {time.strftime('%Y-%m-%d %H:%M:%S')} "
                f"attempt={attempt}/{attempts} port={used_port} =====\n"
            )
            console.flush()
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=console,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    cwd=str(ENV.work),
                    env=env,
                )
            except OSError as exc:
                raise KitError(f"无法启动 Java：{exc}", 1, "检查 runtime/jre 是否完整")
            finally:
                with contextlib.suppress(Exception):
                    console.close()

            Path(ENV.pid_file).write_text(str(proc.pid))
            info(
                f"正在启动 Stirling-PDF（pid={proc.pid}, 端口={used_port}，"
                f"第 {attempt}/{attempts} 次），首次启动约 20-100 秒…"
            )
            real_port = _wait_ready(
                proc=proc,
                expected=used_port,
                log_path=log_path,
                log_offset=log_offset,
                timeout=timeout,
            )
            if real_port:
                version = (_probe(real_port, timeout=2) or {}).get("version") or "unknown"
                state = _write_state(proc.pid, real_port, version, idle_seconds, xmx)
                _touch_last_use()
                wd = _spawn_watchdog(idle_seconds)
                if wd:
                    state["watchdog_pid"] = wd
                    write_json_atomic(ENV.state_file, state)
                info(f"Stirling-PDF 已就绪：端口 {real_port}，版本 {version}")
                return int(real_port), version, False

            last_tail = _read_log_from(log_path, log_offset)[-6000:]
            exited = proc.poll() is not None
            _terminate_proc(proc)
            with contextlib.suppress(OSError):
                Path(ENV.pid_file).unlink()

            conflict = (
                "Address already in use" in last_tail
                or "BindException" in last_tail
                or "Web server failed to start" in last_tail
            )
            if attempt < attempts and conflict:
                info(f"端口 {used_port} 启动失败（可能被占用），自动换端口重试…")
                time.sleep(1)
                continue
            if exited:
                raise KitError(
                    f"Stirling-PDF 启动失败（退出码 {proc.returncode}）",
                    1,
                    f"最近日志：\n{last_tail}",
                )
            raise KitError(
                "等待 Stirling-PDF 就绪超时（已终止本次启动的进程）",
                1,
                f"查看日志：{log_path}\n{last_tail[-3000:]}",
            )
        raise KitError("Stirling-PDF 启动失败", 1, f"查看日志：{log_path}")


def stop_server(quiet=False, _locked=False):
    """停止后端与 watchdog；幂等。返回是否确实停止了进程。"""
    ENV.ensure()
    lock = (
        contextlib.nullcontext()
        if _locked
        else file_lock(ENV.start_lock, exclusive=True, blocking=True)
    )
    with lock:
        st = _read_state() or {}
        pids = []
        for p in (st.get("pid"), _read_pid()):
            if p and int(p) not in pids:
                pids.append(int(p))
        # 清理 pid 文件丢失的孤儿（只匹配本数据目录的 logging 路径）
        for p in _find_our_server_pids():
            if p not in pids:
                pids.append(p)

        wd = None
        try:
            wd = int(Path(ENV.watchdog_pid_file).read_text().strip())
        except (OSError, ValueError):
            pass

        stopped = False
        for pid in pids:
            if _is_our_server(pid):
                stopped = True
                _terminate_pid(pid)

        if wd and _is_watchdog_process(wd):
            _kill_pid(wd, signal.SIGTERM)
            _wait_gone(wd, 3)
            with contextlib.suppress(OSError):
                _kill_pid(wd, signal.SIGKILL)

        for f in (ENV.pid_file, ENV.port_file, ENV.state_file, ENV.watchdog_pid_file):
            with contextlib.suppress(OSError):
                Path(f).unlink()
        _touch_last_use()
        if not quiet:
            if stopped:
                info("已停止 Stirling-PDF 后端")
            else:
                info("Stirling-PDF 未在运行")
        return stopped


def status_info():
    st = _read_state() or {}
    pid = st.get("pid") or _read_pid()
    if pid and not _is_our_server(pid):
        pid = None
    if not pid:
        found = _find_our_server_pids()
        if found:
            pid = found[0]

    port = st.get("port") or _read_port()
    running = bool(pid)
    ready = False
    version = st.get("version")
    if running:
        real = _recover_port(pid, extra=[port], scan=False, timeout=0.8)
        if real:
            port = real
            probe = _probe(port, timeout=1.5)
            if probe:
                ready = True
                version = probe.get("version") or version
        elif not port:
            port = _cmdline_port(pid)
    if not running:
        pid = None
        port = None
        ready = False
        version = None
    return {
        "ok": True,
        "running": running,
        "ready": ready,
        "port": int(port) if port else None,
        "pid": int(pid) if pid else None,
        "version": version if running else None,
        "idle_timeout": st.get("idle_timeout"),
        "data_dir": str(ENV.data),
        "log": str(ENV.console_log),
    }


def ensure_server(timeout=180):
    st = status_info()
    if st["running"] and st["ready"]:
        _touch_last_use()
        return st["port"], st["version"]
    info("Stirling-PDF 后端未运行，正在自动启动（首次约 60-100 秒）…")
    port, version, _ = start_server(timeout=timeout)
    return port, version


# ---------------------------------------------------------------------------
# OpenAPI -> 工具清单
# ---------------------------------------------------------------------------
_SKIP_PREFIXES = (
    "/api/v1/ui-data",
    "/api/v1/info/",
    "/api/v1/general/job",
    "/api/v1/general/files/",
    "/api/v1/general/signatures/",
    "/api/v1/security/cert-sign/hardware",
    "/api/v1/convert/pdf/text-editor/page/",
    "/api/v1/convert/pdf/text-editor/fonts/",
    "/api/v1/convert/pdf/text-editor/partial/",
    "/api/v1/convert/pdf/text-editor/clear-cache",
    "/robots.txt",
)


def _http_get_json(port, path, timeout=30):
    conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=timeout)
    try:
        conn.request("GET", path, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        resp = conn.getresponse()
        body = resp.read()
        if resp.status != 200:
            raise KitError(
                f"请求 {path} 失败：HTTP {resp.status}",
                1,
                body[:300].decode("utf-8", "replace"),
            )
        return json.loads(body.decode("utf-8"))
    finally:
        conn.close()


def _schema_ref(raw, schema):
    if not isinstance(schema, dict):
        return {}
    if "$ref" in schema:
        name = schema["$ref"].rstrip("/").split("/")[-1]
        target = raw.get("components", {}).get("schemas", {}).get(name, {})
        return _schema_ref(raw, target)
    if "oneOf" in schema and schema["oneOf"]:
        return _schema_ref(raw, schema["oneOf"][0])
    if "allOf" in schema and schema["allOf"]:
        merged = {}
        for part in schema["allOf"]:
            merged.update(_schema_ref(raw, part))
        return merged
    return schema


def _field_kind(prop):
    if not isinstance(prop, dict):
        return "string"
    if prop.get("format") == "binary":
        return "file"
    t = prop.get("type", "string")
    if t == "array":
        items = prop.get("items", {}) or {}
        if items.get("format") == "binary":
            return "file-list"
        return "array"
    return t


def _output_kind(op, responses):
    x = op.get("x-stirling-io") or {}
    produces = (x.get("produces") or "").upper()
    if produces in ("PDF",):
        return "pdf"
    if produces in ("IMAGE",):
        return "image"
    if produces in ("TEXT",):
        return "text"
    if produces in ("WORD",):
        return "docx"
    if produces:
        return produces.lower()
    cts = set()
    for code, r in (responses or {}).items():
        if str(code).startswith("2"):
            cts.update((r.get("content") or {}).keys())
    if "application/pdf" in cts:
        return "pdf"
    if "application/zip" in cts:
        return "zip"
    if "application/json" in cts:
        return "json"
    if "text/plain" in cts:
        return "text"
    if any(c.startswith("image/") for c in cts):
        return "image"
    return "file"


def _endpoint_key(path, op, tool_name):
    if tool_name:
        return tool_name
    key = ENDPOINT_KEY_OVERRIDES.get(op.get("operationId"))
    if key:
        return key
    seg = path.rstrip("/").split("/")[-1]
    if seg.startswith("{"):
        return "%s-%s" % (path.rstrip("/").split("/")[-2], op.get("operationId", "op"))
    return seg


def _disabled_endpoints():
    """从后端启动日志里读出被禁用的端点 key（Stirling 启动时打印一次）。"""
    text = ""
    try:
        with open(ENV.console_log, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return []
    matches = re.findall(r"Disabled endpoints:\s*([^\n]*)", text)
    if not matches:
        return []
    return [x.strip() for x in matches[-1].split(",") if x.strip()]


def build_manifest(raw, version):
    alias_by_op = {}
    for name, spec in TOOL_ALIASES.items():
        alias_by_op.setdefault(spec["op"], name)
    tools = []
    for path, methods in raw.get("paths", {}).items():
        if path.startswith(_SKIP_PREFIXES):
            continue
        for method, op in methods.items():
            if method.lower() not in ("post", "get"):
                continue
            if not path.startswith("/api/v1/"):
                continue
            op_id = op.get("operationId", "")
            primary = alias_by_op.get(op_id)
            tool_name = primary or _endpoint_key(path, op, None)
            # 友好名不能覆盖已有工具的其它端点（例如 splitPdf_2 与 splitPdf）
            if tool_name in [t["tool"] for t in tools]:
                tool_name = "%s-%s" % (tool_name, op_id or method)

            rb = (op.get("requestBody") or {}).get("content") or {}
            multipart = rb.get("multipart/form-data")
            schema = _schema_ref(raw, (multipart or {}).get("schema", {})) if multipart else {}
            props = schema.get("properties", {}) if isinstance(schema, dict) else {}
            required = set(schema.get("required", []) if isinstance(schema, dict) else [])

            fields = []
            file_fields = []
            for fname, prop in props.items():
                if fname == "fileId":
                    continue
                kind = _field_kind(prop)
                entry = {
                    "name": fname,
                    "type": kind,
                    "required": fname in required,
                }
                for key in ("default", "enum"):
                    if key in prop:
                        entry[key] = prop[key]
                if prop.get("format") == "password":
                    entry["secret"] = True
                if kind in ("file", "file-list"):
                    entry["multiple"] = kind == "file-list"
                    file_fields.append(entry)
                else:
                    fields.append(entry)

            params = []
            for p in op.get("parameters", []) or []:
                if p.get("in") != "query":
                    continue
                params.append(
                    {
                        "name": p.get("name"),
                        "in": "query",
                        "type": (p.get("schema") or {}).get("type", "string"),
                        "required": bool(p.get("required")),
                        "default": (p.get("schema") or {}).get("default"),
                    }
                )

            x = op.get("x-stirling-io") or {}
            produces = x.get("produces")
            accepts = x.get("accepts")
            tool = {
                "tool": tool_name,
                "operationId": op_id,
                "method": method.upper(),
                "path": path,
                "group": (op.get("tags") or ["Other"])[0],
                "summary": op.get("summary") or op.get("description", "").split("\n")[0] or op_id,
                "description": (op.get("description") or "").strip(),
                "arity": x.get("arity"),
                "accepts": accepts,
                "produces": produces,
                "output_kind": _output_kind(op, op.get("responses")),
                "files": file_fields,
                "fields": fields,
                "query": params,
                "alias": bool(primary),
                "endpoint_key": _endpoint_key(path, op, primary),
            }
            tools.append(tool)

    disabled = _disabled_endpoints()
    for t in tools:
        t["disabled"] = bool(t["endpoint_key"] in disabled or t["tool"] in disabled)
        if t["disabled"] and t["tool"] in DISABLED_HINTS:
            t["disabled_reason"] = DISABLED_HINTS[t["tool"]]
    tools.sort(key=lambda t: (t["group"], t["tool"]))
    return {
        "schema": 2,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source": "/v1/api-docs",
        "version": version,
        "count": len(tools),
        "disabled_endpoints": disabled,
        "tools": tools,
    }


def _fetch_openapi_with_retry(port, timeout=30, attempts=15, delay=2.0):
    """拉取 /v1/api-docs。

    Spring 报告端口就绪后 springdoc 仍可能初始化数秒（实测约 4.5s），期间该端点
    返回 500 或直接断开。这里带退避重试，避免刚 start 就调用工具时误报失败。
    """
    last = None
    for index in range(attempts):
        try:
            return _http_get_json(port, "/v1/api-docs", timeout=timeout)
        except (KitError, OSError, http.client.HTTPException, ValueError) as exc:
            last = exc
            if index + 1 >= attempts:
                break
            time.sleep(delay)
    if isinstance(last, KitError):
        raise KitError(
            f"请求 /v1/api-docs 失败（已重试 {attempts} 次）",
            last.code,
            str(last.hint or last),
        ) from last
    raise KitError(f"请求 /v1/api-docs 失败（已重试 {attempts} 次）：{last}", 1)


def fetch_manifest(port, version, allow_cache=True, refresh=False):
    cached = read_json(ENV.tools_file, None)
    if (
        allow_cache
        and not refresh
        and isinstance(cached, dict)
        and cached.get("schema") == 2
        and cached.get("version")
        and (not version or cached.get("version") == version)
        and cached.get("tools")
    ):
        return cached
    raw = _fetch_openapi_with_retry(port)
    manifest = build_manifest(raw, version or (raw.get("info") or {}).get("version"))
    write_json_atomic(ENV.tools_file, manifest)
    return manifest


def get_manifest(refresh=False, cached_only=False):
    cached = read_json(ENV.tools_file, None)
    valid = (
        isinstance(cached, dict)
        and cached.get("schema") == 2
        and cached.get("tools")
    )
    # list-tools 优先用真实 OpenAPI 生成的缓存：后端未启动时也能立即给出清单
    if valid and not refresh:
        cached = dict(cached)
        cached["from_cache"] = True
        return cached
    if cached_only:
        if valid:
            cached = dict(cached)
            cached["from_cache"] = True
            return cached
        raise KitError("工具缓存不存在", 3, "先运行 pdf list-tools --refresh（会启动后端）")
    port, version = ensure_server()
    manifest = fetch_manifest(port, version, allow_cache=False, refresh=True)
    manifest["from_cache"] = False
    return manifest


def _norm(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _summary_tool():
    return {
        "tool": "summary",
        "operationId": "__summary__",
        "method": "POST",
        "path": "/api/v1/analysis/basic-info",
        "group": "Analysis",
        "summary": "PDF 摘要：基本信息 + 文档属性 + 安全信息 + 页面尺寸",
        "arity": "SISO",
        "accepts": ["PDF"],
        "produces": "JSON",
        "output_kind": "json",
        "files": [{"name": "fileInput", "type": "file", "multiple": False, "required": True}],
        "fields": [],
        "query": [],
        "alias": True,
        "endpoint_key": "summary",
        "disabled": False,
    }


def resolve_tool(manifest, name):
    if (name or "").lower() == "summary":
        return _summary_tool()
    tools = manifest.get("tools", [])
    if not name:
        raise KitError("缺少工具名", 2, "示例：pdf run merge --input a.pdf --input b.pdf --output ab.pdf")
    # 0) 别名表（含非主别名，如 pdf-to-text）
    alias = TOOL_ALIASES.get((name or "").lower())
    if alias and alias.get("op") and alias["op"] != "__summary__":
        for t in tools:
            if t.get("operationId") == alias["op"]:
                return t
    # 1) 别名 / 工具名 / operationId
    for t in tools:
        if t["tool"] == name or t.get("operationId") == name:
            return t
    low = name.lower()
    for t in tools:
        if (t["tool"] or "").lower() == low or (t.get("operationId") or "").lower() == low:
            return t
    # 2) 路径末段，例如 general/merge-pdfs
    clean = name.strip("/").split("/")[-1]
    for t in tools:
        if t["path"].rstrip("/").split("/")[-1] == clean:
            return t
    # 3) 规范化匹配
    n = _norm(name)
    matches = [t for t in tools if _norm(t["tool"]) == n or _norm(t.get("operationId")) == n]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        for t in matches:
            if t.get("alias"):
                return t
    # 4) 模糊建议
    choices = [t["tool"] for t in tools[:400]] + [t.get("operationId", "") for t in tools[:400]]
    sugg = difflib.get_close_matches(name, choices, n=5, cutoff=0.45)
    hint = "可用 pdf list-tools --search <关键词> 查找工具"
    if sugg:
        hint = "你是不是想用：" + "、".join(s for s in sugg if s) + "\n" + hint
    raise KitError(f"未知工具：{name}", 2, hint)


def _is_disabled(manifest, tool, port):
    """端点是否被 Stirling 禁用：优先读取启动日志的禁用清单。"""
    if tool.get("disabled"):
        return True
    disabled = _disabled_endpoints()
    key = tool.get("endpoint_key") or ""
    if key and key in disabled:
        return True
    # 对已知的禁用端点做一次轻量确认（避免日志被轮转后误判）
    return False


# ---------------------------------------------------------------------------
# multipart / HTTP
# ---------------------------------------------------------------------------
class SegmentBody:
    """把内存片段与文件片段串成可 read() 的请求体，避免整包读入内存。"""

    def __init__(self, segments):
        self.segments = segments
        self.length = sum(len(s) if isinstance(s, bytes) else s[1] for s in segments)
        self.index = 0
        self.pos = 0
        self.fh = None

    def __len__(self):
        return self.length

    def _close(self):
        if self.fh:
            with contextlib.suppress(OSError):
                self.fh.close()
        self.fh = None

    def read(self, n=-1):
        if n is None or n < 0:
            n = 1 << 20
        out = bytearray()
        while n > 0 and self.index < len(self.segments):
            seg = self.segments[self.index]
            if isinstance(seg, bytes):
                take = min(n, len(seg) - self.pos)
                out += seg[self.pos : self.pos + take]
                self.pos += take
                n -= take
                if self.pos >= len(seg):
                    self.index += 1
                    self.pos = 0
            else:
                path, size = seg
                if self.fh is None:
                    self.fh = open(path, "rb")
                    if self.pos:
                        self.fh.seek(self.pos)
                take = min(n, size - self.pos)
                data = self.fh.read(take)
                if not data:
                    # 文件在发送过程中变短：按实际长度继续
                    self._close()
                    self.index += 1
                    self.pos = 0
                    continue
                out += data
                self.pos += len(data)
                n -= len(data)
                if self.pos >= size:
                    self._close()
                    self.index += 1
                    self.pos = 0
        return bytes(out)


def _content_type_for(path):
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def _build_multipart(boundary, file_parts, field_parts):
    segments = []
    for part in file_parts:
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{part["name"]}"; filename="{part["filename"]}"\r\n'
            f"Content-Type: {part['content_type']}\r\n\r\n"
        )
        segments.append(head.encode("utf-8"))
        segments.append((part["path"], part["size"]))
        segments.append(b"\r\n")
    for name, value in field_parts:
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
        )
        segments.append(head.encode("utf-8"))
        segments.append(str(value).encode("utf-8"))
        segments.append(b"\r\n")
    segments.append(f"--{boundary}--\r\n".encode("utf-8"))
    return SegmentBody(segments)


def _redact(name, value):
    if re.search(r"password|secret|token|key", name or "", re.I):
        return "***"
    return value


def http_post(port, path, file_parts, field_parts, timeout=300, query=None):
    boundary = "----officekit" + uuid.uuid4().hex
    body = _build_multipart(boundary, file_parts, field_parts)
    url = path
    if query:
        qs = "&".join(
            "%s=%s" % (http_quote(k), http_quote(v)) for k, v in query.items()
        )
        url += ("&" if "?" in url else "?") + qs
    # 同步端点可能要处理几十秒才返回响应头，socket 超时必须等于整个请求预算
    conn = http.client.HTTPConnection("127.0.0.1", int(port), timeout=max(5, timeout))
    deadline = time.time() + timeout
    started = time.time()
    try:
        conn.putrequest("POST", url, skip_accept_encoding=True)
        conn.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
        conn.putheader("Content-Length", str(len(body)))
        conn.putheader("Accept", "*/*")
        conn.putheader("User-Agent", USER_AGENT)
        conn.endheaders()
        while True:
            chunk = body.read(262144)
            if not chunk:
                break
            if time.time() > deadline:
                raise KitError(f"上传超时（>{timeout}s）", 1, "用 --timeout 增大超时")
            conn.send(chunk)
        resp = conn.getresponse()
        remaining = max(1.0, deadline - time.time())
        if conn.sock:
            conn.sock.settimeout(remaining)
        return conn, resp, started
    except Exception:
        conn.close()
        raise


def http_quote(s):
    from urllib.parse import quote

    return quote(str(s), safe="")


def read_response(resp, limit_bytes=64 * 1024 * 1024):
    """返回 (bytes, content_type, disposition, status)。二进制写入临时文件。"""
    ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
    disp = resp.getheader("Content-Disposition") or ""
    is_texty = ctype.startswith("text/") or ctype in (
        "application/json",
        "application/xml",
        "application/problem+json",
    ) or "+json" in ctype
    chunks = []
    total = 0
    while True:
        chunk = resp.read(262144)
        if not chunk:
            break
        total += len(chunk)
        if is_texty and total > limit_bytes:
            raise KitError("响应过大", 1, f"超过 {human_size(limit_bytes)}")
        chunks.append(chunk)
    data = b"".join(chunks)
    return data, ctype, disp, resp.status


def _parse_disposition_filename(disp):
    if not disp:
        return None
    m = re.search(r"filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)", disp)
    if m:
        from urllib.parse import unquote

        return unquote(m.group(1).strip().strip('"'))
    m = re.search(r'filename\s*=\s*"([^"]+)"', disp)
    if m:
        return m.group(1)
    m = re.search(r"filename\s*=\s*([^;]+)", disp)
    return m.group(1).strip() if m else None


def _decode_text(data, ctype):
    enc = "utf-8"
    m = re.search(r"charset=([\w-]+)", ctype or "")
    if m:
        enc = m.group(1)
    for candidate in (enc, "utf-8", "gb18030"):
        try:
            return data.decode(candidate)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", "replace")


def _safe_extract(zip_path, dest_dir, display_dir):
    """解压 ZIP 到目录（只取 basename，防路径穿越），返回实际路径与展示路径。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    results = []
    seen = {}
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = os.path.basename(info.filename.replace("\\", "/"))
            if not name:
                continue
            stem, ext = os.path.splitext(name)
            count = seen.get(name, 0)
            seen[name] = count + 1
            if count:
                name = f"{stem}_{count}{ext}"
            target = dest_dir / name
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
            results.append((target, str(Path(display_dir) / name)))
    return results


def _write_file(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
        with contextlib.suppress(OSError):
            os.chmod(path, 0o644)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _ext_for(ctype, tool):
    mapping = {
        "application/pdf": ".pdf",
        "application/zip": ".zip",
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "text/plain": ".txt",
        "application/json": ".json",
        "application/xml": ".xml",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "application/rtf": ".rtf",
    }
    if ctype in mapping:
        return mapping[ctype]
    kind = (tool or {}).get("output_kind") or "file"
    return {
        "pdf": ".pdf",
        "zip": ".zip",
        "image": ".png",
        "text": ".txt",
        "json": ".json",
        "docx": ".docx",
    }.get(kind, ".bin")


def _looks_zip(path):
    try:
        with open(path, "rb") as f:
            return f.read(4) == b"PK\x03\x04"
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 参数处理
# ---------------------------------------------------------------------------
def parse_pairs(values, what):
    out = []
    for item in values or []:
        if "=" not in item:
            raise KitError(f"{what} 需要 key=value 形式：{item}", 2)
        k, v = item.split("=", 1)
        if not k:
            raise KitError(f"{what} 的 key 不能为空：{item}", 2)
        out.append((k.strip(), v))
    return out


def _coerce(value, field):
    t = (field or {}).get("type", "string")
    text = str(value)
    if t == "boolean":
        low = text.lower()
        if low in ("1", "true", "yes", "on"):
            return "true"
        if low in ("0", "false", "no", "off"):
            return "false"
        return text
    if t in ("integer", "int32", "int64", "number", "float", "double"):
        return text
    return text


def _split_multi(value):
    """数组字段：允许 a+b、a,b 或重复 --option a=x。"""
    parts = []
    for chunk in str(value).split("+"):
        for p in chunk.split(","):
            p = p.strip()
            if p:
                parts.append(p)
    return parts


def _merge_defaults(tool, defaults):
    merged = {}
    schema_defaults = {}
    for f in tool.get("fields", []):
        if "default" in f:
            schema_defaults[f["name"]] = f["default"]
    for k, v in schema_defaults.items():
        merged[k] = v
    for k, v in (defaults or {}).items():
        merged[k] = v
    return merged


def build_request(tool, inputs, options, uploads, queries, output, output_dir):
    file_fields = tool.get("files") or []
    fields_spec = {f["name"]: f for f in tool.get("fields", [])}
    query_spec = {q["name"]: q for q in tool.get("query", [])}

    # ---- 输入文件 ----
    file_parts = []
    upload_map = dict(uploads)
    if inputs:
        primary = None
        for f in file_fields:
            if f["name"] == "fileInput":
                primary = f
                break
        if primary is None:
            for f in file_fields:
                if f["name"] != "watermarkImage":
                    primary = f
                    break
        if primary is None:
            raise KitError(
                f"工具 {tool['tool']} 不接受文件输入（无 multipart 文件字段）",
                2,
                "用 --option 传参数；查看 pdf list-tools 了解该端点",
            )
        if len(inputs) > 1 and not primary.get("multiple"):
            raise KitError(
                f"工具 {tool['tool']} 的字段 {primary['name']} 只接受一个文件",
                2,
                "这个端点一次处理一个文件；多文件请用 merge 或分次调用",
            )
        for path in inputs:
            p = Path(path)
            if not p.is_file():
                raise KitError(f"输入文件不存在：{path}", 2)
            file_parts.append(
                {
                    "name": primary["name"],
                    "path": str(p),
                    "filename": p.name,
                    "content_type": _content_type_for(p),
                    "size": p.stat().st_size,
                }
            )
    for name, path in upload_map.items():
        p = Path(path)
        if not p.is_file():
            raise KitError(f"上传文件不存在：{path}", 2)
        file_parts.append(
            {
                "name": name,
                "path": str(p),
                "filename": p.name,
                "content_type": _content_type_for(p),
                "size": p.stat().st_size,
            }
        )

    # ---- 表单字段 ----
    provided = {}
    for k, v in options:
        if k in query_spec and k not in fields_spec:
            queries.setdefault(k, v)
            continue
        provided[k] = v
    explicit = set(provided)
    defaults = _merge_defaults(tool, TOOL_ALIASES.get(tool["tool"], {}).get("defaults"))
    for k, v in defaults.items():
        if k in fields_spec and k not in provided and v not in (None, ""):
            provided[k] = v

    # 水印类型：用户常只给 watermarkText，自动推断 watermarkType=text
    if tool["tool"] == "watermark" and "watermarkType" not in explicit:
        if "watermarkText" in provided:
            provided["watermarkType"] = "text"
        elif any(p["name"] == "watermarkImage" for p in file_parts):
            provided["watermarkType"] = "image"
    # 含中文的水印需要 alphabet=chinese，否则 Stirling 默认字体没有 CJK 字形
    if (
        tool["tool"] == "watermark"
        and "alphabet" not in explicit
        and provided.get("watermarkType") == "text"
        and re.search(r"[\u4e00-\u9fff]", str(provided.get("watermarkText", "")))
    ):
        provided["alphabet"] = "chinese"

    # 需要文件输入的端点：没给 --input 就提前报错，避免后端 400
    if tool.get("files") and not file_parts and not uploads:
        raise KitError(
            f"工具 {tool['tool']} 需要 --input 文件",
            2,
            "例如：--input 输入.pdf",
        )

    unknown = [k for k in provided if fields_spec and k not in fields_spec]
    if unknown:
        info(f"提示：以下参数不在 OpenAPI 表单定义中，仍按原样发送：{', '.join(unknown)}")

    # 必填校验（文件字段由 --input 处理）
    missing = []
    for f in tool.get("fields", []):
        if f.get("type", "").startswith("file"):
            continue
        if f.get("required") and f["name"] not in provided:
            if f.get("type") == "boolean":
                provided[f["name"]] = "false"
            elif "default" in f:
                provided[f["name"]] = f["default"]
            else:
                missing.append(f["name"])
    if missing:
        raise KitError(
            f"缺少必填参数：{', '.join(missing)}",
            2,
            "用 --option 名称=值 提供，例如 --option %s=...\n可用 pdf list-tools --json 查看字段与枚举"
            % missing[0],
        )

    field_parts = []
    for k, v in provided.items():
        spec = fields_spec.get(k, {})
        if spec.get("type") in ("array", "file-list"):
            for part in _split_multi(v):
                field_parts.append((k, part))
        else:
            field_parts.append((k, _coerce(v, spec)))
    return file_parts, field_parts, queries


# ---------------------------------------------------------------------------
# Ghostscript PDF/A 兜底
# ---------------------------------------------------------------------------
def find_ghostscript():
    env = os.environ.get("OFFICE_KIT_GS")
    candidates = []
    if env:
        candidates.append(env)
    candidates.append(str(ENV.lib / "gs" / "bin" / "gs"))
    candidates.append(str(ENV.lib / "bin" / "gs"))
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    found = shutil.which("gs")
    return found


def gs_pdfa(input_path, output_path, timeout=300):
    gs = find_ghostscript()
    if not gs:
        raise KitError(
            "pdf-to-pdfa 需要 Ghostscript（gs），当前环境未找到",
            3,
            "安装 ghostscript，或设置 OFFICE_KIT_GS=/path/to/gs；"
            "若只是需要归档副本，也可先用 office-kit office convert 生成 PDF（非 PDF/A）",
        )
    icc = ENV.lib / "icc" / "sRGB.icc"
    if not icc.is_file():
        raise KitError(f"缺少 ICC 配置文件：{icc}", 3, "重新安装 modules/pdf/lib/icc/sRGB.icc")
    ps = ENV.cache / "pdf" / "PDFA_def.ps"
    ps.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(
        ps,
        "%%!\n"
        "/ICCProfile (%s) def\n"
        "[/_objdef {icc_PDFA} /type /stream /OBJ pdfmark\n"
        "[{icc_PDFA} << /N 3 >> /PUT pdfmark\n"
        "[{icc_PDFA} ICCProfile (r) file /PUT pdfmark\n"
        "[/_objdef {OutputIntent_PDFA} /type /dict /OBJ pdfmark\n"
        "[{OutputIntent_PDFA} <<\n"
        "  /S /GTS_PDFA1\n"
        "  /DestOutputProfile {icc_PDFA}\n"
        "  /OutputConditionIdentifier (sRGB IEC61966-2.1)\n"
        "  /Info (sRGB IEC61966-2.1)\n"
        ">> /PUT pdfmark\n"
        "[{Catalog} <</OutputIntents [ {OutputIntent_PDFA} ]>> /PUT pdfmark\n"
        % str(icc),
    )
    out_abs = os.path.abspath(str(output_path))
    Path(out_abs).parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        gs,
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dNOOUTERSAVE",
        "-dNOSAFER",
        "-dPDFA=2",
        "-dPDFACompatibilityPolicy=1",
        "-sColorConversionStrategy=RGB",
        "-sDEVICE=pdfwrite",
        f"-sOutputFile={out_abs}",
        str(ps),
        os.path.abspath(str(input_path)),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise KitError(f"Ghostscript 转换超时（>{timeout}s）", 1, "用 --timeout 增大超时")
    if proc.returncode != 0 or not os.path.isfile(out_abs):
        err = (proc.stderr or b"").decode("utf-8", "replace").strip()
        raise KitError(
            f"Ghostscript PDF/A 转换失败（退出码 {proc.returncode}）",
            1,
            err[-800:] or "检查输入 PDF 是否损坏/加密",
        )
    return out_abs


def _has_pdfa_marker(path):
    try:
        with open(path, "rb") as f:
            data = f.read(1024 * 1024)
        return b"pdfaid:part" in data
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 内置 OCR 兜底（系统没有 tesseract 时调用 modules/ocr 的 RapidOCR）
# ---------------------------------------------------------------------------
def _find_tesseract():
    env = os.environ.get("OFFICE_KIT_TESSERACT")
    candidates = []
    if env:
        candidates.append(env)
    candidates.append(str(ENV.lib / "bin" / "tesseract"))
    found = shutil.which("tesseract")
    if found:
        candidates.append(found)
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _find_ocr_bin():
    env = os.environ.get("OFFICE_KIT_OCR")
    candidates = []
    if env:
        candidates.append(env)
    candidates.append(str(ENV.root / "modules" / "ocr" / "bin" / "ocr"))
    for c in candidates:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return None


def _ocr_engine_choice():
    """stirling（tesseract）/ rapidocr（内置 OCR）的选择。"""
    forced = (os.environ.get("OFFICE_KIT_PDF_OCR_ENGINE") or "auto").strip().lower()
    if forced in ("rapid", "rapidocr", "internal", "ocr-module"):
        return "rapidocr"
    if forced in ("stirling", "tess", "tesseract", "system"):
        return "stirling"
    return "stirling" if _find_tesseract() else "rapidocr"


def _has_cjk(text):
    return bool(re.search(r"[\u3400-\u9fff\uf900-\ufaff]", text or ""))


def _ocr_language_string(options):
    values = [v for k, v in options if k == "languages"]
    if not values:
        return "chi_sim+eng"
    parts = []
    for v in values:
        for one in re.split(r"[+,]", str(v)):
            one = one.strip()
            if one and one not in parts:
                parts.append(one)
    return "+".join(parts) or "chi_sim+eng"


def _build_searchable_pdf(src_path, ocr_data, out_path):
    """把 OCR 行文本以不可见文字层叠加到原 PDF 页面上。"""
    try:
        import pymupdf
    except ImportError:
        try:
            import fitz as pymupdf
        except ImportError:
            raise KitError(
                "内置 OCR 兜底需要 PyMuPDF 才能生成可搜索 PDF",
                3,
                "改用 --output 结果.json 或 结果.txt，或先运行 office-kit ocr pdf",
            )
    try:
        src = pymupdf.open(str(src_path))
    except Exception as exc:  # noqa: BLE001
        raise KitError(
            f"无法打开输入 PDF（可能已加密或损坏）：{exc}",
            1,
            "加密文件请先 pdf run decrypt --option password=...",
        )
    dst = pymupdf.open()
    try:
        for page_info in ocr_data.get("pages", []):
            pno = int(page_info.get("page", 0)) - 1
            if pno < 0 or pno >= len(src):
                continue
            spage = src[pno]
            npage = dst.new_page(width=spage.rect.width, height=spage.rect.height)
            npage.show_pdf_page(npage.rect, src, pno)
            iw = float(page_info.get("width") or spage.rect.width) or 1.0
            ih = float(page_info.get("height") or spage.rect.height) or 1.0
            sx = spage.rect.width / iw
            sy = spage.rect.height / ih
            for line in page_info.get("lines", []):
                text = (line.get("text") or "").strip()
                box = line.get("box")
                if not text or not box or len(box) != 4:
                    continue
                try:
                    rect = pymupdf.Rect(
                        float(box[0]) * sx,
                        float(box[1]) * sy,
                        float(box[2]) * sx,
                        float(box[3]) * sy,
                    )
                except (TypeError, ValueError):
                    continue
                if rect.is_empty or rect.width < 1 or rect.height < 1:
                    continue
                fs = max(3.0, min(48.0, rect.height * 0.85))
                fontname = "china-s" if _has_cjk(text) else "helv"
                try:
                    # 用基线定位（textbox 对紧贴文字的框容易判定“放不下”）
                    npage.insert_text(
                        (rect.x0, rect.y1 - fs * 0.15),
                        text,
                        fontsize=fs,
                        fontname=fontname,
                        color=(0, 0, 0),
                        render_mode=3,
                    )
                except Exception:
                    # 单行失败不影响整页
                    continue
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        dst.save(str(out_path), garbage=3, deflate=True)
        with contextlib.suppress(OSError):
            os.chmod(out_path, 0o644)
    finally:
        dst.close()
        src.close()
    return str(out_path)


def run_ocr_fallback(input_path, output, output_dir, languages, timeout, json_mode):
    """用 modules/ocr（RapidOCR）识别 PDF，返回 (outputs, details)。"""
    ocr_bin = _find_ocr_bin()
    if not ocr_bin:
        raise KitError(
            "系统没有 tesseract，且找不到内置 OCR 模块",
            3,
            "安装 tesseract，或确认 modules/ocr/bin/ocr 存在；也可设置 OFFICE_KIT_OCR",
        )
    cmd = [
        ocr_bin,
        "pdf",
        "--input",
        os.path.abspath(str(input_path)),
        "--lang",
        languages,
        "--json",
        "--quiet",
    ]
    forced = (os.environ.get("OFFICE_KIT_PDF_OCR_ENGINE") or "").lower() in (
        "rapid",
        "rapidocr",
        "internal",
        "ocr-module",
    )
    info(
        ("已按 OFFICE_KIT_PDF_OCR_ENGINE 强制使用内置 RapidOCR…" if forced
         else "未检测到 tesseract，改用内置 RapidOCR（modules/ocr）识别…")
    )
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=max(30, timeout),
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise KitError(
            f"内置 OCR 超时（>{timeout}s）",
            1,
            "扫描件较大时用 --timeout 600",
        )
    if proc.returncode != 0:
        raise KitError(
            f"内置 OCR 失败（退出码 {proc.returncode}）",
            1,
            (proc.stderr or proc.stdout or "")[-800:],
        )
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise KitError("内置 OCR 返回的不是 JSON", 1, (proc.stdout or "")[:500])

    pages = data.get("pages", [])
    full_text = "\n".join((p.get("text") or "") for p in pages).strip()
    details = {
        "engine": "rapidocr",
        "fallback": True,
        "ocr_binary": ocr_bin,
        "languages": languages,
        "page_count": len(pages),
        "text": full_text,
        "data": data,
    }
    outputs = []
    target = output
    if not target and output_dir:
        target = str(Path(output_dir) / (Path(input_path).stem + "-ocr.pdf"))
    if target:
        low = str(target).lower()
        if low.endswith(".json"):
            _write_file(
                (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                target,
            )
            outputs = [str(target)]
        elif low.endswith(".txt") or low.endswith(".md"):
            _write_file((full_text + "\n").encode("utf-8"), target)
            outputs = [str(target)]
        else:
            if Path(target).is_dir():
                target = str(Path(target) / (Path(input_path).stem + "-ocr.pdf"))
            _build_searchable_pdf(input_path, data, target)
            outputs = [str(target)]
    details["outputs"] = outputs
    return outputs, details


def cmd_ocr_fallback(args, inputs, options):
    """OCR 内置兜底命令：完全不需要启动 Stirling 后端。"""
    if len(inputs) != 1:
        raise KitError("ocr 需要且仅需要一个 --input", 2)
    languages = _ocr_language_string(options)
    with file_lock(ENV.cache / "pdf" / "activity.lock", exclusive=False, blocking=True):
        _touch_last_use()
        started = time.time()
        outputs, details = run_ocr_fallback(
            inputs[0],
            args.output,
            args.output_dir,
            languages,
            args.timeout,
            args.json,
        )
        details.update(
            {
                "endpoint": "/api/v1/misc/ocr-pdf",
                "operation_id": "processPdfWithOCR",
                "engine": "rapidocr",
                "fallback": True,
                "duration_ms": round((time.time() - started) * 1000),
            }
        )
        _touch_last_use()
        if args.json:
            emit_json({"ok": True, "tool": "ocr", "outputs": outputs, "details": details})
        else:
            if outputs:
                for o in outputs:
                    print(o)
            elif details.get("text"):
                sys.stdout.write(details["text"] + "\n")
        return 0


# ---------------------------------------------------------------------------
# 输出落盘
# ---------------------------------------------------------------------------
def save_result(tool, data, ctype, disp, output, output_dir, status):
    """把响应写入目标位置，返回 (outputs, details)。"""
    outputs = []
    filename = _parse_disposition_filename(disp)
    default_ext = _ext_for(ctype, tool)

    # ZIP（可能是 octet-stream）
    tmp_zip = None
    is_zip = ctype == "application/zip"
    if data and data[:4] == b"PK\x03\x04":
        is_zip = True
    if is_zip:
        fd, tmp_zip = tempfile.mkstemp(prefix="pdf-out-", suffix=".zip", dir=str(ENV.cache / "pdf"))
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if output and str(output).lower().endswith(".zip"):
            _write_file(data, output)
            os.unlink(tmp_zip)
            return [str(output)], {}
        if output_dir:
            dest = Path(output_dir)
            pairs = _safe_extract(tmp_zip, dest, dest)
        elif output:
            outp = str(output).rstrip("/")
            if os.path.isdir(outp):
                pairs = _safe_extract(tmp_zip, outp, outp)
            else:
                stem = os.path.splitext(outp)[0]
                dest = Path(stem + "_files")
                info(f"响应是包含多个文件的 ZIP，已解压到：{dest}")
                pairs = _safe_extract(tmp_zip, dest, dest)
        else:
            raise KitError(
                "该工具返回多个文件（ZIP），需要 --output-dir 或 --output xxx.zip",
                2,
                "例如：--output-dir 输出目录",
            )
        outputs = [display for _, display in pairs]
        os.unlink(tmp_zip)
        if len(outputs) == 1 and output and not os.path.isdir(str(output)) and not output_dir:
            # 只有一项且用户给了具体文件：移动过去
            src = Path(pairs[0][0])
            _write_file(src.read_bytes(), output)
            with contextlib.suppress(OSError):
                src.unlink()
            with contextlib.suppress(OSError):
                src.parent.rmdir()
            outputs = [str(output)]
        return outputs, {"extracted": len(outputs)}

    # 文本类
    if ctype.startswith("text/") or ctype in ("application/json", "application/xml"):
        text = _decode_text(data, ctype)
        if output:
            _write_file(data, output)
            outputs = [str(output)]
            if output_dir:
                info("提示：--output 与 --output-dir 同时给出时使用 --output")
        elif output_dir:
            name = filename or f"{tool['tool']}{default_ext}"
            target = Path(output_dir) / name
            _write_file(data, target)
            outputs = [str(target)]
        details = {}
        if ctype == "application/json" or "+json" in ctype:
            with contextlib.suppress(ValueError):
                details["data"] = json.loads(text)
        if ctype.startswith("text/"):
            details["text"] = text
        return outputs, details

    # 单个二进制
    if not output and not output_dir:
        raise KitError(
            "该工具返回文件，需要 --output 或 --output-dir",
            2,
            "例如：--output 结果.pdf",
        )
    if output:
        target = Path(str(output))
        if target.is_dir():
            name = filename or f"{tool['tool']}{default_ext}"
            target = target / name
        _write_file(data, target)
        return [str(target)], {}

    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    name = filename or f"{tool['tool']}{default_ext}"
    target = dest / name
    _write_file(data, target)
    return [str(target)], {}


# ---------------------------------------------------------------------------
# 命令实现
# ---------------------------------------------------------------------------
def cmd_start(args):
    idle_seconds = args.idle_timeout
    xmx = args.xmx
    if getattr(args, "low_memory", False):
        if idle_seconds is None:
            idle_seconds = 300
        if xmx is None:
            xmx = "768m"
        os.environ.setdefault(
            "OFFICE_KIT_PDF_JAVA_OPTS",
            "-Xms64m -XX:+UseSerialGC -XX:MaxMetaspaceSize=256m",
        )
        info("低内存模式：Xmx=768m，空闲 5 分钟自动退出")
    if idle_seconds is None:
        idle_seconds = 600
    if xmx is None:
        xmx = "1536m"
    args.idle_timeout = idle_seconds
    port, version, reused = start_server(
        port=args.port,
        timeout=args.timeout,
        idle_seconds=idle_seconds,
        xmx=xmx,
        force=args.force,
    )
    st = status_info()
    if args.json:
        emit_json(
            {
                "ok": True,
                "running": True,
                "reused": reused,
                "port": port,
                "version": version,
                "pid": st.get("pid"),
                "idle_timeout": args.idle_timeout,
            }
        )
    else:
        print(
            f"Stirling-PDF {'已在运行' if reused else '已启动'}：端口 {port}，版本 {version}，pid {st.get('pid')}"
        )


def cmd_stop(args):
    stopped = stop_server()
    if args.json:
        emit_json({"ok": True, "stopped": stopped, "running": False})
    else:
        print("已停止 Stirling-PDF" if stopped else "Stirling-PDF 未在运行")


def cmd_status(args):
    st = status_info()
    if args.json:
        emit_json(st)
        return
    if st["running"]:
        print(
            "运行中：端口 %s，pid %s，版本 %s%s"
            % (
                st["port"],
                st["pid"],
                st["version"],
                "" if st["ready"] else "（尚未就绪）",
            )
        )
        print("日志：%s" % st["log"])
    else:
        print("未运行")
        print("启动：office-kit pdf start（或直接 pdf run，会自动启动）")


def cmd_list_tools(args):
    manifest = get_manifest(refresh=args.refresh, cached_only=args.cached)
    tools = manifest.get("tools", [])
    if args.group:
        g = args.group.lower()
        tools = [t for t in tools if g in (t.get("group") or "").lower()]
    if args.search:
        q = args.search.lower()
        tools = [
            t
            for t in tools
            if q in (t.get("tool") or "").lower()
            or q in (t.get("operationId") or "").lower()
            or q in (t.get("summary") or "").lower()
            or q in (t.get("path") or "").lower()
        ]
    if args.json:
        emit_json(
            {
                "ok": True,
                "source": manifest.get("source"),
                "from_cache": bool(manifest.get("from_cache")),
                "version": manifest.get("version"),
                "count": len(tools),
                "total": manifest.get("count"),
                "generated_at": manifest.get("generated_at"),
                "disabled_endpoints": manifest.get("disabled_endpoints", []),
                "tools": tools,
            }
        )
        return
    origin = "本地缓存" if manifest.get("from_cache") else "实时 OpenAPI"
    print(
        f"Stirling-PDF {manifest.get('version')} 工具清单"
        f"（{len(tools)}/{manifest.get('count')} 个端点，{origin}）"
    )
    print("过滤器：--group / --search；完整字段：--json\n")
    last_group = None
    for t in tools:
        g = t.get("group") or "Other"
        if g != last_group:
            print(f"[{g}]")
            last_group = g
        flag = " (disabled)" if t.get("disabled") else ""
        print(f"  {t['tool']:<32} {t['method']:<4} {t['path']}{flag}")
        summary = (t.get("summary") or "").strip().replace("\n", " ")
        if summary:
            print(f"      {summary[:110]}")


def _http_error_message(data, ctype):
    text = _decode_text(data, ctype)
    msg = None
    with contextlib.suppress(ValueError):
        obj = json.loads(text)
        if isinstance(obj, dict):
            msg = (
                obj.get("message")
                or obj.get("error")
                or obj.get("detail")
                or obj.get("title")
            )
            if isinstance(msg, dict):
                msg = json.dumps(msg, ensure_ascii=False)
    if not msg:
        msg = text.strip()[:800]
    return msg, text


def _redirect_hint(msg):
    if "disabled" in (msg or "").lower():
        return "该端点被 Stirling 禁用（通常因缺少外部程序，如 soffice/qpdf）"
    if "password" in (msg or "").lower():
        return "PDF 受密码保护：用 pdf run decrypt --option password=... 先解密"
    if "tesseract" in (msg or "").lower() or "language" in (msg or "").lower():
        return "OCR 语言包/引擎问题：检查 runtime/stirling/tessdata 与系统 tesseract"
    return None


def _run_summary(port, tool, inputs, timeout):
    if len(inputs) != 1:
        raise KitError("summary 只接受一个 --input", 2)
    results = {}
    for name, call in (
        ("basic", ("getBasicInfo", "/api/v1/analysis/basic-info")),
        ("properties", ("getDocumentProperties", "/api/v1/analysis/document-properties")),
        ("security", ("getSecurityInfo", "/api/v1/analysis/security-info")),
        ("dimensions", ("getPageDimensions", "/api/v1/analysis/page-dimensions")),
    ):
        try:
            path = call[1]
            fp = [
                {
                    "name": "fileInput",
                    "path": str(Path(inputs[0]).resolve()),
                    "filename": Path(inputs[0]).name,
                    "content_type": _content_type_for(inputs[0]),
                    "size": os.path.getsize(inputs[0]),
                }
            ]
            conn, resp, started = http_post(port, path, fp, [], timeout=timeout)
            try:
                data, ctype, disp, status = read_response(resp)
            finally:
                conn.close()
            if status >= 400:
                msg, _ = _http_error_message(data, ctype)
                results[name] = {"error": msg, "http_status": status}
            else:
                results[name] = json.loads(_decode_text(data, ctype))
        except (KitError, OSError, ValueError, http.client.HTTPException) as exc:
            results[name] = {"error": str(exc)}
    return results


def cmd_run(args):
    inputs = args.input or []
    options = parse_pairs(args.option, "--option")
    uploads = parse_pairs(args.upload, "--upload")
    queries = dict(parse_pairs(args.query, "--query"))

    # 先做本地校验，避免无谓启动后端
    for p in inputs:
        if not Path(p).is_file():
            raise KitError(f"输入文件不存在：{p}", 2)
    for _, p in uploads:
        if not Path(p).is_file():
            raise KitError(f"上传文件不存在：{p}", 2)

    # 系统没有 tesseract 时，OCR 走内置 RapidOCR，无需启动后端
    if (
        (args.tool or "").lower() in ("ocr", "ocr-pdf", "processpdfwithocr")
        and _ocr_engine_choice() == "rapidocr"
    ):
        return cmd_ocr_fallback(args, inputs, options)

    port, version = ensure_server()
    manifest = fetch_manifest(port, version)
    tool = resolve_tool(manifest, args.tool)

    # 已解析到 OCR 端点但引擎选择为内置（例如通过 operationId 调用）
    if tool["tool"] == "ocr" and _ocr_engine_choice() == "rapidocr":
        return cmd_ocr_fallback(args, inputs, options)

    duration = 0.0
    with file_lock(ENV.cache / "pdf" / "activity.lock", exclusive=False, blocking=True):
        _touch_last_use()
        if tool["tool"] == "summary" or tool.get("operationId") == "__summary__":
            started = time.time()
            data = _run_summary(port, tool, inputs, args.timeout)
            duration = (time.time() - started) * 1000
            outputs = []
            if args.output:
                _write_file(
                    (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
                    args.output,
                )
                outputs = [str(args.output)]
            if args.json:
                emit_json(
                    {
                        "ok": True,
                        "tool": "summary",
                        "outputs": outputs,
                        "details": {
                            "endpoint": "/api/v1/analysis/*",
                            "duration_ms": round(duration),
                            "data": data,
                        },
                    }
                )
            else:
                if outputs:
                    print(outputs[0])
                else:
                    emit_json(data)
            _touch_last_use()
            return

        # 已知被禁用且能本地兜底的端点
        disabled = _is_disabled(manifest, tool, port)
        if disabled and tool["tool"] == "pdf-to-pdfa":
            info("Stirling 端点 pdf-to-pdfa 因缺少 LibreOffice 被禁用，改用 Ghostscript 兜底")
            if len(inputs) != 1:
                raise KitError("pdf-to-pdfa 需要且仅需要一个 --input", 2)
            if not args.output:
                raise KitError("pdf-to-pdfa 需要 --output", 2)
            started = time.time()
            out = gs_pdfa(inputs[0], args.output, timeout=args.timeout)
            duration = (time.time() - started) * 1000
            outputs = [str(args.output)]
            if args.json:
                emit_json(
                    {
                        "ok": True,
                        "tool": "pdf-to-pdfa",
                        "outputs": outputs,
                        "details": {
                            "endpoint": tool["path"],
                            "engine": "ghostscript",
                            "pdfa": "PDF/A-2b",
                            "has_pdfa_marker": _has_pdfa_marker(out),
                            "bytes": os.path.getsize(out),
                            "duration_ms": round(duration),
                            "note": "Stirling 端点被禁用（缺 LibreOffice），已用 Ghostscript 转换",
                        },
                    }
                )
            else:
                print(out)
            _touch_last_use()
            return
        if disabled and tool["tool"] in DISABLED_HINTS:
            raise KitError(
                "端点 %s 被 Stirling 禁用：%s"
                % (tool["tool"], DISABLED_HINTS.get(tool["tool"], "缺少外部依赖")),
                3,
                "安装对应外部程序后重启后端（pdf stop && pdf start）",
            )

        file_parts, field_parts, queries = build_request(
            tool, inputs, options, uploads, queries, args.output, args.output_dir
        )
        started = time.time()
        try:
            conn, resp, _ = http_post(
                port, tool["path"], file_parts, field_parts, timeout=args.timeout, query=queries
            )
            try:
                data, ctype, disp, status = read_response(resp)
            finally:
                conn.close()
        except socket.timeout:
            raise KitError(
                f"请求超时（>{args.timeout}s）",
                1,
                "处理较大的扫描件时用 --timeout 600 增大超时",
            )
        except (OSError, http.client.HTTPException) as exc:
            raise KitError(
                f"与后端通信失败：{exc}",
                1,
                "用 pdf status 检查后端；pdf logs 查看日志；必要时 pdf stop && pdf start",
            )
        duration = (time.time() - started) * 1000

        if status >= 400:
            msg, raw = _http_error_message(data, ctype)
            hint = _redirect_hint(msg)
            if status == 403 and tool["tool"] == "pdf-to-pdfa":
                # 兜底（日志没有记录禁用清单时）
                if len(inputs) == 1 and args.output:
                    info("Stirling 返回 403（端点禁用），改用 Ghostscript 兜底")
                    out = gs_pdfa(inputs[0], args.output, timeout=args.timeout)
                    if args.json:
                        emit_json(
                            {
                                "ok": True,
                                "tool": "pdf-to-pdfa",
                                "outputs": [out],
                                "details": {
                                    "engine": "ghostscript",
                                    "http_status": 403,
                                    "duration_ms": round(duration),
                                },
                            }
                        )
                    else:
                        print(out)
                    return
            if args.json:
                emit_json(
                    {
                        "ok": False,
                        "tool": tool["tool"],
                        "outputs": [],
                        "error": {
                            "http_status": status,
                            "message": msg,
                            "endpoint": tool["path"],
                            "hint": hint,
                        },
                    }
                )
            info(f"pdf: {tool['tool']} 失败（HTTP {status}）：{msg}")
            if hint:
                info(f"提示：{hint}")
            err = KitError("", 1)
            err.json_emitted = True
            raise err

        outputs, extra = save_result(
            tool, data, ctype, disp, args.output, args.output_dir, status
        )
        details = {
            "endpoint": tool["path"],
            "operation_id": tool.get("operationId"),
            "http_status": status,
            "content_type": ctype,
            "bytes": len(data),
            "duration_ms": round(duration),
        }
        if file_parts:
            details["uploaded"] = [
                {"field": p["name"], "filename": p["filename"], "bytes": p["size"]}
                for p in file_parts
            ]
        if field_parts:
            grouped = {}
            for k, v in field_parts:
                grouped.setdefault(k, []).append(_redact(k, v))
            details["fields"] = {
                k: (vals[0] if len(vals) == 1 else vals) for k, vals in grouped.items()
            }
        details.update(extra)
        _touch_last_use()

        if args.json:
            emit_json(
                {
                    "ok": True,
                    "tool": tool["tool"],
                    "outputs": outputs,
                    "details": details,
                }
            )
        else:
            if outputs:
                for o in outputs:
                    print(o)
            elif "text" in details:
                sys.stdout.write(details["text"])
                if not details["text"].endswith("\n"):
                    sys.stdout.write("\n")
            elif "data" in details:
                emit_json(details["data"])
            elif "extracted" not in details:
                info("请求成功（无文件输出）")


def cmd_logs(args):
    path = ENV.console_log
    text = tail_file(path, args.lines)
    if args.json:
        emit_json({"ok": True, "path": str(path), "lines": args.lines, "content": text})
    else:
        print(text)


def cmd_version(args):
    st = status_info()
    if args.json:
        emit_json(
            {
                "ok": True,
                "pdf": VERSION,
                "stirling": st.get("version"),
                "running": st.get("running"),
                "ready": st.get("ready"),
                "port": st.get("port"),
            }
        )
    else:
        print(f"office-kit pdf {VERSION}（Stirling-PDF {st.get('version') or '未运行'}）")


def cmd_watchdog(args):
    idle = max(60, int(args.idle))
    interval = max(20, min(120, idle // 4 or 20))
    while True:
        time.sleep(interval)
        st = _read_state()
        if not st:
            return 0
        pid = st.get("pid")
        if not _is_server_process(pid, st.get("port")):
            return 0
        try:
            last = Path(ENV.last_use_file).stat().st_mtime
        except OSError:
            last = time.time()
        if time.time() - last < idle:
            continue
        # 有正在进行的请求则不退出
        try:
            with file_lock(ENV.cache / "pdf" / "activity.lock", exclusive=True, blocking=False):
                pass
        except OSError:
            continue
        try:
            stop_server(quiet=True)
        except Exception:
            pass
        return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
HELP = """office-kit pdf — 离线 PDF 工具箱（Stirling-PDF 后端）

用法:
  office-kit pdf start [--port N] [--timeout 秒] [--idle-timeout 秒] [--low-memory] [--json]
  office-kit pdf stop [--json]
  office-kit pdf status [--json]
  office-kit pdf list-tools [--json] [--search 关键词] [--group 组] [--refresh]
  office-kit pdf run <工具> --input 文件... --output 输出 [--option k=v ...] [--json]
  office-kit pdf logs [--lines N] [--json]

常用工具（完整清单用 list-tools）:
  merge         合并 PDF/图片               pdf-to-img   PDF 转图片
  split         按页码拆分                  img-to-pdf   图片转 PDF
  rotate        旋转页面                    compress     压缩
  encrypt       添加密码                    decrypt      移除密码
  watermark     水印                        ocr          OCR（chi_sim/eng）
  extract-text  抽文本                      pdf-to-pdfa  转 PDF/A
  info/summary  文档信息/摘要

示例:
  office-kit pdf start
  office-kit pdf run merge --input a.pdf --input b.pdf --output 合并.pdf
  office-kit pdf run split --input 报告.pdf --option pageNumbers=all --output-dir 拆分
  office-kit pdf run rotate --input a.pdf --option angle=90 --output 旋转.pdf
  office-kit pdf run extract-text --input a.pdf --output a.txt --json
  office-kit pdf run pdf-to-img --input a.pdf --option dpi=150 --output-dir 图片
  office-kit pdf run img-to-pdf --input 1.png --input 2.png --output 图片.pdf
  office-kit pdf run compress --input a.pdf --option optimizeLevel=7 --output 小.pdf
  office-kit pdf run encrypt --input a.pdf --option password=secret --output 加密.pdf
  office-kit pdf run decrypt --input 加密.pdf --option password=secret --output 解密.pdf
  office-kit pdf run watermark --input a.pdf --option watermarkText=机密 --output 水印.pdf
  office-kit pdf run ocr --input 扫描件.pdf --option languages=chi_sim+eng --output OCR.pdf
  office-kit pdf run pdf-to-pdfa --input a.pdf --output a-pdfa.pdf
  office-kit pdf run info --input a.pdf --json
  office-kit pdf list-tools --search convert

说明:
  * 后端按需后台启动，首次约 60-100 秒（含配置生成与 JVM 预热）；端口写入 $OFFICE_KIT_DATA/pdf/port。
  * run 会自动启动后端；空闲 10 分钟自动退出（start --idle-timeout 调整，0 关闭）。
  * 内存紧张的机器：start --low-memory（Xmx=768m），或 OFFICE_KIT_PDF_ONESHOT=1 让每次 run 后立即退出。
  * 所有处理都在本机完成，不联网。
  * 成功时打印输出文件路径；--json 输出 {ok,tool,outputs,details}。
"""


def build_parser():
    p = argparse.ArgumentParser(
        prog="pdf",
        description="office-kit pdf — 离线 PDF 工具箱（Stirling-PDF）",
        add_help=True,
    )
    p.add_argument("--version", action="store_true", help="显示版本")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("start", help="启动后端（已运行则复用）")
    sp.add_argument("--port", type=int, default=None, help="指定端口；默认从 8091 起探测空闲端口")
    sp.add_argument("--timeout", type=int, default=180, help="就绪等待秒数（默认 180，首次启动可能 60-100 秒）")
    sp.add_argument(
        "--idle-timeout",
        type=int,
        default=None,
        help="空闲多少秒后自动退出（默认 600；0 表示不自动退出）",
    )
    sp.add_argument("--xmx", default=None, help="JVM 最大堆（默认 1536m，--low-memory 时 768m）")
    sp.add_argument(
        "--low-memory",
        action="store_true",
        help="低内存预设：Xmx=768m、空闲 300 秒退出、SerialGC（适合 8GB 以下机器）",
    )
    sp.add_argument("--force", action="store_true", help="先停止已有实例再启动")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="停止后端")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("status", help="查看运行状态")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("list-tools", help="从 OpenAPI 生成可用工具清单")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--search", default=None, help="按工具名/operationId/说明过滤")
    sp.add_argument("--group", default=None, help="按分组过滤，如 Convert/General/Security")
    sp.add_argument("--refresh", action="store_true", help="强制重新抓取 OpenAPI")
    sp.add_argument("--cached", action="store_true", help="只读本地缓存，不启动后端")
    sp.set_defaults(func=cmd_list_tools)

    sp = sub.add_parser("run", help="调用一个 Stirling 端点")
    sp.add_argument("tool", help="工具名/别名/operationId，如 merge、pdf-to-img")
    sp.add_argument("--input", action="append", default=[], help="输入文件（可重复）")
    sp.add_argument("--output", default=None, help="输出文件或目录")
    sp.add_argument("--output-dir", default=None, help="多文件输出的目录")
    sp.add_argument("--option", action="append", default=[], help="表单参数 k=v（可重复）")
    sp.add_argument("--upload", action="append", default=[], help="附加文件字段 字段名=文件路径")
    sp.add_argument("--query", action="append", default=[], help="查询参数 k=v")
    sp.add_argument("--timeout", type=int, default=300, help="请求超时秒数（默认 300）")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("logs", help="查看后端最近日志")
    sp.add_argument("--lines", type=int, default=60)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_logs)

    sp = sub.add_parser("version", help="显示版本")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_version)

    sp = sub.add_parser("_watchdog", help=argparse.SUPPRESS)
    sp.add_argument("--idle", type=int, default=1800)
    sp.set_defaults(func=cmd_watchdog)
    return p


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(HELP)
        return 0
    if argv[0] in ("-V", "--version"):
        print(f"office-kit pdf {VERSION}")
        return 0
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False) and not getattr(args, "command", None):
        print(f"office-kit pdf {VERSION}")
        return 0
    if not getattr(args, "func", None):
        print(HELP)
        return 0
    try:
        ENV.ensure()
        rc = args.func(args)
        if (
            rc in (0, None)
            and getattr(args, "command", None) == "run"
            and os.environ.get("OFFICE_KIT_PDF_ONESHOT", "").lower() in ("1", "true", "yes", "on")
        ):
            if stop_server(quiet=True):
                info("OFFICE_KIT_PDF_ONESHOT=1：已停止 Stirling 后端，释放内存")
        return int(rc or 0)
    except KitError as exc:
        if exc.message:
            info(f"pdf: {exc.message}")
        if exc.hint:
            info(f"提示：{exc.hint}")
        if getattr(args, "json", False) and not getattr(exc, "json_emitted", False):
            emit_json(
                {
                    "ok": False,
                    "tool": getattr(args, "tool", None),
                    "outputs": [],
                    "error": {"message": exc.message, "hint": exc.hint},
                }
            )
        return exc.code
    except KeyboardInterrupt:
        info("已中断")
        return 130
    except BrokenPipeError:
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI 顶层兜底
        if os.environ.get("OFFICE_KIT_PDF_DEBUG"):
            import traceback

            traceback.print_exc()
        info(f"pdf: 内部错误：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
