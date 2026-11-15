#!/usr/bin/env python3
"""把员工上传的文件读成纯文本。

支持：.txt .md .csv .tsv .json .html .htm .docx（zip+xml 手拆），
以及在装了 pypdf 时的 .pdf。老式 .doc/.xls 这类二进制格式不硬啃，
直接说清楚「另存为 docx 或 txt」，不猜内容。

设计原则：读不出来就说读不出来。宁可报错，也不要把 0 字当成「这份资料是空的」。
"""
import csv
import io
import json
import os
import re
import zipfile
from pathlib import Path

MAX_BYTES = int(os.environ.get("DOC_MAX_BYTES", str(20 * 1024 * 1024)))
MAX_CHARS = int(os.environ.get("DOC_MAX_CHARS", str(400000)))

TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".html", ".htm",
                 ".text", ".log", ".xml", ".yaml", ".yml"}
BLOCK_TAGS = re.compile(r"</?(p|div|br|li|tr|h[1-6]|section|article|table|ul|ol|blockquote)[^>]*>", re.I)


class ReadError(Exception):
    """读文件失败。message 直接展示给使用者。"""


def _decode(raw):
    """按出现顺序试几种编码。中文资料常见 UTF-8 与 GB18030，别一上来就 replace 成问号。"""
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "utf-16", "big5"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace"), "utf-8(有替换字符)"


def _html_to_text(html):
    html = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    text = BLOCK_TAGS.sub("\n", html)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    import html as _html
    return _html.unescape(text)


def _docx_to_text(path):
    try:
        with zipfile.ZipFile(path) as bundle:
            names = [n for n in bundle.namelist() if n.startswith("word/") and n.endswith(".xml")]
            if "word/document.xml" not in names:
                raise ReadError("这个 .docx 里没有正文（word/document.xml），可能不是 Word 文档。")
            xml = bundle.read("word/document.xml").decode("utf-8", "replace")
    except zipfile.BadZipFile:
        raise ReadError("这个 .docx 打不开（不是有效的 Word 文件）。如果它是老的 .doc，请在 Word 里另存为 .docx。")
    # 段落边界：</w:p> 换行；<w:tab/> 制表；其余标签去掉
    xml = re.sub(r"(?i)</w:p>", "\n", xml)
    xml = re.sub(r"(?i)<w:tab[^>]*/>", "\t", xml)
    xml = re.sub(r"(?i)<w:br[^>]*/>", "\n", xml)
    text = re.sub(r"(?s)<[^>]+>", "", xml)
    import html as _html
    return _html.unescape(text)


def _pdf_to_text(path):
    try:
        from pypdf import PdfReader  # 可选依赖
    except ImportError:
        raise ReadError("这台机器没装 pypdf，读不了 PDF。可以装一下（pip install pypdf），"
                        "或者把 PDF 里的正文复制粘贴进来。")
    try:
        reader = PdfReader(str(path))
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        text = "\n".join(pages)
    except Exception as error:
        raise ReadError("PDF 解析失败：%s" % error)
    if len(text.strip()) < 20:
        raise ReadError("这个 PDF 里的文字提取不出来（可能是扫描件）。先用 OCR 转成文本，或把正文粘贴进来。")
    return text


def _csv_to_text(raw, suffix):
    delimiter = "\t" if suffix == ".tsv" else ","
    text, _ = _decode(raw)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error:
        return text
    lines = []
    for row in rows:
        cells = [cell.strip() for cell in row if cell.strip()]
        if cells:
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def read_bytes(raw, filename=""):
    """从字节读文本。返回 {text, encoding, kind, chars, truncated, note}。"""
    suffix = Path(filename or "").suffix.lower()
    if len(raw) > MAX_BYTES:
        raise ReadError("文件太大了（%s MB）。上限是 %s MB，先拆分一下。"
                        % (round(len(raw) / 1048576, 1), MAX_BYTES // 1048576))
    if not raw:
        raise ReadError("文件是空的（0 字节）。")

    note, encoding, kind = "", "utf-8", suffix.lstrip(".") or "文本"
    if suffix == ".docx":
        text = _docx_to_text(io.BytesIO(raw))
        encoding, kind = "utf-8", "docx"
    elif suffix == ".pdf":
        buffer = io.BytesIO(raw)
        text = _pdf_to_text(buffer)
        encoding, kind = "文本层", "pdf"
    elif suffix in (".csv", ".tsv"):
        text = _csv_to_text(raw, suffix)
        encoding, kind = "按分隔符", kind
    elif suffix in (".html", ".htm"):
        decoded, encoding = _decode(raw)
        text = _html_to_text(decoded)
        kind = "html"
    elif suffix == ".json":
        decoded, encoding = _decode(raw)
        try:
            text = json.dumps(json.loads(decoded), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            text, note = decoded, "JSON 解析失败，按纯文本读了"
        kind = "json"
    elif suffix in TEXT_SUFFIXES or suffix == "":
        text, encoding = _decode(raw)
        # 有大量不可打印字节，多半是二进制被当成文本上传了
        weird = sum(1 for ch in text[:4000] if ord(ch) < 9 or (13 < ord(ch) < 32))
        if len(text) >= 200 and weird > len(text[:4000]) * 0.05:
            raise ReadError("这个文件看起来不是文本（里面是二进制内容）。"
                            "如果是 Word/Excel，请上传 .docx/.csv；如果是扫描件，请先把文字提取出来。")
    elif suffix in (".doc", ".xls", ".ppt", ".wps", ".et"):
        raise ReadError("老式 Office 格式（%s）读不了。请在 Office/WPS 里另存为 .docx / .csv，或直接粘贴正文。"
                        % suffix)
    else:
        raise ReadError("还不支持 %s 这类文件。可以上传 txt / md / csv / json / html / docx / pdf，"
                        "或直接把正文粘贴进来。" % (suffix or "这种"))

    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ReadError("读出来是空的。文件里可能只有图片或表格结构，没有可读文字。")
    truncated = False
    if len(text) > MAX_CHARS:
        text, truncated = text[:MAX_CHARS], True
        note = (note + "；" if note else "") + "正文超长，只取了前 %d 字" % MAX_CHARS
    return {"text": text, "encoding": encoding, "kind": kind,
            "chars": len(text), "truncated": truncated, "note": note}


def read_file(path):
    """从磁盘读。"""
    path = Path(path)
    if not path.exists():
        raise ReadError("文件不存在：%s" % path.name)
    return read_bytes(path.read_bytes(), path.name)


def status():
    try:
        import pypdf  # noqa: F401
        pdf = True
    except ImportError:
        pdf = False
    return {"max_mb": MAX_BYTES // 1048576, "max_chars": MAX_CHARS,
            "formats": ["txt", "md", "csv", "tsv", "json", "html", "docx"] + (["pdf"] if pdf else []),
            "pdf": pdf}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print(json.dumps(status(), ensure_ascii=False))
        raise SystemExit(0)
    info = read_file(sys.argv[1])
    print(json.dumps({k: v for k, v in info.items() if k != "text"}, ensure_ascii=False))
    print(info["text"][:1500])
