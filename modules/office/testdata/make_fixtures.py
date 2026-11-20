#!/usr/bin/env python3
"""生成 office 模块自测素材（不依赖任何外部样本）。

用法:
    python3 make_fixtures.py OUTDIR

生成:
    OUTDIR/自测 文档.docx   —— 两页、标题、表格、中文
    OUTDIR/预算 表.xlsx     —— 两个工作表、公式、样式
    OUTDIR/汇报 演示.pptx   —— 封面 + 内容页 + 表格页
"""

from __future__ import annotations

import sys
from pathlib import Path


def make_docx(path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_BREAK
    from docx.shared import Cm, Pt, RGBColor

    document = Document()
    document.core_properties.title = "自测文档"
    document.core_properties.author = "office-kit test"
    document.add_heading("离线办公套件自测文档", level=0)
    document.add_paragraph("本文件由 python-docx 生成，用于验证转换、渲染与结构摘要。")

    document.add_heading("一、基本信息", level=1)
    paragraph = document.add_paragraph()
    run = paragraph.add_run("覆盖能力：")
    run.bold = True
    paragraph.add_run("Word / Excel / PowerPoint 转换、渲染、摘要。")
    document.add_paragraph("项目一", style="List Bullet")
    document.add_paragraph("项目二", style="List Bullet")

    table = document.add_table(rows=3, cols=3)
    table.style = "Table Grid"
    headers = ["模块", "状态", "备注"]
    values = [["office", "完成", "5 个子命令"], ["pdf", "测试中", "Stirling"]]
    for col, text in enumerate(headers):
        cell = table.cell(0, col)
        cell.text = text
        for p in cell.paragraphs:
            for r in p.runs:
                r.bold = True
    for row_index, row in enumerate(values, start=1):
        for col_index, text in enumerate(row):
            table.cell(row_index, col_index).text = text
    for row in table.rows:
        for col_index, width in enumerate((3.0, 2.5, 6.0)):
            row.cells[col_index].width = Cm(width)

    # 第二页：验证 --pages 区间渲染
    document.add_paragraph().add_run().add_break(WD_BREAK.PAGE)
    document.add_heading("二、第二页内容", level=1)
    document.add_paragraph("这是第二页，用于验证 --pages 1-2 的区间渲染。")
    second = document.add_paragraph()
    second.add_run("结尾：").italic = True
    second.add_run("谢谢使用 office-kit。").font.color.rgb = RGBColor(0xC0, 0x00, 0x00)

    document.save(str(path))


def make_xlsx(path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "预算"
    rows = [
        ["项目", "金额", "备注"],
        ["设备", 1200, "一次性"],
        ["软件", 800, "年度"],
        ["合计", "=SUM(B2:B3)", "公式"],
        ["平均", "=AVERAGE(B2:B3)", "公式"],
    ]
    for row in rows:
        sheet.append(row)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill(fill_type="solid", start_color="DDEBF7", end_color="DDEBF7")
        cell.alignment = Alignment(horizontal="center")
    sheet["B2"].number_format = "#,##0.00"
    sheet["B3"].number_format = "#,##0.00"
    sheet["B4"].number_format = "#,##0.00"
    sheet["B5"].number_format = "#,##0.00"
    sheet.column_dimensions["A"].width = 12
    sheet.column_dimensions["B"].width = 14
    sheet.column_dimensions["C"].width = 18
    sheet.freeze_panes = "A2"

    detail = workbook.create_sheet("明细")
    detail.append(["订单号", "客户", "金额"])
    detail.append(["A001", "北京 某某科技有限公司", 500])
    detail.append(["A002", "上海 某某贸易有限公司", 700])
    detail.append(["A003", "广州 某某设计工作室", 800])
    detail.column_dimensions["B"].width = 30

    workbook.save(str(path))


def make_pptx(path: Path) -> None:
    from pptx import Presentation
    from pptx.util import Inches

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    presentation.core_properties.title = "自测演示"
    presentation.core_properties.author = "office-kit test"

    cover = presentation.slides.add_slide(presentation.slide_layouts[0])
    cover.shapes.title.text = "离线办公套件"
    if len(cover.placeholders) > 1:
        cover.placeholders[1].text = "自测演示文稿"

    content = presentation.slides.add_slide(presentation.slide_layouts[1])
    content.shapes.title.text = "能力列表"
    body = content.placeholders[1].text_frame
    body.text = "转换 PDF"
    for text, level in (("渲染 PNG", 0), ("按页/按区域", 1), ("公式重算", 0)):
        paragraph = body.add_paragraph()
        paragraph.text = text
        paragraph.level = level
    content.notes_slide.notes_text_frame.text = "这是备注，用于验证 pptx 备注读取。"

    table_slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    table_slide.shapes.title.text = "指标"
    shape = table_slide.shapes.add_table(
        3, 2, Inches(0.8), Inches(1.6), Inches(11.5), Inches(2.2)
    )
    table = shape.table
    data = [["指标", "数值"], ["转换成功率", "100%"], ["离线", "是"]]
    for row_index, row in enumerate(data):
        for col_index, value in enumerate(row):
            table.cell(row_index, col_index).text = value
            if row_index == 0:
                for paragraph in table.cell(row_index, col_index).text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.bold = True

    presentation.save(str(path))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("用法: make_fixtures.py OUTDIR", file=sys.stderr)
        return 2
    outdir = Path(argv[1]).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    make_docx(outdir / "自测 文档.docx")
    make_xlsx(outdir / "预算 表.xlsx")
    make_pptx(outdir / "汇报 演示.pptx")
    print(f"已生成测试素材: {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
