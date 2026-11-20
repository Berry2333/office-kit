#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""office-kit asr —— 离线语音识别 / 听写 / 语音输入（SenseVoiceSmall + llama.cpp）。

只用 Python 标准库；音频归一化与录音交给系统 ffmpeg / arecord。
入口：modules/asr/bin/asr（由 bin/office-kit 调用）。

子命令：
  file     任意音频文件 -> 文本 / SRT / JSON
  mic      录 N 秒 -> 文本
  listen   连续听写，一行一句（VAD 切句）
  input    语音输入：识别 -> 剪贴板 -> 尝试自动粘贴
  devices  列出 ALSA 采集设备
  models   报告引擎 / 模型 / 校验值 / 可用工具
"""

from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import math
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import wave
from collections import deque
from pathlib import Path

VERSION = "1.0.0"
ENGINE_NAME = "sensevoice-small-q8"
RATE = 16000
FRAME_MS = 30
FRAME_SAMPLES = RATE * FRAME_MS // 1000          # 480 samples / 30 ms
FRAME_BYTES = FRAME_SAMPLES * 2                  # 960 bytes
CHUNK_MS = 100
CHUNK_BYTES = RATE * CHUNK_MS // 1000 * 2        # 3200 bytes / 100 ms
PREROLL_FRAMES = 10                              # 300 ms 预卷，避免吞掉句首
MIN_VOICED_SEC = 0.20                            # 少于 200 ms 的“语音”丢弃
TAIL_SEC = 0.24                                  # 句尾保留 240 ms
MAX_SEGMENT_SEC = 15.0                           # 单句上限，超长强制切分
DEFAULT_VAD = 0.02
DEFAULT_SILENCE = 0.6
DEFAULT_MIC_SECONDS = 5.0
DEFAULT_INPUT_SECONDS = 6.0
MAX_LISTEN_QUEUE = 32


# ---------------------------------------------------------------------------
# 路径与运行时
# ---------------------------------------------------------------------------
def _kit_root() -> Path:
    env = os.environ.get("OFFICE_KIT_ROOT", "")
    if env and (Path(env) / "modules").is_dir():
        return Path(env)
    # lib/asr_cli.py -> lib -> asr -> modules -> 仓库根
    return Path(__file__).resolve().parents[3]


ROOT = _kit_root()
RUNTIME = Path(os.environ.get("OFFICE_KIT_RUNTIME") or (ROOT / "runtime"))
MODELS = Path(os.environ.get("OFFICE_KIT_MODELS") or (RUNTIME / "models"))
if os.environ.get("OFFICE_KIT_CACHE"):
    CACHE = Path(os.environ["OFFICE_KIT_CACHE"]).expanduser()
else:
    _xdg_cache = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    CACHE = Path(_xdg_cache).expanduser() / "office-kit" / "cache"
if not CACHE.is_absolute():
    CACHE = (Path.cwd() / CACHE).resolve()
ASR_CACHE = CACHE / "asr"
ENGINE = (MODELS / "llama" / "llama-funasr-sensevoice").expanduser().resolve()
MODEL = (MODELS / "sensevoice" / "sensevoice-small-q8.gguf").expanduser().resolve()

_CACHE_READY = None


def cache_dir() -> Path:
    """可写缓存目录；$OFFICE_KIT_CACHE 不可写时退到系统临时目录。"""
    global _CACHE_READY
    if _CACHE_READY is not None:
        return _CACHE_READY
    try:
        ASR_CACHE.mkdir(parents=True, exist_ok=True)
        _CACHE_READY = ASR_CACHE
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "office-kit-asr"
        fallback.mkdir(parents=True, exist_ok=True)
        _CACHE_READY = fallback
    return _CACHE_READY


class DependencyError(Exception):
    """缺依赖：退出码 3。"""


class RuntimeFailure(Exception):
    """运行时错误：退出码 1。"""


def human_size(n: int) -> str:
    try:
        value = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            if unit == "B":
                return "%d B" % int(value)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "?"


def worker_threads() -> int:
    cpu = os.cpu_count() or 4
    raw = os.environ.get("OFFICE_KIT_ASR_THREADS", "").strip()
    if raw:
        try:
            n = int(raw)
            if n > 0:
                return max(1, min(n, max(1, cpu)))
        except ValueError:
            pass
    return max(1, min(5, cpu - 1))


# ---------------------------------------------------------------------------
# 引擎调用
# ---------------------------------------------------------------------------
def require_engine() -> None:
    if not ENGINE.is_file():
        raise DependencyError(
            "未找到 SenseVoice 识别引擎：%s\n"
            "修复：确认 runtime/models/llama/llama-funasr-sensevoice 已随 office-kit 安装；"
            "运行 `office-kit asr models` 查看检查结果。" % ENGINE
        )
    if not os.access(str(ENGINE), os.X_OK):
        raise DependencyError(
            "识别引擎没有执行权限：%s\n修复：chmod +x %s" % (ENGINE, ENGINE)
        )
    if not MODEL.is_file():
        raise DependencyError(
            "未找到 SenseVoice 模型：%s\n"
            "修复：确认 runtime/models/sensevoice/sensevoice-small-q8.gguf 已安装（约 242 MiB）。"
            % MODEL
        )


def _kill_proc_group(proc: subprocess.Popen, sig: int = signal.SIGTERM) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (OSError, ProcessLookupError):
        try:
            proc.terminate()
        except OSError:
            pass


def run_engine(wav_path: Path, srt: bool = False, keep_tags: bool = False,
               duration: float = 0.0) -> str:
    """调用一次 llama-funasr-sensevoice，返回原始 stdout 文本。"""
    require_engine()
    wav_abs = Path(wav_path).expanduser().resolve()
    cmd = [str(ENGINE), "-m", str(MODEL), "-a", str(wav_abs), "--backend", "cpu"]
    if srt:
        cmd.append("--srt")
    if keep_tags:
        cmd.append("--keep-tags")

    env = os.environ.copy()
    # 上游运行程序不提供 -t 参数，线程数通过 SV_THREADS 传给底层运行时。
    env["SV_THREADS"] = str(worker_threads())
    env["OMP_NUM_THREADS"] = str(worker_threads())

    timeout = max(60.0, min(600.0, float(duration or 0) * 8.0 + 40.0))
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(cache_dir()),
        env=env,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_proc_group(proc, signal.SIGKILL)
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        raise RuntimeFailure("语音识别超时（超过 %.0f 秒），音频可能过长或引擎卡住。" % timeout)
    except KeyboardInterrupt:
        _kill_proc_group(proc)
        try:
            proc.communicate(timeout=2)
        except Exception:
            pass
        raise

    stderr_text = (err or b"").decode("utf-8", "replace").strip()
    if proc.returncode != 0:
        tail = stderr_text.splitlines()[-1][:400] if stderr_text else ""
        raise RuntimeFailure(
            "识别引擎失败（退出码 %s）%s"
            % (proc.returncode, ("：" + tail) if tail else "")
        )
    return (out or b"").decode("utf-8", "replace")


_TAG_RE = re.compile(r"<\|[^|<>]*\|>")
_LANG_TAGS = {
    "zh", "en", "yue", "ja", "ko", "fr", "de", "es", "ru", "pt", "it",
    "ar", "th", "vi", "id", "tr", "hi", "ms", "nl", "sv", "pl", "uk",
}


def extract_language(raw: str):
    for tag in re.findall(r"<\|([^|<>]+)\|>", raw):
        key = tag.strip().lower()
        if key in _LANG_TAGS:
            return key
    return None


def clean_text(raw: str) -> str:
    return _TAG_RE.sub("", raw or "").strip()


def language_mismatch_note(requested: str, detected) -> None:
    if not detected or requested not in ("zh", "en"):
        return
    normalized = "zh" if detected == "yue" else detected
    if normalized != requested:
        sys.stderr.write(
            "asr: 提示：SenseVoice 自动检测为 %s，与 --language %s 不一致；"
            "该引擎不支持强制语言。\n" % (detected, requested)
        )
        sys.stderr.flush()


# ---------------------------------------------------------------------------
# 音频 WAV / 归一化
# ---------------------------------------------------------------------------
def wav_info(path: Path):
    try:
        with wave.open(str(path), "rb") as w:
            return {
                "channels": w.getnchannels(),
                "width": w.getsampwidth(),
                "rate": w.getframerate(),
                "frames": w.getnframes(),
                "comp": w.getcomptype(),
            }
    except Exception:
        return None


def is_native_wav(path: Path) -> bool:
    info = wav_info(path)
    return bool(
        info
        and info["channels"] == 1
        and info["width"] == 2
        and info["rate"] == RATE
        and info["comp"] == "NONE"
        and info["frames"] > 0
    )


def wav_duration(path: Path) -> float:
    info = wav_info(path)
    if info and info["rate"] > 0:
        return info["frames"] / float(info["rate"])
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        try:
            p = subprocess.run(
                [ffprobe, "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=nw=1:nk=1", str(path)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            if p.returncode == 0:
                return float(p.stdout.decode("utf-8", "replace").strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return 0.0


def _python_wav_to_native(src: Path, out: Path) -> None:
    """无 ffmpeg 时的后备：用标准库 wave + audioop 把 PCM WAV 转 16k/mono/s16。"""
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import audioop

    with wave.open(str(src), "rb") as reader:
        channels = reader.getnchannels()
        width = reader.getsampwidth()
        rate = reader.getframerate()
        comp = reader.getcomptype()
        if comp != "NONE":
            raise ValueError("压缩 WAV（%s）需要 ffmpeg" % comp)
        if width not in (1, 2, 3, 4):
            raise ValueError("不支持的采样位宽：%d 字节" % width)
        if channels not in (1, 2):
            raise ValueError("不支持的声道数：%d" % channels)
        raw = reader.readframes(reader.getnframes())

    if width != 2:
        raw = audioop.lin2lin(raw, width, 2)
    if channels == 2:
        raw = audioop.tomono(raw, 2, 0.5, 0.5)
    if rate != RATE:
        converted, _state = audioop.ratecv(raw, 2, 1, rate, RATE, None)
        raw = converted

    with wave.open(str(out), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(RATE)
        writer.writeframes(raw)


def normalize_audio(src: Path):
    """把任意音频转成 16 kHz / mono / s16le WAV；返回 (路径, 是否临时文件)。"""
    if is_native_wav(src):
        return src, False

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        info = wav_info(src)
        if (info and info["comp"] == "NONE"
                and info["channels"] in (1, 2)
                and info["width"] in (1, 2, 3, 4)
                and info["frames"] > 0):
            out = cache_dir() / (
                "norm-%d-%s.wav" % (os.getpid(), uuid.uuid4().hex[:12])
            )
            try:
                _python_wav_to_native(src, out)
            except Exception as exc:
                _unlink(out)
                raise DependencyError(
                    "系统中没有 ffmpeg，且无法用 Python 转换该 WAV：%s\n"
                    "修复：安装 ffmpeg，或先把音频转成 16 kHz 单声道 16 位 WAV。"
                    % exc
                )
            if not out.is_file() or out.stat().st_size <= 44:
                _unlink(out)
                raise RuntimeFailure("WAV 转换后为空：%s" % src)
            return out, True
        raise DependencyError(
            "输入音频不是 16 kHz 单声道 16 位 WAV，且系统中没有 ffmpeg。\n"
            "修复：安装 ffmpeg（目标机一般自带）；无 ffmpeg 时仅支持 PCM WAV。"
        )

    out = cache_dir() / ("norm-%d-%s.wav" % (os.getpid(), uuid.uuid4().hex[:12]))
    cmd = [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src), "-vn", "-ac", "1", "-ar", str(RATE),
        "-c:a", "pcm_s16le", "-f", "wav", str(out),
    ]
    try:
        proc = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=600,
        )
    except subprocess.TimeoutExpired:
        _unlink(out)
        raise RuntimeFailure("ffmpeg 转码超时（超过 600 秒）：%s" % src)
    except OSError as exc:
        _unlink(out)
        raise RuntimeFailure("无法启动 ffmpeg：%s" % exc)

    if proc.returncode != 0 or not out.is_file():
        detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
        tail = detail.splitlines()[-1][:400] if detail else ""
        _unlink(out)
        raise RuntimeFailure(
            "音频转码失败（ffmpeg 退出码 %s）%s"
            % (proc.returncode, ("：" + tail) if tail else "")
        )
    if out.stat().st_size <= 44:
        _unlink(out)
        raise RuntimeFailure("音频转码后为空，可能没有音轨：%s" % src)
    return out, True


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def is_digital_silence(path: Path) -> bool:
    """整段都是 0 采样（纯数字静音）时直接返回空文本，避免引擎幻觉。"""
    try:
        with wave.open(str(path), "rb") as w:
            while True:
                block = w.readframes(RATE)
                if not block:
                    return True
                if any(block):
                    return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# SRT
# ---------------------------------------------------------------------------
_TIMING_RE = re.compile(
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*"
    r"(\d+):(\d{2}):(\d{2})[,.](\d{1,3})"
)


def _ts_to_sec(h, m, s, ms) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000.0


def parse_srt(text: str):
    segments = []
    text = (text or "").strip()
    if not text:
        return segments
    for block in re.split(r"\r?\n\s*\r?\n", text):
        lines = [ln for ln in block.replace("\r\n", "\n").split("\n")]
        timing_at = None
        match = None
        for i, line in enumerate(lines):
            match = _TIMING_RE.search(line)
            if match:
                timing_at = i
                break
        if not match or timing_at is None:
            continue
        body = "\n".join(lines[timing_at + 1:]).strip()
        if not body:
            continue
        g = match.groups()
        segments.append({
            "start": round(_ts_to_sec(*g[0:4]), 3),
            "end": round(_ts_to_sec(*g[4:8]), 3),
            "text": body,
        })
    return segments


def fmt_timestamp(seconds: float) -> str:
    ms = int(round(max(0.0, float(seconds)) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return "%02d:%02d:%02d,%03d" % (h, m, s, ms)


def make_srt(text: str, duration: float) -> str:
    body = (text or "").strip()
    return "1\n%s --> %s\n%s\n" % (
        fmt_timestamp(0.0), fmt_timestamp(duration), body
    )


# ---------------------------------------------------------------------------
# VAD（能量 + 过零率）
# ---------------------------------------------------------------------------
def frame_stats(frame: bytes):
    n = len(frame) // 2
    if n <= 0:
        return 0.0, 0.0
    samples = array.array("h")
    samples.frombytes(frame[: n * 2])
    total = 0
    crossings = 0
    prev = samples[0]
    for value in samples:
        total += value * value
        if (value >= 0) != (prev >= 0):
            crossings += 1
        prev = value
    rms = math.sqrt(total / float(n)) / 32768.0
    zcr = crossings / float(max(1, n - 1))
    return rms, zcr


def is_speech_frame(frame: bytes, threshold: float) -> bool:
    rms, zcr = frame_stats(frame)
    # 能量过阈值且过零率处于人声范围；持续噪声通常能量低或过零率高。
    return rms >= threshold and zcr <= 0.35


def wav_max_rms(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            peak = 0.0
            while True:
                block = w.readframes(FRAME_SAMPLES)
                if not block:
                    break
                rms, _ = frame_stats(block)
                if rms > peak:
                    peak = rms
            return peak
    except Exception:
        return 0.0


def pcm_to_wav_bytes(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# 录音
# ---------------------------------------------------------------------------
def normalize_device(device):
    """把用户写的 `1,0` 补成 ALSA 的 `plughw:1,0`。"""
    if not device:
        return None
    device = device.strip()
    if re.fullmatch(r"\d+,\d+", device):
        return "plughw:" + device
    return device


def _record_error_text(proc) -> str:
    try:
        err = proc.stderr.read() if proc.stderr else b""
    except Exception:
        err = b""
    text = (err or b"").decode("utf-8", "replace").strip()
    return text.splitlines()[-1][:300] if text else ""


def record_wav(seconds: float, device=None) -> Path:
    """录 N 秒到临时 WAV；返回路径，调用方负责删除。"""
    seconds = max(0.5, float(seconds))
    dev = normalize_device(device)
    out = cache_dir() / ("mic-%d-%s.wav" % (os.getpid(), uuid.uuid4().hex[:12]))
    arecord = shutil.which("arecord")
    ffmpeg = shutil.which("ffmpeg")
    integer_seconds = int(math.ceil(seconds))

    if arecord:
        cmd = [arecord]
        if dev:
            cmd += ["-D", dev]
        cmd += ["-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1",
                "-d", str(integer_seconds), "-t", "wav", str(out)]
    elif ffmpeg:
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
               "-f", "alsa", "-i", dev or "default", "-t", "%.2f" % seconds,
               "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(out)]
    else:
        raise DependencyError(
            "未找到录音工具 arecord / ffmpeg，无法使用麦克风。\n"
            "修复：安装 alsa-utils 或 ffmpeg；纯文件转写（asr file）不需要它们。"
        )

    try:
        proc = subprocess.run(
            cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=seconds + 30,
        )
    except subprocess.TimeoutExpired:
        _unlink(out)
        raise RuntimeFailure("录音超时（%.1f 秒）。" % (seconds + 30))
    except OSError as exc:
        _unlink(out)
        raise DependencyError("无法启动录音程序 %s：%s" % (cmd[0], exc))

    if proc.returncode != 0 or not out.is_file() or out.stat().st_size <= 44:
        detail = _record_error_text(proc)
        _unlink(out)
        raise DependencyError(
            "录音失败（%s 退出码 %s）%s\n"
            "修复：检查麦克风是否接入、是否被其他程序占用；"
            "用 `office-kit asr devices` 查看设备，用 `--device plughw:<card>,<device>` 指定。"
            % (os.path.basename(cmd[0]), proc.returncode,
               ("：" + detail) if detail else "")
        )
    return out


def open_capture(device=None):
    """打开连续采集：返回 (可 read 的文件对象, Popen 或 None, 描述)。"""
    dev = normalize_device(device)
    arecord = shutil.which("arecord")
    if arecord:
        cmd = [arecord, "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"]
        if dev:
            cmd += ["-D", dev]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
            )
        except OSError as exc:
            raise DependencyError("无法启动 arecord：%s" % exc)
        return proc.stdout, proc, "arecord（%s）" % (dev or "默认设备")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        cmd = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error",
               "-f", "alsa", "-i", dev or "default",
               "-ac", "1", "-ar", str(RATE), "-f", "s16le", "-"]
        try:
            proc = subprocess.Popen(
                cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, start_new_session=True,
            )
        except OSError as exc:
            raise DependencyError("无法启动 ffmpeg ALSA 采集：%s" % exc)
        return proc.stdout, proc, "ffmpeg/alsa（%s）" % (dev or "默认设备")

    raise DependencyError(
        "未找到录音工具 arecord / ffmpeg，无法连续听写。\n"
        "修复：安装 alsa-utils 或 ffmpeg。"
    )


# ---------------------------------------------------------------------------
# 剪贴板 / 自动粘贴
# ---------------------------------------------------------------------------
def _run_tool(cmd, data=None, timeout=5) -> bool:
    try:
        proc = subprocess.run(
            cmd, input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def clipboard_tool_name():
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    has_display = bool(os.environ.get("DISPLAY"))
    if wayland and shutil.which("wl-copy"):
        return "wl-copy"
    if has_display and shutil.which("xclip"):
        return "xclip"
    if has_display and shutil.which("xsel"):
        return "xsel"
    if shutil.which("wl-copy"):
        return "wl-copy"
    return None


def copy_to_clipboard(text: str):
    """写剪贴板；成功返回工具名，否则 None。"""
    wayland = bool(os.environ.get("WAYLAND_DISPLAY")) or \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
    has_display = bool(os.environ.get("DISPLAY"))
    candidates = []
    if wayland and shutil.which("wl-copy"):
        candidates.append(("wl-copy", ["wl-copy"]))
    if has_display and shutil.which("xclip"):
        candidates.append(("xclip", ["xclip", "-selection", "clipboard"]))
    if has_display and shutil.which("xsel"):
        candidates.append(("xsel", ["xsel", "--clipboard", "--input"]))
    if shutil.which("wl-copy"):
        candidates.append(("wl-copy", ["wl-copy"]))
    for name, cmd in candidates:
        if _run_tool(cmd, data=text.encode("utf-8"), timeout=8):
            return name
    return None


def paste_tool_name():
    if shutil.which("ydotool"):
        return "ydotool"
    if shutil.which("xdotool") and os.environ.get("DISPLAY"):
        return "xdotool"
    return None


def try_paste() -> bool:
    """尝试模拟 Ctrl+V；成功返回 True。"""
    candidates = []
    if shutil.which("ydotool"):
        candidates.append(
            ("ydotool", ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"])
        )
    if shutil.which("xdotool") and os.environ.get("DISPLAY"):
        candidates.append(
            ("xdotool", ["xdotool", "key", "--clearmodifiers", "ctrl+v"])
        )
    for _name, cmd in candidates:
        if _run_tool(cmd, timeout=10):
            return True
    return False


# ---------------------------------------------------------------------------
# 设备枚举
# ---------------------------------------------------------------------------
_ARECORD_CARD_RE = re.compile(
    r"^card\s+(\d+):\s+(\S+)\s+\[([^\]]*)\],\s+device\s+(\d+):\s*(.*)$"
)


def _device_name(rest: str, fallback: str) -> str:
    rest = (rest or "").strip()
    match = re.match(r"^(.*?)\s*\[([^\]]*)\]\s*$", rest)
    if match:
        desc = match.group(1).strip()
        bracket = match.group(2).strip()
        return desc or bracket or fallback
    return rest or fallback


def detect_devices():
    devices = []
    seen = set()
    arecord = shutil.which("arecord")
    if arecord:
        try:
            proc = subprocess.run(
                [arecord, "-l"], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10,
            )
            output = (proc.stdout or b"").decode("utf-8", "replace")
            for line in output.splitlines():
                match = _ARECORD_CARD_RE.match(line.strip())
                if not match:
                    continue
                card = int(match.group(1))
                device = int(match.group(4))
                key = (card, device)
                if key in seen:
                    continue
                seen.add(key)
                devices.append({
                    "card": card,
                    "device": device,
                    "name": _device_name(match.group(5), match.group(3) or match.group(2)),
                })
        except (OSError, subprocess.TimeoutExpired):
            pass

    if not devices:
        # /proc/asound 后备：没有 arecord 时也能报告采集设备。
        card_names = {}
        try:
            cards_text = Path("/proc/asound/cards").read_text(
                encoding="utf-8", errors="replace"
            )
            for line in cards_text.splitlines():
                match = re.match(r"^\s*(\d+)\s+\[([^\]]*)\]:\s*(\S+)", line)
                if match:
                    card_names[int(match.group(1))] = match.group(2).strip()
        except OSError:
            card_names = {}
        try:
            pcm_text = Path("/proc/asound/pcm").read_text(
                encoding="utf-8", errors="replace"
            )
            for line in pcm_text.splitlines():
                if "capture" not in line:
                    continue
                parts = line.split(":")
                head = parts[0].strip()
                match = re.match(r"^(\d+)-(\d+)$", head)
                if not match:
                    continue
                card = int(match.group(1))
                device = int(match.group(2))
                if (card, device) in seen:
                    continue
                seen.add((card, device))
                name = parts[2].strip() if len(parts) > 2 else ""
                devices.append({
                    "card": card,
                    "device": device,
                    "name": name or card_names.get(card, "card %d" % card),
                })
        except OSError:
            pass
    devices.sort(key=lambda item: (item["card"], item["device"]))
    return devices


# ---------------------------------------------------------------------------
# 校验值
# ---------------------------------------------------------------------------
def _sha256_cache_file() -> Path:
    return cache_dir() / "sha256-cache.json"


def _load_sha_cache():
    try:
        data = json.loads(_sha256_cache_file().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError, UnicodeDecodeError):
        pass
    return {}


def sha256_12(path: Path) -> str:
    try:
        stat = path.stat()
    except OSError:
        return ""
    key = str(path)
    cache = _load_sha_cache()
    entry = cache.get(key)
    if (
        isinstance(entry, dict)
        and entry.get("size") == stat.st_size
        and entry.get("mtime_ns") == stat.st_mtime_ns
        and isinstance(entry.get("sha256"), str)
        and len(entry["sha256"]) >= 12
    ):
        return entry["sha256"][:12]

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError:
        return ""
    value = digest.hexdigest()
    cache[key] = {
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": value,
    }
    try:
        tmp = _sha256_cache_file().with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(str(tmp), str(_sha256_cache_file()))
    except OSError:
        pass
    return value[:12]


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
def emit_json(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def build_file_result(src: Path, duration: float, text: str, segments,
                      elapsed_ms: int, language) -> dict:
    return {
        "input": str(src.resolve()),
        "duration": round(float(duration), 3),
        "duration_ms": int(round(float(duration) * 1000)),
        "text": text,
        "segments": segments,
        "engine": ENGINE_NAME,
        "elapsed_ms": int(elapsed_ms),
        "language": language or "auto",
    }


# ---------------------------------------------------------------------------
# file
# ---------------------------------------------------------------------------
def cmd_file(args) -> int:
    src = Path(args.input).expanduser().resolve()
    if not src.exists():
        raise RuntimeFailure("输入文件不存在：%s" % src)
    if src.is_dir():
        raise RuntimeFailure("--input 需要一个音频文件，而不是目录：%s" % src)

    started = time.monotonic()
    normalized, temp = normalize_audio(src)
    try:
        duration = wav_duration(normalized)
        if duration <= 0:
            raise RuntimeFailure("无法读取音频时长（空文件或损坏）：%s" % src)

        fmt = args.format
        if args.json:
            fmt = "json" if fmt == "text" else fmt

        silent = is_digital_silence(normalized)
        if silent:
            sys.stderr.write("asr: 输入音频为纯静音，未调用识别引擎。\n")
            elapsed = int(round((time.monotonic() - started) * 1000))
            if fmt == "srt":
                result = build_file_result(
                    src, duration, "", [], elapsed,
                    args.language if args.language != "auto" else "auto",
                )
                result["format"] = "srt"
                result["srt"] = ""
                if args.json:
                    emit_json(result)
                return 0
            if fmt == "json":
                emit_json(build_file_result(
                    src, duration, "", [], elapsed, "auto"
                ))
                return 0
            print("")
            return 0

        if fmt == "srt":
            raw = run_engine(normalized, srt=True, duration=duration)
            segments = parse_srt(raw)
            if not segments:
                body = clean_text(raw)
                srt_text = make_srt(body, duration)
                segments = [{
                    "start": 0.0,
                    "end": round(duration, 3),
                    "text": body,
                }]
            else:
                srt_text = raw.strip() + "\n"
            text = " ".join(
                " ".join(seg["text"].split()) for seg in segments
            ).strip()
            elapsed = int(round((time.monotonic() - started) * 1000))
            if args.json:
                result = build_file_result(
                    src, duration, text, segments, elapsed,
                    args.language if args.language != "auto" else "auto",
                )
                result["format"] = "srt"
                result["srt"] = srt_text.rstrip("\n")
                emit_json(result)
            else:
                sys.stdout.write(srt_text)
                sys.stdout.flush()
            return 0

        if fmt == "json":
            raw = run_engine(normalized, keep_tags=True, duration=duration)
            detected = extract_language(raw)
            text = clean_text(raw)
            if args.language != "auto":
                language_mismatch_note(args.language, detected)
            segments = [{
                "start": 0.0,
                "end": round(duration, 3),
                "text": text,
            }]
            elapsed = int(round((time.monotonic() - started) * 1000))
            emit_json(build_file_result(
                src, duration, text, segments, elapsed, detected or "auto"
            ))
            return 0

        # text
        need_tags = args.language != "auto"
        raw = run_engine(normalized, keep_tags=need_tags, duration=duration)
        if need_tags:
            language_mismatch_note(args.language, extract_language(raw))
        text = clean_text(raw)
        print(text)
        return 0
    finally:
        if temp:
            _unlink(normalized)


# ---------------------------------------------------------------------------
# mic
# ---------------------------------------------------------------------------
def _recognize_recorded(path: Path, duration: float, threshold: float):
    """返回 (text, language, silence)。"""
    if wav_max_rms(path) < threshold:
        return "", None, True
    raw = run_engine(path, keep_tags=True, duration=duration)
    return clean_text(raw), extract_language(raw), False


def cmd_mic(args) -> int:
    started = time.monotonic()
    seconds = max(0.5, float(args.seconds))
    sys.stderr.write(
        "asr: 录音 %.1f 秒，请开始说话…（%s）\n"
        % (seconds, normalize_device(args.device) or "默认设备")
    )
    sys.stderr.flush()
    path = record_wav(seconds, args.device)
    try:
        duration = wav_duration(path)
        text, language, silence = _recognize_recorded(
            path, duration, float(args.vad_threshold)
        )
        if silence:
            sys.stderr.write("asr: 未检测到有效语音（静音或麦克风增益过低）。\n")
        elapsed = int(round((time.monotonic() - started) * 1000))
        if args.json or args.format == "json":
            emit_json({
                "device": normalize_device(args.device) or "default",
                "seconds": round(seconds, 2),
                "duration": round(duration, 3),
                "text": text,
                "language": language or "auto",
                "speech": not silence,
                "engine": ENGINE_NAME,
                "elapsed_ms": elapsed,
            })
        else:
            print(text)
        return 0
    finally:
        _unlink(path)


# ---------------------------------------------------------------------------
# listen：连续听写
# ---------------------------------------------------------------------------
def _emit_segment(frames, start_sample, end_sample, voiced, sequence, put) -> None:
    if voiced < int(MIN_VOICED_SEC * RATE):
        return
    if end_sample <= start_sample:
        return
    pcm = b"".join(frames)
    max_bytes = (end_sample - start_sample) * 2
    if len(pcm) > max_bytes:
        pcm = pcm[:max_bytes]
    if len(pcm) < int(MIN_VOICED_SEC * RATE) * 2:
        return
    sequence[0] += 1
    put({
        "type": "segment",
        "index": sequence[0],
        "start": round(start_sample / float(RATE), 3),
        "end": round(end_sample / float(RATE), 3),
        "pcm": pcm,
    })


def _capture_loop(reader, proc, stop_event, out_queue, args) -> None:
    """后台采集线程：固定 100 ms 读取 + 30 ms 帧 VAD，切句后入队。"""
    buffer = b""
    position = 0
    preroll = deque(maxlen=PREROLL_FRAMES)
    in_segment = False
    frames = []
    voiced = 0
    silence = 0
    start_sample = 0
    last_voice_end = 0
    sequence = [0]
    total_read = 0
    threshold = float(args.vad_threshold)
    silence_samples = max(1, int(float(args.silence) * RATE))

    def put(item) -> bool:
        while not stop_event.is_set():
            try:
                out_queue.put(item, timeout=0.2)
                return True
            except queue.Full:
                continue
        return False

    failure = None
    try:
        while not stop_event.is_set():
            chunk = reader.read(CHUNK_BYTES)
            if not chunk:
                break
            total_read += len(chunk)
            buffer += chunk
            while len(buffer) >= FRAME_BYTES and not stop_event.is_set():
                frame = buffer[:FRAME_BYTES]
                buffer = buffer[FRAME_BYTES:]
                speech = is_speech_frame(frame, threshold)

                if not in_segment:
                    preroll.append(frame)
                    if speech:
                        in_segment = True
                        frames = list(preroll)
                        preroll.clear()
                        start_sample = max(
                            0,
                            position + FRAME_SAMPLES
                            - len(frames) * FRAME_SAMPLES,
                        )
                        last_voice_end = position + FRAME_SAMPLES
                        voiced = FRAME_SAMPLES
                        silence = 0
                else:
                    frames.append(frame)
                    if speech:
                        last_voice_end = position + FRAME_SAMPLES
                        silence = 0
                        voiced += FRAME_SAMPLES
                    else:
                        silence += FRAME_SAMPLES

                    close = False
                    end_sample = 0
                    if silence >= silence_samples:
                        end_sample = min(
                            position + FRAME_SAMPLES,
                            last_voice_end + int(TAIL_SEC * RATE),
                        )
                        close = True
                    elif (position + FRAME_SAMPLES - start_sample
                          >= int(MAX_SEGMENT_SEC * RATE)):
                        end_sample = position + FRAME_SAMPLES
                        close = True

                    if close:
                        _emit_segment(
                            frames, start_sample, end_sample, voiced,
                            sequence, put,
                        )
                        in_segment = False
                        frames = []
                        voiced = 0
                        silence = 0
                        preroll.clear()

                position += FRAME_SAMPLES

        if not stop_event.is_set() and in_segment:
            end_sample = min(
                position + len(buffer) // 2,
                last_voice_end + int(TAIL_SEC * RATE),
            )
            _emit_segment(frames, start_sample, end_sample, voiced, sequence, put)
    except Exception as exc:  # 读取失败等
        if not stop_event.is_set():
            failure = str(exc)
    finally:
        if proc is not None:
            try:
                returncode = proc.wait(timeout=3)
            except Exception:
                returncode = None
            if (
                not stop_event.is_set()
                and returncode not in (0, None, -15, -9, -2, 130)
                and total_read == 0
            ):
                detail = _record_error_text(proc)
                if not failure:
                    failure = (
                        "麦克风采集失败（%s 退出码 %s）%s\n"
                        "修复：用 `office-kit asr devices` 查看设备，"
                        "并用 `--device plughw:<card>,<device>` 指定。"
                        % (args.device or "默认设备", returncode,
                           ("：" + detail) if detail else "")
                    )
        if failure and not stop_event.is_set():
            put({"type": "error", "message": failure})
        put({"type": "eof"})


def cmd_listen(args) -> int:
    temp_input = None
    proc = None
    reader = None
    capture_thread = None
    stop_event = threading.Event()
    out_queue: "queue.Queue" = queue.Queue(maxsize=MAX_LISTEN_QUEUE)

    if args.input:
        src = Path(args.input).expanduser().resolve()
        if not src.exists():
            raise RuntimeFailure("输入文件不存在：%s" % src)
        normalized, temp = normalize_audio(src)
        temp_input = normalized if temp else None
        try:
            reader = open(str(normalized), "rb")
        except OSError as exc:
            if temp_input is not None:
                _unlink(temp_input)
            raise RuntimeFailure("无法读取音频：%s" % exc)
        description = "文件 %s" % args.input
    else:
        reader, proc, description = open_capture(args.device)

    capture_thread = threading.Thread(
        target=_capture_loop,
        args=(reader, proc, stop_event, out_queue, args),
        name="asr-capture",
        daemon=True,
    )
    capture_thread.start()

    if args.input:
        sys.stderr.write("asr: 连续听写（离线文件模拟麦克风）…\n")
    else:
        sys.stderr.write(
            "asr: 连续听写中（%s），Ctrl-C 结束…\n" % description
        )
    if args.once:
        sys.stderr.write("asr: --once 只识别一句。\n")
    sys.stderr.flush()

    processed = 0
    try:
        while not stop_event.is_set():
            try:
                item = out_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item.get("type") == "error":
                raise DependencyError(item.get("message") or "麦克风采集失败。")
            if item.get("type") == "eof":
                break
            if item.get("type") != "segment":
                continue

            pcm = item["pcm"]
            seg_start = float(item["start"])
            seg_end = float(item["end"])
            seg_len = max(0.0, seg_end - seg_start)
            index = item["index"]
            segment_path = cache_dir() / (
                "seg-%d-%s.wav" % (os.getpid(), uuid.uuid4().hex[:12])
            )
            try:
                segment_path.write_bytes(pcm_to_wav_bytes(pcm))
                t0 = time.monotonic()
                raw = run_engine(segment_path, keep_tags=True, duration=seg_len)
                text = clean_text(raw)
                language = extract_language(raw)
                elapsed = int(round((time.monotonic() - t0) * 1000))
            finally:
                _unlink(segment_path)

            if not text:
                sys.stderr.write(
                    "asr: 第 %d 句未识别出文本（%.2f–%.2f 秒），已跳过。\n"
                    % (index, seg_start, seg_end)
                )
                sys.stderr.flush()
                continue

            processed += 1
            if args.json:
                emit_json({
                    "index": index,
                    "text": text,
                    "start": seg_start,
                    "end": seg_end,
                    "duration": round(seg_len, 3),
                    "language": language or "auto",
                    "elapsed_ms": elapsed,
                })
            else:
                print(text, flush=True)
            sys.stderr.write(
                "asr: 第 %d 句 %.2f–%.2f 秒，识别 %.0f ms\n"
                % (index, seg_start, seg_end, elapsed)
            )
            sys.stderr.flush()

            if args.once:
                stop_event.set()
                break
    except KeyboardInterrupt:
        stop_event.set()
        sys.stderr.write("\nasr: 已停止听写。\n")
        sys.stderr.flush()
        return 0
    finally:
        stop_event.set()
        if proc is not None:
            _kill_proc_group(proc)
            try:
                proc.wait(timeout=3)
            except Exception:
                _kill_proc_group(proc, signal.SIGKILL)
        try:
            if reader is not None:
                reader.close()
        except Exception:
            pass
        if capture_thread is not None:
            capture_thread.join(timeout=3)
        if temp_input is not None:
            _unlink(temp_input)

    if processed == 0 and not args.input:
        sys.stderr.write("asr: 没有识别到语音；检查麦克风或降低 --vad-threshold。\n")
    return 0


# ---------------------------------------------------------------------------
# input：语音输入
# ---------------------------------------------------------------------------
def cmd_input(args) -> int:
    started = time.monotonic()
    seconds = max(0.5, float(args.seconds))
    owned = False
    path = None
    try:
        if args.input:
            src = Path(args.input).expanduser().resolve()
            if not src.exists():
                raise RuntimeFailure("输入文件不存在：%s" % src)
            path, is_temp = normalize_audio(src)
            owned = is_temp
            duration = wav_duration(path)
            text, language, silence = _recognize_recorded(
                path, duration, float(args.vad_threshold)
            )
        else:
            sys.stderr.write(
                "asr: 语音输入：录音 %.1f 秒，请开始说话…（%s）\n"
                % (seconds, normalize_device(args.device) or "默认设备")
            )
            sys.stderr.flush()
            path = record_wav(seconds, args.device)
            owned = True
            duration = wav_duration(path)
            text, language, silence = _recognize_recorded(
                path, duration, float(args.vad_threshold)
            )

        if silence:
            sys.stderr.write("asr: 未检测到有效语音，没有写入剪贴板。\n")
        clipboard = None
        pasted = False
        if text:
            clipboard = copy_to_clipboard(text)
            if clipboard:
                sys.stderr.write("asr: 已复制到剪贴板（%s）。\n" % clipboard)
                if not args.no_paste:
                    time.sleep(0.15)
                    if paste_tool_name():
                        pasted = try_paste()
                        if pasted:
                            sys.stderr.write("asr: 已尝试模拟 Ctrl+V 粘贴。\n")
                        else:
                            sys.stderr.write(
                                "asr: 自动粘贴失败（ydotool 守护进程/xdotool 不可用），"
                                "请手动 Ctrl+V。\n"
                            )
                    else:
                        sys.stderr.write(
                            "asr: 未找到 ydotool/xdotool，请手动 Ctrl+V 粘贴。\n"
                        )
            else:
                sys.stderr.write(
                    "asr: 未找到可用的剪贴板工具（wl-copy/xclip/xsel）；"
                    "文本已打印，请手动复制粘贴。\n"
                )
        elapsed = int(round((time.monotonic() - started) * 1000))
        if args.json:
            emit_json({
                "text": text,
                "language": language or "auto",
                "device": normalize_device(args.device) or "default",
                "seconds": round(seconds, 2),
                "duration": round(duration, 3),
                "speech": not silence,
                "clipboard": clipboard,
                "pasted": bool(pasted),
                "engine": ENGINE_NAME,
                "elapsed_ms": elapsed,
            })
        else:
            print(text)
        return 0
    finally:
        if owned and path is not None:
            _unlink(path)


# ---------------------------------------------------------------------------
# devices / models
# ---------------------------------------------------------------------------
def cmd_devices(args) -> int:
    devices = detect_devices()
    if args.json:
        emit_json(devices)
        return 0
    if not devices:
        print("未发现 ALSA 采集设备。")
        print("提示：检查麦克风是否接入；纯文件转写（asr file）无需采集设备。")
        return 0
    print("发现 %d 个采集设备：" % len(devices))
    for item in devices:
        print("  card %d, device %d  %s"
              % (item["card"], item["device"], item["name"]))
    print("提示：asr mic --device plughw:<card>,<device> 可指定设备。")
    return 0


def _engine_build_date() -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(ENGINE.stat().st_mtime))
    except OSError:
        return ""


def cmd_models(args) -> int:
    engine_ok = ENGINE.is_file() and os.access(str(ENGINE), os.X_OK)
    model_ok = MODEL.is_file()
    available = engine_ok and model_ok
    engine_size = ENGINE.stat().st_size if ENGINE.is_file() else 0
    model_size = MODEL.stat().st_size if MODEL.is_file() else 0
    result = {
        "engine": ENGINE_NAME,
        "available": available,
        "engine_bin": str(ENGINE),
        "engine_size": engine_size,
        "engine_size_human": human_size(engine_size),
        "engine_version": "llama-funasr-sensevoice（bundled）",
        "engine_build": _engine_build_date(),
        "engine_sha256_12": sha256_12(ENGINE) if engine_ok else "",
        "model": str(MODEL),
        "model_size": model_size,
        "model_size_human": human_size(model_size),
        "model_sha256_12": sha256_12(MODEL) if model_ok else "",
        "threads": worker_threads(),
        "tools": {
            "ffmpeg": shutil.which("ffmpeg"),
            "ffprobe": shutil.which("ffprobe"),
            "arecord": shutil.which("arecord"),
            "clipboard": clipboard_tool_name(),
            "paste": paste_tool_name(),
        },
        "devices": len(detect_devices()),
    }
    if args.json:
        emit_json(result)
        return 0 if available else 3

    print("引擎：%s  %s" % (ENGINE_NAME, "可用" if available else "不可用"))
    print("  程序  ：%s" % (result["engine_bin"] if engine_ok
                            else "缺失（%s）" % ENGINE))
    if engine_ok:
        print("           %s，构建日期 %s，sha256 %s"
              % (result["engine_size_human"], result["engine_build"] or "未知",
                 result["engine_sha256_12"] or "?"))
    print("  模型  ：%s" % (result["model"] if model_ok
                            else "缺失（%s）" % MODEL))
    if model_ok:
        print("           %s，sha256 %s"
              % (result["model_size_human"], result["model_sha256_12"] or "?"))
    print("  线程  ：%d（可用 OFFICE_KIT_ASR_THREADS 覆盖）" % result["threads"])
    tools = result["tools"]
    print("  工具  ：ffmpeg=%s  arecord=%s"
          % (tools["ffmpeg"] or "缺失", tools["arecord"] or "缺失"))
    print("          剪贴板=%s  自动粘贴=%s  采集设备=%d 个"
          % (tools["clipboard"] or "无", tools["paste"] or "无",
             result["devices"]))
    if not available:
        print("")
        print("修复：确认 runtime/models/llama/llama-funasr-sensevoice 与 "
              "runtime/models/sensevoice/sensevoice-small-q8.gguf 均已安装。")
        return 3
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def positive_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("需要一个数字：%r" % value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须大于 0：%r" % value)
    return number


def nonnegative_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError("需要一个数字：%r" % value)
    if number < 0:
        raise argparse.ArgumentTypeError("不能为负数：%r" % value)
    return number


EPILOG = """\
示例:
  asr file --input 会议.wav
  asr file --input 录音.mp3 --format srt
  asr file --input 采访.m4a --format json
  asr listen --json
  asr listen --device plughw:1,0 --silence 0.8
  asr input --seconds 6
  asr devices --json
  asr models --json

说明:
  识别引擎为 SenseVoiceSmall（llama.cpp，CPU，aarch64），完全离线；
  音频先由 ffmpeg 归一化为 16 kHz 单声道 WAV，识别后清理临时文件。
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asr",
        description="office-kit 离线语音识别 / 听写 / 语音输入（SenseVoiceSmall）。",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version",
                        version="asr %s (office-kit)" % VERSION)
    sub = parser.add_subparsers(dest="command", metavar="<子命令>",
                                title="子命令", required=True)

    p_file = sub.add_parser(
        "file", help="转写音频文件",
        description="转写任意音频文件（mp3/m4a/flac/ogg/wav…），先归一化为 16 kHz 单声道。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_file.add_argument("--input", "-i", required=True, metavar="F",
                        help="输入音频文件路径")
    p_file.add_argument("--format", choices=("text", "srt", "json"),
                        default="text", help="输出格式（默认 text）")
    p_file.add_argument("--json", action="store_true",
                        help="等价于 --format json；与 --format srt 同用时输出 JSON 信封")
    p_file.add_argument("--language", choices=("auto", "zh", "en"),
                        default="auto",
                        help="期望语言（SenseVoice 自动检测，仅作校验提示）")
    p_file.set_defaults(func=cmd_file)

    p_mic = sub.add_parser(
        "mic", help="录 N 秒并识别",
        description="从麦克风录制 N 秒，VAD 确认有语音后识别并打印。",
    )
    p_mic.add_argument("--seconds", type=positive_float, default=DEFAULT_MIC_SECONDS,
                       metavar="N", help="录音秒数（默认 %.0f）" % DEFAULT_MIC_SECONDS)
    p_mic.add_argument("--format", choices=("text", "json"), default="text",
                       help="输出格式（默认 text）")
    p_mic.add_argument("--json", action="store_true", help="输出 JSON")
    p_mic.add_argument("--device", metavar="D",
                       help="ALSA 设备，如 plughw:1,0（默认系统默认设备）")
    p_mic.add_argument("--vad-threshold", type=nonnegative_float, default=DEFAULT_VAD,
                       metavar="R", help="语音能量阈值（默认 %.3f）" % DEFAULT_VAD)
    p_mic.set_defaults(func=cmd_mic)

    p_listen = sub.add_parser(
        "listen", help="连续听写，一行一句",
        description="连续采集并按 VAD 切句，逐句识别，一行输出一句；Ctrl-C 优雅退出。",
    )
    p_listen.add_argument("--device", metavar="D",
                          help="ALSA 设备，如 plughw:1,0")
    p_listen.add_argument("--once", action="store_true",
                          help="只识别一句就退出")
    p_listen.add_argument("--json", action="store_true",
                          help="每行输出一个 JSON 对象")
    p_listen.add_argument("--vad-threshold", type=nonnegative_float, default=DEFAULT_VAD,
                          metavar="R", help="语音能量阈值（默认 %.3f）" % DEFAULT_VAD)
    p_listen.add_argument("--silence", type=positive_float, default=DEFAULT_SILENCE,
                          metavar="S",
                          help="句间静音秒数，超过则断句（默认 %.1f）"
                               % DEFAULT_SILENCE)
    p_listen.add_argument("--input", metavar="F",
                          help="（调试/测试）从音频文件模拟麦克风，不占用声卡")
    p_listen.set_defaults(func=cmd_listen)

    p_input = sub.add_parser(
        "input", help="语音输入：识别→剪贴板→尝试粘贴",
        description="录一段话，识别后写入剪贴板，并在 ydotool/xdotool 可用时模拟 Ctrl+V。",
    )
    p_input.add_argument("--device", metavar="D",
                         help="ALSA 设备，如 plughw:1,0")
    p_input.add_argument("--input", metavar="F",
                         help="（调试/测试）用音频文件代替麦克风")
    p_input.add_argument("--seconds", type=positive_float, default=DEFAULT_INPUT_SECONDS,
                         metavar="N",
                         help="录音秒数（默认 %.0f）" % DEFAULT_INPUT_SECONDS)
    p_input.add_argument("--json", action="store_true", help="输出 JSON")
    p_input.add_argument("--no-paste", action="store_true",
                         help="只写剪贴板，不尝试自动粘贴")
    p_input.add_argument("--vad-threshold", type=nonnegative_float, default=DEFAULT_VAD,
                         metavar="R", help="语音能量阈值（默认 %.3f）" % DEFAULT_VAD)
    p_input.set_defaults(func=cmd_input)

    p_devices = sub.add_parser(
        "devices", help="列出 ALSA 采集设备",
        description="列出 ALSA 采集设备（arecord -l，后备 /proc/asound）。",
    )
    p_devices.add_argument("--json", action="store_true", help="输出 JSON 数组")
    p_devices.set_defaults(func=cmd_devices)

    p_models = sub.add_parser(
        "models", help="报告引擎/模型状态",
        description="报告模型路径、大小、引擎构建信息、sha256 前 12 位与可用工具。",
    )
    p_models.add_argument("--json", action="store_true", help="输出 JSON")
    p_models.set_defaults(func=cmd_models)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except DependencyError as exc:
        sys.stderr.write("asr: %s\n" % exc)
        return 3
    except RuntimeFailure as exc:
        sys.stderr.write("asr: %s\n" % exc)
        return 1
    except KeyboardInterrupt:
        sys.stderr.write("\nasr: 已中断。\n")
        return 130


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
