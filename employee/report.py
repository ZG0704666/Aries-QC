"""交付包生成：HTML / Markdown / JSON / CSV / 证据缩略图 / ZIP。"""
from __future__ import annotations

import base64
import html
import json
import zipfile
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from .dataset import Batch
from .findings import SEVERITY_ORDER
from .merge_guard import ClassMap
from .recollect import to_csv
from .spec import Spec


COLORS = {'P0': (60, 60, 240), 'P1': (40, 170, 250), 'P2': (60, 200, 220)}
HEX = {'P0': '#ff5f56', 'P1': '#ffb020', 'P2': '#4dd0e1'}


def build_artifacts(*, run_dir: Path, state: dict, batch: Batch, spec: Spec | None,
                    class_map: ClassMap | None, findings: list, coverage: dict,
                    task_plan: dict, recollect: list, fix_summary: dict) -> list[dict]:
    run_dir = Path(run_dir)
    evidence_dir = run_dir / 'evidence'
    evidence_dir.mkdir(exist_ok=True)

    summary = _summary(state, batch, spec, class_map, findings, coverage, task_plan,
                       recollect, fix_summary)
    _write_json(run_dir / 'summary.json', summary)
    _write_json(run_dir / 'findings.json', findings)
    _write_json(run_dir / 'coverage.json', coverage)
    if class_map is not None:
        _write_json(run_dir / 'classes.json', class_map.to_dict())
    if spec is not None:
        _write_json(run_dir / 'spec.json', spec.to_dict(include_source=True))

    thumbs = _render_evidence(run_dir, batch, findings)
    markdown = _markdown(summary, findings, coverage, task_plan, recollect, fix_summary)
    (run_dir / 'report.md').write_text(markdown, encoding='utf-8')
    (run_dir / 'task_plan.md').write_text(_task_plan_md(task_plan), encoding='utf-8')
    html_text = _html(summary, findings, coverage, task_plan, recollect, fix_summary, thumbs)
    (run_dir / 'report.html').write_text(html_text, encoding='utf-8')

    # 修复后的标签目录清单
    fixed_files = []
    fixed_root = run_dir / 'fixed'
    if fixed_root.exists():
        fixed_files = [p for p in fixed_root.rglob('*') if p.is_file()]

    zip_path = run_dir / 'delivery.zip'
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in ('report.html', 'report.md', 'summary.json', 'findings.json', 'classes.json',
                     'coverage.json', 'spec.json', 'task_plan.json', 'task_plan.md',
                     'recollect.csv', 'recollect.json', 'fix_diff.json', 'class_map.json',
                     'trace.jsonl'):
            path = run_dir / name
            if path.exists():
                archive.write(path, name)
        for path in fixed_files:
            archive.write(path, str(path.relative_to(run_dir)).replace('\\', '/'))
        for path in evidence_dir.glob('*.jpg'):
            archive.write(path, 'evidence/' + path.name)
        archive.writestr('README.txt', _delivery_readme(summary, bool(fixed_files)))

    artifacts = []
    for name in ('report.html', 'report.md', 'summary.json', 'findings.json', 'recollect.csv',
                 'recollect.json', 'task_plan.json', 'coverage.json', 'classes.json',
                 'fix_diff.json', 'delivery.zip'):
        path = run_dir / name
        if path.exists():
            artifacts.append({'name': name, 'size': path.stat().st_size})
    return artifacts


def _summary(state, batch, spec, class_map, findings, coverage, task_plan,
             recollect, fix_summary) -> dict:
    counts = Counter(f['severity'] for f in findings)
    confidence = Counter(f['confidence'] for f in findings)
    checks = Counter(f['check'] for f in findings)
    stats = batch.stats()
    return {
        'run_id': state.get('id'),
        'created_at': state.get('created_at'),
        'finished_at': state.get('finished_at'),
        'project': (spec.data.get('project') if spec else '') or '',
        'batch': {
            'root': str(batch.root),
            'fingerprint': (state.get('batch') or {}).get('fingerprint'),
            'stats': stats,
        },
        'spec': {
            'method': spec.method if spec else 'none',
            'source_name': spec.source_name if spec else '',
            'label_format': spec.data.get('label_format') if spec else '',
            'classes': spec.class_names if spec else [],
            'evidence_check': spec.evidence_check if spec else {},
            'missing': spec.missing if spec else [],
            'conflicts': spec.conflicts if spec else [],
            'error': spec.error if spec else '',
        },
        'classes': class_map.to_dict() if class_map else {},
        'findings': {
            'total': len(findings),
            'by_severity': dict(counts),
            'by_confidence': dict(confidence),
            'by_check': dict(checks),
            'accepted': sum(1 for f in findings if f['status'] == 'accepted'),
            'rejected': sum(1 for f in findings if f['status'] == 'rejected'),
        },
        'coverage': coverage,
        'task_plan': task_plan,
        'recollect': {
            'total': len(recollect),
            'by_priority': dict(Counter(x['priority'] for x in recollect)),
            'items': recollect,
        },
        'fix': {k: v for k, v in fix_summary.items() if k != 'diff_preview'},
        'probe': state.get('probe') or {},
        'llm': state.get('llm') or {},
        'summary': state.get('summary') or {},
        'limitations': (state.get('summary') or {}).get('limitations') or [],
    }


def _render_evidence(run_dir: Path, batch: Batch, findings: list, limit: int = 36) -> dict:
    thumbs: dict[str, str] = {}
    by_sample: dict[int, list] = {}
    for finding in findings:
        sample_id = finding.get('subject', {}).get('sample_id')
        if sample_id is not None:
            by_sample.setdefault(sample_id, []).append(finding)
    # 优先 P0/P1，每个样图只取一次，保证证据多样
    ordered = sorted(by_sample.items(), key=lambda kv: (
        min(SEVERITY_ORDER.get(f['severity'], 9) for f in kv[1]), kv[0]))
    samples = {s.id: s for s in batch.samples}
    for sample_id, items in ordered[:limit]:
        sample = samples.get(sample_id)
        if sample is None or not sample.readable:
            continue
        image = _load(sample.image_path)
        if image is None:
            continue
        canvas = image.copy()
        names = batch.names_for(sample.batch)
        # 第一层：GT 标注（绿色）
        for obj in sample.objects:
            _draw_object(canvas, obj, (80, 220, 120), 2)
        # 第二层：finding 证据（按严重度）
        focus = items[0]
        for finding in items[:4]:
            bbox = finding.get('subject', {}).get('bbox')
            if not bbox:
                continue
            color = COLORS.get(finding['severity'], (255, 255, 255))
            _draw_box(canvas, bbox, color, 2)
            label = f"{finding['severity']} {finding['check']}"
            _put_label(canvas, label, (int(bbox[0] * canvas.shape[1]), int(bbox[1] * canvas.shape[0])), color)
        if not items[0].get('subject', {}).get('bbox'):
            _put_label(canvas, f"{items[0]['severity']} {items[0]['check']}", (12, 24),
                       COLORS.get(items[0]['severity'], (255, 255, 255)))
        height, width = canvas.shape[:2]
        if width > 760:
            scale = 760 / width
            canvas = cv2.resize(canvas, (760, int(height * scale)), interpolation=cv2.INTER_AREA)
        name = f'evidence_{sample_id:05d}.jpg'
        path = run_dir / 'evidence' / name
        ok, encoded = cv2.imencode('.jpg', canvas, [int(cv2.IMWRITE_JPEG_QUALITY), 78])
        if not ok:
            continue
        path.write_bytes(encoded.tobytes())
        thumbs[focus['id']] = base64.b64encode(encoded.tobytes()).decode()
    return thumbs


def _load(path: str):
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _draw_object(canvas, obj, color, thickness) -> None:
    height, width = canvas.shape[:2]
    if obj.kind == 'polygon':
        points = np.array([[int(x * width), int(y * height)] for x, y in zip(obj.coords[0::2], obj.coords[1::2])],
                          dtype=np.int32)
        if len(points) >= 3:
            cv2.polylines(canvas, [points], True, color, max(1, int(thickness / 4)))
    else:
        _draw_box(canvas, obj.bbox, color, max(1, int(thickness / 4)))


def _draw_box(canvas, bbox, color, thickness=2) -> None:
    height, width = canvas.shape[:2]
    cx, cy, w, h = bbox
    x1, y1 = int((cx - w / 2) * width), int((cy - h / 2) * height)
    x2, y2 = int((cx + w / 2) * width), int((cy + h / 2) * height)
    cv2.rectangle(canvas, (x1, y1), (x2, y2), color, thickness)


def _put_label(canvas, text, origin, color) -> None:
    x, y = max(4, origin[0]), max(18, origin[1])
    (tw, th), _ = cv2.getTextSize(text[:48], cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
    cv2.rectangle(canvas, (x - 2, y - th - 4), (x + tw + 4, y + 4), (20, 20, 20), -1)
    cv2.putText(canvas, text[:48], (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def _markdown(summary, findings, coverage, task_plan, recollect, fix_summary) -> str:
    lines = [
        f"# {summary.get('project') or '数据质检'} · 质检交付报告",
        '',
        f"- 批次：`{summary['batch']['root']}`",
        f"- 指纹：`{(summary['batch'].get('fingerprint') or {}).get('fingerprint', '')}`",
        f"- 规范：{summary['spec'].get('source_name', '')}（{summary['spec'].get('method', '')}）",
        f"- 结论：**{_gate_text(summary)}**",
        f"- 覆盖率：{coverage.get('score')}%",
        '',
        '## 1. 摘要',
        '',
        summary.get('summary', {}).get('headline', ''),
        '',
        '## 2. 任务拆解',
        '',
        '| 角色 | 人数 | 工时 | 职责 |',
        '|---|---|---|---|',
    ]
    for role in task_plan.get('roles', []):
        lines.append(f"| {role['role']} | {role['headcount']} | {role['hours']}h | {role['responsibility']} |")
    effort = task_plan.get('effort', {})
    lines += ['', f"总工时 **{effort.get('total_hours', 0)}h**，建议投入 **{effort.get('headcount', 0)} 人**。", '',
              '## 3. 标签体系', '', '| Canonical ID | 类别 | 来源批次 |', '|---|---|---|']
    for item in summary.get('classes', {}).get('classes', []):
        sources = '；'.join(f"{s['batch']}:{s['old_id']}" for s in item.get('sources', []))
        lines.append(f"| {item['canonical_id']} | {item['name']} | {sources} |")
    lines += ['', '## 4. 质检结果', '',
              f"- P0：{summary['findings']['by_severity'].get('P0', 0)}",
              f"- P1：{summary['findings']['by_severity'].get('P1', 0)}",
              f"- P2：{summary['findings']['by_severity'].get('P2', 0)}",
              '', '| 严重度 | 检查项 | 消息 | 置信度 |', '|---|---|---|---|']
    for finding in findings[:60]:
        lines.append(f"| {finding['severity']} | {finding['check']} | {finding['message']} | {finding['confidence']} |")
    lines += ['', '## 5. 补采清单', '',
              '| 编号 | 优先级 | 目标 | 缺口 | 动作 | 验收标准 |', '|---|---|---|---|---|---|']
    for item in recollect:
        lines.append(f"| {item['id']} | {item['priority']} | {item['target']} | {item['gap']} | "
                     f"{item['action']} | {item['acceptance']} |")
    lines += ['', '## 6. 修复预览', '',
              f"- 可自动修复文件：{fix_summary.get('changed_files', 0)}",
              f"- 动作统计：{json.dumps(fix_summary.get('actions', {}), ensure_ascii=False)}",
              f"- 转人工：{fix_summary.get('manual_count', 0)}",
              f"- {fix_summary.get('note', '')}",
              '', '## 7. 方法与边界', '']
    for item in summary.get('limitations', []):
        lines.append(f'- {item}')
    lines += ['', '> 本报告由「Aries QC」AI 数据质检员工生成；所有数字由脚本计算，候选问题须人工裁定后执行。']
    return '\n'.join(lines)


def _html(summary, findings, coverage, task_plan, recollect, fix_summary, thumbs) -> str:
    esc = html.escape
    gate = summary.get('summary', {}).get('gate', '')
    gate_text = _gate_text(summary)
    gate_color = {'blocked': '#ff5f56', 'at_risk': '#ffb020', 'pass': '#7bd88f'}.get(gate, '#9aa4b2')
    cards = [
        ('图像', summary['batch']['stats'].get('images', 0), '张'),
        ('实例', summary['batch']['stats'].get('objects', 0), '个'),
        ('P0', summary['findings']['by_severity'].get('P0', 0), '条硬伤'),
        ('P1', summary['findings']['by_severity'].get('P1', 0), '条高风险'),
        ('覆盖', summary['coverage'].get('score', '—'), '%'),
    ]
    rows = []
    for finding in findings[:120]:
        thumb = thumbs.get(finding['id'])
        image = (f'<img src="data:image/jpeg;base64,{thumb}" alt="evidence">'
                 if thumb else '')
        rows.append(f'''<tr class="sev-{finding['severity'].lower()}">
<td><span class="badge {finding['severity'].lower()}">{finding['severity']}</span></td>
<td><code>{esc(finding['check'])}</code><div class="muted">{esc(finding['confidence'])}</div></td>
<td>{esc(finding['message'])}</td>
<td>{esc(finding.get('subject', {}).get('image_rel', ''))}</td>
<td>{image}</td></tr>''')
    collect_rows = []
    for item in recollect:
        collect_rows.append(f'''<tr>
<td>{esc(item['id'])}</td><td><span class="badge {item['priority'].lower()}">{item['priority']}</span></td>
<td>{esc(item['target'])}</td><td>{item['current']} / {item['required']}</td>
<td>{esc(item['reason'])}</td><td>{esc(item['action'])}</td><td>{esc(item['acceptance'])}</td></tr>''')
    class_rows = []
    for item in summary.get('classes', {}).get('classes', []):
        sources = '；'.join(f"{s['batch']}:{s['old_id']}" for s in item.get('sources', []))
        class_rows.append(f"<tr><td>{item['canonical_id']}</td><td>{esc(item['name'])}</td>"
                          f"<td>{esc(sources)}</td><td>{'是' if item.get('in_spec') else '否'}</td></tr>")
    role_rows = []
    for role in task_plan.get('roles', []):
        role_rows.append(f"<tr><td>{esc(role['role'])}</td><td>{role['headcount']}</td>"
                         f"<td>{role['hours']}h</td><td>{esc(role['responsibility'])}</td></tr>")
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(summary.get('project') or '数据质检')} · 交付报告</title>
<style>
:root{{--bg:#0d1117;--panel:#161b22;--line:#242c38;--fg:#e6edf3;--muted:#8b98a9;--lime:#7bd88f;--cyan:#4dd0e1}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.7 "Segoe UI","Microsoft YaHei",sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:32px 22px 60px}}
header{{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:24px}}
h1{{font-size:26px;margin:0 0 6px}}h2{{font-size:18px;margin:34px 0 12px;color:var(--lime)}}
.muted{{color:var(--muted)}}.gate{{display:inline-block;padding:3px 10px;border:1px solid {gate_color};color:{gate_color};border-radius:999px;font-size:12px}}
.cards{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:18px 0}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}}
.card b{{display:block;font-size:26px;color:var(--cyan)}}.card span{{color:var(--muted);font-size:12px}}
table{{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:8px;overflow:hidden}}
th,td{{padding:9px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--muted);font-size:12px;font-weight:600}}tr:last-child td{{border-bottom:0}}
.badge{{display:inline-block;padding:1px 7px;border-radius:5px;font-size:11px;font-weight:700}}
.badge.p0{{background:#3a1416;color:#ff7b72}}.badge.p1{{background:#3a2a10;color:#ffb020}}.badge.p2{{background:#103034;color:#4dd0e1}}
img{{max-width:220px;border-radius:6px;border:1px solid var(--line)}}
code{{color:#d2a8ff}}pre{{background:var(--panel);padding:14px;border-radius:8px;overflow:auto}}
.note{{border-left:3px solid var(--cyan);padding:8px 14px;background:#101820;color:#b9c7d6}}
</style></head><body><div class="wrap">
<header><div class="muted">Aries QC · AI 数据采集与标注质检专员</div><h1>{esc(summary.get('project') or '数据质检交付报告')}</h1>
<div class="muted">批次 {esc(summary['batch']['root'])} · 指纹 {esc((summary['batch'].get('fingerprint') or {}).get('fingerprint', ''))} · 规范 {esc(summary['spec'].get('source_name', ''))}</div>
<p><span class="gate">{esc(gate_text)}</span></p>
<p>{esc(summary.get('summary', {}).get('headline', ''))}</p></header>
<div class="cards">{''.join(f'<div class="card"><b>{esc(str(v))}</b><span>{esc(k)} · {esc(u)}</span></div>' for k, v, u in cards)}</div>
<h2>1. 任务拆解</h2><table><tr><th>角色</th><th>人数</th><th>工时</th><th>职责</th></tr>{''.join(role_rows)}</table>
<h2>2. 标签体系</h2><table><tr><th>Canonical ID</th><th>类别</th><th>来源（批次:原 ID）</th><th>规范内</th></tr>{''.join(class_rows)}</table>
<h2>3. 质检报告</h2><p class="muted">P0 为确定性硬伤；P1/P2 中 candidate 为待人工裁定候选，不是已确认错误。完整明细见 findings.json。</p>
<table><tr><th>严重度</th><th>检查项</th><th>证据描述</th><th>图片</th><th>证据图</th></tr>{''.join(rows)}</table>
<h2>4. 补采清单</h2><table><tr><th>编号</th><th>优先级</th><th>目标</th><th>当前/要求</th><th>原因</th><th>动作</th><th>验收标准</th></tr>{''.join(collect_rows)}</table>
<h2>5. 修复预览</h2><p>可自动修复文件 <b>{fix_summary.get('changed_files', 0)}</b> 个，动作 {esc(json.dumps(fix_summary.get('actions', {}), ensure_ascii=False))}；转人工 {fix_summary.get('manual_count', 0)} 个。</p>
<p class="note">{esc(fix_summary.get('note', ''))}</p>
<h2>6. 方法与边界</h2><ul>{''.join(f'<li>{esc(x)}</li>' for x in summary.get('limitations', []))}</ul>
<p class="muted">本报告由「Aries QC」生成；所有数字由脚本计算，模型只做规范编译与文字归纳；候选问题须人工裁定后执行。</p>
</div></body></html>'''


def _task_plan_md(task_plan: dict) -> str:
    lines = ['# 任务拆解与人员安排', '']
    effort = task_plan.get('effort') or {}
    lines.append(f"- 总工时：{effort.get('total_hours', 0)}h")
    lines.append(f"- 建议人数：{effort.get('headcount', 0)}")
    lines.append(f"- 人工抽检：{effort.get('review_images', 0)} 张 / {effort.get('review_boxes', 0)} 个实例")
    lines += ['', '| 角色 | 人数 | 工时 | 职责 |', '|---|---|---|---|']
    for role in task_plan.get('roles') or []:
        lines.append(f"| {role['role']} | {role['headcount']} | {role['hours']}h | {role['responsibility']} |")
    lines += ['', '## 里程碑', '', '| 阶段 | 名称 | 产出 | 质量门 |', '|---|---|---|---|']
    for item in task_plan.get('milestones') or []:
        lines.append(f"| {item['day']} | {item['name']} | {item['output']} | {item['gate']} |")
    lines += ['', '## 计算假设', '', '```json',
              json.dumps(task_plan.get('assumptions') or {}, ensure_ascii=False, indent=2),
              '```', '', task_plan.get('note', '')]
    return '\n'.join(lines)


def _gate_text(summary) -> str:
    gate = summary.get('summary', {}).get('gate')
    return {'blocked': '不可交付：存在 P0 硬伤', 'at_risk': '有风险：覆盖率不足',
            'pass': '可进入人工复核'}.get(gate, '待评估')


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _delivery_readme(summary, has_fixed: bool) -> str:
    return f'''Aries QC · 数据质检交付包
======================
项目：{summary.get('project') or ''}
批次：{summary['batch']['root']}
指纹：{(summary['batch'].get('fingerprint') or {}).get('fingerprint', '')}
生成时间：{summary.get('finished_at') or summary.get('created_at')}

内容：
- report.html / report.md：交付报告
- summary.json：机器可读摘要
- findings.json：全部证据明细
- coverage.json：覆盖度核算
- classes.json / class_map.json：类别体系与映射
- task_plan.json / task_plan.md：任务拆解与人员安排
- recollect.csv / recollect.json：补采清单
- fix_diff.json：修复预览（原始标签未改动）
- evidence/：证据缩略图
- fixed/：修复后的标签（如有；导出前请人工确认）
- trace.jsonl：审计轨迹

边界：
1. 模型交叉复核只作候选，不是真值。
2. 候选问题必须人工裁定后执行。
3. 修复包不覆盖原始数据。
4. 本包不包含原始图片，避免数据外传。
'''