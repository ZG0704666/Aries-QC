"""回归门禁报告：Markdown 报告 + JSON 产物写入。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict


def write_artifacts(run_dir: Path, comparison: Dict, decision: Dict, metadata: Dict) -> list[dict]:
    """写 comparison.json / decision.json / report.md，返回产物清单。"""
    _write_json(run_dir / 'comparison.json', comparison)
    _write_json(run_dir / 'decision.json', decision)
    markdown = _markdown(comparison, decision, metadata)
    (run_dir / 'report.md').write_text(markdown, encoding='utf-8')
    artifacts = []
    for name in ('comparison.json', 'decision.json', 'report.md'):
        path = run_dir / name
        if path.exists():
            artifacts.append({'name': name, 'size': path.stat().st_size})
    return artifacts


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _markdown(comparison: Dict, decision: Dict, metadata: Dict) -> str:
    overall = comparison['overall']
    lines = [
        '# 模型回归门禁报告',
        '',
        f"- 数据集：{metadata.get('dataset_name', '—')}",
        f"- 基线模型：{comparison.get('baseline_backend', '—')}",
        f"- 候选模型：{comparison.get('candidate_backend', '—')}",
        f"- 判定：**{decision['verdict']}** — {decision['summary']}",
        '',
        '## 实际推理运行信息',
        '',
        _runtime_line('基线', overall.get('baseline', {}).get('runtime')),
        _runtime_line('候选', overall.get('candidate', {}).get('runtime')),
        '',
        '## 整体指标对比',
        '',
        '| 指标 | 基线 | 候选 | 变化 |',
        '| --- | --- | --- | --- |',
    ]
    for key, label in (('precision', '精确率'), ('recall', '召回率'), ('f1', 'F1 分数'), ('ap50', 'mAP50')):
        base = overall['baseline'][key]
        cand = overall['candidate'][key]
        drop = overall['drop'][key]
        arrow = '↓' if drop > 0 else ('↑' if drop < 0 else '—')
        lines.append(f'| {label} | {base:.4f} | {cand:.4f} | {drop:+.4f} {arrow} |')

    lines += ['', '## 逐类指标对比', '', '| 类别 | 基线 AP50 | 候选 AP50 | 跌幅 | 状态 |', '| --- | --- | --- | --- | --- |']
    for cls_name, cls_compare in comparison['per_class'].items():
        status = '❌ 退化' if cls_compare['degraded'] else ('➖ 持平' if cls_compare['drop']['ap50'] == 0 else '✅ 提升')
        lines.append(
            f"| {cls_name} | {cls_compare['baseline']['ap50']:.4f} | {cls_compare['candidate']['ap50']:.4f} | "
            f"{cls_compare['drop']['ap50']:+.4f} | {status} |")

    lines += ['', '## 判定原因', '']
    lines += [f'- {reason}' for reason in decision['reasons']]

    if decision['suggestions']:
        lines += ['', '## 处理建议', '']
        for suggestion in decision['suggestions']:
            lines.append(f"- **[{suggestion['priority'].upper()}] {suggestion['action']}**：{suggestion['detail']}")

    lines += ['', f"候选模型新增漏检 {len(comparison['missed_cases'])} 条，新增错检 {len(comparison['false_positive_cases'])} 条。"]
    return '\n'.join(lines) + '\n'


def _runtime_line(label: str, runtime: dict | None) -> str:
    if not runtime:
        return f'- {label}：暂无运行信息'
    return (f"- {label}：设备 **{runtime.get('device', '—')}**，"
            f"实际耗时 **{runtime.get('elapsed_seconds', '—')} 秒**，"
            f"处理 **{runtime.get('images', '—')} 张**，"
            f"{runtime.get('images_per_second', '—')} 张/秒")
