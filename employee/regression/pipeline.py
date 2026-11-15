"""回归门禁执行器：intake → profiles → evaluate → compare → decide → report。

与 employee.runner.Runner 同构：步骤 trace、状态落盘 runs/reg_<id>/state.json，
前端轮询方式和现有数据质检流水线保持一致，可以复用大部分展示代码。
"""
from __future__ import annotations

import json
import time
import traceback
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from employee.config import Config, ensure_dirs, state_path

from .decision import ReleaseDecision
from .evaluator import RegressionEvaluator
from .report import write_artifacts
from .sim_backend import SimBackend
from .yolo_dataset import YoloDataset

STEP_TITLES = {
    'intake': '接单：加载旧展项数据集',
    'profiles': '加载基线与候选模拟档案',
    'evaluate_baseline': '评估基线模型',
    'evaluate_candidate': '评估候选模型',
    'compare': '逐类对比退化',
    'decide': '按阈值判定放行',
    'report': '生成报告与交付包',
}
STEP_ORDER = list(STEP_TITLES.keys())


class RegressionRunner:
    """模型回归门禁运行器：模拟后端，零 ML 依赖。"""

    def __init__(self, config: Config, dataset_path: str, baseline_path: str, candidate_path: str,
                 thresholds: dict | None = None, run_id: str | None = None):
        ensure_dirs()
        self.config = config
        self.run_id = run_id or 'reg_' + time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6]
        self.run_dir = state_path() / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.dataset_path = dataset_path
        self.baseline_path = baseline_path
        self.candidate_path = candidate_path
        self.thresholds = thresholds or config.regression_thresholds()
        self.dataset: YoloDataset | None = None
        self.comparison: dict | None = None
        self.decision: dict | None = None
        self.started = time.time()
        self.cancel_flag = False
        self.state: dict = {
            'id': self.run_id,
            'kind': 'regression',
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'status': 'created',
            'dataset_path': dataset_path,
            'baseline_path': baseline_path,
            'candidate_path': candidate_path,
            'thresholds': self.thresholds,
            'steps': [],
            'progress': {'done': 0, 'total': 0, 'label': '等待开始'},
            'dataset': None,
            'comparison': None,
            'decision': None,
            'artifacts': [],
            'error': '',
        }

    def start(self) -> None:
        self.state['status'] = 'running'
        self._save()
        try:
            self._pipeline()
        except Exception as error:  # noqa: BLE001 - 运行器需要兜底任何评估异常
            self.state['status'] = 'failed'
            self.state['error'] = f'{type(error).__name__}: {error}'
            self._trace_add('error', '运行失败', 'failed', detail={
                'error': self.state['error'], 'traceback': traceback.format_exc()[-4000:]})
            self._save()

    def cancel(self) -> None:
        self.cancel_flag = True

    def _pipeline(self) -> None:
        for name in STEP_ORDER:
            if self.cancel_flag:
                self.state['status'] = 'cancelled'
                self._trace_add('cancel', '用户取消', 'cancelled')
                self._save()
                return
            getattr(self, f'_step_{name}')()
        self.state['status'] = 'done'
        self.state['finished_at'] = datetime.now().isoformat(timespec='seconds')
        self._save()

    # ---------- 步骤 ----------
    def _step_intake(self) -> None:
        entry = self._trace_add('intake', STEP_TITLES['intake'], 'running')
        self.dataset = YoloDataset(Path(self.dataset_path))
        stats = {
            'images': len(self.dataset.images),
            'classes': len(self.dataset.names),
            'names': self.dataset.names,
        }
        self.state['dataset'] = stats
        self._save()
        self._trace_end(entry, 'ok', detail=stats)

    def _step_profiles(self) -> None:
        entry = self._trace_add('profiles', STEP_TITLES['profiles'], 'running')
        self.baseline_backend = SimBackend(Path(self.baseline_path), self.dataset)
        self.candidate_backend = SimBackend(Path(self.candidate_path), self.dataset)
        detail = {'baseline': self.baseline_backend.name(), 'candidate': self.candidate_backend.name()}
        self._save()
        self._trace_end(entry, 'ok', detail=detail)

    def _step_evaluate_baseline(self) -> None:
        self._evaluate_one('evaluate_baseline', self.baseline_backend, 'baseline_result')

    def _step_evaluate_candidate(self) -> None:
        self._evaluate_one('evaluate_candidate', self.candidate_backend, 'candidate_result')

    def _evaluate_one(self, step: str, backend, attr: str) -> None:
        entry = self._trace_add(step, STEP_TITLES[step], 'running')
        evaluator = RegressionEvaluator(self.dataset)
        total = len(self.dataset.images)

        def on_progress(done: int, total_images: int) -> None:
            self.state['progress'] = {'done': done, 'total': total_images, 'label': f'{backend.name()} {done}/{total_images}'}
            if done % 20 == 0 or done == total_images:
                self._save()

        result = evaluator.evaluate(backend, on_progress=on_progress)
        setattr(self, attr, result)
        self._save()
        self._trace_end(entry, 'ok', detail={
            'precision': round(result['overall']['precision'], 4),
            'recall': round(result['overall']['recall'], 4),
            'ap50': round(result['overall']['ap50'], 4),
            'missed': len(result['missed_cases']),
            'false_positive': len(result['false_positive_cases']),
        })

    def _step_compare(self) -> None:
        entry = self._trace_add('compare', STEP_TITLES['compare'], 'running')
        evaluator = RegressionEvaluator(self.dataset)
        self.comparison = evaluator.compare(self.baseline_result, self.candidate_result)
        self.state['comparison'] = self.comparison
        self._save()
        self._trace_end(entry, 'ok', detail={
            'degraded_classes': self.comparison['degraded_classes'],
            'new_missed': len(self.comparison['missed_cases']),
            'new_false_positive': len(self.comparison['false_positive_cases']),
        })

    def _step_decide(self) -> None:
        entry = self._trace_add('decide', STEP_TITLES['decide'], 'running')
        self.decision = ReleaseDecision(self.thresholds).decide(self.comparison)
        self.state['decision'] = self.decision
        self._save()
        self._trace_end(entry, 'ok', detail={'verdict': self.decision['verdict']})

    def _step_report(self) -> None:
        entry = self._trace_add('report', STEP_TITLES['report'], 'running')
        metadata = {'dataset_name': Path(self.dataset_path).parent.name}
        artifacts = write_artifacts(self.run_dir, self.comparison, self.decision, metadata)
        self._write_delivery_zip()
        artifacts.append({'name': 'delivery.zip', 'size': (self.run_dir / 'delivery.zip').stat().st_size})
        self.state['artifacts'] = artifacts
        self._save()
        self._trace_end(entry, 'ok', detail={'artifacts': len(artifacts)})

    def _write_delivery_zip(self) -> None:
        path = self.run_dir / 'delivery.zip'
        with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('report.md', 'comparison.json', 'decision.json'):
                source = self.run_dir / name
                if source.exists():
                    archive.write(source, name)

    # ---------- trace / state ----------
    def _trace_add(self, step: str, title: str, status: str, detail: dict | None = None) -> dict:
        entry = {'step': step, 'title': title, 'status': status, 'started': time.time(), 'duration': 0.0, 'detail': detail or {}}
        self.state['steps'].append(entry)
        return entry

    def _trace_end(self, entry: dict, status: str, detail: dict | None = None) -> None:
        entry['status'] = status
        entry['duration'] = round(time.time() - entry['started'], 2)
        if detail is not None:
            entry['detail'] = detail

    def _save(self) -> None:
        self.state['duration_seconds'] = round(time.time() - self.started, 1)
        tmp = self.run_dir / 'state.json.tmp'
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.run_dir / 'state.json')
        (self.run_dir / 'trace.jsonl').write_text(
            '\n'.join(json.dumps(step, ensure_ascii=False) for step in self.state['steps']), encoding='utf-8')
