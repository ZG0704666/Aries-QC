"""YOLO 数据集扫描：检测/分割标签、CJK 路径安全读图、批次指纹。"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
import yaml

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tif', '.tiff'}
LABEL_EXTS = {'.txt'}


@dataclass
class LabelObject:
    cls_id: int
    kind: str                 # box | polygon
    coords: list[float]       # 归一化；box 为 cx cy w h，polygon 为 x1 y1 ...
    bbox: tuple[float, float, float, float]
    line_no: int
    raw: str

    def to_dict(self) -> dict:
        return {
            'cls': self.cls_id,
            'kind': self.kind,
            'coords': [round(v, 6) for v in self.coords],
            'bbox': [round(v, 6) for v in self.bbox],
            'line': self.line_no,
        }


@dataclass
class Sample:
    id: int
    batch: str
    split: str
    scene: str
    seq: int
    stem: str
    image_path: str
    label_path: str | None
    image_rel: str
    label_rel: str | None
    width: int = 0
    height: int = 0
    md5: str = ''
    dhash: int = 0
    brightness: float = 0.0
    blur: float = 0.0
    readable: bool = True
    label_state: str = 'missing'   # ok | empty | missing | malformed | unreadable
    label_errors: list[str] = field(default_factory=list)
    objects: list[LabelObject] = field(default_factory=list)

    def to_dict(self, brief: bool = False) -> dict:
        data = {
            'id': self.id,
            'batch': self.batch,
            'split': self.split,
            'scene': self.scene,
            'seq': self.seq,
            'stem': self.stem,
            'image_rel': self.image_rel,
            'label_rel': self.label_rel or '',
            'width': self.width,
            'height': self.height,
            'readable': self.readable,
            'label_state': self.label_state,
            'label_errors': self.label_errors,
            'objects': [] if brief else [o.to_dict() for o in self.objects],
            'object_count': len(self.objects),
        }
        if not brief:
            data.update({
                'md5': self.md5,
                'dhash': self.dhash,
                'brightness': round(self.brightness, 2),
                'blur': round(self.blur, 2),
            })
        return data


@dataclass
class SubBatch:
    name: str
    root: Path
    yaml_path: Path | None
    names: dict[int, str]
    nc: int | None
    samples: list[Sample] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'root': str(self.root),
            'yaml': str(self.yaml_path) if self.yaml_path else '',
            'names': {str(k): v for k, v in sorted(self.names.items())},
            'nc': self.nc,
            'notes': self.notes,
            'images': len(self.samples),
        }


@dataclass
class Batch:
    root: Path
    sub_batches: list[SubBatch]
    samples: list[Sample]

    def to_dict(self) -> dict:
        return {
            'root': str(self.root),
            'sub_batches': [s.to_dict() for s in self.sub_batches],
            'stats': self.stats(),
        }

    def stats(self) -> dict:
        total_obj = sum(len(s.objects) for s in self.samples)
        boxes = sum(1 for s in self.samples for o in s.objects if o.kind == 'box')
        polys = total_obj - boxes
        empty = sum(1 for s in self.samples if s.label_state == 'empty')
        missing = sum(1 for s in self.samples if s.label_state == 'missing')
        malformed = sum(1 for s in self.samples if s.label_state == 'malformed')
        unreadable = sum(1 for s in self.samples if not s.readable)
        scenes = Counter(s.scene for s in self.samples)
        class_counts: dict[str, Counter] = {}
        for sub in self.sub_batches:
            counter: Counter = Counter()
            for sample in self.samples:
                if sample.batch != sub.name:
                    continue
                for obj in sample.objects:
                    counter[sub.names.get(obj.cls_id, f'class_{obj.cls_id}')] += 1
            class_counts[sub.name] = counter
        orientations = Counter(
            'portrait' if s.height > s.width else ('landscape' if s.width > s.height else 'square')
            for s in self.samples if s.readable
        )
        resolutions = Counter(f'{s.width}x{s.height}' for s in self.samples if s.readable)
        return {
            'images': len(self.samples),
            'objects': total_obj,
            'boxes': boxes,
            'polygons': polys,
            'empty_labels': empty,
            'missing_labels': missing,
            'malformed_labels': malformed,
            'unreadable_images': unreadable,
            'scenes': dict(scenes),
            'class_counts': {k: dict(v) for k, v in class_counts.items()},
            'orientations': dict(orientations),
            'resolutions': dict(resolutions.most_common(8)),
            'sub_batches': len(self.sub_batches),
        }

    def names_for(self, batch_name: str) -> dict[int, str]:
        for sub in self.sub_batches:
            if sub.name == batch_name:
                return sub.names
        return {}

    def class_name(self, batch_name: str, cls_id: int) -> str:
        return self.names_for(batch_name).get(cls_id, f'class_{cls_id}')


def is_dataset_root(path: Path) -> bool:
    return path.is_dir() and ((path / 'images').is_dir() or (path / 'labels').is_dir())


def discover_roots(root: Path) -> list[Path]:
    if is_dataset_root(root):
        return [root]
    found = []
    for child in sorted(root.iterdir()):
        if child.is_dir() and is_dataset_root(child):
            found.append(child)
    return found


def read_yaml_meta(root: Path) -> tuple[dict[int, str], int | None, Path | None]:
    for filename in ('dataset.yaml', 'data.yaml', 'dataset.yml', 'data.yml'):
        path = root / filename
        if not path.exists():
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}
        except Exception:
            return {}, None, path
        names: dict[int, str] = {}
        raw = data.get('names')
        if isinstance(raw, dict):
            for key, value in raw.items():
                try:
                    names[int(key)] = str(value)
                except (TypeError, ValueError):
                    continue
        elif isinstance(raw, list):
            names = {i: str(v) for i, v in enumerate(raw)}
        nc = data.get('nc')
        try:
            nc = int(nc) if nc is not None else None
        except (TypeError, ValueError):
            nc = None
        return names, nc, path
    return {}, None, None


def _split_layout(root: Path) -> list[tuple[str, Path, Path | None]]:
    """返回 (split, images_dir, labels_dir|None)。兼容 images/train 与平铺 images。"""
    images_root = root / 'images'
    labels_root = root / 'labels'
    if not images_root.is_dir():
        # 有些导出直接把图片放在根目录
        images_root = root
    if not labels_root.is_dir():
        labels_root = root / 'labels' if (root / 'labels').is_dir() else None
    layouts: list[tuple[str, Path, Path | None]] = []
    if images_root != root:
        splits = [p for p in images_root.iterdir() if p.is_dir()] if images_root.is_dir() else []
        if splits:
            for split_dir in sorted(splits):
                split = split_dir.name
                labels_dir = None
                if labels_root:
                    candidate = labels_root / split
                    labels_dir = candidate if candidate.is_dir() else labels_root
                layouts.append((split, split_dir, labels_dir))
            return layouts
        layouts.append(('', images_root, labels_root))
        return layouts
    # 根目录平铺
    layouts.append(('', root, (root / 'labels') if (root / 'labels').is_dir() else None))
    return layouts


def _scene_of(stem: str) -> tuple[str, int]:
    match = re.match(r'^(.*?)[\s_\-]*(\d+)$', stem)
    if match and match.group(1).strip():
        return match.group(1).strip(' _-'), int(match.group(2))
    return stem, 0


def _dhash(gray: np.ndarray) -> int:
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bool(bit))
    return value


def _read_image(path: Path) -> tuple[np.ndarray | None, str, int, int, float, float]:
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
        image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        image = None
    if image is None:
        return None, '', 0, 0, 0.0, 0.0
    md5 = hashlib.md5(buf).hexdigest()
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(gray.mean())
    height, width = image.shape[:2]
    return image, md5, width, height, brightness, blur


def parse_label(text: str) -> tuple[list[LabelObject], list[str]]:
    objects: list[LabelObject] = []
    errors: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            errors.append(f'第 {line_no} 行字段不足（{len(parts)} 列）')
            continue
        try:
            cls = int(float(parts[0]))
            values = [float(x) for x in parts[1:]]
        except (TypeError, ValueError):
            errors.append(f'第 {line_no} 行含非数字字段')
            continue
        if any(not math.isfinite(v) for v in values):
            errors.append(f'第 {line_no} 行含 NaN/Inf')
            continue
        if len(values) == 4:
            kind = 'box'
            bbox = tuple(values)  # type: ignore[assignment]
        elif len(values) >= 6 and len(values) % 2 == 0:
            kind = 'polygon'
            xs = values[0::2]
            ys = values[1::2]
            x1, x2 = min(xs), max(xs)
            y1, y2 = min(ys), max(ys)
            bbox = ((x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1)
        else:
            errors.append(f'第 {line_no} 行坐标数量不合法（{len(values)} 个）')
            continue
        objects.append(LabelObject(cls, kind, values, bbox, line_no, line))
    return objects, errors


def scan_batch(root: str | Path, progress=None) -> Batch:
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f'批次路径不存在：{root}')
    roots = discover_roots(root)
    if not roots:
        raise ValueError(f'未在 {root} 下找到 images/ 或 labels/ 目录')
    sub_batches: list[SubBatch] = []
    samples: list[Sample] = []
    next_id = 0
    total = 0
    for dataset_root in roots:
        names, nc, yaml_path = read_yaml_meta(dataset_root)
        sub = SubBatch(dataset_root.name, dataset_root, yaml_path, names, nc)
        if not names:
            sub.notes.append('缺少 dataset.yaml 的 names，无法解释类别 ID')
        elif nc is not None and nc != len(names):
            sub.notes.append(f'dataset.yaml 中 nc={nc} 与 names 数量 {len(names)} 不一致')
        for split, images_dir, labels_dir in _split_layout(dataset_root):
            image_files = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
            total += len(image_files)
            for image_path in image_files:
                stem = image_path.stem
                label_path = (labels_dir / f'{stem}.txt') if labels_dir else None
                scene, seq = _scene_of(stem)
                sample = Sample(
                    id=next_id,
                    batch=sub.name,
                    split=split or 'all',
                    scene=scene,
                    seq=seq,
                    stem=stem,
                    image_path=str(image_path),
                    label_path=str(label_path) if label_path and label_path.exists() else None,
                    image_rel=str(image_path.relative_to(dataset_root)).replace('\\', '/'),
                    label_rel=(str(label_path.relative_to(dataset_root)).replace('\\', '/')
                               if label_path and label_path.exists() else None),
                )
                next_id += 1
                _fill_sample(sample)
                if names:
                    for obj in sample.objects:
                        if obj.cls_id < 0 or obj.cls_id >= len(names):
                            sample.label_errors.append(
                                f'类别 ID {obj.cls_id} 超出 names 范围（0..{len(names) - 1}）')
                elif sample.objects:
                    sample.label_errors.append('缺少类别表，无法校验类别 ID')
                samples.append(sample)
                if progress and total % 40 == 0:
                    progress(total)
        sub.samples = [s for s in samples if s.batch == sub.name]
        sub_batches.append(sub)
    batch = Batch(root, sub_batches, samples)
    _mark_split_issues(batch)
    return batch


def _fill_sample(sample: Sample) -> None:
    image_path = Path(sample.image_path)
    image, md5, width, height, brightness, blur = _read_image(image_path)
    if image is None:
        sample.readable = False
        sample.label_state = 'unreadable'
        return
    sample.md5 = md5
    sample.width = width
    sample.height = height
    sample.brightness = brightness
    sample.blur = blur
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sample.dhash = _dhash(gray)
    if not sample.label_path:
        sample.label_state = 'missing'
        return
    try:
        text = Path(sample.label_path).read_text(encoding='utf-8-sig', errors='replace')
    except Exception:
        sample.label_state = 'unreadable'
        sample.label_errors.append('标签文件不可读')
        return
    if not text.strip():
        sample.label_state = 'empty'
        return
    objects, errors = parse_label(text)
    sample.objects = objects
    sample.label_errors.extend(errors)
    if errors:
        sample.label_state = 'malformed'
    elif not objects:
        sample.label_state = 'empty'
    else:
        sample.label_state = 'ok'


def _mark_split_issues(batch: Batch) -> None:
    """把跨 split 重名等结构问题记录到子批次 notes（不产生逐图噪音）。"""
    for sub in batch.sub_batches:
        stems: dict[str, str] = {}
        for sample in sub.samples:
            key = sample.stem
            if key in stems and stems[key] != sample.split:
                note = f'同一文件名出现在多个 split：{key}'
                if note not in sub.notes:
                    sub.notes.append(note)
            stems[key] = sample.split


def batch_fingerprint(batch: Batch) -> dict:
    """批次指纹：用于二轮 diff 和审计。"""
    stats = batch.stats()
    digest = hashlib.sha256()
    for sample in sorted(batch.samples, key=lambda s: s.image_rel):
        digest.update(sample.md5.encode())
        digest.update(sample.label_state.encode())
        digest.update(str(len(sample.objects)).encode())
    return {
        'fingerprint': digest.hexdigest()[:32],
        'images': stats['images'],
        'objects': stats['objects'],
        'sub_batches': [s.name for s in batch.sub_batches],
    }


def iter_class_objects(batch: Batch) -> Iterable[tuple[Sample, LabelObject, str]]:
    for sample in batch.samples:
        names = batch.names_for(sample.batch)
        for obj in sample.objects:
            yield sample, obj, names.get(obj.cls_id, f'class_{obj.cls_id}')


def scene_groups(batch: Batch) -> dict[tuple[str, str, str], list[Sample]]:
    groups: dict[tuple[str, str, str], list[Sample]] = defaultdict(list)
    for sample in batch.samples:
        groups[(sample.batch, sample.split, sample.scene)].append(sample)
    for key in groups:
        groups[key].sort(key=lambda s: (s.seq, s.stem))
    return groups