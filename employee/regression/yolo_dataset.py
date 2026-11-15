"""YOLO 格式数据集加载。

旧展项数据集用 YOLO 格式存放（归一化 bbox + classes.txt / dataset.yaml）。
标注与评估都走绝对像素坐标，这里只负责加载和缓存。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml
from PIL import Image

IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.bmp'}


class YoloDataset:
    """YOLO 格式数据集加载器。

    Attributes:
        root: 数据集根目录。
        names: 类别名列表（索引即类别 ID）。
        images: 验证集图片路径列表。
    """

    def __init__(self, data_yaml: Path):
        self.data_yaml = Path(data_yaml)
        self._meta = yaml.safe_load(self.data_yaml.read_text(encoding='utf-8-sig')) or {}
        self.root = self._load_root()
        self.names = self._load_names()
        self.images = self._scan_images()
        self._gt_cache: Dict[Path, List[dict]] = {}

    def _load_root(self) -> Path:
        path = self._meta.get('path')
        if not path:
            return self.data_yaml.parent
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = self.data_yaml.parent / candidate
        # 旧展项 fixture 可能携带另一台机器上的绝对路径；数据集文件本身
        # 仍然是可移植的，此时以 dataset.yaml 所在目录作为本地根目录。
        return candidate if candidate.exists() else self.data_yaml.parent

    def _load_names(self) -> List[str]:
        names = self._meta.get('names')
        if names is None:
            classes_file = self.root / 'classes.txt'
            if classes_file.exists():
                return [line.strip() for line in classes_file.read_text(encoding='utf-8').splitlines() if line.strip()]
            raise ValueError(f'dataset.yaml 缺少 names 字段，且找不到 classes.txt: {classes_file}')
        if isinstance(names, dict):
            return [str(v) for _, v in sorted(names.items(), key=lambda x: int(x[0]))]
        return [str(n) for n in names]

    def _scan_images(self) -> List[Path]:
        val_dir = self.root / self._meta.get('val', 'images/val')
        if not val_dir.exists():
            raise FileNotFoundError(f'验证集目录不存在: {val_dir}')
        return sorted(p for p in val_dir.rglob('*') if p.suffix.lower() in IMAGE_SUFFIXES)

    def load_ground_truth(self, image_path: Path) -> List[dict]:
        """加载图片对应的标注框（绝对像素坐标）。"""
        if image_path in self._gt_cache:
            return self._gt_cache[image_path]
        label_path = self._find_label_file(image_path)
        if label_path is None or not label_path.exists():
            self._gt_cache[image_path] = []
            return []
        img_w, img_h = self._get_image_size(image_path)
        boxes = []
        for line in label_path.read_text(encoding='utf-8').splitlines():
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            cls_id = int(parts[0])
            x_center, y_center, width, height = (float(v) for v in parts[1:5])
            x_center *= img_w
            y_center *= img_h
            width *= img_w
            height *= img_h
            boxes.append({
                'cls': cls_id,
                'cls_name': self.names[cls_id] if cls_id < len(self.names) else f'class_{cls_id}',
                'bbox': [x_center - width / 2, y_center - height / 2, x_center + width / 2, y_center + height / 2],
            })
        self._gt_cache[image_path] = boxes
        return boxes

    def _find_label_file(self, image_path: Path) -> Optional[Path]:
        relative = image_path.relative_to(self.root)
        parts = list(relative.parts)
        if 'images' in parts:
            parts[parts.index('images')] = 'labels'
        return self.root / Path(*parts).with_suffix('.txt')

    def _get_image_size(self, image_path: Path) -> Tuple[int, int]:
        with Image.open(image_path) as img:
            return img.size
