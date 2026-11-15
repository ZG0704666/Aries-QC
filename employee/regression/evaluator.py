"""回归评估核心：IoU、贪心匹配、指标计算、漏检/错检案例收集。"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Tuple

from .yolo_dataset import YoloDataset


def compute_iou(box1: List[float], box2: List[float]) -> float:
    """计算两个 [x1,y1,x2,y2] 框的 IoU。"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union = area1 + area2 - intersection
    return intersection / union if union else 0.0


def match_boxes(
    gt_boxes: List[dict], pred_boxes: List[dict], iou_thres: float = 0.5,
) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
    """贪心匹配预测框与 GT 框，按置信度降序。

    Returns:
        (matches, unmatched_gt, unmatched_pred)
    """
    if not gt_boxes:
        return [], [], list(range(len(pred_boxes)))
    if not pred_boxes:
        return [], list(range(len(gt_boxes))), []
    pred_order = sorted(range(len(pred_boxes)), key=lambda i: pred_boxes[i]['conf'], reverse=True)
    matches: List[Tuple[int, int]] = []
    matched_gt: set = set()
    matched_pred: set = set()
    for pred_idx in pred_order:
        pred_box = pred_boxes[pred_idx]
        best_iou, best_gt_idx = 0.0, -1
        for gt_idx, gt_box in enumerate(gt_boxes):
            if gt_idx in matched_gt or gt_box['cls'] != pred_box['cls']:
                continue
            iou = compute_iou(gt_box['bbox'], pred_box['bbox'])
            if iou > best_iou and iou >= iou_thres:
                best_iou, best_gt_idx = iou, gt_idx
        if best_gt_idx >= 0:
            matches.append((best_gt_idx, pred_idx))
            matched_gt.add(best_gt_idx)
            matched_pred.add(pred_idx)
    unmatched_gt = [i for i in range(len(gt_boxes)) if i not in matched_gt]
    unmatched_pred = [i for i in range(len(pred_boxes)) if i not in matched_pred]
    return matches, unmatched_gt, unmatched_pred


class RegressionEvaluator:
    """对比基线模型和候选模型在验证集上的表现。"""

    def __init__(self, dataset: YoloDataset, conf_thres: float = 0.25, iou_thres: float = 0.5):
        self.dataset = dataset
        self.conf_thres = conf_thres
        self.iou_thres = iou_thres

    def evaluate(self, backend, on_progress=None) -> Dict:
        """评估单个后端，返回逐类指标与漏检/错检案例。"""
        per_class_stats = defaultdict(lambda: {'tp': 0, 'fp': 0, 'fn': 0})
        missed_cases: List[dict] = []
        false_positive_cases: List[dict] = []
        images = self.dataset.images
        for idx, image_path in enumerate(images):
            gt_boxes = self.dataset.load_ground_truth(image_path)
            pred_boxes = backend.predict(image_path, self.conf_thres)
            matches, unmatched_gt, unmatched_pred = match_boxes(gt_boxes, pred_boxes, self.iou_thres)
            for gt_idx, _pred_idx in matches:
                per_class_stats[gt_boxes[gt_idx]['cls_name']]['tp'] += 1
            for gt_idx in unmatched_gt:
                cls_name = gt_boxes[gt_idx]['cls_name']
                per_class_stats[cls_name]['fn'] += 1
                missed_cases.append({
                    'category': 'missed',
                    'category_label': '漏检',
                    'image': str(image_path.relative_to(self.dataset.root)).replace('\\', '/'),
                    'gt_box': gt_boxes[gt_idx],
                    'severity': self._assess_severity(gt_boxes[gt_idx], image_path),
                })
            for pred_idx in unmatched_pred:
                cls_name = pred_boxes[pred_idx]['cls_name']
                per_class_stats[cls_name]['fp'] += 1
                false_positive_cases.append({
                    'category': 'false_positive',
                    'category_label': '错检',
                    'image': str(image_path.relative_to(self.dataset.root)).replace('\\', '/'),
                    'pred_box': pred_boxes[pred_idx],
                    'conf': pred_boxes[pred_idx]['conf'],
                })
            if on_progress:
                on_progress(idx + 1, len(images))

        per_class_metrics = {}
        total_tp = total_fp = total_fn = 0
        for cls_name in self.dataset.names:
            stats = per_class_stats[cls_name]
            tp, fp, fn = stats['tp'], stats['fp'], stats['fn']
            total_tp += tp
            total_fp += fp
            total_fn += fn
            precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
            per_class_metrics[cls_name] = {
                'tp': tp, 'fp': fp, 'fn': fn,
                'precision': precision, 'recall': recall, 'f1': f1,
                'ap50': f1,  # 简化版 AP50（无置信度排序积分，用 F1 近似）
            }
        overall_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
        overall_recall = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
        overall_f1 = (2 * overall_precision * overall_recall / (overall_precision + overall_recall)
                      if (overall_precision + overall_recall) > 0 else 0.0)
        return {
            'backend_name': backend.name(),
            'overall': {
                'precision': overall_precision, 'recall': overall_recall,
                'f1': overall_f1, 'ap50': overall_f1,
            },
            'per_class': per_class_metrics,
            'missed_cases': missed_cases,
            'false_positive_cases': false_positive_cases,
        }

    def _assess_severity(self, gt_box: dict, image_path: Path) -> str:
        """漏检严重程度的简单启发式：大目标漏检更严重。"""
        from PIL import Image

        bbox = gt_box['bbox']
        area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
        with Image.open(image_path) as img:
            img_area = img.size[0] * img.size[1]
        if area > img_area * 0.01:
            return 'high'
        if gt_box['cls_name'] in ('robotic arm', 'rail door'):
            return 'medium'
        return 'low'

    def compare(self, baseline_result: Dict, candidate_result: Dict) -> Dict:
        """对比基线和候选模型，计算逐类退化与新增案例。"""
        overall_drop = {
            key: baseline_result['overall'][key] - candidate_result['overall'][key]
            for key in ('precision', 'recall', 'f1', 'ap50')
        }
        per_class_compare = {}
        degraded_classes = []
        for cls_name in self.dataset.names:
            baseline_metrics = baseline_result['per_class'].get(cls_name, {})
            candidate_metrics = candidate_result['per_class'].get(cls_name, {})
            if not baseline_metrics or not candidate_metrics:
                continue
            drop = {key: baseline_metrics[key] - candidate_metrics[key] for key in ('precision', 'recall', 'f1', 'ap50')}
            is_degraded = drop['ap50'] > 0.05
            per_class_compare[cls_name] = {
                'baseline': baseline_metrics, 'candidate': candidate_metrics,
                'drop': drop, 'degraded': is_degraded,
            }
            if is_degraded:
                degraded_classes.append(cls_name)

        def _case_key(case: dict, field: str) -> str:
            return case['image'] + str(case[field]['bbox'])

        baseline_missed = {_case_key(c, 'gt_box') for c in baseline_result['missed_cases']}
        new_missed_cases = [c for c in candidate_result['missed_cases'] if _case_key(c, 'gt_box') not in baseline_missed]
        baseline_fp = {_case_key(c, 'pred_box') for c in baseline_result['false_positive_cases']}
        new_fp_cases = [c for c in candidate_result['false_positive_cases'] if _case_key(c, 'pred_box') not in baseline_fp]

        return {
            'overall': {'baseline': baseline_result['overall'], 'candidate': candidate_result['overall'], 'drop': overall_drop},
            'per_class': per_class_compare,
            'degraded_classes': degraded_classes,
            'missed_cases': new_missed_cases,
            'false_positive_cases': new_fp_cases,
            'baseline_backend': baseline_result['backend_name'],
            'candidate_backend': candidate_result['backend_name'],
        }

