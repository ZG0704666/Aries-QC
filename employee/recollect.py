"""补采清单：把覆盖缺口和缺陷聚类成可派工、可验收的行动项。"""
from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict

from .dataset import Batch
from .merge_guard import ClassMap


PRIORITY_WEIGHT = {'P0': 30, 'P1': 18, 'P2': 8}


def build_recollect(batch: Batch, spec: dict, coverage: dict, findings: list) -> list[dict]:
    items: list[dict] = []

    def add(kind: str, target: str, current, required, gap, reason: str,
            acceptance: str, action: str, priority: str, score: float,
            evidence_ids: list[str] | None = None, shot_spec: str = '') -> None:
        items.append({
            'kind': kind,
            'target': target,
            'current': current,
            'required': required,
            'gap': gap,
            'reason': reason,
            'acceptance': acceptance,
            'action': action,
            'priority': priority,
            'score': round(score, 1),
            'evidence_finding_ids': evidence_ids or [],
            'shot_spec': shot_spec,
        })

    for item in coverage.get('class_quota') or []:
        if item['gap'] <= 0:
            continue
        ratio = (item['actual'] / item['required']) if item['required'] else 0
        priority = 'P0' if ratio < 0.5 else 'P1'
        definition = _class_definition(spec, item['name'])
        add('class_quota', f'类别 {item["name"]}', item['actual'], item['required'], item['gap'],
            f'规范要求 ≥{item["required"]} 个，当前 {item["actual"]} 个，缺口 {item["gap"]}',
            f'新增 {item["gap"]} 个「{item["name"]}」有效实例，抽检 20% 全部通过',
            f'按场景补采并标注 {item["name"]}',
            priority, 70 + min(20, (1 - ratio) * 20),
            shot_spec=definition)

    image_gap = int(coverage.get('image_gap') or 0)
    if image_gap > 0:
        add('image_quota', '批次图像总量', coverage['images'], coverage['image_requirement'], image_gap,
            f'规范要求 ≥{coverage["image_requirement"]} 张，当前 {coverage["images"]} 张',
            f'新增 {image_gap} 张有效图像，且全部通过格式/画质检查',
            '按场景配额补拍，避免同一视角连续帧',
            'P1', 62)

    for item in coverage.get('scenes') or []:
        if item['gap'] <= 0:
            continue
        add('scene', f'场景 {item["name"]}', item['actual'], item['required'], item['gap'],
            f'场景「{item["name"]}」当前 {item["actual"]} 张，缺口 {item["gap"]} 张',
            f'新增 {item["gap"]} 张该场景图像，且至少覆盖 2 个机位/时段',
            '按采集规范补拍目标场景',
            'P1', 60 + min(15, item['gap'] / max(1, item['required']) * 15))

    low = coverage.get('low_resolution') or {}
    if low.get('count'):
        add('resolution', '分辨率不达标', low['count'], 0, low['count'],
            f'{low["count"]} 张低于规范 {low["required"][0]}×{low["required"][1]}',
            '不达标图像全部替换；替换后复检为 0',
            '删除低分辨率图并重拍', 'P1', 55 + min(15, low['ratio'] * 30),
            shot_spec=f'短边 ≥{min(low["required"])} px')

    clarity = coverage.get('clarity') or {}
    if clarity.get('blurry_count'):
        allowed = clarity.get('allowed_ratio')
        if allowed is None or clarity['blurry_ratio'] > allowed:
            add('clarity', '画质模糊', clarity['blurry_count'], 0, clarity['blurry_count'],
                f'{clarity["blurry_count"]} 张清晰度低于阈值 {clarity["blur_threshold"]}'
                + (f'（规范允许比例 {allowed:.0%}）' if allowed is not None else ''),
                '模糊图比例降到规范允许范围内，且关键目标可辨认',
                '重拍失焦/运动模糊帧', 'P1', 50 + min(15, clarity['blurry_ratio'] * 30))

    orientation = coverage.get('orientation') or {}
    if orientation.get('mismatch'):
        add('orientation', '画面方向不符', orientation['mismatch'], 0, orientation['mismatch'],
            f'规范要求 {orientation["expected"]}，{orientation["mismatch"]} 张方向不符',
            '方向不符图像全部替换或重新导出',
            '按规范方向重拍/旋转', 'P2', 35)

    # 缺陷类：按检查项聚类
    grouped: dict[str, list] = defaultdict(list)
    for finding in findings:
        if finding.severity in ('P0', 'P1'):
            grouped[finding.check].append(finding)
    for check, rows in sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        severity = 'P0' if any(r.severity == 'P0' for r in rows) else 'P1'
        samples = sorted({r.subject.get('stem') for r in rows if r.subject.get('stem')})
        add('defect_fix', _check_label(check), len(rows), 0, len(rows),
            f'{len(rows)} 条 {severity} 问题（{check}）',
            '问题全部关闭；P0 全量复核，P1 抽检 20% 无复发',
            _check_action(check),
            severity, 55 + PRIORITY_WEIGHT[severity] + min(15, len(rows) / 10),
            evidence_ids=[r.id for r in rows[:20]])
    # 规范外类别也纳入
    for finding in findings:
        if finding.check == 'class_outside_spec':
            add('defect_fix', '规范外类别确认', 1, 0, 1,
                finding.message,
                '确认是新增类别（更新规范）还是误标（修正标签）',
                '业务方 + 标注负责人共同裁定', 'P1', 68,
                evidence_ids=[finding.id])

    items.sort(key=lambda item: (-item['score'], item['priority'], item['kind']))
    for index, item in enumerate(items, 1):
        item['id'] = f'RC-{index:03d}'
    return items


def to_csv(items: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(['编号', '优先级', '类型', '目标', '当前', '要求', '缺口',
                     '原因', '动作', '验收标准', '拍摄/采集要求', '证据'])
    for item in items:
        writer.writerow([
            item['id'], item['priority'], item['kind'], item['target'],
            item['current'], item['required'], item['gap'], item['reason'],
            item['action'], item['acceptance'], item.get('shot_spec', ''),
            ','.join(item.get('evidence_finding_ids') or []),
        ])
    return buffer.getvalue()


def _class_definition(spec: dict, name: str) -> str:
    for item in spec.get('classes') or []:
        if item['name'] == name:
            parts = []
            if item.get('definition'):
                parts.append(item['definition'])
            if item.get('include'):
                parts.append('包含：' + '、'.join(item['include']))
            if item.get('exclude'):
                parts.append('排除：' + '、'.join(item['exclude']))
            return '；'.join(parts)
    return ''


CHECK_LABELS = {
    'image_unreadable': '图片不可读',
    'label_missing': '标签缺失',
    'label_coverage_missing': '标签整体缺失',
    'label_malformed': '标签格式错误',
    'class_id_out_of_range': '类别 ID 越界',
    'coord_out_of_range': '坐标越界',
    'box_zero_area': '零面积框',
    'duplicate_box': '重复框',
    'duplicate_image': '重复图片',
    'overlap_conflict': '跨类别重叠',
    'geometry_outlier': '框尺寸离群',
    'sequence_missing_label': '序列疑似漏标',
    'model_missing_label': '模型疑似漏标',
    'model_class_mismatch': '模型疑似错标',
    'label_format_mismatch': '标签格式不符',
    'class_same_id_different_name': '类别 ID 冲突',
    'class_same_name_different_id': '类别 ID 漂移',
}


def _check_label(check: str) -> str:
    return CHECK_LABELS.get(check, check)


def _check_action(check: str) -> str:
    if check in ('coord_out_of_range', 'box_zero_area', 'duplicate_box'):
        return '执行修复预览，人工确认后导出修复包'
    if check in ('class_id_out_of_range', 'label_malformed'):
        return '逐条人工确认并重写标签'
    if check in ('duplicate_image', 'sequence_missing_label', 'model_missing_label'):
        return '打开证据图逐条裁定，确认后补标或剔除'
    if check in ('class_same_id_different_name', 'class_same_name_different_id'):
        return '按规范类别表重映射后复检'
    return '按证据逐条处理'