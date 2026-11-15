"""任务拆解：按规范基准计算工时、人员与抽样方案（算术全部由脚本完成）。"""
from __future__ import annotations

import math

from .dataset import Batch
from .merge_guard import ClassMap


def build_task_plan(batch: Batch, spec: dict, class_map: ClassMap, coverage: dict) -> dict:
    norms = spec.get('norms') or {}
    qc = spec.get('qc') or {}
    stats = batch.stats()
    objects = stats['objects']
    images = stats['images']
    polygons = stats['polygons']
    sample_rate = float(qc.get('sample_rate') or 0.1)
    sample_rate = min(1.0, max(0.0, sample_rate))
    annotate_rate = max(1, int(norms.get('annotate_boxes_per_hour') or 80))
    review_rate = max(1, int(norms.get('review_boxes_per_hour') or 250))
    qa_rate = max(1, int(norms.get('qa_images_per_hour') or 200))
    workday = float(norms.get('workday_hours') or 8)
    deadline_days = float(norms.get('deadline_days') or 3)

    # 多边形按 1.5 倍框工时计（边界更费时），这是脚本假设，报告中会写明
    effective_objects = objects + polygons * 0.5
    annotation_hours = effective_objects / annotate_rate
    review_boxes = max(1, round(objects * sample_rate)) if objects else 0
    review_hours = review_boxes / review_rate
    qa_hours = images / qa_rate
    total_hours = annotation_hours + review_hours + qa_hours
    capacity = max(1.0, deadline_days * workday)
    headcount = max(1, math.ceil(total_hours / capacity)) if total_hours else 1
    review_images = max(20, math.ceil(images * sample_rate)) if images else 0
    review_images = min(images, review_images)

    roles = [
        {
            'role': '采集/补采',
            'headcount': 1 if coverage.get('image_gap') or coverage.get('scenes') else 0,
            'hours': round(_collect_hours(coverage), 1),
            'responsibility': '按补采清单补齐类别配额、场景与画质缺口',
        },
        {
            'role': '标注',
            'headcount': max(1, math.ceil(annotation_hours / capacity)) if objects else 0,
            'hours': round(annotation_hours, 1),
            'responsibility': f'按 {annotate_rate} 框/人时完成 {objects} 个实例（多边形按 1.5× 框工时）',
        },
        {
            'role': '复核',
            'headcount': max(1, math.ceil(review_hours / capacity)) if review_boxes else 0,
            'hours': round(review_hours, 1),
            'responsibility': f'人工抽检 {review_images} 张 / {review_boxes} 个实例（{sample_rate:.0%}）',
        },
        {
            'role': '质检',
            'headcount': 1 if images else 0,
            'hours': round(qa_hours, 1),
            'responsibility': f'运行自动质检并对候选问题裁定，{qa_rate} 图/人时',
        },
    ]

    milestones = [
        {'day': 'D0', 'name': '工作台与规范冻结', 'output': '规范编译结果、类别映射、缺项/冲突清单',
         'gate': 'P0：类别表与映射无冲突'},
        {'day': 'D1', 'name': '采集/补采与标注', 'output': '批次数据、标注文件、采集记录',
         'gate': 'P0：标签格式与类别 ID 合法'},
        {'day': 'D2', 'name': '自动质检与人工复核', 'output': '质检报告、证据包、修复预览',
         'gate': 'P0：无越界/格式错误；候选问题已裁定'},
        {'day': 'D3', 'name': '补采闭环与交付', 'output': '补采工单、二轮复检 diff、交付包',
         'gate': 'P0：覆盖率达标且二轮无回归'},
    ]

    return {
        'inputs': {
            'images': images,
            'objects': objects,
            'polygons': polygons,
            'sample_rate': sample_rate,
            'deadline_days': deadline_days,
        },
        'assumptions': {
            'annotate_boxes_per_hour': annotate_rate,
            'review_boxes_per_hour': review_rate,
            'qa_images_per_hour': qa_rate,
            'workday_hours': workday,
            'polygon_weight': 1.5,
            'efficiency_note': '工时按规范基准与脚本公式计算；实际以现场测时校准，不采用模型心算。',
        },
        'effort': {
            'annotation_hours': round(annotation_hours, 1),
            'review_hours': round(review_hours, 1),
            'qa_hours': round(qa_hours, 1),
            'total_hours': round(total_hours, 1),
            'headcount': headcount,
            'review_images': review_images,
            'review_boxes': review_boxes,
        },
        'roles': roles,
        'milestones': milestones,
        'sampling': {
            'auto': '100% 全量自动检查',
            'human_review_images': review_images,
            'human_review_ratio': round(review_images / images, 3) if images else 0,
            'priority': 'P0 全量人工确认；P1/P2 按 10% 抽检，命中即升级',
        },
        'note': '人员安排与工时是脚本按客户基准计算的建议值，最终由项目经理确认。',
    }


def _collect_hours(coverage: dict) -> float:
    gap = int(coverage.get('image_gap') or 0)
    class_gap = sum(int(item.get('gap') or 0) for item in coverage.get('class_quota') or [])
    scene_gap = sum(int(item.get('gap') or 0) for item in coverage.get('scenes') or [])
    return (gap / 120) + (class_gap / 60) + (scene_gap / 80)