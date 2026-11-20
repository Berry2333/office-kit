"""OCR 引擎层：RapidOCR（ONNX，默认）与系统 tesseract（可选后备）。

设计约束（AGENTS-CONTRACT）：
  * 运行期绝不联网：RapidOCR 的模型必须来自随包 wheel 或
    modules/ocr/lib/models/（固化的兜底模型）；
  * 目标机不假定有 tesseract：缺失时只影响可选后备引擎；
  * 引擎不可用时抛 DependencyError（退出码 3）并给出可执行的修复命令。

两个引擎统一返回：lines = [{"text": str, "box": [x1,y1,x2,y2], "score": float}]，
坐标是“识别用图”的像素坐标，由调用方映射回基准图。
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile

from ocr_util import DependencyError, OcrError, UsageError, cleanup, log, temp_dir

DEFAULT_LANG = "chi_sim+eng"
DEFAULT_ENGINE = "rapid"

MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

# 常见语言别名 -> tesseract 语言码
_LANG_ALIASES = {
    "zh": "chi_sim",
    "zh_cn": "chi_sim",
    "zhcn": "chi_sim",
    "chinese": "chi_sim",
    "chs": "chi_sim",
    "chi": "chi_sim",
    "chi_sim": "chi_sim",
    "zh_tw": "chi_tra",
    "cht": "chi_tra",
    "traditional": "chi_tra",
    "chi_tra": "chi_tra",
    "en": "eng",
    "english": "eng",
    "eng": "eng",
    "ja": "japan",
    "jp": "japan",
    "japan": "japan",
    "japanese": "japan",
    "ko": "korean",
    "korean": "korean",
    "ru": "rus",
    "russian": "rus",
    "fr": "fra",
    "french": "fra",
    "de": "deu",
    "german": "deu",
    "es": "spa",
    "spanish": "spa",
    "osd": "osd",
}

# 默认 RapidOCR 中文模型能覆盖的语言（ch_PP-OCRv4 字典含简体/繁体/英文/常见符号）
_RAPID_LANGS = ("chi_sim", "chi_tra", "eng")

_CJK_RE = re.compile(
    r"[\u2e80-\u303f\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f\uff00-\uffef]"
)


def normalize_langs(spec):
    """把 --lang 解析为 tesseract 风格语言码列表（去重保序）。"""
    if not spec:
        return ["chi_sim", "eng"]
    tokens = [t for t in re.split(r"[+,;\s]+", str(spec).strip()) if t]
    result = []
    for token in tokens:
        code = _LANG_ALIASES.get(token.lower(), token.lower())
        if code not in result:
            result.append(code)
    return result or ["chi_sim", "eng"]


def rapid_supports(langs):
    return all(code in _RAPID_LANGS for code in langs)


def _temp_png(image):
    fd, path = tempfile.mkstemp(suffix=".png", dir=temp_dir())
    os.close(fd)
    image.save(path, format="PNG")
    return path


def _clean_box(box):
    x1, y1, x2, y2 = box
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return [x1, y1, x2, y2]


# ---------------------------------------------------------------------------
# RapidOCR
# ---------------------------------------------------------------------------


def _bundled_models():
    """modules/ocr/lib/models/ 中固化的兜底模型（存在才用）。

    PP-OCRv4 的识别模型把字表写在 ONNX metadata 里，故 keys 可选。
    """
    if not os.path.isdir(MODELS_DIR):
        return None
    found = {}
    for key, names in (
        ("det", ("ch_PP-OCRv4_det_infer.onnx", "ch_PP-OCRv3_det_infer.onnx")),
        ("rec", ("rec_ch_PP-OCRv4_infer.onnx", "ch_PP-OCRv4_rec_infer.onnx")),
        ("cls", ("ch_ppocr_mobile_v2.0_cls_infer.onnx",)),
        ("keys", ("ppocr_keys_v1.txt", "dict_chinese.txt")),
    ):
        for name in names:
            path = os.path.join(MODELS_DIR, name)
            if os.path.isfile(path):
                found[key] = path
                break
    if all(k in found for k in ("det", "rec", "cls")):
        return found
    return None


class RapidEngine:
    """RapidOCR（onnxruntime）引擎，中英混排默认引擎。

    rapidocr_onnxruntime 的模型随 wheel 放在
    site-packages/rapidocr_onnxruntime/models/，运行期不会联网下载；
    若目标环境缺模型，可用 modules/ocr/lib/models/ 里固化的 ONNX 显式指定。
    """

    name = "rapid"
    label = "RapidOCR(ONNX)"

    def __init__(self, langs=None, use_cls=True):
        self.langs = list(langs or ["chi_sim", "eng"])
        self.use_cls = use_cls
        self._engine = None
        self._model_source = None

    # -- 懒加载 ---------------------------------------------------------
    def ensure(self):
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise DependencyError(
                f"RapidOCR 不可用：未安装 rapidocr_onnxruntime（{exc}）",
                hint='"$OFFICE_KIT_PY" -m pip install --no-cache-dir rapidocr_onnxruntime',
            ) from exc

        models = _bundled_models()
        errors = []
        # 先按 wheel 自带模型初始化；失败再尝试显式指到固化的兜底模型。
        candidates = [None]
        if models:
            candidates.append(models)
        for candidate in candidates:
            kwargs = {}
            if candidate:
                kwargs = {
                    "det_model_path": candidate["det"],
                    "rec_model_path": candidate["rec"],
                    "cls_model_path": candidate["cls"],
                }
                if candidate.get("keys"):
                    kwargs["rec_keys_path"] = candidate["keys"]
            try:
                # 引擎初始化会打印日志，统一引导到 stderr，避免污染 --json
                with contextlib.redirect_stdout(sys.stderr):
                    engine = RapidOCR(**kwargs)
                self._engine = engine
                self._model_source = os.path.dirname(candidate["det"]) if candidate else "wheel"
                return engine
            except Exception as exc:  # noqa: BLE001 - 逐个候选降级
                errors.append(
                    f"{'固化的 lib/models' if candidate else 'wheel 内置模型'}：{exc}"
                )
                continue

        raise DependencyError(
            "RapidOCR 初始化失败（模型缺失或 onnxruntime 不可用）：" + "；".join(errors),
            hint=(
                "确认已安装 onnxruntime；或把 PP-OCR ONNX 模型（det/rec/cls）放到 "
                f"{MODELS_DIR}/ 后重试"
            ),
        )

    @property
    def model_source(self):
        return self._model_source

    # -- 识别 -----------------------------------------------------------
    def run(self, image):
        """image: PIL.Image（RapidOCR 的 LoadImage 会把 PIL 图按 RGB->BGR 正确处理）。"""
        engine = self.ensure()
        try:
            with contextlib.redirect_stdout(sys.stderr):
                result, _elapse = engine(
                    image, use_det=True, use_cls=self.use_cls, use_rec=True
                )
        except Exception as exc:
            raise OcrError(f"RapidOCR 识别失败：{exc}") from exc

        lines = []
        for item in result or []:
            if not item or len(item) < 3:
                continue
            box, text, score = item[0], item[1], item[2]
            text = (text or "").strip()
            if not text:
                continue
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
            lines.append(
                {
                    "text": text,
                    "box": _clean_box([min(xs), min(ys), max(xs), max(ys)]),
                    "score": float(score),
                }
            )
        return lines

    def detect_180(self, image):
        """用 RapidOCR 的 cls 模型判断整体是否倒置（只能判 0/180）。"""
        engine = self.ensure()
        try:
            import numpy as np

            array = np.asarray(image.convert("RGB"))[:, :, ::-1].copy()  # BGR
            with contextlib.redirect_stdout(sys.stderr):
                result = engine.text_cls(array)
        except Exception as exc:  # noqa: BLE001 - 方向检测失败不致命
            log(f"RapidOCR 方向检测失败，跳过：{exc}")
            return None
        label = None
        if isinstance(result, (tuple, list)):
            # v1.4.x: (img_list, cls_res, elapse)，其中 cls_res = [[label, score], ...]
            if len(result) >= 2 and isinstance(result[1], (list, tuple)) and result[1]:
                first = result[1][0]
                label = first[0] if isinstance(first, (list, tuple)) else first
            else:
                label = result[0]
        else:
            label = result
        if isinstance(label, int):
            label = str(label)
        if isinstance(label, str) and label.strip() == "180":
            return 180
        return None


# ---------------------------------------------------------------------------
# tesseract（可选后备）
# ---------------------------------------------------------------------------


def _tess_exe():
    exe = os.environ.get("OCR_TESSERACT") or shutil.which("tesseract")
    if not exe or not os.path.isfile(exe):
        return None
    return exe


def _tessdata_dirs():
    """可能可用的 tessdata 目录（含随包的 runtime/stirling/tessdata）。"""
    runtime = os.environ.get("OFFICE_KIT_RUNTIME")
    if not runtime:
        runtime = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "runtime")
        )
    stirling = os.environ.get("OFFICE_KIT_STIRLING") or os.path.join(runtime, "stirling")
    candidates = [
        os.environ.get("TESSDATA_PREFIX"),
        os.path.join(os.environ.get("TESSDATA_PREFIX") or "", "tessdata"),
        "/usr/share/tesseract-ocr/5/tessdata",
        "/usr/share/tesseract-ocr/4.00/tessdata",
        "/usr/share/tessdata",
        "/usr/local/share/tessdata",
        os.path.join(stirling, "tessdata"),
    ]
    ordered = []
    for path in candidates:
        if path and path not in ordered and os.path.isdir(path):
            ordered.append(path)
    return ordered


def _langs_in_dir(path):
    try:
        names = os.listdir(path)
    except OSError:
        return []
    return sorted(
        name[: -len(".traineddata")]
        for name in names
        if name.endswith(".traineddata") and os.path.isfile(os.path.join(path, name))
    )


def _system_langs(exe):
    """tesseract 默认 tessdata 下的语言（不带 --tessdata-dir 时的真实行为）。"""
    try:
        proc = subprocess.run(
            [exe, "--list-langs"], capture_output=True, text=True, timeout=20
        )
    except Exception:  # noqa: BLE001
        return []
    out = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    langs = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.endswith(":") or line.lower().startswith("list of"):
            continue
        if line.startswith("[") or " " in line:
            continue
        langs.append(line)
    return langs


def tesseract_info():
    """返回系统 tesseract 的可用性、版本、语言与 tessdata 目录。"""
    exe = _tess_exe()
    if not exe:
        return {
            "available": False,
            "version": None,
            "languages": [],
            "system_languages": [],
            "tessdata_dir": None,
            "tessdata_dirs": [],
            "error": "未找到 tesseract 可执行文件",
        }
    version = None
    try:
        proc = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=20)
        match = re.search(r"tesseract\s+([0-9][0-9.]*)", (proc.stdout or "") + (proc.stderr or ""))
        if match:
            version = match.group(1)
    except Exception:  # noqa: BLE001
        pass
    system_languages = _system_langs(exe)
    dirs = []
    union = set(system_languages)
    for path in _tessdata_dirs():
        langs = _langs_in_dir(path)
        dirs.append({"path": path, "languages": langs})
        union.update(langs)
    # 默认 tessdata 就够用时不传 --tessdata-dir；否则指向覆盖最多的目录
    tessdata_dir = None
    if not {"chi_sim", "eng"}.issubset(set(system_languages)):
        best = None
        best_score = 0
        for entry in dirs:
            score = len({"chi_sim", "eng"} & set(entry["languages"]))
            if score > best_score:
                best, best_score = entry["path"], score
        tessdata_dir = best
    return {
        "available": True,
        "version": version,
        "languages": sorted(union),
        "system_languages": list(system_languages),
        "tessdata_dir": tessdata_dir,
        "tessdata_dirs": dirs,
        "error": None,
    }


class TesseractEngine:
    """系统 tesseract 引擎，通过 TSV 输出取词框与置信度。"""

    name = "tess"
    label = "tesseract"

    def __init__(self, langs=None):
        self.langs = list(langs or ["chi_sim", "eng"])
        self._info = None

    @property
    def info(self):
        if self._info is None:
            self._info = tesseract_info()
        return self._info

    def _resolve(self):
        info = self.info
        if not info["available"]:
            raise DependencyError(
                "tesseract 未安装，无法使用 --engine tess",
                hint="安装 tesseract-ocr 与中文包（如 tesseract-ocr-chi-sim），或改用 --engine rapid",
            )
        system_langs = set(info.get("system_languages") or [])
        chosen = [code for code in self.langs if code in system_langs]
        tessdata_dir = None
        if len(chosen) < len(self.langs):
            # 默认 tessdata 不够用：尝试随包 / 系统其它 tessdata 目录
            best_dir = None
            best_codes = chosen
            for entry in info.get("tessdata_dirs") or []:
                codes = [code for code in self.langs if code in set(entry["languages"])]
                if len(codes) > len(best_codes):
                    best_dir, best_codes = entry["path"], codes
            if best_dir:
                chosen = best_codes
                tessdata_dir = best_dir
        if not chosen:
            available = info.get("languages") or []
            raise DependencyError(
                "tesseract 缺少所需语言包：需要 %s，当前可用 %s"
                % ("+".join(self.langs), "+".join(available) if available else "无"),
                hint=(
                    "安装对应语言包（Debian/Ubuntu: apt install tesseract-ocr-chi-sim），"
                    "或用 --engine rapid 走内置中英模型"
                ),
            )
        missing = [code for code in self.langs if code not in chosen]
        if missing:
            log(f"tesseract 缺少 {'+'.join(missing)}，本次使用 {'+'.join(chosen)} 识别")
        return info, chosen, tessdata_dir

    def run(self, image):
        info, langs, tessdata_dir = self._resolve()
        exe = _tess_exe()
        temp_path = _temp_png(image)
        try:
            command = [
                exe,
                temp_path,
                "stdout",
                "-l",
                "+".join(langs),
                "--psm",
                "3",
            ]
            if tessdata_dir:
                command.extend(["--tessdata-dir", tessdata_dir])
            command.append("tsv")
            try:
                proc = subprocess.run(
                    command, capture_output=True, text=True, timeout=600
                )
            except subprocess.TimeoutExpired as exc:
                raise OcrError("tesseract 识别超时（>10 分钟）") from exc
            if proc.returncode != 0:
                detail = (proc.stderr or "").strip().splitlines()
                raise OcrError(
                    "tesseract 识别失败："
                    + (detail[-1] if detail else f"退出码 {proc.returncode}")
                )
            return parse_tesseract_tsv(proc.stdout)
        finally:
            cleanup(temp_path)


def _join_words(words):
    """中英混排拼接：CJK 相邻不加空格，其余加空格。"""
    text = ""
    for word in words:
        if not word:
            continue
        if not text:
            text = word
            continue
        if _CJK_RE.search(text[-1]) or _CJK_RE.search(word[0]):
            text += word
        else:
            text += " " + word
    return text


def parse_tesseract_tsv(tsv):
    """解析 tesseract TSV，按行聚合为 {text, box, score} 列表。"""
    rows = (tsv or "").splitlines()
    if not rows:
        return []
    header = rows[0].split("\t")
    index = {name: i for i, name in enumerate(header)}
    required = ("level", "page_num", "block_num", "par_num", "line_num", "text", "conf")
    if any(name not in index for name in required):
        raise OcrError("tesseract TSV 输出格式异常（缺少字段）")

    lines = []
    order = {}
    for row in rows[1:]:
        cols = row.split("\t")
        if len(cols) < len(header):
            continue
        if cols[index["level"]] != "5":
            continue
        word = cols[index["text"]].strip()
        if not word:
            continue
        try:
            conf = float(cols[index["conf"]])
        except ValueError:
            continue
        if conf < 0:
            continue
        key = (
            cols[index["page_num"]],
            cols[index["block_num"]],
            cols[index["par_num"]],
            cols[index["line_num"]],
        )
        try:
            left = float(cols[index["left"]])
            top = float(cols[index["top"]])
            width = float(cols[index["width"]])
            height = float(cols[index["height"]])
        except (KeyError, ValueError):
            continue
        if key not in order:
            order[key] = {"words": [], "confs": [], "box": [left, top, left + width, top + height]}
            lines.append(order[key])
        entry = order[key]
        entry["words"].append(word)
        entry["confs"].append(conf)
        entry["box"][0] = min(entry["box"][0], left)
        entry["box"][1] = min(entry["box"][1], top)
        entry["box"][2] = max(entry["box"][2], left + width)
        entry["box"][3] = max(entry["box"][3], top + height)

    result = []
    for key in [k for k in order]:
        entry = order[key]
        text = _join_words(entry["words"]).strip()
        if not text:
            continue
        result.append(
            {
                "text": text,
                "box": _clean_box(entry["box"]),
                "score": round(sum(entry["confs"]) / len(entry["confs"]) / 100.0, 4),
            }
        )
    return result


# ---------------------------------------------------------------------------
# 引擎选择
# ---------------------------------------------------------------------------


def _rapid_available():
    try:
        import rapidocr_onnxruntime  # noqa: F401
    except Exception:  # noqa: BLE001
        return False, "未安装 rapidocr_onnxruntime"
    return True, None


def detect_engines():
    """探测两个引擎的可用性（不加载模型，快）。"""
    rapid_ok, rapid_error = _rapid_available()
    rapid_version = None
    if rapid_ok:
        try:
            from importlib.metadata import version

            rapid_version = version("rapidocr_onnxruntime")
        except Exception:  # noqa: BLE001
            try:
                import rapidocr_onnxruntime as module

                rapid_version = getattr(module, "__version__", None)
            except Exception:  # noqa: BLE001
                pass
    rapid_models = None
    if rapid_ok:
        try:
            import rapidocr_onnxruntime as module

            candidate = os.path.join(os.path.dirname(module.__file__), "models")
            if os.path.isdir(candidate):
                rapid_models = candidate
        except Exception:  # noqa: BLE001
            pass
        if rapid_models is None and _bundled_models():
            rapid_models = MODELS_DIR
    engines = {
        "rapid": {
            "available": rapid_ok,
            "version": rapid_version,
            "languages": list(_RAPID_LANGS) if rapid_ok else [],
            "model_dir": rapid_models,
            "error": rapid_error,
        },
        "tess": tesseract_info(),
    }
    return engines


def make_engine(requested, langs, prefer_rapid=True):
    """根据 --engine 与语言选择引擎实例。"""
    engines = detect_engines()
    requested = (requested or "auto").lower()
    if requested not in ("auto", "rapid", "tess"):
        raise UsageError(f"--engine 只支持 auto|rapid|tess，收到 {requested!r}")

    rapid = engines["rapid"]
    tess = engines["tess"]

    if requested == "rapid":
        if not rapid["available"]:
            raise DependencyError(
                f"RapidOCR 不可用：{rapid['error']}",
                hint='"$OFFICE_KIT_PY" -m pip install --no-cache-dir rapidocr_onnxruntime onnxruntime',
            )
        if not rapid_supports(langs):
            raise DependencyError(
                f"RapidOCR 内置模型只支持 chi_sim/chi_tra/eng，不支持 {'+'.join(langs)}",
                hint=(
                    "改用 --engine tess（需系统 tesseract 语言包），"
                    f"或把对应语言的 PP-OCR 模型放到 {MODELS_DIR}/ 并扩展 ocr_engine.py"
                ),
            )
        return RapidEngine(langs)

    if requested == "tess":
        return TesseractEngine(langs)

    # auto
    if prefer_rapid and rapid["available"] and rapid_supports(langs):
        return RapidEngine(langs)
    if tess["available"]:
        return TesseractEngine(langs)
    if rapid["available"]:
        log(f"RapidOCR 不支持 {'+'.join(langs)}，降级为内置中英模型识别")
        return RapidEngine(langs)
    raise DependencyError(
        f"没有可用的 OCR 引擎（RapidOCR: {rapid['error']}；tesseract: {tess['error']}）",
        hint=(
            '"$OFFICE_KIT_PY" -m pip install --no-cache-dir rapidocr_onnxruntime onnxruntime '
            "，或安装系统 tesseract-ocr"
        ),
    )
