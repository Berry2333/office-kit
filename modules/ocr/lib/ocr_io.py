"""图像 / PDF 读取、预处理与坐标映射。

基准坐标系（base）：
  * 图片：文件解码后的像素坐标（已按 EXIF 方向矫正、以及 --rotate 摆正）；
  * PDF ：按 DPI 渲染后的像素坐标。
所有对外输出的 box 都映射回 base 坐标；识别时若缩放过，内部自动反算。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

from PIL import Image, ImageOps

from ocr_util import (
    DEFAULT_DPI,
    MAX_SIDE_DEFAULT,
    DependencyError,
    OcrError,
    UsageError,
    cleanup,
    log,
    temp_dir,
)


class Transform:
    """识别用图坐标 -> 基准图坐标。

    work = (base - offset) * scale   =>   base = work / scale + offset
    """

    def __init__(self, scale=1.0, ox=0.0, oy=0.0):
        self.scale = float(scale) or 1.0
        self.ox = float(ox)
        self.oy = float(oy)

    def box(self, box):
        x1, y1, x2, y2 = box
        scale = self.scale
        return [
            x1 / scale + self.ox,
            y1 / scale + self.oy,
            x2 / scale + self.ox,
            y2 / scale + self.oy,
        ]


# ---------------------------------------------------------------------------
# 图片
# ---------------------------------------------------------------------------


def load_image(path):
    """读取图片为 RGB（按 EXIF 方向矫正，多帧 TIFF 取第一帧）。"""
    if not os.path.isfile(path):
        raise OcrError(f"输入图片不存在：{path}")
    try:
        with Image.open(path) as handle:
            frames = getattr(handle, "n_frames", 1)
            if frames and frames > 1:
                log(f"多帧图片只识别第一帧（共 {frames} 帧）：{path}")
            image = handle.convert("RGB")
            image = ImageOps.exif_transpose(image) or image
    except OcrError:
        raise
    except Exception as exc:
        raise OcrError(f"无法解码图片（{path}）：{exc}") from exc
    if image.width < 1 or image.height < 1:
        raise OcrError(f"图片尺寸异常：{path}")
    return image


def parse_region(region, width, height):
    """解析 --region "x1,y1,x2,y2"（允许 0 与越界，自动裁剪到图内）。"""
    if region is None:
        return None
    text = str(region).strip()
    if not text:
        return None
    parts = [p for p in re.split(r"[,;\s]+", text) if p]
    if len(parts) != 4:
        raise UsageError(f"--region 需要 4 个整数 x1,y1,x2,y2，收到：{region!r}")
    try:
        x1, y1, x2, y2 = (int(round(float(p))) for p in parts)
    except ValueError as exc:
        raise UsageError(f"--region 含非数字：{region!r}") from exc
    x1 = max(0, min(x1, width))
    x2 = max(0, min(x2, width))
    y1 = max(0, min(y1, height))
    y2 = max(0, min(y2, height))
    if x2 - x1 < 2 or y2 - y1 < 2:
        raise UsageError(
            f"--region 裁切区域为空：{region!r}（图片尺寸 {width}x{height}）"
        )
    return (x1, y1, x2, y2)


def prepare_image(image, max_side=MAX_SIDE_DEFAULT, region=None):
    """裁切 + 超大图缩放；返回 (识别用图, Transform, 说明列表)。"""
    notes = []
    offset_x = offset_y = 0
    box = parse_region(region, image.width, image.height)
    if box:
        image = image.crop(box)
        offset_x, offset_y = box[0], box[1]
        notes.append(f"裁切 {box[0]},{box[1]}-{box[2]},{box[3]}")

    scale = 1.0
    if max_side and max_side > 0:
        long_side = max(image.width, image.height)
        if long_side > max_side:
            scale = max_side / float(long_side)
            new_size = (
                max(1, int(round(image.width * scale))),
                max(1, int(round(image.height * scale))),
            )
            image = image.resize(new_size, Image.LANCZOS)
            notes.append(f"长边 {long_side}px 缩放到 {max_side}px")
    return image, Transform(scale=scale, ox=offset_x, oy=offset_y), notes


# ---------------------------------------------------------------------------
# 方向检测
# ---------------------------------------------------------------------------


def _osd_rotate(img):
    """调用系统 tesseract 的 OSD 检测方向。

    返回 tesseract 报告的 Rotate 值（0/90/180/270），失败返回 None。
    实测语义：把原图顺时针旋转该角度即可摆正（见 test.sh 的方向用例）。
    """
    exe = shutil.which("tesseract")
    if not exe:
        return None
    tmp_path = None
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".png", dir=temp_dir())
        os.close(fd)
        img.save(tmp_path, format="PNG")
        proc = subprocess.run(
            [exe, tmp_path, "-", "--psm", "0", "-l", "osd"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        match = re.search(r"Rotate:\s*(\d+)", out)
        if not match:
            return None
        angle = int(match.group(1)) % 360
        return angle if angle in (90, 180, 270) else 0
    except Exception:
        return None
    finally:
        cleanup(tmp_path)


def rotate_clockwise(img, angle):
    """顺时针旋转（PIL 的 rotate 是逆时针，故取负角）。"""
    angle = int(angle) % 360
    if angle == 0:
        return img
    if angle not in (90, 180, 270):
        raise UsageError(f"--rotate 只支持 auto / 0 / 90 / 180 / 270，收到 {angle}")
    return img.rotate(-angle, expand=True)


def rotate_image(img, mode="0", rapid_engine=None):
    """按 --rotate 摆正图片。

    返回 (image, info)。info 为 None 表示未旋转；否则
    {"angle": 顺时针角度, "method": "osd"|"rapid-cls"}。
    """
    mode = str(mode or "0").strip().lower()
    if mode in ("", "0", "none", "no", "off"):
        return img, None
    if mode == "auto":
        angle = None
        method = None
        if shutil.which("tesseract"):
            angle = _osd_rotate(img)
            method = "osd"
        if angle is None and rapid_engine is not None:
            angle = rapid_engine.detect_180(img)
            method = "rapid-cls"
        if not angle:
            log("自动方向检测未发现需要旋转（或缺少 OSD 能力），按原方向识别")
            return img, None
        return rotate_clockwise(img, angle), {"angle": int(angle) % 360, "method": method}
    try:
        angle = int(mode) % 360
    except ValueError as exc:
        raise UsageError(
            f"--rotate 只支持 auto / 0 / 90 / 180 / 270，收到 {mode!r}"
        ) from exc
    if angle not in (0, 90, 180, 270):
        raise UsageError(f"--rotate 只支持 auto / 0 / 90 / 180 / 270，收到 {mode!r}")
    if angle == 0:
        return img, None
    return rotate_clockwise(img, angle), {"angle": angle, "method": "manual"}


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def parse_pages(spec, total):
    """解析 "1-3,5" / "3-" / "2" 为 1-based 页码列表（去重且保持给定顺序）。"""
    if not spec:
        return list(range(1, total + 1))
    pages = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            left, _, right = part.partition("-")
            left = left.strip()
            right = right.strip()
            if not left.isdigit() or (right and not right.isdigit()):
                raise UsageError(f"--pages 区间写法不合法：{part!r}（示例 1-3,5）")
            start = int(left)
            end = int(right) if right else total
        else:
            if not part.isdigit():
                raise UsageError(f"--pages 页号不合法：{part!r}（示例 1-3,5）")
            start = end = int(part)
        if start > end:
            start, end = end, start
        if start < 1 or end > total:
            raise UsageError(f"--pages 越界：{part!r}（文档共 {total} 页）")
        for number in range(start, end + 1):
            if number not in pages:
                pages.append(number)
    if not pages:
        raise UsageError(f"--pages 没有解析出任何页码：{spec!r}")
    return pages


def fitz_module():
    """PyMuPDF：新包名 pymupdf，旧包名 fitz（2.x 会对 fitz 发弃用警告）。"""
    try:
        import pymupdf  # type: ignore

        return pymupdf
    except ImportError:
        pass
    try:
        import fitz  # type: ignore

        return fitz
    except ImportError as exc:  # pragma: no cover - 环境缺包时才会走到
        raise DependencyError(
            f"PDF 渲染需要 PyMuPDF：{exc}",
            hint='"$OFFICE_KIT_PY" -m pip install --no-cache-dir pymupdf',
        ) from exc


def open_pdf(path):
    fitz = fitz_module()
    if not os.path.isfile(path):
        raise OcrError(f"输入 PDF 不存在：{path}")
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise OcrError(f"无法打开 PDF（{path}）：{exc}") from exc
    if doc.needs_pass:
        doc.close()
        raise OcrError(
            f"PDF 已加密，需要密码才能渲染：{path}",
            hint="先用 office-kit pdf run decrypt 解密，再对本模块使用",
        )
    if doc.page_count < 1:
        doc.close()
        raise OcrError(f"PDF 没有任何页面：{path}")
    return doc


def render_pdf_pages(doc, page_numbers, dpi=DEFAULT_DPI):
    """逐页渲染为 PIL RGB，生成 (page_no, image, dpi, pixels_per_point)。

    生成器实现：大文档不会一次性把每页位图堆在内存里。
    """
    if dpi < 36 or dpi > 1200:
        raise UsageError(f"--dpi 应在 36~1200 之间，收到 {dpi}")
    fitz = fitz_module()
    pixels_per_point = dpi / 72.0
    for number in page_numbers:
        page = doc.load_page(number - 1)
        try:
            pixmap = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        except Exception as exc:
            raise OcrError(f"PDF 第 {number} 页渲染失败：{exc}") from exc
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
        del pixmap
        yield number, image, dpi, pixels_per_point
