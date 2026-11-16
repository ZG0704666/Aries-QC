# -*- coding: utf-8 -*-
"""把一组截图拼成《对话图集（仅图片）》docx：每页一张图。"""
from __future__ import annotations

import os

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


def build_docx(
    images: list[str],
    out_path: str,
    title: str,
    author: str = "",
    width_inch: float = 7.0,
) -> str:
    if not images:
        raise ValueError("images 为空")
    doc = Document()
    sec = doc.sections[0]
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(sec, attr, Inches(0.6))

    head = doc.add_paragraph()
    head.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = head.add_run(title)
    run.bold = True
    run.font.size = Pt(14)

    for i, img in enumerate(images, 1):
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        cr = cap.add_run(f"图 {i}（共 {len(images)} 张）")
        cr.font.size = Pt(9)
        pic = doc.add_paragraph()
        pic.alignment = WD_ALIGN_PARAGRAPH.CENTER
        pic.add_run().add_picture(img, width=Inches(width_inch))
        if i < len(images):
            doc.add_page_break()

    if author:
        doc.core_properties.author = author
        doc.core_properties.last_modified_by = author
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    doc.save(out_path)
    return out_path
