"""ocr 模块通用工具：退出码、异常、日志、JSON / 文本落盘。

退出码约定（与 AGENTS-CONTRACT §2.2 一致）：
  0  成功
  1  运行时错误
  2  参数 / 用法错误
  3  缺少依赖（消息里带可执行的修复提示）
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

EXIT_OK = 0
EXIT_RUNTIME = 1
EXIT_USAGE = 2
EXIT_DEP = 3

PROG = "ocr"

# 与引擎无关的公共常量（放这里，CLI 不 import PIL/fitz 也能用）
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff")
PDF_EXTS = (".pdf",)
SUPPORTED_EXTS = IMAGE_EXTS + PDF_EXTS
MAX_SIDE_DEFAULT = 4000
DEFAULT_DPI = 200


class OcrError(Exception):
    """带退出码的业务异常。"""

    def __init__(self, message, code=EXIT_RUNTIME, hint=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.hint = hint


class UsageError(OcrError):
    def __init__(self, message, hint=None):
        super().__init__(message, EXIT_USAGE, hint)


class DependencyError(OcrError):
    def __init__(self, message, hint=None):
        super().__init__(message, EXIT_DEP, hint)


def log(message):
    """诊断信息一律写 stderr，stdout 只留结果。"""
    sys.stderr.write(f"[ocr] {message}\n")
    sys.stderr.flush()


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def write_text(path, text):
    parent = os.path.dirname(os.path.abspath(path))
    try:
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except OSError as exc:
        raise OcrError(f"无法写入文件（{path}）：{exc}") from exc


def write_json(path, obj):
    write_text(path, dumps(obj) + "\n")


def print_json(obj):
    sys.stdout.write(dumps(obj) + "\n")
    sys.stdout.flush()


def temp_dir():
    """临时文件放缓存目录（$OFFICE_KIT_CACHE/ocr-tmp），不落到用户好奇的路径。"""
    base = os.environ.get("OFFICE_KIT_CACHE") or os.path.join(
        tempfile.gettempdir(), "office-kit-cache"
    )
    path = os.path.join(base, "ocr-tmp")
    os.makedirs(path, exist_ok=True)
    return path


def cleanup(path):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
