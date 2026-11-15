"""模拟检测后端：零 ML 依赖，用健康度配置生成预测框。

每个类别的健康度（召回率、置信度漂移、类别混淆）写在 YAML 档案里；
更换档案模拟"换权重"，匹配与指标计算走真实 IoU 逻辑，
因此候选档案的回归结果是算出来的，不是写死的。
"""
from __future__ import annotations

import json
import platform
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import yaml
from PIL import Image

from .yolo_dataset import YoloDataset


class SimBackend:
    """根据健康度档案生成预测框的模拟后端。"""

    def __init__(self, profile_path: Path, dataset: YoloDataset, seed: int = 42):
        self.profile_path = Path(profile_path)
        self.dataset = dataset
        self.seed = seed
        if self.profile_path.suffix == '.json':
            self.profile = json.loads(self.profile_path.read_text(encoding='utf-8'))
        else:
            self.profile = yaml.safe_load(self.profile_path.read_text(encoding='utf-8-sig'))
        self.model_name = self.profile.get('model_name', self.profile_path.stem)
        self.per_class_health = self.profile.get('per_class_health', {})
        self.global_health = self.profile.get('global_health', {})
        self._rng = np.random.default_rng(seed)
        self._call_count = 0
        # 这是当前实际执行预测的设备：SimBackend 不依赖 torch，始终在 Python CPU 上运行。
        self.device = 'CPU'

    def predict(self, image_path: Path, conf_thres: float = 0.25) -> List[dict]:
        """对单张图片生成预测框（同一张图多次调用结果一致）。"""
        img_hash = hash(str(image_path)) % (2 ** 32)
        self._rng = np.random.default_rng(self.seed + img_hash)
        gt_boxes = self.dataset.load_ground_truth(image_path)
        predictions: List[dict] = []
        for gt_box in gt_boxes:
            predictions.extend(self._predict_one(gt_box, conf_thres))
        predictions.extend(self._false_positives(image_path, gt_boxes, conf_thres))
        self._call_count += 1
        return predictions

    def _predict_one(self, gt_box: dict, conf_thres: float) -> List[dict]:
        cls_name = gt_box['cls_name']
        health = self.per_class_health.get(cls_name, {})
        recall = health.get('recall', self.global_health.get('recall', 0.95))
        conf_drift = health.get('conf_drift', self.global_health.get('conf_drift', 0.0))
        confusion = health.get('confusion', {})
        detected = self._rng.random() < recall
        if not detected:
            if confusion and self._rng.random() < 0.3:
                return self._misclassified_box(gt_box, confusion, conf_thres, low_conf=True)
            return []
        bbox = self._jitter(gt_box['bbox'])
        conf = max(0.0, min(1.0, self._rng.uniform(0.75, 0.95) + conf_drift))
        predicted_cls_name = cls_name
        predicted_cls = gt_box['cls']
        if confusion and self._rng.random() < sum(confusion.values()):
            wrong_classes = list(confusion.keys())
            wrong_probs = np.array(list(confusion.values()))
            wrong_probs = wrong_probs / wrong_probs.sum()
            predicted_cls_name = str(self._rng.choice(wrong_classes, p=wrong_probs))
            predicted_cls = self.dataset.names.index(predicted_cls_name)
        if conf < conf_thres:
            return []
        return [{'cls': predicted_cls, 'cls_name': predicted_cls_name, 'bbox': bbox, 'conf': conf}]

    def _misclassified_box(self, gt_box: dict, confusion: dict, conf_thres: float, low_conf: bool) -> List[dict]:
        wrong_classes = list(confusion.keys())
        predicted_cls_name = str(self._rng.choice(wrong_classes))
        predicted_cls = self.dataset.names.index(predicted_cls_name)
        conf = self._rng.uniform(0.3, 0.6) if low_conf else self._rng.uniform(0.6, 0.9)
        if conf < conf_thres:
            return []
        return [{'cls': predicted_cls, 'cls_name': predicted_cls_name, 'bbox': list(gt_box['bbox']), 'conf': conf}]

    def _jitter(self, bbox: List[float]) -> List[float]:
        jitter = self.global_health.get('bbox_jitter', 0.02)
        bbox = list(bbox)
        if jitter <= 0:
            return bbox
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        bbox[0] += self._rng.uniform(-jitter, jitter) * w
        bbox[1] += self._rng.uniform(-jitter, jitter) * h
        bbox[2] += self._rng.uniform(-jitter, jitter) * w
        bbox[3] += self._rng.uniform(-jitter, jitter) * h
        return bbox

    def _false_positives(self, image_path: Path, gt_boxes: List[dict], conf_thres: float) -> List[dict]:
        fp_rate = self.global_health.get('false_positive_rate', 0.05)
        if fp_rate <= 0:
            return []
        with Image.open(image_path) as img:
            img_w, img_h = img.size
        predictions = []
        # 按每个真实目标进行概率采样，避免单目标图片因 int(目标数 * 率) 被截断为 0。
        # 这样 false_positive_rate 才能在真实数据规模下稳定体现为可观测的错检案例。
        for _ in gt_boxes:
            if self._rng.random() >= fp_rate:
                continue
            x1 = self._rng.uniform(0, img_w * 0.8)
            y1 = self._rng.uniform(0, img_h * 0.8)
            w = self._rng.uniform(img_w * 0.05, img_w * 0.2)
            h = self._rng.uniform(img_h * 0.05, img_h * 0.2)
            conf = self._rng.uniform(0.3, 0.6)
            if conf < conf_thres:
                continue
            cls_id = int(self._rng.integers(0, len(self.dataset.names)))
            predictions.append({
                'cls': cls_id,
                'cls_name': self.dataset.names[cls_id],
                'bbox': [x1, y1, min(x1 + w, img_w), min(y1 + h, img_h)],
                'conf': conf,
            })
        return predictions

    def name(self) -> str:
        return f'SimBackend({self.model_name})'

    def runtime_info(self) -> dict:
        return {
            'backend': self.name(),
            'device': self.device,
            'engine': 'SimBackend · Python/NumPy',
            'python': platform.python_version(),
            'calls': self._call_count,
        }

    def reset(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self._call_count = 0


def create_sim_profile(
    output_path: Path,
    model_name: str,
    dataset_names: List[str],
    degraded_classes: Optional[Dict[str, dict]] = None,
    global_recall: float = 0.95,
) -> Path:
    """生成一份模拟健康度档案（演示用）。"""
    profile = {
        'model_name': model_name,
        'global_health': {
            'recall': global_recall, 'conf_drift': 0.0,
            'bbox_jitter': 0.01, 'false_positive_rate': 0.03,
        },
        'per_class_health': {},
    }
    for cls_name in dataset_names:
        if degraded_classes and cls_name in degraded_classes:
            profile['per_class_health'][cls_name] = degraded_classes[cls_name]
        else:
            profile['per_class_health'][cls_name] = {'recall': global_recall, 'conf_drift': 0.0}
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix == '.json':
        output_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        output_path.write_text(yaml.safe_dump(profile, allow_unicode=True, sort_keys=False), encoding='utf-8')
    return output_path
