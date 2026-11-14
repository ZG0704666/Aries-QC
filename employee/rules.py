"""确定性质检规则。所有数量与坐标均由脚本计算，模型不参与。"""
from __future__ import annotations

from collections import Counter, defaultdict

from .dataset import Batch, Sample, scene_groups
from .findings import Finding, FindingBook, area, aspect, hamming, iou, median, robust_z
from .merge_guard import ClassMap, conflict_findings


DEFAULT_OPTIONS = {
    'max_per_check': 200,
    'near_dup_hamming': 4,
    'geometry_z': 4.0,
    'geometry_min_samples': 8,
    'overlap_iou': 0.5,
    'duplicate_iou': 0.98,
    'sequence_lookback': 3,
    'sequence_similarity': 12,
    'flag_border': False,
}


def _sample_subject(sample: Sample, obj=None, extra: dict | None = None) -> dict:
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
    if obj is not None:
        data.update({
            'cls': obj.cls_id,
            'bbox': [round(v, 6) for v in obj.bbox],
            'line': obj.line_no,
            'kind': obj.kind,
        })
    if extra:
        data.update(extra)
    return data


class Limited:
    """按检查项限量，避免一个坏批次产出几万条噪音。"""

    def __init__(self, book: FindingBook, cap: int):
        self.book = book
        self.cap = cap
        self.counts: Counter = Counter()
        self.omitted: Counter = Counter()

    def add(self, finding: Finding) -> None:
        if self.counts[finding.check] >= self.cap:
            self.omitted[finding.check] += 1
            return
        self.counts[finding.check] += 1
        self.book.add(finding)

    def flush(self) -> None:
        for check, count in self.omitted.items():
            self.book.add(Finding(
                check='findings_truncated',
                severity='P2',
                confidence='deterministic',
                title='同类问题已折叠',
                message=f'检查项 {check} 还有 {count} 条同类结果未逐条列出（已计数）',
                subject={'check': check},
                evidence={'check': check, 'omitted': count, 'cap': self.cap},
            ))


def run_all(batch: Batch, class_map: ClassMap, spec: dict | None = None,
            options: dict | None = None) -> FindingBook:
    spec = spec or {}
    opts = dict(DEFAULT_OPTIONS)
    opts.update({k: v for k, v in (options or {}).items() if v is not None})
    book = FindingBook()
    limited = Limited(book, int(opts['max_per_check']))

    for sub in batch.sub_batches:
        for note in sub.notes:
            book.add(Finding(
                check='dataset_note',
                severity='P1',
                confidence='deterministic',
                title='数据集结构提示',
                message=f'{sub.name}：{note}',
                subject={'batch': sub.name},
                evidence={'batch': sub.name, 'note': note},
            ))
        if not sub.names and sub.samples:
            book.add(Finding(
                check='missing_class_table',
                severity='P0',
                confidence='deterministic',
                title='缺少类别表',
                message=f'{sub.name} 缺少 dataset.yaml 的 names，无法解释标签类别，禁止交付',
                subject={'batch': sub.name},
                evidence={'batch': sub.name, 'yaml': str(sub.yaml_path or '')},
                suggested_fix={'kind': 'human_supply_class_table',
                               'description': '提供与标签 ID 一一对应的类别表'},
                requires_human=True,
            ))

    _check_unreadable(batch, limited)
    _check_label_presence(batch, limited)
    _check_label_lines(batch, class_map, limited, opts)
    _check_duplicates(batch, limited, opts)
    _check_duplicate_boxes(batch, class_map, limited, opts)
    _check_overlap(batch, class_map, limited, opts)
    _check_geometry(batch, class_map, limited, opts)
    _check_sequence(batch, class_map, limited, opts)
    _check_density(batch, class_map, limited, opts)
    _check_format_contract(batch, spec, limited)
    _check_imbalance(batch, class_map, limited)

    for finding in conflict_findings(class_map):
        book.add(finding)

    limited.flush()
    return book


def _check_unreadable(batch: Batch, limited: Limited) -> None:
    for sample in batch.samples:
        if not sample.readable:
            limited.add(Finding(
                check='image_unreadable',
                severity='P0',
                confidence='deterministic',
                title='图片不可读',
                message=f'图片无法解码：{sample.image_rel}',
                subject=_sample_subject(sample),
                evidence={'path': sample.image_path, 'decoder': 'cv2.imdecode'},
                suggested_fix={'kind': 'recollect_single', 'description': '重新导出或补采该帧'},
            ))


def _check_label_presence(batch: Batch, limited: Limited) -> None:
    missing = [s for s in batch.samples if s.label_path is None]
    if batch.samples and len(missing) / len(batch.samples) > 0.5:
        limited.book.add(Finding(
            check='label_coverage_missing',
            severity='P0',
            confidence='deterministic',
            title='标签整体缺失',
            message=f'{len(missing)}/{len(batch.samples)} 张图片没有标签文件；这更像"未标注批次"，而不是个别漏标',
            subject={'missing': len(missing), 'total': len(batch.samples)},
            evidence={'missing_ratio': round(len(missing) / len(batch.samples), 4)},
            suggested_fix={'kind': 'block_delivery', 'description': '先完成标注或确认是否走模型验收模式'},
            requires_human=True,
        ))
        return
    for sample in missing:
        limited.add(Finding(
            check='label_missing',
            severity='P1',
            confidence='deterministic',
            title='标签文件缺失',
            message=f'有图片无标签：{sample.image_rel}',
            subject=_sample_subject(sample),
            evidence={'image': sample.image_rel, 'label': ''},
            suggested_fix={'kind': 'label_or_recollect', 'description': '补标；若为负样本则建立空标签文件并登记'},
            requires_human=True,
        ))


def _check_label_lines(batch: Batch, class_map: ClassMap, limited: Limited, opts: dict) -> None:
    for sample in batch.samples:
        if sample.label_state == 'malformed':
            limited.add(Finding(
                check='label_malformed',
                severity='P0',
                confidence='deterministic',
                title='标签格式错误',
                message=f'{sample.image_rel} 的标签存在格式错误：' + '；'.join(sample.label_errors[:3]),
                subject=_sample_subject(sample),
                evidence={'errors': sample.label_errors, 'label': sample.label_rel},
                suggested_fix={'kind': 'fix_label_line', 'description': '按 YOLO 格式重写或剔除非法行'},
                requires_human=True,
            ))
        names_count = len(batch.names_for(sample.batch))
        for obj in sample.objects:
            cls_name = class_map.canonical_name(sample.batch, obj.cls_id)
            if names_count and (obj.cls_id < 0 or obj.cls_id >= names_count):
                limited.add(Finding(
                    check='class_id_out_of_range',
                    severity='P0',
                    confidence='deterministic',
                    title='类别 ID 越界',
                    message=f'{sample.image_rel} 第 {obj.line_no} 行类别 ID={obj.cls_id}，类别表只有 {names_count} 类',
                    subject=_sample_subject(sample, obj, {'cls_name': cls_name}),
                    evidence={'cls': obj.cls_id, 'names_count': names_count},
                    suggested_fix={'kind': 'human_decide_class', 'description': '确认正确类别后修复或删除该行'},
                    requires_human=True,
                ))
            coords = [v for v in obj.coords]
            out = [v for v in coords if v < -1e-6 or v > 1 + 1e-6]
            if out:
                limited.add(Finding(
                    check='coord_out_of_range',
                    severity='P0',
                    confidence='deterministic',
                    title='坐标越界',
                    message=f'{sample.image_rel} 第 {obj.line_no} 行有 {len(out)} 个坐标超出 [0,1]',
                    subject=_sample_subject(sample, obj),
                    evidence={'out_of_range': [round(v, 6) for v in out[:8]], 'count': len(out)},
                    suggested_fix={'kind': 'clamp_coords', 'description': '裁剪到 [0,1] 并复核几何形状'},
                ))
            if area(obj.bbox) <= 1e-8:
                limited.add(Finding(
                    check='box_zero_area',
                    severity='P0',
                    confidence='deterministic',
                    title='零面积框',
                    message=f'{sample.image_rel} 第 {obj.line_no} 行框面积为 0',
                    subject=_sample_subject(sample, obj),
                    evidence={'bbox': obj.bbox},
                    suggested_fix={'kind': 'drop_object', 'description': '删除该行或重画'},
                ))


def _check_duplicates(batch: Batch, limited: Limited, opts: dict) -> None:
    by_md5: dict[str, list[Sample]] = defaultdict(list)
    for sample in batch.samples:
        if sample.md5:
            by_md5[sample.md5].append(sample)
    for digest, group in by_md5.items():
        if len(group) < 2:
            continue
        for sample in group[1:]:
            limited.add(Finding(
                check='duplicate_image',
                severity='P1',
                confidence='deterministic',
                title='完全重复图片',
                message=f'{sample.image_rel} 与 {group[0].image_rel} 字节级相同',
                subject=_sample_subject(sample, extra={'duplicate_of': group[0].image_rel}),
                evidence={'md5': digest, 'duplicate_of': group[0].image_rel},
                suggested_fix={'kind': 'drop_or_keep_one', 'description': '保留一张，避免训练集泄漏'},
            ))
    # 近重复（感知哈希）
    readable = [s for s in batch.samples if s.readable and s.dhash]
    near_cap = 40
    count = 0
    for i, left in enumerate(readable):
        for right in readable[i + 1:]:
            if left.md5 == right.md5:
                continue
            distance = hamming(left.dhash, right.dhash)
            if distance <= int(opts['near_dup_hamming']):
                count += 1
                if count > near_cap:
                    break
                limited.add(Finding(
                    check='near_duplicate_image',
                    severity='P2',
                    confidence='candidate',
                    title='疑似近重复图片',
                    message=f'{left.image_rel} 与 {right.image_rel} 感知哈希距离 {distance}',
                    subject=_sample_subject(right, extra={'peer': left.image_rel}),
                    evidence={'hamming': distance, 'peer': left.image_rel, 'md5_left': left.md5,
                              'md5_right': right.md5},
                    suggested_fix={'kind': 'human_check_duplicate', 'description': '确认是否为同一场景重复帧'},
                    requires_human=True,
                ))
        if count > near_cap:
            break


def _check_duplicate_boxes(batch: Batch, class_map: ClassMap, limited: Limited, opts: dict) -> None:
    threshold = float(opts['duplicate_iou'])
    for sample in batch.samples:
        objects = sample.objects
        for i, left in enumerate(objects):
            for right in objects[i + 1:]:
                if left.cls_id != right.cls_id:
                    continue
                value = iou(left.bbox, right.bbox)
                if value >= threshold:
                    limited.add(Finding(
                        check='duplicate_box',
                        severity='P1',
                        confidence='deterministic',
                        title='重复标注框',
                        message=(f'{sample.image_rel} 第 {left.line_no}/{right.line_no} 行同类别框重复'
                                 f'（IoU={value:.3f}）'),
                        subject=_sample_subject(sample, right, {
                            'cls_name': class_map.canonical_name(sample.batch, right.cls_id),
                            'peer_line': left.line_no,
                            'iou': round(value, 4),
                        }),
                        evidence={'iou': round(value, 4), 'peer_line': left.line_no,
                                  'kept_line': left.line_no, 'dropped_line': right.line_no},
                        suggested_fix={'kind': 'drop_duplicate_box', 'description': '保留一行，删除重复行'},
                    ))


def _check_overlap(batch: Batch, class_map: ClassMap, limited: Limited, opts: dict) -> None:
    for sample in batch.samples:
        objects = sample.objects
        for i, left in enumerate(objects):
            for right in objects[i + 1:]:
                if left.cls_id == right.cls_id:
                    continue
                value = iou(left.bbox, right.bbox)
                if value >= float(opts['overlap_iou']):
                    limited.add(Finding(
                        check='overlap_conflict',
                        severity='P1',
                        confidence='candidate',
                        title='不同类别框高度重叠',
                        message=(f'{sample.image_rel} 第 {left.line_no}/{right.line_no} 行：'
                                 f'{class_map.canonical_name(sample.batch, left.cls_id)} 与 '
                                 f'{class_map.canonical_name(sample.batch, right.cls_id)} IoU={value:.2f}'),
                        subject=_sample_subject(sample, left, {
                            'peer_cls': right.cls_id,
                            'peer_cls_name': class_map.canonical_name(sample.batch, right.cls_id),
                            'peer_line': right.line_no,
                            'peer_bbox': [round(v, 6) for v in right.bbox],
                        }),
                        evidence={'iou': round(value, 4),
                                  'left': [left.line_no, class_map.canonical_name(sample.batch, left.cls_id)],
                                  'right': [right.line_no, class_map.canonical_name(sample.batch, right.cls_id)]},
                        suggested_fix={'kind': 'human_relabel', 'description': '确认两个类别的边界或删除误标'},
                        requires_human=True,
                    ))


def _check_geometry(batch: Batch, class_map: ClassMap, limited: Limited, opts: dict) -> None:
    groups: dict[tuple[str, int], list[tuple[Sample, object]]] = defaultdict(list)
    for sample in batch.samples:
        for obj in sample.objects:
            if area(obj.bbox) > 0:
                groups[(sample.batch, obj.cls_id)].append((sample, obj))
    min_samples = int(opts['geometry_min_samples'])
    per_class_cap = int(opts.get('geometry_per_class', 5))
    for (batch_name, cls_id), rows in groups.items():
        if len(rows) < min_samples:
            continue
        areas = [area(obj.bbox) for _, obj in rows]
        aspects = [aspect(obj.bbox) for _, obj in rows]
        center = median(areas)
        center_aspect = median(aspects)
        candidates = []
        for sample, obj in rows:
            value = area(obj.bbox)
            z_area = robust_z(value, areas)
            z_aspect = robust_z(aspect(obj.bbox), aspects)
            ratio = value / center if center > 0 else 1.0
            aspect_ratio = aspect(obj.bbox) / center_aspect if center_aspect > 0 else 1.0
            if abs(z_area) >= 5.0 and (ratio > 6.0 or ratio < 1 / 6.0):
                candidates.append((abs(z_area), sample, obj, 'area', value, center, z_area, ratio))
            elif abs(z_aspect) >= 5.0 and (aspect_ratio > 3.0 or aspect_ratio < 1 / 3.0):
                candidates.append((abs(z_aspect), sample, obj, 'aspect', aspect(obj.bbox),
                                   center_aspect, z_aspect, aspect_ratio))
        candidates.sort(key=lambda row: -row[0])
        for _, sample, obj, kind, value, center_value, z_value, ratio in candidates[:per_class_cap]:
            if kind == 'area':
                limited.add(Finding(
                    check='geometry_outlier',
                    severity='P2',
                    confidence='candidate',
                    title='框尺寸离群',
                    message=(f'{sample.image_rel} 第 {obj.line_no} 行 '
                             f'{class_map.canonical_name(sample.batch, cls_id)} 面积是同类中位数的 {ratio:.1f}×'),
                    subject=_sample_subject(sample, obj, {
                        'cls_name': class_map.canonical_name(sample.batch, cls_id)}),
                    evidence={'area': round(value, 6), 'median_area': round(center_value, 6),
                              'robust_z': round(z_value, 2), 'ratio': round(ratio, 3),
                              'samples': len(rows), 'rule': '|z|>=5 且倍数>6'},
                    suggested_fix={'kind': 'human_check_box', 'description': '复核是否框大了/框小了'},
                    requires_human=True,
                ))
            else:
                limited.add(Finding(
                    check='geometry_outlier',
                    severity='P2',
                    confidence='candidate',
                    title='长宽比离群',
                    message=(f'{sample.image_rel} 第 {obj.line_no} 行长宽比异常'
                             f'（{value:.2f}，同类中位数 {center_value:.2f}）'),
                    subject=_sample_subject(sample, obj, {
                        'cls_name': class_map.canonical_name(sample.batch, cls_id)}),
                    evidence={'aspect': round(value, 3), 'median_aspect': round(center_value, 3),
                              'robust_z': round(z_value, 2), 'ratio': round(ratio, 3),
                              'samples': len(rows), 'rule': '|z|>=5 且倍数>3'},
                    suggested_fix={'kind': 'human_check_box', 'description': '复核框是否贴合目标'},
                    requires_human=True,
                ))


def _check_sequence(batch: Batch, class_map: ClassMap, limited: Limited, opts: dict) -> None:
    lookback = int(opts['sequence_lookback'])
    similarity = int(opts['sequence_similarity'])
    for (batch_name, split, scene), group in scene_groups(batch).items():
        if len(group) < 3:
            continue
        for index, sample in enumerate(group):
            if sample.objects or sample.label_state not in ('empty', 'missing'):
                continue
            previous = next((group[j] for j in range(index - 1, max(-1, index - lookback - 1), -1)
                             if group[j].objects), None)
            following = next((group[j] for j in range(index + 1, min(len(group), index + lookback + 1))
                              if group[j].objects), None)
            if not previous or not following:
                continue
            if hamming(previous.dhash, sample.dhash) > similarity:
                continue
            if hamming(following.dhash, sample.dhash) > similarity:
                continue
            classes = sorted({class_map.canonical_name(batch_name, obj.cls_id)
                              for obj in previous.objects + following.objects})
            limited.add(Finding(
                check='sequence_missing_label',
                severity='P1',
                confidence='candidate',
                title='序列中间帧疑似漏标',
                message=(f'{sample.image_rel} 位于连续帧中间且画面高度相似，前后帧均有标注'
                         f'（{", ".join(classes[:4])}），本帧为空'),
                subject=_sample_subject(sample, extra={'scene': scene}),
                evidence={
                    'previous': previous.image_rel,
                    'following': following.image_rel,
                    'hamming_previous': hamming(previous.dhash, sample.dhash),
                    'hamming_following': hamming(following.dhash, sample.dhash),
                    'neighbor_classes': classes,
                    'previous_lines': [o.line_no for o in previous.objects],
                    'following_lines': [o.line_no for o in following.objects],
                },
                suggested_fix={'kind': 'inspect_frame', 'description': '打开前后帧对照，确认是否漏标'},
                requires_human=True,
            ))


def _check_density(batch: Batch, class_map: ClassMap, limited: Limited, opts: dict) -> None:
    for (batch_name, split, scene), group in scene_groups(batch).items():
        if len(group) < 6:
            continue
        counts = [len(s.objects) for s in group]
        center = median(counts)
        if center < 1:
            continue
        for sample in group:
            if len(sample.objects) >= max(10, center * 3):
                limited.add(Finding(
                    check='label_density_outlier',
                    severity='P2',
                    confidence='candidate',
                    title='单帧标注数量异常偏多',
                    message=f'{sample.image_rel} 有 {len(sample.objects)} 个框，同场景中位数 {center:.1f}',
                    subject=_sample_subject(sample),
                    evidence={'count': len(sample.objects), 'median': center,
                              'scene_images': len(group)},
                    suggested_fix={'kind': 'human_check_duplicate_boxes', 'description': '检查是否重复框或误标'},
                    requires_human=True,
                ))


def _check_format_contract(batch: Batch, spec: dict, limited: Limited) -> None:
    expected = str((spec.get('requirements') or {}).get('label_format')
                   or spec.get('label_format') or 'either').lower()
    if expected not in ('detection', 'segmentation'):
        return
    found_box = found_poly = 0
    for sample in batch.samples:
        for obj in sample.objects:
            if obj.kind == 'box':
                found_box += 1
            else:
                found_poly += 1
    if expected == 'detection' and found_poly:
        limited.book.add(Finding(
            check='label_format_mismatch',
            severity='P1',
            confidence='deterministic',
            title='标签格式与规范不符',
            message=f'规范要求检测框，但数据中有 {found_poly} 个分割多边形',
            subject={'expected': expected, 'polygons': found_poly, 'boxes': found_box},
            evidence={'expected': expected, 'boxes': found_box, 'polygons': found_poly},
            suggested_fix={'kind': 'convert_or_confirm', 'description': '确认交付格式；可转换为外接框'},
            requires_human=True,
        ))
    if expected == 'segmentation' and found_box:
        limited.book.add(Finding(
            check='label_format_mismatch',
            severity='P1',
            confidence='deterministic',
            title='标签格式与规范不符',
            message=f'规范要求分割多边形，但数据中有 {found_box} 个检测框',
            subject={'expected': expected, 'polygons': found_poly, 'boxes': found_box},
            evidence={'expected': expected, 'boxes': found_box, 'polygons': found_poly},
            suggested_fix={'kind': 'human_confirm', 'description': '确认是否允许混用检测框'},
            requires_human=True,
        ))


def _check_imbalance(batch: Batch, class_map: ClassMap, limited: Limited) -> None:
    for sub in batch.sub_batches:
        counts: Counter = Counter()
        for sample in batch.samples:
            if sample.batch != sub.name:
                continue
            for obj in sample.objects:
                counts[class_map.canonical_name(sub.name, obj.cls_id)] += 1
        if len(counts) < 2 or sum(counts.values()) < 30:
            continue
        low_name, low = min(counts.items(), key=lambda kv: kv[1])
        high_name, high = max(counts.items(), key=lambda kv: kv[1])
        if high > 0 and low / high < 0.15:
            limited.book.add(Finding(
                check='class_imbalance',
                severity='P2',
                confidence='deterministic',
                title='类别分布失衡',
                message=f'{sub.name}：{low_name}={low}，{high_name}={high}（比例 {low / high:.1%}）',
                subject={'batch': sub.name, 'low_class': low_name, 'high_class': high_name},
                evidence={'counts': dict(counts), 'ratio': round(low / high, 4)},
                suggested_fix={'kind': 'recollect', 'description': '补采少数类，避免模型偏置'},
            ))