from __future__ import annotations

from pathlib import Path

from employee.provider import extract_json
from employee.spec import _normalize_and_check, compile_spec


def test_yaml_spec_compiles(spec_path: Path) -> None:
    spec = compile_spec(path=spec_path)
    assert spec.method == 'yaml'
    assert spec.class_names == ['agv', 'rail door']
    assert spec.data['requirements']['min_images'] == 50
    assert spec.data['requirements']['min_resolution'] == [64, 64]
    assert spec.data['norms']['deadline_days'] == 2
    assert not spec.blocking


def test_spec_evidence_is_checked_against_source(spec_path: Path) -> None:
    source = spec_path.read_text(encoding='utf-8')
    raw = {
        'project': '测试项目',
        'label_format': 'detection',
        'classes': [{'name': 'agv', 'definition': 'AGV 车体', 'min_boxes': 10}],
        'requirements': {'min_images': 50},
        'evidence': [
            {'field': 'classes[0].min_boxes', 'quote': 'min_boxes: 10'},
            {'field': 'classes[0].name', 'quote': '不存在的原文'},
        ],
    }
    spec = _normalize_and_check(raw, source, 'spec.yaml', 'llm', None)
    assert spec.evidence_check['total'] == 2
    assert spec.evidence_check['verified'] == 1
    assert spec.evidence_check['invalid'] == 1


def test_spec_enriches_regular_numbers() -> None:
    text = '分辨率不低于 720×720；模糊图像比例不得超过 20%；本批次不少于 300 张。'
    raw = {'project': 'x', 'label_format': 'either', 'classes': [{'name': 'agv'}],
           'requirements': {'min_images': None, 'min_resolution': None, 'max_blur_ratio': None}}
    spec = _normalize_and_check(raw, text, 'x.md', 'llm', None)
    assert spec.data['requirements']['min_resolution'] == [720, 720]
    assert spec.data['requirements']['max_blur_ratio'] == 0.2
    assert spec.data['requirements']['min_images'] == 300
    assert spec.data['label_format'] == 'either'


def test_extract_json_fenced() -> None:
    assert extract_json('```json\n{"ok": true}\n```') == {'ok': True}
    assert extract_json('前缀 {"a": 1} 后缀') == {'a': 1}