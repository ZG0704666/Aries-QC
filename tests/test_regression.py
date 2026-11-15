from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

import employee.regression.pipeline as pipeline_module
from employee.config import Config
from employee.regression.evaluator import RegressionEvaluator, compute_iou, match_boxes
from employee.regression.pipeline import RegressionRunner
from employee.regression.sim_backend import SimBackend
from employee.regression.yolo_dataset import YoloDataset


def _make_dataset(root: Path, names: list[str], boxes_per_image: dict[str, list[list[float]]]) -> Path:
    images_dir = root / 'images' / 'val'
    labels_dir = root / 'labels' / 'val'
    images_dir.mkdir(parents=True)
    labels_dir.mkdir(parents=True)
    for stem, boxes in boxes_per_image.items():
        image = Image.new('RGB', (200, 200), (30, 30, 30))
        image.save(images_dir / f'{stem}.jpg')
        lines = [' '.join(str(v) for v in box) for box in boxes]
        (labels_dir / f'{stem}.txt').write_text('\n'.join(lines), encoding='utf-8')
    (root / 'dataset.yaml').write_text(yaml.safe_dump({
        'path': str(root), 'train': 'images/val', 'val': 'images/val',
        'nc': len(names), 'names': {i: n for i, n in enumerate(names)},
    }, allow_unicode=True), encoding='utf-8')
    return root / 'dataset.yaml'


def _write_profile(path: Path, model_name: str, per_class_health: dict, global_health: dict | None = None) -> Path:
    profile = {'model_name': model_name, 'per_class_health': per_class_health,
               'global_health': global_health or {'recall': 0.95, 'conf_drift': 0.0, 'bbox_jitter': 0.0, 'false_positive_rate': 0.0}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(profile, allow_unicode=True), encoding='utf-8')
    return path


def test_compute_iou_basic():
    assert compute_iou([0, 0, 10, 10], [0, 0, 10, 10]) == pytest.approx(1.0)
    assert compute_iou([0, 0, 10, 10], [20, 20, 30, 30]) == 0.0
    assert compute_iou([0, 0, 10, 10], [5, 5, 15, 15]) == pytest.approx(25 / 175)


def test_match_boxes_greedy_by_confidence():
    gt = [{'cls': 0, 'bbox': [0, 0, 10, 10]}, {'cls': 0, 'bbox': [50, 50, 60, 60]}]
    pred = [{'cls': 0, 'bbox': [0, 0, 10, 10], 'conf': 0.9}, {'cls': 0, 'bbox': [100, 100, 110, 110], 'conf': 0.5}]
    matches, unmatched_gt, unmatched_pred = match_boxes(gt, pred, iou_thres=0.5)
    assert matches == [(0, 0)]
    assert unmatched_gt == [1]
    assert unmatched_pred == [1]


def test_yolo_dataset_loads_ground_truth(tmp_path: Path):
    data_yaml = _make_dataset(tmp_path / 'ds', ['agv', 'rail door'], {
        'img_0001': [[0, 0.5, 0.5, 0.2, 0.2]],
    })
    dataset = YoloDataset(data_yaml)
    assert dataset.names == ['agv', 'rail door']
    assert len(dataset.images) == 1
    boxes = dataset.load_ground_truth(dataset.images[0])
    assert boxes[0]['cls_name'] == 'agv'
    assert boxes[0]['bbox'] == pytest.approx([80.0, 80.0, 120.0, 120.0])


def test_yolo_dataset_falls_back_when_yaml_path_is_from_another_machine(tmp_path: Path):
    data_yaml = _make_dataset(tmp_path / 'portable', ['agv'], {
        'img_0001': [[0, 0.5, 0.5, 0.2, 0.2]],
    })
    content = data_yaml.read_text(encoding='utf-8').replace(
        f'path: {tmp_path / "portable"}', 'path: F:/old-machine/old-exhibits')
    data_yaml.write_text(content, encoding='utf-8')

    dataset = YoloDataset(data_yaml)

    assert dataset.root == data_yaml.parent
    assert len(dataset.images) == 1


def test_sim_backend_degraded_recall_reduces_detections(tmp_path: Path):
    boxes = {f'img_{i:04d}': [[0, 0.5, 0.5, 0.2, 0.2]] for i in range(60)}
    data_yaml = _make_dataset(tmp_path / 'ds', ['agv'], boxes)
    dataset = YoloDataset(data_yaml)
    healthy = SimBackend(_write_profile(tmp_path / 'healthy.yaml', 'healthy', {'agv': {'recall': 1.0, 'conf_drift': 0.0}}), dataset)
    degraded = SimBackend(_write_profile(tmp_path / 'degraded.yaml', 'degraded', {'agv': {'recall': 0.2, 'conf_drift': 0.0}}), dataset)
    healthy_detections = sum(len(healthy.predict(p)) for p in dataset.images)
    degraded_detections = sum(len(degraded.predict(p)) for p in dataset.images)
    assert healthy_detections > degraded_detections


def test_evaluator_compare_flags_degraded_class(tmp_path: Path):
    boxes = {f'img_{i:04d}': [[0, 0.5, 0.5, 0.2, 0.2]] for i in range(80)}
    data_yaml = _make_dataset(tmp_path / 'ds', ['agv'], boxes)
    dataset = YoloDataset(data_yaml)
    baseline = SimBackend(_write_profile(tmp_path / 'baseline.yaml', 'baseline', {'agv': {'recall': 0.97, 'conf_drift': 0.0}}), dataset)
    candidate = SimBackend(_write_profile(tmp_path / 'candidate.yaml', 'candidate', {'agv': {'recall': 0.5, 'conf_drift': -0.1}}), dataset)
    evaluator = RegressionEvaluator(dataset)
    baseline_result = evaluator.evaluate(baseline)
    candidate_result = evaluator.evaluate(candidate)
    comparison = evaluator.compare(baseline_result, candidate_result)
    assert 'agv' in comparison['degraded_classes']
    assert comparison['overall']['drop']['recall'] > 0
    assert all(case['category'] == 'missed' and case['category_label'] == '漏检'
               for case in candidate_result['missed_cases'])
    assert all(case['category'] == 'false_positive' and case['category_label'] == '错检'
               for case in candidate_result['false_positive_cases'])


def test_regression_runner_end_to_end_blocks_on_critical_degradation(monkeypatch, tmp_path: Path):
    run_root = tmp_path / 'runs'
    monkeypatch.setattr(pipeline_module, 'state_path', lambda: run_root)
    monkeypatch.setattr(pipeline_module, 'ensure_dirs', lambda: run_root.mkdir(parents=True, exist_ok=True))

    boxes = {f'img_{i:04d}': [[0, 0.5, 0.5, 0.2, 0.2], [1, 0.3, 0.3, 0.1, 0.1]] for i in range(50)}
    data_yaml = _make_dataset(tmp_path / 'ds', ['agv', 'rail door'], boxes)
    baseline_path = _write_profile(tmp_path / 'baseline.yaml', 'baseline', {
        'agv': {'recall': 0.97, 'conf_drift': 0.0}, 'rail door': {'recall': 0.97, 'conf_drift': 0.0},
    })
    candidate_path = _write_profile(tmp_path / 'candidate.yaml', 'candidate', {
        'agv': {'recall': 0.3, 'conf_drift': -0.2}, 'rail door': {'recall': 0.97, 'conf_drift': 0.0},
    })
    thresholds = {'map50_min': 0.75, 'per_class_drop_max': 0.05, 'recall_drop_max': 0.1, 'critical_classes': ['agv']}

    config = Config(data_root='', model_path='', base_url='', model='', api_key='', timeout=5, max_llm_calls=0)
    runner = RegressionRunner(config, str(data_yaml), str(baseline_path), str(candidate_path), thresholds=thresholds)
    runner.start()

    assert runner.state['status'] == 'done', runner.state.get('error')
    assert runner.state['decision']['verdict'] == 'BLOCK'
    assert 'agv' in runner.state['comparison']['degraded_classes']
    artifacts = {item['name'] for item in runner.state['artifacts']}
    assert {'report.md', 'comparison.json', 'decision.json', 'delivery.zip'} <= artifacts
    assert (runner.run_dir / 'delivery.zip').stat().st_size > 0
    report_text = (runner.run_dir / 'report.md').read_text(encoding='utf-8')
    assert 'BLOCK' in report_text


def test_config_discovers_regression_fixtures(tmp_path: Path, monkeypatch):
    fixtures_dir = tmp_path / 'fixtures' / 'regression'
    datasets_dir = fixtures_dir / 'datasets' / 'demo'
    profiles_dir = fixtures_dir / 'profiles'
    _make_dataset(datasets_dir, ['agv'], {'img_0001': [[0, 0.5, 0.5, 0.2, 0.2]]})
    _write_profile(profiles_dir / 'sim_baseline.yaml', 'baseline', {'agv': {'recall': 0.95}})
    (profiles_dir / 'thresholds.yaml').write_text(yaml.safe_dump({'map50_min': 0.8}), encoding='utf-8')

    import employee.config as config_module
    monkeypatch.setattr(config_module, 'REGRESSION_DIR', fixtures_dir)
    monkeypatch.setattr(config_module, 'REGRESSION_DATASETS_DIR', datasets_dir.parent)
    monkeypatch.setattr(config_module, 'REGRESSION_PROFILES_DIR', profiles_dir)

    config = Config(data_root='', model_path='', base_url='', model='', api_key='', timeout=5, max_llm_calls=0)
    datasets = config.regression_datasets()
    profiles = config.regression_profiles()
    thresholds = config.regression_thresholds()
    assert any(item['id'] == 'demo' for item in datasets)
    assert any(item['id'] == 'sim_baseline' for item in profiles)
    assert thresholds['map50_min'] == 0.8
