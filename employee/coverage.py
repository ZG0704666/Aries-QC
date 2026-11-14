"""覆盖度核算：类别配额、场景、分辨率、清晰度、方向、冗余。"""
from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median

from .dataset import Batch
from .merge_guard import ClassMap, norm

BLUR_ABSOLUTE = 40.0


def compute_coverage(batch: Batch, spec: dict, class_map: ClassMap) -> dict:
    req = spec.get('requirements') or {}
    spec_classes = [c['name'] for c in spec.get('classes') or []]
    counts_total: Counter = Counter()
    counts_by_batch: dict[str, Counter] = defaultdict(Counter)
    for sample in batch.samples:
        for obj in sample.objects:
            name = class_map.canonical_name(sample.batch, obj.cls_id)
            counts_total[name] += 1
            counts_by_batch[sample.batch][name] += 1

    per_class_quota = []
    class_quota_items = spec.get('classes') or []
    for item in class_quota_items:
        required = item.get('min_boxes') or req.get('min_per_class') or 0
        actual = counts_total.get(item['name'], 0)
        per_class_quota.append({
            'name': item['name'],
            'required': required,
            'actual': actual,
            'gap': max(0, required - actual),
            'ratio': round(actual / required, 3) if required else None,
        })

    scene_counts = Counter(sample.scene for sample in batch.samples)
    scenes = []
    matched_scenes: set[str] = set()
    for item in spec.get('scenes') or []:
        key = norm(item['name'])
        matched = [scene for scene in scene_counts if key in norm(scene) or norm(scene) in key]
        actual = sum(scene_counts[scene] for scene in matched) if matched else 0
        matched_scenes.update(matched)
        required = item.get('min_images') or 0
        scenes.append({
            'name': item['name'],
            'required': required,
            'actual': actual,
            'gap': max(0, required - actual),
            'matched_scenes': sorted(matched),
        })

    min_w, min_h = (req.get('min_resolution') or [0, 0])[:2]
    low_res = [s for s in batch.samples
               if s.readable and min_w and min_h
               and (s.width < min_w or s.height < min_h)]
    blurs = [s.blur for s in batch.samples if s.readable and s.blur > 0]
    blur_center = median(blurs) if blurs else 0.0
    blur_threshold = max(BLUR_ABSOLUTE, blur_center * 0.25)
    blurry = [s for s in batch.samples if s.readable and 0 < s.blur < blur_threshold]
    orientations = Counter(
        'portrait' if s.height > s.width else ('landscape' if s.width > s.height else 'square')
        for s in batch.samples if s.readable
    )
    empty = sum(1 for s in batch.samples if s.label_state == 'empty')
    missing = sum(1 for s in batch.samples if s.label_state == 'missing')
    duplicate = _duplicate_count(batch)

    image_req = int(req.get('min_images') or 0)
    images = len(batch.samples)
    resolution_ratio = len(low_res) / images if images else 0.0
    blur_ratio = len(blurry) / images if images else 0.0
    expected_orientation = str(req.get('orientation') or 'any').lower()
    orientation_mismatch = 0
    if expected_orientation in ('portrait', 'landscape'):
        orientation_mismatch = sum(1 for s in batch.samples if s.readable and
                                   ('portrait' if s.height > s.width else 'landscape') != expected_orientation)

    scores = []
    if image_req:
        scores.append(min(1.0, images / image_req))
    for item in per_class_quota:
        if item['required']:
            scores.append(min(1.0, item['actual'] / item['required']))
    for item in scenes:
        if item['required']:
            scores.append(min(1.0, item['actual'] / item['required']))
    if min_w and min_h:
        scores.append(max(0.0, 1 - resolution_ratio))
    if req.get('max_blur_ratio') is not None:
        scores.append(max(0.0, 1 - max(0.0, blur_ratio - float(req['max_blur_ratio']))))
    score = round(sum(scores) / len(scores) * 100, 1) if scores else None

    return {
        'images': images,
        'image_requirement': image_req,
        'image_gap': max(0, image_req - images),
        'class_counts': dict(counts_total),
        'class_counts_by_batch': {k: dict(v) for k, v in counts_by_batch.items()},
        'class_quota': per_class_quota,
        'scenes': scenes,
        'unmatched_scenes': sorted(set(scene_counts) - matched_scenes) if spec.get('scenes') else [],
        'low_resolution': {
            'required': [min_w, min_h],
            'count': len(low_res),
            'ratio': round(resolution_ratio, 4),
            'examples': [s.image_rel for s in low_res[:5]],
        },
        'clarity': {
            'blur_threshold': round(blur_threshold, 2),
            'median_blur': round(blur_center, 2),
            'blurry_count': len(blurry),
            'blurry_ratio': round(blur_ratio, 4),
            'allowed_ratio': req.get('max_blur_ratio'),
            'examples': [s.image_rel for s in blurry[:5]],
        },
        'orientation': {
            'expected': expected_orientation,
            'counts': dict(orientations),
            'mismatch': orientation_mismatch,
        },
        'labels': {
            'empty': empty,
            'missing': missing,
            'empty_ratio': round((empty + missing) / images, 4) if images else 0,
        },
        'redundancy': duplicate,
        'score': score,
    }


def _duplicate_count(batch: Batch) -> dict:
    by_md5: Counter = Counter(s.md5 for s in batch.samples if s.md5)
    exact = sum(count - 1 for count in by_md5.values() if count > 1)
    hashes = [s.dhash for s in batch.samples if s.dhash]
    near = 0
    sampled = hashes[:500]
    for i, left in enumerate(sampled):
        for right in sampled[i + 1:]:
            if int(left ^ right).bit_count() <= 4:
                near += 1
                if near >= 200:
                    return {'exact': exact, 'near': near, 'near_capped': True}
    return {'exact': exact, 'near': near, 'near_capped': False}