"""模型交叉复核：把模型预测当"第二意见"，只产出候选，不冒充真值。"""
from __future__ import annotations

import time
from pathlib import Path

from .dataset import Batch
from .findings import Finding, FindingBook, iou
from .merge_guard import ClassMap, norm


def _subject(sample, bbox=None, extra=None) -> dict:
    data = {
        'sample_id': sample.id,
        'image_rel': sample.image_rel,
        'label_rel': sample.label_rel or '',
        'batch': sample.batch,
        'split': sample.split,
        'scene': sample.scene,
        'stem': sample.stem,
        'width': sample.width,
        'height': sample.height,
    }
    if bbox is not None:
        data['bbox'] = [round(v, 6) for v in bbox]
    if extra:
        data.update(extra)
    return data


def _pick_samples(batch: Batch, max_images: int) -> list:
    samples = [s for s in batch.samples if s.readable]
    if max_images and max_images > 0 and len(samples) > max_images:
        stride = len(samples) / max_images
        samples = [samples[int(i * stride)] for i in range(max_images)]
    return samples


def _center_inside(inner: tuple, outer: tuple) -> bool:
    cx, cy = inner[0], inner[1]
    ox, oy, ow, oh = outer
    return ox - ow / 2 <= cx <= ox + ow / 2 and oy - oh / 2 <= cy <= oy + oh / 2


def run_probe(batch: Batch, class_map: ClassMap, spec: dict, model_path: str,
              options: dict | None = None, progress=None,
              skip_sample_ids: set[int] | None = None) -> tuple[FindingBook, dict]:
    options = options or {}
    book = FindingBook()
    meta: dict = {
        'requested': True,
        'available': False,
        'model_path': model_path,
        'limitations': [],
    }
    if not model_path or not Path(model_path).exists():
        meta['reason'] = '模型权重不存在'
        return book, meta
    try:
        from ultralytics import YOLO  # 懒加载：未安装时自动降级
    except Exception as error:
        meta['reason'] = f'ultralytics 不可用：{error}'
        meta['limitations'].append('未安装模型依赖，本次只跑确定性规则')
        return book, meta

    conf_threshold = float((spec.get('qc') or {}).get('model_conf') or 0.5)
    max_images = int(options.get('probe_max_images') or 0)
    max_findings = int(options.get('probe_max_findings') or 40)
    samples = _pick_samples(batch, max_images)
    if not samples:
        meta['reason'] = '没有可读图片'
        return book, meta

    started = time.time()
    try:
        model = YOLO(model_path)
        model_names = {int(k): str(v) for k, v in (model.names or {}).items()}
        canonical_by_norm = {norm(entry.name): entry.name for entry in class_map.classes}
        mapping = {i: canonical_by_norm.get(norm(name)) for i, name in model_names.items()}
        mapped_count = sum(1 for value in mapping.values() if value)
        if not mapped_count:
            meta.update({
                'reason': '模型类别表与当前批次类别无交集，跳过交叉复核',
                'model_names': list(model_names.values()),
            })
            return book, meta
        device = options.get('device')
        if not device:
            try:
                import torch
                device = '0' if torch.cuda.is_available() else 'cpu'
            except Exception:
                device = 'cpu'
        meta.update({'available': True, 'device': device, 'model_names': list(model_names.values()),
                     'mapped_classes': [v for v in mapping.values() if v]})
        paths = [s.image_path for s in samples]
        results = model.predict(paths, conf=min(0.25, conf_threshold), iou=0.7, imgsz=640,
                                device=device, verbose=False, stream=False, batch=16)
    except Exception as error:
        meta['reason'] = f'模型推理失败：{type(error).__name__}: {str(error)[:200]}'
        meta['limitations'].append('模型链路失败，本次只跑确定性规则')
        return book, meta

    if progress:
        progress(len(samples), len(samples))

    skip_sample_ids = skip_sample_ids or set()
    by_path = {str(s.image_path): s for s in samples}
    by_name = {Path(s.image_path).name: s for s in samples}
    missing_candidates: list[dict] = []
    confusion_candidates: list[dict] = []
    missing_by_scene: dict[tuple[str, str], list[dict]] = {}
    confusion_by_pair: dict[tuple[str, str], list[dict]] = {}
    total_preds = 0

    for result in results:
        path = str(result.path)
        sample = by_path.get(path)
        if sample is None:
            sample = by_name.get(Path(path).name)
        if sample is None:
            sample = next((s for s in samples if s.image_path == path), None)
        if sample is None:
            continue
        height, width = result.orig_shape[:2]
        preds = []
        for box, conf, cls in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(),
                                  result.boxes.cls.tolist()):
            x1, y1, x2, y2 = box
            bbox = ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height,
                    (x2 - x1) / width, (y2 - y1) / height)
            preds.append({'bbox': bbox, 'conf': float(conf), 'model_cls': int(cls),
                          'name': mapping.get(int(cls))})
        total_preds += len(preds)
        gt = [(obj, class_map.canonical_name(sample.batch, obj.cls_id)) for obj in sample.objects]
        for pred in preds:
            if pred['conf'] < conf_threshold or not pred['name']:
                continue
            best_iou, best_gt, best_name = 0.0, None, ''
            for obj, name in gt:
                value = iou(pred['bbox'], obj.bbox)
                if value > best_iou:
                    best_iou, best_gt, best_name = value, obj, name
            matched_by_center = bool(best_gt) and (
                _center_inside(pred['bbox'], best_gt.bbox) or _center_inside(best_gt.bbox, pred['bbox']))
            if best_iou < 0.2 and not matched_by_center:
                row = {'sample': sample, 'bbox': pred['bbox'], 'conf': pred['conf'],
                       'name': pred['name'], 'best_iou': best_iou,
                       'model_cls': pred['model_cls']}
                missing_candidates.append(row)
                missing_by_scene.setdefault((sample.scene, pred['name']), []).append(row)
            elif best_iou >= 0.5 and best_name and norm(best_name) != norm(pred['name']):
                row = {'sample': sample, 'bbox': pred['bbox'], 'conf': pred['conf'],
                       'pred_name': pred['name'], 'gt_name': best_name, 'iou': best_iou,
                       'model_cls': pred['model_cls']}
                confusion_candidates.append(row)
                confusion_by_pair.setdefault((pred['name'], best_name), []).append(row)

    # 每张图最多保留 2 条最高置信候选，再按置信度截断，避免报告被模型噪音淹没
    def select(rows: list[dict], limit: int) -> list[dict]:
        grouped: dict[int, list[dict]] = {}
        for row in rows:
            if row['sample'].id in skip_sample_ids:
                continue
            grouped.setdefault(row['sample'].id, []).append(row)
        selected: list[dict] = []
        for items in grouped.values():
            items.sort(key=lambda x: -x['conf'])
            selected.extend(items[:2])
        selected.sort(key=lambda x: -x['conf'])
        return selected[:limit]

    listed_missing = select(missing_candidates, max_findings)
    listed_confusion = select(confusion_candidates, max(10, max_findings // 2))

    for row in listed_missing:
        sample = row['sample']
        book.add(Finding(
            check='model_missing_label',
            severity='P1',
            confidence='candidate',
            title='疑似漏标（模型交叉复核）',
            message=(f'模型以 {row["conf"]:.2f} 置信度检出 {row["name"]}，'
                     f'但该位置没有对应标注（最大 IoU {row["best_iou"]:.2f}）'),
            subject=_subject(sample, row['bbox'], {
                'cls_name': row['name'],
                'model_cls': row['model_cls'],
            }),
            evidence={
                'model': Path(model_path).name,
                'model_class': row['name'],
                'confidence': round(row['conf'], 4),
                'best_iou_with_gt': round(row['best_iou'], 4),
                'threshold': conf_threshold,
                'total_candidates': len(missing_candidates),
                'listed_candidates': len(listed_missing),
            },
            suggested_fix={'kind': 'inspect_frame',
                           'description': '打开图片确认是漏标还是模型误检；人工裁定后才可修'},
            requires_human=True,
        ))
    for row in listed_confusion:
        sample = row['sample']
        book.add(Finding(
            check='model_class_mismatch',
            severity='P1',
            confidence='candidate',
            title='疑似类别错标（模型交叉复核）',
            message=(f'同一位置模型判为 {row["pred_name"]}（{row["conf"]:.2f}），'
                     f'标注为 {row["gt_name"]}，IoU {row["iou"]:.2f}'),
            subject=_subject(sample, row['bbox'], {
                'cls_name': row['pred_name'],
                'peer_cls_name': row['gt_name'],
            }),
            evidence={
                'model': Path(model_path).name,
                'prediction': row['pred_name'],
                'label': row['gt_name'],
                'confidence': round(row['conf'], 4),
                'iou': round(row['iou'], 4),
                'total_candidates': len(confusion_candidates),
            },
            suggested_fix={'kind': 'human_relabel', 'description': '人工确认类别边界后修正'},
            requires_human=True,
        ))

    for (scene, name), rows in missing_by_scene.items():
        if len(rows) >= 3:
            book.add(Finding(
                check='model_missing_hotspot',
                severity='P2',
                confidence='candidate',
                title='漏标热点（按场景）',
                message=f'场景「{scene}」有 {len(rows)} 处高置信 {name} 预测无对应标注，建议整段复核',
                subject={'scene': scene, 'cls_name': name},
                evidence={'scene': scene, 'class': name, 'count': len(rows),
                          'images': [row['sample'].image_rel for row in rows[:8]]},
                suggested_fix={'kind': 'batch_inspect', 'description': '按场景筛选后批量复核'},
                requires_human=True,
            ))
    for (pred_name, gt_name), rows in confusion_by_pair.items():
        if len(rows) >= 3:
            book.add(Finding(
                check='model_confusion_hotspot',
                severity='P2',
                confidence='candidate',
                title='类别混淆热点',
                message=f'{len(rows)} 处标注为 {gt_name}，模型判为 {pred_name}，需统一判定口径',
                subject={'cls_name': pred_name, 'peer_cls_name': gt_name},
                evidence={'prediction': pred_name, 'label': gt_name, 'count': len(rows),
                          'images': [row['sample'].image_rel for row in rows[:8]]},
                suggested_fix={'kind': 'spec_clarify', 'description': '在标签体系中补充两者的包含/排除规则'},
                requires_human=True,
            ))

    meta.update({
        'images': len(samples),
        'predictions': total_preds,
        'candidate_missing': len(missing_candidates),
        'candidate_confusion': len(confusion_candidates),
        'listed_missing': len(listed_missing),
        'listed_confusion': len(listed_confusion),
        'omitted_missing': max(0, len(missing_candidates) - len(listed_missing)),
        'seconds': round(time.time() - started, 1),
        'confidence_threshold': conf_threshold,
        'limitations': [
            '模型只作为第二意见，不构成真值；所有模型类 finding 均需人工裁定。',
            '若模型训练时见过本批次，预测置信度会偏高，召回不能当作标注质量指标。',
            '模型类别表与规范不一致的类别会被跳过，不做强行映射。',
            '候选按置信度截断展示，完整数量见 candidate_missing；未展示项不等于已排除。',
        ],
    })
    return book, meta