#!/usr/bin/env python3
"""把 ocr 模块的 JSON 结果按坐标聚类重建成 Markdown 表格（启发式）。

用法:
  "$OFFICE_KIT_PY" ocr-to-md-table.py 结果.json [--page 1] [--gap 40]

思路：
  1. 行聚类：按文本框纵向中心聚合，容差取行高中位数的 0.6 倍；
  2. 单元格：同一行内水平重叠的框合并，按 x1 排序；
  3. 列聚类：所有单元格的横向中心一维聚类，间距超过 --gap 视为新列；
  4. 首行（含 ≥2 个单元格）当表头，其余行按列中心就近落位，缺列补空。

只依赖标准库，便于在离线机器上直接使用。坐标来自 `ocr image/pdf --json` 的
`pages[].lines[]`，单位是图片像素。
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys


def load_lines(path, page=None):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if "items" in data:  # batch 结果：逐文件处理
        raise SystemExit("这是 batch 结果，请先用 --output-dir 生成单文件 JSON 再转换")
    pages = data.get("pages") or []
    if page is not None:
        pages = [p for p in pages if p.get("page") == page]
        if not pages:
            raise SystemExit(f"结果里没有第 {page} 页")
    lines = []
    for item in pages:
        for line in item.get("lines") or []:
            text = (line.get("text") or "").strip()
            box = line.get("box")
            if text and isinstance(box, list) and len(box) == 4:
                lines.append((item.get("page", 1), text, [float(v) for v in box]))
    return data, lines


def cluster_rows(lines, tolerance):
    """按纵向重叠/邻近把行分组，返回 [[(text, box), ...], ...]。"""
    ordered = sorted(lines, key=lambda row: (row[0], (row[2][1] + row[2][3]) / 2, row[2][0]))
    rows = []
    current = []
    current_center = None
    current_page = None
    for page, text, box in ordered:
        center = (box[1] + box[3]) / 2
        if (
            current
            and page == current_page
            and abs(center - current_center) <= tolerance
        ):
            current.append((text, box))
            current_center = sum((b[1] + b[3]) / 2 for _, b in current) / len(current)
        else:
            if current:
                rows.append(current)
            current = [(text, box)]
            current_center = center
            current_page = page
    if current:
        rows.append(current)
    return rows


def merge_cells(row):
    """行内水平重叠的框合并成一个单元格；返回按 x 排序的 [(x_center, text)]。"""
    ordered = sorted(row, key=lambda item: item[1][0])
    cells = []
    for text, box in ordered:
        if cells and box[0] <= cells[-1]["x2"] + 1:
            cells[-1]["text"] = (cells[-1]["text"] + " " + text).strip()
            cells[-1]["x2"] = max(cells[-1]["x2"], box[2])
            cells[-1]["center"] = (cells[-1]["x1"] + cells[-1]["x2"]) / 2
        else:
            cells.append(
                {
                    "text": text,
                    "x1": box[0],
                    "x2": box[2],
                    "center": (box[0] + box[2]) / 2,
                }
            )
    return [(cell["center"], cell["text"]) for cell in cells]


def cluster_columns(centers, gap):
    """一维中心聚类：相邻中心间距 > gap 则开新列；返回列中心列表。"""
    ordered = sorted(set(round(value, 1) for value in centers))
    if not ordered:
        return []
    columns = [ordered[0]]
    for value in ordered[1:]:
        if value - columns[-1] > gap:
            columns.append(value)
        else:
            columns[-1] = (columns[-1] + value) / 2
    return columns


def to_markdown(rows, gap):
    header_index = next(
        (index for index, row in enumerate(rows) if len(merge_cells(row)) >= 2),
        None,
    )
    if header_index is None:
        return None, [cell for row in rows for cell in merge_cells(row)]

    preamble = []
    for row in rows[:header_index]:
        preamble.extend(text for _, text in merge_cells(row))

    rendered = [merge_cells(row) for row in rows[header_index:]]
    centers = [center for row in rendered for center, _ in row]
    columns = cluster_columns(centers, gap)
    if len(columns) < 2:
        return None, [cell for row in rendered for cell in row]

    def place(row):
        cells = [""] * len(columns)
        for center, text in row:
            index = min(range(len(columns)), key=lambda i: abs(columns[i] - center))
            cells[index] = (cells[index] + " " + text).strip()
        return cells

    table = [place(row) for row in rendered]
    header = table[0]
    if len([cell for cell in header if cell]) < 2:
        header = [f"列 {i + 1}" for i in range(len(columns))]
        body = table
    else:
        body = table[1:]

    def escape(text):
        return text.replace("|", "\\|").replace("\n", " ")

    md = ["| " + " | ".join(escape(cell) for cell in header) + " |"]
    md.append("| " + " | ".join("---" for _ in header) + " |")
    for row in body:
        md.append("| " + " | ".join(escape(cell) for cell in row) + " |")
    return "\n".join(md), preamble


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="把 ocr JSON 的带坐标文本行重建为 Markdown 表格（启发式）",
    )
    parser.add_argument("json", metavar="JSON", help="ocr image/pdf --json 或 --output-json 的结果")
    parser.add_argument("--page", type=int, help="只转换指定页")
    parser.add_argument(
        "--gap",
        type=float,
        default=None,
        help="列间距阈值（像素），默认取行高中位数的 2.5 倍",
    )
    args = parser.parse_args(argv)

    data, lines = load_lines(args.json, args.page)
    if not lines:
        raise SystemExit("结果里没有可用的 text/box 行")

    heights = [box[3] - box[1] for _, _, box in lines]
    median_height = statistics.median(heights) or 12.0
    tolerance = median_height * 0.6
    gap = args.gap if args.gap is not None else max(median_height * 2.5, 16.0)

    rows = cluster_rows(lines, tolerance)
    markdown, preamble = to_markdown(rows, gap)
    if markdown is None:
        raise SystemExit("没有识别出两列以上结构，无法重建表格；请检查原图或 --gap")

    if preamble:
        print("\n".join(preamble))
        print()
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
