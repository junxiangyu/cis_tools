#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""图像信息查看器 (Image Inspector)

一个基于 PySide6 + Pillow 的 PC 端桌面小工具：
  * 左侧：QScrollArea 承载图像，支持大图滚动查看、缩放、拖拽平移、适应窗口
  * 右侧：解析并展示图像的完整元信息
        图像类型 / 文件大小 / 长宽尺寸 / 位深 / 颜色空间 / 压缩方式 等

运行:
    python image_info_viewer.py [图片路径]
"""

from __future__ import annotations

import io
import math
import mimetypes
import os
import re
import sys
from datetime import datetime

from PIL import Image, ImageCms, ImageFile

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QImage,
    QImageReader,
    QKeySequence,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

ImageFile.LOAD_TRUNCATED_IMAGES = True

APP_TITLE = "图像信息查看器"

# --------------------------------------------------------------------------- #
# 常量表
# --------------------------------------------------------------------------- #

#: Pillow 颜色模式 -> (每通道位数, 通道数, 人类可读描述)
MODE_INFO: dict[str, tuple[int, int, str]] = {
    "1": (1, 1, "1-bit 二值位图（黑白）"),
    "L": (8, 1, "8-bit 灰度"),
    "LA": (8, 2, "8-bit 灰度 + Alpha"),
    "La": (8, 2, "8-bit 灰度 + 预乘 Alpha"),
    "P": (8, 1, "8-bit 调色板索引"),
    "PA": (8, 2, "8-bit 调色板 + Alpha"),
    "RGB": (8, 3, "8-bit RGB 真彩色"),
    "RGBA": (8, 4, "8-bit RGB + Alpha"),
    "RGBX": (8, 4, "8-bit RGBX（忽略 Alpha）"),
    "RGBa": (8, 4, "8-bit RGB + 预乘 Alpha"),
    "CMYK": (8, 4, "8-bit CMYK 印刷色"),
    "YCbCr": (8, 3, "8-bit YCbCr 亮度色度"),
    "LAB": (8, 3, "8-bit CIE LAB 色彩空间"),
    "HSV": (8, 3, "8-bit HSV 色彩空间"),
    "I": (32, 1, "32-bit 有符号整型灰度"),
    "I;16": (16, 1, "16-bit 无符号整型灰度"),
    "I;16B": (16, 1, "16-bit 大端整型灰度"),
    "I;16L": (16, 1, "16-bit 小端整型灰度"),
    "F": (32, 1, "32-bit 单精度浮点灰度"),
}

#: 容器格式 -> (简称, MIME, 说明)
FORMAT_INFO: dict[str, tuple[str, str, str]] = {
    "JPEG": ("JPEG", "image/jpeg", "JPEG 联合图像专家组 —— 有损压缩光栅格式"),
    "MPO": ("MPO", "image/mpo", "多图对象格式（由多个 JPEG 帧组成）"),
    "PNG": ("PNG", "image/png", "PNG 便携式网络图形 —— 无损压缩光栅格式"),
    "APNG": ("APNG", "image/apng", "动态 PNG 便携式网络图形"),
    "GIF": ("GIF", "image/gif", "GIF 图形交换格式 —— 无损压缩、支持动画"),
    "BMP": ("BMP", "image/bmp", "BMP Windows 位图"),
    "DIB": ("BMP", "image/bmp", "BMP Windows 位图"),
    "TIFF": ("TIFF", "image/tiff", "TIFF 标签图像文件格式"),
    "WEBP": ("WebP", "image/webp", "WebP 谷歌网络图像格式"),
    "ICO": ("ICO", "image/x-icon", "ICO Windows 图标"),
    "CUR": ("CUR", "image/x-icon", "CUR Windows 光标"),
    "TGA": ("TGA", "image/x-tga", "TGA Truevision 光栅格式"),
    "PSD": ("PSD", "image/vnd.adobe.photoshop", "PSD Adobe Photoshop 文档"),
    "JPEG2000": ("JPEG2000", "image/jp2", "JPEG 2000 小波变换格式"),
    "PPM": ("PNM", "image/x-portable-anymap", "PNM 便携式任意图格式族"),
    "PCX": ("PCX", "image/x-pcx", "PCX ZSoft 画笔格式"),
    "XBM": ("XBM", "image/x-xbitmap", "XBM X 位图"),
    "DDS": ("DDS", "image/vnd-ms.dds", "DDS DirectDraw 表面"),
    "AVIF": ("AVIF", "image/avif", "AVIF AV1 图像文件格式"),
    "HEIF": ("HEIF", "image/heif", "HEIF 高效图像文件格式"),
    "SGI": ("SGI", "image/x-sgi", "SGI 光栅格式"),
}

#: libjpeg 标准亮度量化表（用于反推编码质量）
_STD_LUMA = [
    16, 11, 10, 16, 24, 40, 51, 61,
    12, 12, 14, 19, 26, 58, 60, 55,
    14, 13, 16, 24, 40, 57, 69, 56,
    14, 17, 22, 29, 51, 87, 80, 62,
    18, 22, 37, 56, 68, 109, 103, 77,
    24, 35, 55, 64, 81, 104, 113, 92,
    49, 64, 78, 87, 103, 121, 120, 101,
    72, 92, 95, 98, 112, 100, 103, 99,
]
_STD_CHROMA = [
    17, 18, 24, 47, 99, 99, 99, 99,
    18, 21, 26, 66, 99, 99, 99, 99,
    24, 26, 56, 99, 99, 99, 99, 99,
    47, 66, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
    99, 99, 99, 99, 99, 99, 99, 99,
]

IMAGE_EXTENSIONS = sorted(
    {
        ".png", ".jpg", ".jpeg", ".jpe", ".jfif", ".bmp", ".gif", ".tif",
        ".tiff", ".webp", ".ico", ".cur", ".tga", ".psd", ".jp2", ".j2k",
        ".ppm", ".pgm", ".pbm", ".pnm", ".pcx", ".xbm", ".dds", ".avif",
        ".heic", ".heif", ".blp", ".exr", ".hdr",
    }
)


# --------------------------------------------------------------------------- #
# 通用格式化辅助
# --------------------------------------------------------------------------- #
def human_size(num_bytes: float) -> str:
    """把字节数格式化成人类友好的字符串。"""
    if num_bytes < 1024:
        return f"{num_bytes:.0f} B"
    value = float(num_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1024 or unit == "TB":
            return f"{value:.2f} {unit}"
    return f"{num_bytes:.0f} B"


def fmt_int(value: int) -> str:
    return f"{value:,}"


def fmt_aspect_ratio(width: int, height: int) -> str:
    """给出最简整数比，例如 16:9。"""
    if not width or not height:
        return "-"
    divisor = math.gcd(width, height)
    a, b = width // divisor, height // divisor
    if a > 200 or b > 200:  # 比值过于刁钻，退回小数形式
        return f"{width / height:.4g} : 1"
    return f"{a}:{b}　（{width / height:.4g} : 1）"


def read_head(path: str, size: int = 65536) -> bytes:
    try:
        with open(path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


# --------------------------------------------------------------------------- #
# 文件头解析：位深 / 像素格式
# --------------------------------------------------------------------------- #
def probe_png(head: bytes):
    """返回 (每通道位深, 每像素位深, 通道数, 像素格式描述)。"""
    if head[:8] != b"\x89PNG\r\n\x1a\n" or len(head) < 26:
        return None
    bit_depth = head[24]
    color_type = head[25]
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color_type)
    if channels is None:
        return None
    desc = {
        0: "灰度",
        2: "真彩色 RGB",
        3: "调色板索引",
        4: "灰度 + Alpha",
        6: "真彩色 RGB + Alpha",
    }.get(color_type, "未知")
    return bit_depth, bit_depth * channels, channels, f"PNG 颜色类型 {color_type}（{desc}）"


def probe_jpeg(head: bytes):
    """返回 (每通道位深, 每像素位深, 通道数, 编码过程描述)。"""
    if not head.startswith(b"\xff\xd8"):
        return None
    markers = {
        0xC0: "基线顺序 DCT（Baseline）",
        0xC1: "扩展顺序 DCT",
        0xC2: "渐进式 DCT（Progressive）",
        0xC3: "无损顺序（Lossless）",
        0xC5: "差分顺序 DCT",
        0xC6: "差分渐进 DCT",
        0xC7: "差分无损",
        0xC9: "算术编码扩展顺序",
        0xCA: "算术编码渐进",
        0xCB: "算术编码无损",
    }
    idx = 2
    end = len(head)
    while idx + 9 < end:
        if head[idx] != 0xFF:
            idx += 1
            continue
        marker = head[idx + 1]
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0xFF:
            idx += 2
            continue
        if marker == 0xDA:  # 进入压缩数据，之后不再有 SOF
            break
        if idx + 4 > end:
            break
        length = int.from_bytes(head[idx + 2:idx + 4], "big")
        if length < 2:
            break
        if marker in markers and idx + 10 <= end:
            precision = head[idx + 4]
            components = head[idx + 9]
            return precision, precision * components, components, markers[marker]
        idx += 2 + length
    return None


def probe_gif(head: bytes):
    if head[:6] not in (b"GIF87a", b"GIF89a") or len(head) < 13:
        return None
    packed = head[10]
    if packed >> 7:
        palette_size = 2 ** ((packed & 0x07) + 1)
        desc = f"LZW 无损压缩，全局调色板 {palette_size} 色"
    else:
        desc = "LZW 无损压缩，无全局调色板"
    return 8, 8, 1, desc


def probe_bmp(head: bytes):
    if head[:2] != b"BM" or len(head) < 34:
        return None
    bpp = int.from_bytes(head[28:30], "little")
    compression = int.from_bytes(head[30:34], "little")
    names = {
        0: "BI_RGB（未压缩）",
        1: "BI_RLE8 游程编码",
        2: "BI_RLE4 游程编码",
        3: "BI_BITFIELDS 位域掩码",
        4: "BI_JPEG 内嵌 JPEG",
        5: "BI_PNG 内嵌 PNG",
    }
    channels = max(1, bpp // 8)
    return bpp // channels, bpp, channels, names.get(compression, f"压缩方式代码 {compression}")


def probe_webp(head: bytes):
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    chunk = head[12:16]
    if chunk == b"VP8 ":
        return None, None, None, "有损压缩（VP8 帧内编码）"
    if chunk == b"VP8L":
        return None, None, None, "无损压缩（VP8L）"
    if chunk == b"VP8X":
        return None, None, None, "扩展容器 VP8X（可能含 Alpha / 动画）"
    return None, None, None, "未知 WebP 编码"


def probe_tiff(img: Image.Image):
    try:
        bits = img.tag_v2.get(258)  # BitsPerSample
        comp = img.tag_v2.get(259)  # Compression
    except Exception:
        return None
    if bits is None:
        return None
    if isinstance(bits, int):
        bits = (bits,)
    bits = tuple(int(b) for b in bits)
    comp_names = {
        1: "未压缩", 2: "CCITT 1D", 3: "CCITT Group 3", 4: "CCITT Group 4",
        5: "LZW 无损压缩", 6: "JPEG 旧式有损", 7: "JPEG 有损压缩",
        8: "Deflate / zlib 无损压缩", 9: "JBIG", 32773: "PackBits 无损压缩",
        32946: "Deflate 无损压缩", 34887: "LZMA 无损压缩", 50000: "ZSTD 无损压缩",
    }
    desc = comp_names.get(comp, f"压缩方式代码 {comp}" if comp else "未知")
    return bits[0], bits[0] * len(bits), len(bits), desc


def estimate_jpeg_quality(img: Image.Image):
    """依据量化表反推 JPEG 编码质量（1-100，估算值）。"""
    try:
        tables = img.quantization
    except Exception:
        return None
    if not tables:
        return None

    def scaled(std, quality: int):
        factor = 5000.0 / quality if quality < 50 else 200.0 - quality * 2.0
        return [max(1, min(255, int((value * factor + 50) // 100))) for value in std]

    keys = sorted(tables)
    actual = [sum(tables[key]) for key in keys]
    best_quality, best_error = None, None
    for quality in range(1, 101):
        candidate = [
            sum(scaled(_STD_LUMA if index == 0 else _STD_CHROMA, quality))
            for index in range(len(keys))
        ]
        error = sum(abs(a - c) for a, c in zip(actual, candidate))
        if best_error is None or error < best_error:
            best_error, best_quality = error, quality
    return best_quality


def chroma_subsampling(img: Image.Image) -> str:
    """从 JPEG 采样因子推断色度二次采样方式。

    Pillow 的 ``img.layer`` 每项形如 ``(分量ID, 水平采样, 垂直采样, 量化表ID)``。
    """
    try:
        layer = img.layer
    except Exception:
        return "-"
    if not layer or len(layer) < 2:
        return "-"
    try:
        luma_h, luma_v = int(layer[0][1]), int(layer[0][2])
        chroma_h, chroma_v = int(layer[1][1]), int(layer[1][2])
    except Exception:
        return "-"
    if not luma_h or not luma_v or not chroma_h or not chroma_v:
        return "-"
    ratio = (luma_h / chroma_h, luma_v / chroma_v)
    known = {
        (2.0, 2.0): "4:2:0（色度水平、垂直各降采样一半）",
        (2.0, 1.0): "4:2:2（色度水平降采样一半）",
        (1.0, 1.0): "4:4:4（色度不降采样，画质最佳）",
        (1.0, 2.0): "4:4:0（色度垂直降采样一半）",
        (4.0, 1.0): "4:1:1（色度水平降采样为 1/4）",
    }
    if ratio in known:
        return known[ratio]
    return f"亮度采样 {luma_h}×{luma_v}，色度采样 {chroma_h}×{chroma_v}"


# --------------------------------------------------------------------------- #
# 颜色空间 / ICC
# --------------------------------------------------------------------------- #
def describe_color_space(img: Image.Image, fmt: str | None, head: bytes) -> tuple[str, str | None]:
    """返回 (颜色空间描述, ICC 配置文件名称或 None)。"""
    icc_name = None
    space = None
    icc = img.info.get("icc_profile")
    if icc:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            icc_name = (ImageCms.getProfileDescription(profile) or "").strip() or None
            space = getattr(profile.profile, "xcolor_space", None)
            if isinstance(space, bytes):
                space = space.decode("ascii", "ignore").strip()
        except Exception:
            icc_name = "（ICC 配置文件存在但无法解析）"

    if icc_name and space:
        return f"{space}（ICC 配置文件：{icc_name}）", icc_name
    if icc_name:
        return f"由 ICC 配置文件定义（{icc_name}）", icc_name

    mode = img.mode
    if fmt == "PNG":
        if b"sRGB" in head[:1024]:
            return "sRGB（PNG sRGB 色彩块声明）", None
        if b"iCCP" in head:
            return "由 PNG iCCP 色块定义（未解析）", None
        if b"gAMA" in head:
            return "灰度/RGB（PNG gAMA 伽马块，未嵌入 ICC）", None
    if mode in ("L", "LA", "1", "I", "I;16", "I;16B", "I;16L", "F"):
        return "灰度（未嵌入 ICC 配置文件）", None
    if mode in ("P", "PA"):
        return "调色板颜色（未嵌入 ICC 配置文件，按 sRGB 解释）", None
    if mode in ("RGB", "RGBA", "RGBX"):
        return "sRGB（未嵌入 ICC 配置文件，按 sRGB 解释）", None
    if mode == "CMYK":
        return "CMYK（未嵌入 ICC 配置文件）", None
    if mode == "YCbCr":
        return "YCbCr（亮度/色度，显示时转换为 sRGB）", None
    if mode == "LAB":
        return "CIE LAB", None
    return f"{mode}（未嵌入 ICC 配置文件）", None


def describe_compression(fmt: str | None, probe) -> tuple[bool, str]:
    """返回 (是否经过压缩, 压缩方式描述)。"""
    fmt = (fmt or "").upper()
    table = {
        "PNG": (True, "无损压缩（DEFLATE / zlib）"),
        "APNG": (True, "无损压缩（DEFLATE / zlib），多帧动画"),
        "JPEG": (True, "有损压缩（DCT 离散余弦变换 + 量化）"),
        "MPO": (True, "有损压缩（多帧 JPEG 组合）"),
        "GIF": (True, "无损压缩（LZW 字典编码）"),
        "PSD": (True, "RLE 无损压缩 / 原样存储"),
        "PCX": (True, "RLE 游程编码（无损）"),
        "JPEG2000": (True, "小波变换压缩（可无损，可有损）"),
        "AVIF": (True, "压缩（AV1 帧内编码，可有损可无损）"),
        "HEIF": (True, "有损压缩（HEVC 帧内编码）"),
        "TGA": (True, "RLE 游程编码，或未压缩"),
        "DDS": (True, "块压缩（DXT / S3TC 等），或未压缩"),
        "XBM": (False, "未压缩（文本位图源码）"),
        "PPM": (False, "未压缩（原始像素转储）"),
        "SGI": (True, "RLE 无损压缩，或未压缩"),
    }
    if fmt in table:
        return table[fmt]
    if fmt in ("BMP", "DIB"):
        if probe and probe[3]:
            return ("未压缩" not in probe[3]), probe[3]
        return False, "未压缩（BI_RGB）"
    if fmt == "TIFF":
        if probe and probe[3]:
            return ("未压缩" not in probe[3]), probe[3]
        return True, "TIFF 内部压缩（未能识别具体方式）"
    if fmt == "WEBP":
        return True, (probe[3] if probe and probe[3] else "压缩（WebP）")
    if fmt in ("ICO", "CUR"):
        return True, "内部条目为 PNG 或 BMP（BMP 条目可再含 PNG 无损压缩）"
    return False, "未检测到压缩编码（按原始像素存储）"


def describe_alpha(img: Image.Image) -> str:
    mode = img.mode
    if mode in ("RGBA", "LA", "PA", "RGBa", "La") or mode.endswith("A"):
        return "有（包含 Alpha 透明通道）"
    if mode == "P":
        try:
            transparency = img.info.get("transparency")
        except Exception:
            transparency = None
        return "有（调色板透明索引）" if transparency is not None else "无"
    return "无"


# --------------------------------------------------------------------------- #
# EXIF
# --------------------------------------------------------------------------- #
EXIF_MAIN = {
    271: "制造商",
    272: "相机型号",
    274: "方向标记",
    305: "处理软件",
    306: "文件修改时间",
}
EXIF_SUB = {
    36867: "拍摄时间",
    36868: "数字化时间",
    33434: "曝光时间",
    33437: "光圈值",
    34855: "ISO 感光度",
    37386: "焦距",
    41986: "曝光模式",
    41987: "白平衡",
    42036: "镜头型号",
    40962: "图像宽度",
    40963: "图像高度",
}
ORIENTATION_NAMES = {
    1: "正常", 2: "水平镜像", 3: "旋转 180°", 4: "垂直镜像",
    5: "转置", 6: "顺时针旋转 90°", 7: "反转置", 8: "逆时针旋转 90°",
}


def _fmt_exif_value(tag: int, value) -> str:
    try:
        if tag == 33434:
            seconds = float(value)
            if seconds <= 0:
                return str(value)
            return f"1/{round(1 / seconds)} 秒" if seconds < 1 else f"{seconds:g} 秒"
        if tag == 33437:
            return f"f/{float(value):g}"
        if tag == 37386:
            return f"{float(value):g} mm"
        if tag == 41986:
            return {0: "自动曝光", 1: "手动曝光", 2: "自动包围曝光"}.get(int(value), str(value))
        if tag == 41987:
            return {0: "自动白平衡", 1: "手动白平衡"}.get(int(value), str(value))
        if tag == 274:
            return ORIENTATION_NAMES.get(int(value), str(value))
        if isinstance(value, bytes):
            return value.decode("utf-8", "ignore").strip().strip("\x00") or "-"
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
    except Exception:
        pass
    return str(value).strip() or "-"


def _gps_to_decimal(value, ref):
    if not value or len(value) != 3:
        return None
    try:
        degrees, minutes, seconds = (float(item) for item in value)
        result = degrees + minutes / 60.0 + seconds / 3600.0
        if isinstance(ref, bytes):
            ref = ref.decode("ascii", "ignore")
        if str(ref).upper() in ("S", "W"):
            result = -result
        return result
    except Exception:
        return None


def extract_exif_rows(img: Image.Image, fmt: str | None) -> list[tuple[str, str]]:
    if (fmt or "").upper() not in ("JPEG", "MPO", "TIFF", "WEBP", "HEIF", "PNG"):
        return []
    rows: list[tuple[str, str]] = []
    try:
        exif = img.getexif()
    except Exception:
        return rows
    if not exif:
        return rows

    for tag, label in EXIF_MAIN.items():
        if tag in exif:
            rows.append((label, _fmt_exif_value(tag, exif[tag])))

    try:
        sub = exif.get_ifd(0x8769)
    except Exception:
        sub = {}
    for tag, label in EXIF_SUB.items():
        if tag in sub:
            rows.append((label, _fmt_exif_value(tag, sub[tag])))

    try:
        gps = exif.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            lat = _gps_to_decimal(gps.get(2), gps.get(1))
            lon = _gps_to_decimal(gps.get(4), gps.get(3))
            if lat is not None and lon is not None:
                rows.append(("GPS 坐标", f"{lat:.6f}, {lon:.6f}"))
    except Exception:
        pass
    return rows


# --------------------------------------------------------------------------- #
# 核心分析：把一张图片解析成 [ (分组标题, [(键, 值), ...]), ... ]
# --------------------------------------------------------------------------- #
def analyze_image(path: str) -> list[tuple[str, list[tuple[str, str]]]]:
    sections: list[tuple[str, list[tuple[str, str]]]] = []
    head = read_head(path)

    stat = os.stat(path)
    file_size = stat.st_size
    mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    ext = os.path.splitext(path)[1].lower()
    guessed_mime = mimetypes.guess_type(path)[0] or "-"

    try:
        img = Image.open(path)
        img.load()
    except Exception as exc:  # noqa: BLE001
        return [("① 文件信息", [
            ("文件名", os.path.basename(path)),
            ("所在目录", os.path.dirname(os.path.abspath(path))),
            ("文件大小", f"{human_size(file_size)}（{fmt_int(file_size)} 字节）"),
            ("修改时间", mtime),
            ("解析状态", f"无法解析图像内容：{exc}"),
        ])]

    fmt = (img.format or "").upper() or None
    short, mime, fmt_desc = FORMAT_INFO.get(
        fmt or "", (fmt or "未知", guessed_mime, f"{fmt or '未知'} 图像")
    )

    width, height = img.size
    pixel_count = width * height
    mode = img.mode
    per_channel, channels, mode_desc = MODE_INFO.get(mode, (None, None, mode))
    if per_channel is None:  # 兜底：从模式串里抠数字
        match = re.search(r"(\d+)", mode)
        per_channel = int(match.group(1)) if match else None
        channels = len(img.getbands()) if hasattr(img, "getbands") else None

    # ---- 文件头探测 -------------------------------------------------------- #
    probe = None
    for probe_fn in (probe_png, probe_jpeg, probe_gif, probe_bmp):
        probe = probe_fn(head)
        if probe:
            break
    if probe is None:
        probe = probe_webp(head)
    if probe is None and fmt == "TIFF":
        probe = probe_tiff(img)

    depth_per_channel = probe[0] if probe and probe[0] else per_channel
    depth_per_pixel = probe[1] if probe and probe[1] else (
        per_channel * channels if per_channel and channels else None
    )
    probe_channels = probe[2] if probe and probe[2] else channels

    # ---- ① 文件信息 -------------------------------------------------------- #
    sections.append(("① 文件信息", [
        ("文件名", os.path.basename(path)),
        ("所在目录", os.path.dirname(os.path.abspath(path))),
        ("文件大小", f"{human_size(file_size)}（{fmt_int(file_size)} 字节）"),
        ("修改时间", mtime),
        ("图像类型", f"{short}　—　{fmt_desc}"),
        ("文件扩展名", ext or "（无）"),
        ("MIME 类型", mime),
        ("文件头标识", " ".join(f"{b:02X}" for b in head[:8]) or "-"),
    ]))

    # ---- ② 尺寸信息 -------------------------------------------------------- #
    size_rows = [
        ("图像长宽", f"{fmt_int(width)} × {fmt_int(height)} 像素　（宽 × 高）"),
        ("宽高比", fmt_aspect_ratio(width, height)),
        ("总像素数", f"{fmt_int(pixel_count)} 像素（约 {pixel_count / 1e6:.2f} 百万像素）"),
    ]
    dpi = None
    try:
        raw_dpi = img.info.get("dpi")
        # 1 dpi 之类的取值在实践中等同于「未标注」，低于 10 一律视为无效
        if raw_dpi and float(raw_dpi[0]) >= 10 and float(raw_dpi[1]) >= 10:
            dpi = (float(raw_dpi[0]), float(raw_dpi[1]))
    except Exception:
        dpi = None
    if dpi:
        size_rows.append(("分辨率 (DPI)", f"{round(dpi[0], 1):g} × {round(dpi[1], 1):g} dpi"))
        size_rows.append((
            "物理打印尺寸",
            f"{width / dpi[0] * 2.54:.2f} × {height / dpi[1] * 2.54:.2f} 厘米",
        ))
    else:
        size_rows.append(("分辨率 (DPI)", "文件中未标注"))
        size_rows.append((
            "物理打印尺寸",
            f"{width / 72 * 2.54:.2f} × {height / 72 * 2.54:.2f} 厘米（按 72 dpi 估算）",
        ))
    sections.append(("② 尺寸信息", size_rows))

    # ---- ③ 颜色与位深 ------------------------------------------------------ #
    color_space, icc_name = describe_color_space(img, fmt, head)
    # 调色板格式（PNG 颜色类型 3 / GIF）的位深描述的是「索引位宽」，
    # 而不是最终呈现颜色的位深，需要额外说明避免误读。
    is_paletted = fmt == "GIF" or mode in ("P", "PA") or (
        fmt == "PNG" and len(head) > 25 and head[25] == 3
    )
    if depth_per_channel and depth_per_pixel:
        depth_text = f"{depth_per_channel} bit / 通道　共 {depth_per_pixel} bit / 像素"
    elif depth_per_pixel:
        depth_text = f"{depth_per_pixel} bit / 像素"
    else:
        depth_text = "无法确定"
    if is_paletted and depth_per_pixel:
        depth_text += "　（调色板索引位宽）"
    color_rows = [
        ("颜色模式", f"{mode}　—　{mode_desc}"),
        ("颜色空间", color_space),
        ("通道数", f"{probe_channels} 通道" if probe_channels else "-"),
        ("位深", depth_text),
        ("每通道位深", f"{depth_per_channel} bit" if depth_per_channel else "-"),
        ("每像素位深", f"{depth_per_pixel} bit" if depth_per_pixel else "-"),
        ("Alpha 透明通道", describe_alpha(img)),
    ]
    if mode in ("P", "PA"):
        palette = img.getpalette()
        color_rows.append(("调色板颜色数", f"{len(palette) // 3} 色" if palette else "未知"))
    if probe and probe[3]:
        color_rows.append(("像素格式", probe[3]))
    if icc_name:
        color_rows.append(("ICC 配置文件", icc_name))
    sections.append(("③ 颜色与位深", color_rows))

    # ---- ④ 压缩信息 -------------------------------------------------------- #
    compressed, compression_desc = describe_compression(fmt, probe)
    comp_rows = [
        ("是否压缩", "是（已压缩存储）" if compressed else "否（原始像素存储）"),
        ("压缩方式", compression_desc),
    ]
    if fmt == "JPEG":
        quality = estimate_jpeg_quality(img)
        comp_rows.append((
            "编码质量（估算）",
            f"约 {quality} / 100　（依据量化表反推，仅供参考）" if quality else "无法估算",
        ))
        comp_rows.append(("色度采样", chroma_subsampling(img)))
    if compressed and depth_per_pixel and pixel_count:
        raw_bytes = pixel_count * depth_per_pixel / 8.0
        comp_rows.append((
            "压缩比",
            f"{raw_bytes / file_size:.2f} : 1　（相对未压缩位图 {human_size(raw_bytes)}）",
        ))
        comp_rows.append(("每像素平均占用", f"{file_size / pixel_count:.3f} 字节 / 像素"))
    sections.append(("④ 压缩信息", comp_rows))

    # ---- ⑤ 扩展信息 -------------------------------------------------------- #
    other_rows: list[tuple[str, str]] = []
    n_frames = getattr(img, "n_frames", 1)
    if n_frames > 1:
        other_rows.append(("动画帧数", f"{n_frames} 帧"))
        duration = img.info.get("duration")
        if duration:
            total = duration * n_frames
            other_rows.append((
                "动画时长",
                f"约 {total / 1000:.2f} 秒（每帧 {duration} 毫秒）",
            ))
    if fmt == "JPEG":
        progressive = b"\xff\xc2" in head
        other_rows.append((
            "渐进式加载",
            "是（Progressive JPEG，分次扫描呈现）" if progressive else "否（Baseline 基线加载）",
        ))
    comment = img.info.get("comment")
    if comment:
        if isinstance(comment, bytes):
            comment = comment.decode("utf-8", "ignore")
        other_rows.append(("注释", str(comment).strip()[:200]))
    other_rows.extend(extract_exif_rows(img, fmt))

    if other_rows:
        sections.append(("⑤ 扩展信息（EXIF / 动画等）", other_rows))

    try:
        img.close()
    except Exception:
        pass
    return sections


# --------------------------------------------------------------------------- #
# 左侧：可滚动、可缩放的图像视图
# --------------------------------------------------------------------------- #
class ImageCanvas(QLabel):
    """自绘棋盘格底纹的画布，用于直观展示透明区域。"""

    CHECKER = 10

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ImageCanvas")
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self._background = QColor("#eceef1")
        self._light = QColor("#ffffff")
        self._dark = QColor("#e8ebef")

    def paintEvent(self, event):  # noqa: N802
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            # 空状态：交给 QLabel 自己绘制占位文案
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.fillRect(self.rect(), self._background)

        x = (self.width() - pixmap.width()) // 2
        y = (self.height() - pixmap.height()) // 2
        image_rect = self.rect().intersected(
            self.rect().adjusted(x, y, x + pixmap.width(), y + pixmap.height())
        )

        step = self.CHECKER
        painter.fillRect(image_rect, self._light)
        top, bottom = image_rect.top(), image_rect.bottom()
        left, right = image_rect.left(), image_rect.right()
        for row in range(top, bottom + 1, step):
            for col in range(left, right + 1, step):
                if ((col // step) + (row // step)) % 2 == 0:
                    painter.fillRect(
                        col, row,
                        min(step, right - col + 1),
                        min(step, bottom - row + 1),
                        self._dark,
                    )

        painter.drawPixmap(x, y, pixmap)
        painter.setPen(QColor("#c9ced6"))
        painter.drawRect(image_rect.adjusted(0, 0, -1, -1))
        painter.end()


class ImageView(QScrollArea):
    """支持滚动查看大图、滚轮缩放、拖拽平移的图像显示区。"""

    zoomChanged = Signal(float)

    MIN_SCALE = 0.02
    MAX_SCALE = 32.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setAlignment(Qt.AlignCenter)
        self.setFrameShape(QFrame.NoFrame)

        self.canvas = ImageCanvas()
        self.setWidget(self.canvas)

        self._pixmap: QPixmap | None = None
        self._scale = 1.0
        self._fit_mode = True
        self._panning = False
        self._pan_origin = QPoint()
        self._scroll_origin = QPoint()
        self.show_placeholder()

    # -- 状态 -------------------------------------------------------------- #
    def has_image(self) -> bool:
        return self._pixmap is not None and not self._pixmap.isNull()

    def current_scale(self) -> float:
        return self._scale

    def show_placeholder(self, text: str = "把图片拖到这里\n或点击工具栏「打开图片」") -> None:
        self._pixmap = None
        self.canvas.setPixmap(QPixmap())
        self.canvas.setText(text)
        self.canvas.setStyleSheet("color:#9aa1ab; font-size:15px;")
        self.canvas.setMinimumSize(QSize(0, 0))
        self.canvas.resize(self.viewport().size())
        self.zoomChanged.emit(0.0)

    # -- 加载 -------------------------------------------------------------- #
    def load(self, path: str) -> tuple[bool, str, bool]:
        """返回 (是否成功, 错误信息, 是否带 EXIF 方向标记)。"""
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()

        rotated = False
        try:
            with Image.open(path) as pil_image:
                exif = pil_image.getexif()
                rotated = bool(exif and exif.get(274) and int(exif.get(274)) != 1)
        except Exception:
            rotated = False

        if image.isNull():
            # Qt 解不开的格式，退回 Pillow 解码
            try:
                pil_image = Image.open(path)
                pil_image.load()
                pil_image = pil_image.convert("RGBA")
                buffer = pil_image.tobytes("raw", "RGBA")
                image = QImage(
                    buffer, pil_image.width, pil_image.height,
                    pil_image.width * 4, QImage.Format_RGBA8888,
                ).copy()
                pil_image.close()
            except Exception as exc:  # noqa: BLE001
                self.show_placeholder("图片解码失败")
                return False, str(exc), False

        self._pixmap = QPixmap.fromImage(image)
        self._fit_mode = True
        self.canvas.setStyleSheet("")
        self._apply_scale()

        self.verticalScrollBar().setValue(0)
        self.horizontalScrollBar().setValue(0)
        return True, "", rotated

    # -- 缩放 -------------------------------------------------------------- #
    def fit_to_window(self) -> None:
        if not self.has_image():
            return
        self._fit_mode = True
        self._apply_scale()

    def reset_zoom(self) -> None:
        if not self.has_image():
            return
        self._fit_mode = False
        self._scale = 1.0
        self._apply_scale()

    def zoom_in(self, step: float = 1.25) -> None:
        self._zoom_to(self._scale * step)

    def zoom_out(self, step: float = 1.25) -> None:
        self._zoom_to(self._scale / step)

    def _zoom_to(self, target: float) -> None:
        if not self.has_image():
            return
        self._fit_mode = False
        self._scale = max(self.MIN_SCALE, min(self.MAX_SCALE, target))
        self._apply_scale()

    def _fit_scale(self) -> float:
        viewport = self.viewport().size()
        fit = min(
            max(1, viewport.width() - 8) / self._pixmap.width(),
            max(1, viewport.height() - 8) / self._pixmap.height(),
        )
        # 小图不放大：保持像素级清晰（1:1 上限）
        return min(fit, 1.0)

    def _apply_scale(self) -> None:
        if not self.has_image():
            return
        if self._fit_mode:
            self._scale = self._fit_scale()
        if abs(self._scale - 1.0) < 1e-3:
            scaled = self._pixmap  # 1:1 直接使用原图，不做重采样
        else:
            target = QSize(
                max(1, int(self._pixmap.width() * self._scale)),
                max(1, int(self._pixmap.height() * self._scale)),
            )
            scaled = self._pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.canvas.setPixmap(scaled)
        self.canvas.setMinimumSize(scaled.size())
        self.canvas.resize(
            max(scaled.width(), self.viewport().width()),
            max(scaled.height(), self.viewport().height()),
        )
        self.zoomChanged.emit(self._scale)

    # -- 事件 -------------------------------------------------------------- #
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        if not self.has_image():
            self.canvas.resize(self.viewport().size())
            return
        if self._fit_mode:
            self._apply_scale()
        else:
            pixmap = self.canvas.pixmap()
            self.canvas.resize(
                max(pixmap.width(), self.viewport().width()),
                max(pixmap.height(), self.viewport().height()),
            )

    def wheelEvent(self, event):  # noqa: N802
        if not self.has_image():
            return super().wheelEvent(event)
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self._zoom_to(self._scale * (1.15 if delta > 0 else 1 / 1.15))
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event):  # noqa: N802
        if (
            self.has_image()
            and event.button() in (Qt.LeftButton, Qt.MiddleButton)
            and self._can_pan()
        ):
            self._panning = True
            self._pan_origin = event.position().toPoint()
            self._scroll_origin = QPoint(
                self.horizontalScrollBar().value(), self.verticalScrollBar().value()
            )
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._panning:
            delta = event.position().toPoint() - self._pan_origin
            self.horizontalScrollBar().setValue(self._scroll_origin.x() - delta.x())
            self.verticalScrollBar().setValue(self._scroll_origin.y() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self._panning and event.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._panning = False
            self.viewport().setCursor(Qt.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _can_pan(self) -> bool:
        pixmap = self.canvas.pixmap()
        if pixmap is None or pixmap.isNull():
            return False
        viewport = self.viewport().size()
        return pixmap.width() > viewport.width() or pixmap.height() > viewport.height()


# --------------------------------------------------------------------------- #
# 右侧：信息面板
# --------------------------------------------------------------------------- #
class InfoCard(QFrame):
    """一张信息卡片：标题 + 若干「键 / 值」行。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InfoCard")
        self._rows = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QLabel(title)
        header.setObjectName("CardTitle")
        layout.addWidget(header)

        self.body = QWidget()
        self.body.setObjectName("CardBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(10, 6, 10, 10)
        self.body_layout.setSpacing(0)
        layout.addWidget(self.body)

    def add_row(self, key: str, value: str) -> None:
        row = QWidget()
        row.setObjectName("CardRowAlt" if self._rows % 2 else "CardRow")
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(6, 6, 6, 6)
        row_layout.setSpacing(10)

        key_label = QLabel(key)
        key_label.setObjectName("RowKey")
        key_label.setFixedWidth(104)
        key_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        value_label = QLabel(str(value))
        value_label.setObjectName("RowValue")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        row_layout.addWidget(key_label)
        row_layout.addWidget(value_label, 1)
        self.body_layout.addWidget(row)
        self._rows += 1


class InfoPanel(QWidget):
    """右侧信息面板：滚动承载多张信息卡片。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InfoPanel")
        self._sections: list[tuple[str, list[tuple[str, str]]]] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QWidget()
        head.setObjectName("PanelHead")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(16, 12, 16, 12)
        title = QLabel("图像信息")
        title.setObjectName("PanelTitle")
        self.copy_button = QPushButton("复制全部")
        self.copy_button.setObjectName("GhostButton")
        self.copy_button.setCursor(Qt.PointingHandCursor)
        head_layout.addWidget(title)
        head_layout.addStretch(1)
        head_layout.addWidget(self.copy_button)
        outer.addWidget(head)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.container = QWidget()
        self.container.setObjectName("PanelContainer")
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(14, 12, 14, 18)
        self.container_layout.setSpacing(12)
        self.scroll.setWidget(self.container)
        outer.addWidget(self.scroll, 1)

        self.show_placeholder()

    # -- 状态 -------------------------------------------------------------- #
    def show_placeholder(
        self, text: str = "尚未选择图片\n\n打开或拖入一张图片后，\n这里会显示它的详细元信息。"
    ) -> None:
        self._sections = []
        self._clear()
        hint = QLabel(text)
        hint.setObjectName("Placeholder")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self.container_layout.addWidget(hint)
        self.container_layout.addStretch(1)
        self.copy_button.setEnabled(False)

    def show_sections(self, sections: list[tuple[str, list[tuple[str, str]]]]) -> None:
        self._sections = sections
        self._clear()
        for title, rows in sections:
            card = InfoCard(title)
            for key, value in rows:
                card.add_row(key, value)
            self.container_layout.addWidget(card)
        self.container_layout.addStretch(1)
        self.scroll.verticalScrollBar().setValue(0)
        self.copy_button.setEnabled(True)

    def _clear(self) -> None:
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()

    def as_text(self) -> str:
        lines: list[str] = []
        for title, rows in self._sections:
            lines.append(f"【{title}】")
            width = max((len(key) for key, _ in rows), default=0)
            for key, value in rows:
                lines.append(f"  {key.ljust(width)}  {value}")
            lines.append("")
        return "\n".join(lines).rstrip()


# --------------------------------------------------------------------------- #
# 主窗口
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self, initial_path: str | None = None) -> None:
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1280, 820)
        self.setMinimumSize(900, 560)
        self.setAcceptDrops(True)

        self._current_path: str | None = None

        self.image_view = ImageView()
        self.info_panel = InfoPanel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.setObjectName("MainSplitter")
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)
        splitter.addWidget(self.image_view)
        splitter.addWidget(self.info_panel)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([760, 520])
        self.setCentralWidget(splitter)

        self._build_toolbar()
        self.statusBar().setObjectName("StatusBar")
        self.statusBar().showMessage("就绪 —— 打开或拖入一张图片开始")

        self.image_view.zoomChanged.connect(self._on_zoom_changed)
        self.info_panel.copy_button.clicked.connect(self._copy_info)

        if initial_path:
            self.load_image(initial_path)

    # -- 工具栏 ------------------------------------------------------------ #
    def _build_toolbar(self) -> None:
        bar = QToolBar("工具栏")
        bar.setObjectName("MainToolBar")
        bar.setMovable(False)
        self.addToolBar(bar)

        def add_action(text: str, slot, shortcut: str | None = None, tip: str = "") -> QAction:
            action = QAction(text, self)
            if shortcut:
                action.setShortcut(QKeySequence(shortcut))
            action.setToolTip(tip or text)
            action.triggered.connect(slot)
            bar.addAction(action)
            return action

        add_action("打开图片", self.open_image, "Ctrl+O", "选择一张图片文件（Ctrl+O）")
        bar.addSeparator()
        # 注意：QAction.triggered 会回传一个 checked 布尔值，若直接连到带默认参数的
        # zoom_in / zoom_out，该布尔值会被当作 step 参数传入，必须用无参 lambda 包裹。
        self.act_zoom_in = add_action(
            "放大", lambda: self.image_view.zoom_in(), "Ctrl+=", "放大显示（也可 Ctrl+滚轮）"
        )
        self.act_zoom_out = add_action(
            "缩小", lambda: self.image_view.zoom_out(), "Ctrl+-", "缩小显示（也可 Ctrl+滚轮）"
        )
        self.act_fit = add_action("适应窗口", self.image_view.fit_to_window, "Ctrl+0", "按窗口大小自适应显示")
        self.act_actual = add_action("原始大小", self.image_view.reset_zoom, "Ctrl+1", "按 1:1 原始像素显示")
        bar.addSeparator()
        add_action("复制信息", self._copy_info, "Ctrl+Shift+C", "把右侧图像信息复制到剪贴板")

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.zoom_label = QLabel("缩放 --")
        self.zoom_label.setObjectName("ZoomLabel")
        bar.addWidget(self.zoom_label)

        self._zoom_actions = (self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_actual)
        for action in self._zoom_actions:
            action.setEnabled(False)

    # -- 交互 -------------------------------------------------------------- #
    def open_image(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in IMAGE_EXTENSIONS)
        path, _ = QFileDialog.getOpenFileName(
            self, "选择图片", "", f"图像文件 ({patterns});;所有文件 (*)"
        )
        if path:
            self.load_image(path)

    def load_image(self, path: str) -> None:
        if not os.path.isfile(path):
            QMessageBox.warning(self, APP_TITLE, f"文件不存在：\n{path}")
            return

        ok, error, rotated = self.image_view.load(path)
        if not ok:
            QMessageBox.critical(self, APP_TITLE, f"无法打开该图片：\n{error}")
            return

        self._current_path = path
        self.info_panel.show_sections(analyze_image(path))

        for action in self._zoom_actions:
            action.setEnabled(True)

        self.setWindowTitle(f"{os.path.basename(path)} — {APP_TITLE}")
        message = f"已加载 {os.path.basename(path)}"
        if rotated:
            message += "　（检测到 EXIF 方向标记，显示已自动校正）"
        self.statusBar().showMessage(message)
        self._on_zoom_changed(self.image_view.current_scale())

    def _copy_info(self) -> None:
        text = self.info_panel.as_text()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("图像信息已复制到剪贴板", 3000)

    def _on_zoom_changed(self, scale: float) -> None:
        self.zoom_label.setText(f"缩放 {scale * 100:.0f}%" if scale > 0 else "缩放 --")

    # -- 拖放 -------------------------------------------------------------- #
    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                path = url.toLocalFile()
                if url.isLocalFile() and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event):  # noqa: N802
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS:
                self.load_image(path)
                event.acceptProposedAction()
                return
        event.ignore()


# --------------------------------------------------------------------------- #
# 样式与入口
# --------------------------------------------------------------------------- #
STYLE_SHEET = """
QMainWindow { background: #f4f5f7; }
QWidget { color: #1f2328; font-size: 13px; }

QToolBar#MainToolBar {
    background: #ffffff;
    border: none;
    border-bottom: 1px solid #e3e6ea;
    padding: 6px 10px;
    spacing: 4px;
}
QToolBar#MainToolBar QToolButton {
    padding: 6px 12px;
    border: 1px solid transparent;
    border-radius: 6px;
    color: #374151;
    font-size: 13px;
}
QToolBar#MainToolBar QToolButton:hover { background: #eef2f8; border-color: #d7dfea; }
QToolBar#MainToolBar QToolButton:pressed { background: #e2e8f2; }
QToolBar#MainToolBar QToolButton:disabled { color: #b3b9c2; }
QToolBar#MainToolBar::separator { background: #e3e6ea; width: 1px; margin: 6px 8px; }
QLabel#ZoomLabel { color: #6b7280; font-size: 12px; padding-right: 8px; }

QSplitter#MainSplitter::handle { background: #e3e6ea; }
QSplitter#MainSplitter::handle:horizontal { width: 1px; }

QScrollArea { border: none; background: #eceef1; }
QLabel#ImageCanvas { background: #eceef1; }

QWidget#InfoPanel { background: #ffffff; border-left: 1px solid #e3e6ea; }
QWidget#PanelHead { background: #ffffff; border-bottom: 1px solid #eceef1; }
QLabel#PanelTitle { font-size: 15px; font-weight: 600; color: #1f2328; }
QPushButton#GhostButton {
    padding: 4px 12px;
    border: 1px solid #d7dfea;
    border-radius: 6px;
    background: #ffffff;
    color: #2f6fed;
    font-size: 12px;
}
QPushButton#GhostButton:hover { background: #f3f7ff; }
QPushButton#GhostButton:disabled { color: #b3b9c2; border-color: #e3e6ea; }
QWidget#PanelContainer { background: #f7f8fa; }

QFrame#InfoCard {
    background: #ffffff;
    border: 1px solid #e3e6ea;
    border-radius: 8px;
}
QLabel#CardTitle {
    font-size: 12px;
    font-weight: 600;
    color: #2f6fed;
    padding: 9px 14px 8px 14px;
    border-bottom: 1px solid #eef1f5;
    background: #fbfcfe;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}
QWidget#CardBody { background: #ffffff; }
QWidget#CardRow { background: transparent; }
QWidget#CardRowAlt { background: #fafbfc; }
QLabel#RowKey { color: #6b7280; font-size: 12px; }
QLabel#RowValue { color: #1f2328; font-size: 12.5px; }
QLabel#Placeholder { color: #9aa1ab; font-size: 13px; padding: 48px 24px; }

QStatusBar#StatusBar { background: #ffffff; border-top: 1px solid #e3e6ea; color: #6b7280; font-size: 12px; }

QScrollBar:vertical { background: #f4f5f7; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #c9ced6; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #aeb5bf; }
QScrollBar:horizontal { background: #f4f5f7; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #c9ced6; border-radius: 5px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #aeb5bf; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ImageInspector")
    app.setApplicationDisplayName(APP_TITLE)
    app.setStyle("Fusion")

    font = QFont("Microsoft YaHei UI", 9)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)
    app.setStyleSheet(STYLE_SHEET)

    initial = sys.argv[1] if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]) else None
    window = MainWindow(initial)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
