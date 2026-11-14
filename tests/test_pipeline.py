from __future__ import annotations

import json
from pathlib import Path

import employee.runner as runner_module
from employee.config import Config
from employee.dataset import scan_batch
from employee.fix import preview_fix
from employee.merge_guard import build_class_map
from employee.runner import Runner


def test_fix_remaps_without_touching_original(merge_batch: Path, tmp_path: Path) -> None:
    batch = scan_batch(merge_batch)
    class_map = build_class_map(batch, ['agv', 'rail door'])
    beta_label = merge_batch / 'beta' / 'labels' / 'train' / 'b_0001.txt'
    before = beta_label.read_text(encoding='utf-8')
    result = preview_fix(batch, class_map, [], tmp_path / 'out')
    assert result['available']
    fixed = tmp_path / 'out' / 'fixed' / 'beta' / 'labels' / 'train' / 'b_0001.txt'
    assert fixed.read_text(encoding='utf-8').startswith('2 ')
    assert beta_label.read_text(encoding='utf-8') == before
    assert (tmp_path / 'out' / 'class_map.json').exists()
    diff = json.loads((tmp_path / 'out' / 'fix_diff.json').read_text(encoding='utf-8'))
    assert diff['changed_files'] >= 1
    assert any(action['kind'] == 'class_remap' for row in diff['diff'] for action in row['actions'])


def test_runner_end_to_end(monkeypatch, merge_batch: Path, spec_path: Path, tmp_path: Path) -> None:
    run_root = tmp_path / 'runs'
    monkeypatch.setattr(runner_module, 'state_path', lambda: run_root)
    monkeypatch.setattr(runner_module, 'ensure_dirs', lambda: run_root.mkdir(parents=True, exist_ok=True))
    config = Config(data_root=str(merge_batch), model_path='', base_url='', model='',
                    api_key='', timeout=5, max_llm_calls=0)
    runner = Runner(config, str(merge_batch), spec_path=str(spec_path),
                    options={'use_model': False, 'use_llm_summary': False})
    runner.start()
    state = runner.state
    assert state['status'] == 'done', state.get('error')
    assert state['findings']['by_severity']['P0'] >= 1
    assert state['spec']['method'] == 'yaml'
    assert state['coverage']['images'] == 4
    assert state['task_plan']['effort']['total_hours'] > 0
    assert state['recollect']
    artifacts = {item['name'] for item in state['artifacts']}
    assert {'report.html', 'report.md', 'delivery.zip', 'recollect.csv'} <= artifacts
    report = (runner.run_dir / 'report.html').read_text(encoding='utf-8')
    assert '交付报告' in report
    assert (runner.run_dir / 'delivery.zip').stat().st_size > 1000
    # 修复预览不应覆盖原标签
    beta_label = merge_batch / 'beta' / 'labels' / 'train' / 'b_0001.txt'
    assert beta_label.read_text(encoding='utf-8').startswith('0 ')
    assert runner.state['fix']['changed_files'] >= 1