from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml


def _write_image(path: Path, color: tuple[int, int, int], shift: int = 0) -> None:
    image = np.zeros((96, 96, 3), dtype=np.uint8)
    image[:] = (18, 22, 30)
    x1, y1 = 10 + shift, 14 + shift
    x2, y2 = 70 + shift, 74 + shift
    cv2.rectangle(image, (x1, y1), (x2, y2), color, -1)
    cv2.circle(image, (30 + shift, 30 + shift), 9, (255, 255, 255), -1)
    ok, buf = cv2.imencode('.jpg', image)
    assert ok
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())


def make_dataset(root: Path, name: str, names: list[str], samples: list[dict]) -> Path:
    dataset = root / name
    images = dataset / 'images' / 'train'
    labels = dataset / 'labels' / 'train'
    images.mkdir(parents=True)
    labels.mkdir(parents=True)
    (dataset / 'dataset.yaml').write_text(yaml.safe_dump({
        'path': str(dataset), 'train': 'images/train', 'val': 'images/train',
        'nc': len(names), 'names': {i: n for i, n in enumerate(names)},
    }, allow_unicode=True), encoding='utf-8')
    for index, sample in enumerate(samples):
        stem = sample['stem']
        _write_image(images / f'{stem}.jpg', sample.get('color', (40, 160 + index * 7, 220)),
                     sample.get('shift', 0))
        if sample.get('no_label'):
            continue
        lines = []
        for obj in sample.get('objects', []):
            lines.append(' '.join(str(v) for v in obj))
        (labels / f'{stem}.txt').write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    return dataset


@pytest.fixture
def rules_batch(tmp_path: Path) -> Path:
    samples = [
        {'stem': 'scene_0001', 'color': (80, 200, 120), 'objects': [[0, 0.5, 0.5, 0.4, 0.4]]},
        {'stem': 'scene_0002', 'color': (80, 200, 120), 'objects': []},
        {'stem': 'scene_0003', 'color': (80, 200, 120), 'objects': [[0, 0.5, 0.5, 0.4, 0.4]]},
        {'stem': 'bad_0001', 'color': (200, 100, 80), 'objects': [[0, 1.5, 0.5, 0.2, 0.2]]},
        {'stem': 'bad_0002', 'color': (200, 100, 80), 'objects': [[9, 0.5, 0.5, 0.2, 0.2]]},
        {'stem': 'bad_0003', 'color': (200, 100, 80), 'objects': [[0, 0.5, 0.5]]},
        {'stem': 'bad_0004', 'color': (200, 100, 80), 'objects': [[0, 0.5, 0.5, 0.0, 0.0]]},
        {'stem': 'dup_0001', 'color': (120, 160, 220),
         'objects': [[1, 0.3, 0.5, 0.2, 0.2], [1, 0.3, 0.5, 0.2, 0.2]]},
        {'stem': 'missing_0001', 'color': (160, 120, 220), 'objects': [], 'no_label': True},
    ]
    make_dataset(tmp_path / 'batch', 'alpha', ['alpha', 'beta'], samples)
    # 字节级重复图：与 scene_0001 相同
    source = tmp_path / 'batch' / 'alpha' / 'images' / 'train' / 'scene_0001.jpg'
    duplicate = source.parent / 'copy_0001.jpg'
    duplicate.write_bytes(source.read_bytes())
    (source.parents[2] / 'labels' / 'train' / 'copy_0001.txt').write_text('0 0.5 0.5 0.4 0.4\n',
                                                                         encoding='utf-8')
    return tmp_path / 'batch'


@pytest.fixture
def merge_batch(tmp_path: Path) -> Path:
    root = tmp_path / 'merge'
    make_dataset(root, 'alpha', ['agv', 'rail door'], [
        {'stem': 'a_0001', 'objects': [[0, 0.4, 0.4, 0.3, 0.3]]},
        {'stem': 'a_0002', 'objects': [[1, 0.6, 0.6, 0.2, 0.2]]},
    ])
    make_dataset(root, 'beta', ['sliding door', 'smart hand'], [
        {'stem': 'b_0001', 'objects': [[0, 0.4, 0.4, 0.3, 0.3]]},
        {'stem': 'b_0002', 'objects': [[1, 0.6, 0.6, 0.2, 0.2]]},
    ])
    return root


@pytest.fixture
def spec_path(tmp_path: Path) -> Path:
    path = tmp_path / 'spec.yaml'
    path.write_text(yaml.safe_dump({
        'project': '测试项目',
        'label_format': 'detection',
        'classes': [
            {'name': 'agv', 'definition': 'AGV 车体', 'min_boxes': 10},
            {'name': 'rail door', 'definition': '轨道门', 'min_boxes': 10},
        ],
        'scenes': [{'name': 'scene', 'min_images': 20}],
        'requirements': {'min_images': 50, 'min_resolution': [64, 64], 'max_blur_ratio': 0.5},
        'qc': {'sample_rate': 0.2, 'model_conf': 0.5},
        'norms': {'annotate_boxes_per_hour': 60, 'review_boxes_per_hour': 200,
                  'qa_images_per_hour': 150, 'workday_hours': 8, 'deadline_days': 2},
    }, allow_unicode=True), encoding='utf-8')
    return path