# -*- coding: utf-8 -*-
"""chat-shot 命令行：读配置 → 生成对话 HTML → 截图 → 生成对话图集 docx。

用法示例：
    python src/cli.py --config config/项目一.json --out "D:\\作业\\项目一_WPS文字处理"
    python src/cli.py --config config/项目一.json config/项目二.json \
        --out-root "D:\\作业\\新建文件夹 (2)" --name 鹕安
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render  # noqa: E402
import template  # noqa: E402
from docx_builder import build_docx  # noqa: E402


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    if "turns" not in cfg or not cfg["turns"]:
        raise SystemExit(f"配置缺少 turns：{path}")
    return cfg


def run_one(cfg: dict, out_dir: str, name: str | None, shots: int | None,
            size, dpr, keep_html: str | None) -> dict:
    project = cfg.get("project") or "对话"
    username = name or cfg.get("username") or "我"
    shots = shots or int(cfg.get("shots", 8))
    size = size or tuple(cfg.get("size", [1440, 900]))
    dpr = dpr or int(cfg.get("dpr", 2))

    work = keep_html or tempfile.mkdtemp(prefix="chat-shot-")
    os.makedirs(work, exist_ok=True)
    html_path = os.path.join(work, f"{project}.html")
    template.build({"title": project}, cfg["turns"], username,
                   out_path=html_path, history=cfg.get("history", []))

    img_dir = os.path.join(out_dir, "_对话图")
    images = render.render_html(html_path, img_dir, f"{project}_对话图", shots=shots, size=size, dpr=dpr)

    docx_name = cfg.get("docx_name") or f"{project}_对话图集（仅图片）.docx"
    docx_path = build_docx(images, os.path.join(out_dir, docx_name),
                           title=f"{project} 对话图集（仅图片）", author=username)

    return {"project": project, "username": username, "images": len(images),
            "out_dir": out_dir, "docx": docx_path}


def main() -> None:
    ap = argparse.ArgumentParser(description="对话图生成器：配置 → 截图 → 图集")
    ap.add_argument("--config", nargs="+", required=True, help="一个或多个 JSON 配置")
    ap.add_argument("--out", help="单个配置的输出目录（与 --out-root 二选一）")
    ap.add_argument("--out-root", help="批量输出根目录，配合配置里的 out_subdir")
    ap.add_argument("--name", help="覆盖配置里的账号名")
    ap.add_argument("--shots", type=int, help="每个项目截几张，默认读配置或 8")
    ap.add_argument("--size", help="窗口尺寸，如 1440x900")
    ap.add_argument("--dpr", type=int, help="像素倍率，默认 2")
    ap.add_argument("--keep-html", help="保留生成的 HTML 到这个目录（调试用）")
    args = ap.parse_args()

    size = None
    if args.size:
        w, h = args.size.lower().split("x")
        size = (int(w), int(h))

    if len(args.config) > 1 and not args.out_root:
        raise SystemExit("多个配置时请用 --out-root")
    if not args.out_root and not args.out:
        raise SystemExit("请给 --out（单配置）或 --out-root（批量）")

    results = []
    for path in args.config:
        cfg = load_config(path)
        out_dir = args.out_root if args.out_root else args.out
        if args.out_root:
            out_dir = os.path.join(args.out_root, cfg.get("out_subdir") or cfg["project"])
        results.append(run_one(cfg, out_dir, args.name, args.shots, size, args.dpr, args.keep_html))

    print(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
