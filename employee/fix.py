"""修复预览与导出：只生成新文件，绝不覆盖原始标签。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .dataset import Batch, LabelObject
from .findings import iou
from .merge_guard import ClassMap


def preview_fix(batch: Batch, class_map: ClassMap, findings: list, out_dir: Path) -> dict:
    out_dir = Path(out_dir)
    fixed_root = out_dir / 'fixed'
    if fixed_root.exists():
        shutil.rmtree(fixed_root, ignore_errors=True)
    fixed_root.mkdir(parents=True, exist_ok=True)
    (out_dir / 'class_map.json').write_text(
        json.dumps(class_map.to_dict(), ensure_ascii=False, indent=2), encoding='utf-8')

    action_counts: dict[str, int] = {}
    diff: list[dict] = []
    manual: list[dict] = []
    changed_files = 0

    finding_by_sample: dict[int, list] = {}
    for finding in findings:
        sample_id = finding.subject.get('sample_id')
        if sample_id is not None:
            finding_by_sample.setdefault(sample_id, []).append(finding)

    for sample in batch.samples:
        if sample.label_state == 'malformed':
            manual.append({
                'sample_id': sample.id,
                'image_rel': sample.image_rel,
                'reason': '标签存在格式错误，自动修复可能丢数据，转人工',
                'findings': [f.id for f in finding_by_sample.get(sample.id, [])],
            })
            continue
        if not sample.label_path or sample.label_state not in ('ok', 'empty'):
            continue
        names_count = len(batch.names_for(sample.batch))
        objects = list(sample.objects)
        actions: list[dict] = []
        kept: list[LabelObject] = []
        for obj in objects:
            if names_count and (obj.cls_id < 0 or obj.cls_id >= names_count):
                manual.append({
                    'sample_id': sample.id,
                    'image_rel': sample.image_rel,
                    'reason': f'类别 ID {obj.cls_id} 越界，无法安全映射',
                    'findings': [f.id for f in finding_by_sample.get(sample.id, [])],
                })
                kept = []
                actions = []
                break
            new_cls = class_map.remap(sample.batch, obj.cls_id)
            if new_cls != obj.cls_id:
                actions.append({'kind': 'class_remap', 'line': obj.line_no,
                                'from': obj.cls_id, 'to': new_cls})
            coords = [min(1.0, max(0.0, float(v))) for v in obj.coords]
            if coords != obj.coords:
                actions.append({'kind': 'clamp_coords', 'line': obj.line_no,
                                'changed': sum(1 for a, b in zip(coords, obj.coords) if a != b)})
            candidate = LabelObject(new_cls, obj.kind, coords,
                                    _bbox(kind=obj.kind, coords=coords), obj.line_no, obj.raw)
            if candidate.kind == 'box' and (candidate.bbox[2] <= 1e-8 or candidate.bbox[3] <= 1e-8):
                actions.append({'kind': 'drop_zero_area', 'line': obj.line_no})
                continue
            duplicate = None
            for previous in kept:
                if previous.cls_id == candidate.cls_id and iou(previous.bbox, candidate.bbox) >= 0.98:
                    duplicate = previous
                    break
            if duplicate is not None:
                actions.append({'kind': 'drop_duplicate_box', 'line': obj.line_no,
                                'kept_line': duplicate.line_no})
                continue
            kept.append(candidate)
        if not actions:
            continue
        # 全部对象都被丢弃时仍写出空文件，表示"清空重复/无效标注"
        target_dir = fixed_root / sample.batch / (Path(sample.label_rel).parent if sample.label_rel else Path('.'))
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / Path(sample.label_rel or f'labels/{sample.stem}.txt').name
        before = Path(sample.label_path).read_text(encoding='utf-8-sig', errors='replace') if sample.label_path else ''
        after = '\n'.join(_format_object(obj) for obj in kept)
        if after:
            after += '\n'
        target.write_text(after, encoding='utf-8')
        changed_files += 1
        for action in actions:
            action_counts[action['kind']] = action_counts.get(action['kind'], 0) + 1
        diff.append({
            'sample_id': sample.id,
            'batch': sample.batch,
            'image_rel': sample.image_rel,
            'label_rel': sample.label_rel,
            'output_rel': str(target.relative_to(out_dir)).replace('\\', '/'),
            'actions': actions,
            'before_lines': len(before.splitlines()),
            'after_lines': len(after.splitlines()) if after else 0,
        })

    (out_dir / 'fix_diff.json').write_text(json.dumps({
        'changed_files': changed_files,
        'actions': action_counts,
        'diff': diff,
        'manual': manual,
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return {
        'available': changed_files > 0,
        'changed_files': changed_files,
        'actions': action_counts,
        'manual_count': len(manual),
        'manual': manual[:50],
        'diff_preview': diff[:30],
        'note': '修复文件写在 runs/<id>/fixed/ 下，原始标签未改动；导出前必须人工确认。',
    }


def _bbox(kind: str, coords: list[float]) -> tuple[float, float, float, float]:
    if kind == 'box':
        return tuple(coords)  # type: ignore[return-value]
    xs = coords[0::2]
    ys = coords[1::2]
    return (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, max(xs) - min(xs), max(ys) - min(ys)


def _format_object(obj: LabelObject) -> str:
    return str(obj.cls_id) + ' ' + ' '.join(f'{v:.6f}' for v in obj.coords)