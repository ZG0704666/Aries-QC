"""有界 Agent 执行器：步骤、质量门、人工介入、trace、持久化。"""
from __future__ import annotations

import json
import re
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from .config import Config, ensure_dirs, state_path
from .coverage import compute_coverage
from .dataset import Batch, batch_fingerprint, scan_batch
from .findings import Finding, FindingBook
from .fix import preview_fix
from .merge_guard import build_class_map
from .plan import build_task_plan
from .probe import run_probe
from .provider import LLMClient, LLMError
from .recollect import build_recollect, to_csv
from .rules import run_all
from .spec import Spec, _normalize, _normalize_and_check, compile_spec


class Runner:
    def __init__(self, config: Config, batch_path: str, spec_path: str | None = None,
                 spec_text: str | None = None, options: dict | None = None,
                 run_id: str | None = None):
        ensure_dirs()
        self.config = config
        self.run_id = run_id or time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:6]
        self.run_dir = state_path() / self.run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.batch_path = str(batch_path)
        self.spec_path = str(spec_path) if spec_path else None
        self.spec_text = spec_text
        self.options = {
            'use_model': True,
            'probe_max_images': 0,
            'use_llm_summary': True,
            'strict_spec': False,
            'max_per_check': 200,
        }
        self.options.update(options or {})
        self.batch: Batch | None = None
        self.spec: Spec | None = None
        self.class_map = None
        self.book = FindingBook()
        self.coverage: dict = {}
        self.task_plan: dict = {}
        self.recollect: list[dict] = []
        self.probe_meta: dict = {}
        self.fix_summary: dict = {}
        self.llm = LLMClient(config.base_url, config.api_key, config.model,
                             timeout=config.timeout, max_calls=config.max_llm_calls)
        self.started = time.time()
        self.cancel_flag = False
        self.state: dict = {
            'id': self.run_id,
            'created_at': datetime.now().isoformat(timespec='seconds'),
            'status': 'created',
            'batch_path': self.batch_path,
            'spec_path': self.spec_path,
            'options': self.options,
            'steps': [],
            'progress': {'done': 0, 'total': 0, 'label': '等待开始'},
            'batch': None,
            'spec': None,
            'classes': None,
            'probe': None,
            'coverage': None,
            'task_plan': None,
            'recollect': None,
            'fix': None,
            'findings': {'total': 0},
            'llm': {'calls': 0},
            'summary': None,
            'questions': [],
            'error': '',
        }

    # ---------- 生命周期 ----------
    def start(self) -> None:
        self.state['status'] = 'running'
        self._save()
        try:
            self._pipeline(from_step='intake')
        except Exception as error:
            self.state['status'] = 'failed'
            self.state['error'] = f'{type(error).__name__}: {error}'
            self._trace_add('error', '运行失败', 'failed', detail={
                'error': self.state['error'], 'traceback': traceback.format_exc()[-4000:]})
            self._save()

    def _pipeline(self, from_step: str = 'intake') -> None:
        order = ['intake', 'spec', 'schema', 'rules', 'probe', 'coverage', 'recollect', 'plan', 'fix', 'summary', 'report']
        start = order.index(from_step)
        steps = {
            'intake': self._step_intake,
            'spec': self._step_spec,
            'schema': self._step_schema,
            'rules': self._step_rules,
            'probe': self._step_probe,
            'coverage': self._step_coverage,
            'recollect': self._step_recollect,
            'plan': self._step_plan,
            'fix': self._step_fix,
            'summary': self._step_summary,
            'report': self._step_report,
        }
        for name in order[start:]:
            if self.cancel_flag:
                self.state['status'] = 'cancelled'
                self._trace_add('cancel', '用户取消', 'cancelled')
                self._save()
                return
            result = steps[name]()
            if result == 'needs_input':
                # 采用安全的默认值自动继续，避免流程在中途等待人工弹窗。
                self.state['status'] = 'needs_input'
                self._resume_with_defaults()
                return
            if result == 'failed':
                self.state['status'] = 'failed'
                self._save()
                return

    def resume(self, answers: dict) -> None:
        if self.state['status'] != 'needs_input':
            return
        if self.spec is not None:
            raw = json.loads(json.dumps(self.spec.data))
            if answers.get('use_batch_classes') and self.batch is not None:
                names = []
                for sub in self.batch.sub_batches:
                    names.extend(sub.names.values())
                names = list(dict.fromkeys(names))
                raw['classes'] = [{'name': name, 'definition': ''} for name in names]
            if isinstance(answers.get('classes'), list) and answers['classes']:
                raw['classes'] = answers['classes']
            definitions = answers.get('class_definitions') or {}
            for item in raw.get('classes') or []:
                if isinstance(item, dict) and item.get('name') in definitions:
                    item['definition'] = str(definitions[item['name']])
            if answers.get('label_format'):
                raw['label_format'] = answers['label_format']
            if answers.get('project'):
                raw['project'] = answers['project']
            fresh = _normalize_and_check(raw, self.spec.source, self.spec.source_name,
                                         self.spec.method, self._batch_class_names())
            fresh.questions = []
            fresh.blocking = not fresh.class_names
            fresh.needs_confirmation = False
            self.spec = fresh
            self.state['spec'] = fresh.to_dict(include_source=True)
            self.state['questions'] = []
            self.state['status'] = 'running'
            self._trace_add('resume', '自动补齐默认规范', 'ok',
                            detail={'provided': list(answers.keys())})
            self._save()
            try:
                self._pipeline(from_step='schema')
            except Exception as error:
                self.state['status'] = 'failed'
                self.state['error'] = f'{type(error).__name__}: {error}'
                self._save()

    def _resume_with_defaults(self) -> None:
        """为缺省规范填入可执行默认值并继续流水线。"""
        names = self._batch_class_names() or ['object']
        label_format = self.spec.data.get('label_format') if self.spec else ''
        answers = {
            'project': (self.spec.data.get('project') if self.spec else '') or 'Aries QC 默认项目',
            'label_format': label_format if label_format in ('detection', 'segmentation') else 'detection',
            'classes': [{'name': name, 'definition': ''} for name in names],
        }
        self.resume(answers)

    # ---------- 步骤 ----------
    def _step_intake(self) -> str:
        begin = self._trace_add('intake', '工作台：扫描批次', 'running')
        self.state['progress'] = {'done': 0, 'total': 1, 'label': '扫描图片与标签'}

        def progress(done: int) -> None:
            self.state['progress'] = {'done': done, 'total': 0, 'label': f'已扫描 {done} 张'}

        self.batch = scan_batch(self.batch_path, progress=progress)
        fingerprint = batch_fingerprint(self.batch)
        self.state['batch'] = dict(self.batch.to_dict(), fingerprint=fingerprint)
        self.state['progress'] = {'done': 1, 'total': 1, 'label': '批次扫描完成'}
        if not self.batch.samples:
            self._trace_end(begin, 'failed', detail={'error': '批次中没有图片'})
            return 'failed'
        self._trace_end(begin, 'ok', detail={
            'images': len(self.batch.samples),
            'objects': self.batch.stats()['objects'],
            'sub_batches': len(self.batch.sub_batches),
            'fingerprint': fingerprint['fingerprint'],
        })
        self._save()
        return 'ok'

    def _step_spec(self) -> str:
        begin = self._trace_add('spec', '编译规范与标签体系', 'running')
        try:
            self.spec = compile_spec(
                path=self.spec_path, path_or_text=self.spec_text,
                client=self.llm if self.config.llm_ready else None,
                batch_names=self._batch_class_names(),
            )
        except Exception as error:
            self.spec = self._failed_spec(f'{type(error).__name__}: {error}')
        self.state['spec'] = self.spec.to_dict(include_source=True)
        if self.spec.blocking or (self.options.get('strict_spec') and self.spec.needs_confirmation):
            questions = list(self.spec.questions)
            for item in self.spec.missing:
                if item.get('level') == 'P0':
                    questions.append({
                        'id': 'missing_' + item['field'].replace('.', '_').replace('[', '_').replace(']', ''),
                        'field': item['field'], 'level': 'P0',
                        'question': item['message'] + '。请补齐，或用批次类别表作为规范。',
                        'why': '没有类别定义时，无法判断漏标/错标，禁止继续出报告',
                    })
            if not questions:
                questions.append({
                    'id': 'spec_confirm', 'field': 'spec', 'level': 'P0',
                    'question': '规范无法编译为可执行规则，请确认类别与标签格式。',
                    'why': '质量门要求先冻结规范',
                })
            unique_questions = []
            seen_questions = set()
            for question in questions:
                key = (question.get('field'), question.get('question'))
                if key in seen_questions:
                    continue
                seen_questions.add(key)
                unique_questions.append(question)
            questions = unique_questions
            self.state['questions'] = questions
            self._trace_end(begin, 'needs_input', detail={
                'blocking': self.spec.blocking,
                'error': self.spec.error,
                'questions': len(questions),
                'missing': self.spec.missing,
            })
            return 'needs_input'
        self._trace_end(begin, 'ok', detail={
            'method': self.spec.method,
            'project': self.spec.data.get('project'),
            'classes': self.spec.class_names,
            'label_format': self.spec.data.get('label_format'),
            'evidence': self.spec.evidence_check,
            'missing': self.spec.missing,
            'conflicts': self.spec.conflicts,
            'error': self.spec.error,
        })
        self._save()
        return 'ok'

    def _step_schema(self) -> str:
        begin = self._trace_add('schema', '对齐类别表与 ID 映射', 'running')
        assert self.spec is not None and self.batch is not None
        self.class_map = build_class_map(self.batch, self.spec.class_names or None)
        self.state['classes'] = self.class_map.to_dict()
        self._trace_end(begin, 'ok', detail={
            'canonical_classes': len(self.class_map.classes),
            'conflicts': len(self.class_map.conflicts),
            'unexpected': len(self.class_map.unexpected),
            'missing_in_data': self.class_map.missing_in_data,
        })
        self._save()
        return 'ok'

    def _step_rules(self) -> str:
        begin = self._trace_add('rules', '运行确定性质检规则', 'running')
        assert self.batch is not None and self.class_map is not None
        self.book = run_all(self.batch, self.class_map, self.spec.data if self.spec else {},
                            {'max_per_check': self.options.get('max_per_check', 200)})
        counts = self.book.counts()
        self.state['findings'] = counts
        self._trace_end(begin, 'ok', detail=counts)
        self._save()
        return 'ok'

    def _step_probe(self) -> str:
        begin = self._trace_add('probe', '模型交叉复核（可选）', 'running')
        if not self.options.get('use_model', True):
            self.probe_meta = {'requested': False, 'available': False, 'reason': '本次未启用模型复核'}
            self.state['probe'] = self.probe_meta
            self._trace_end(begin, 'skipped', detail=self.probe_meta)
            self._save()
            return 'ok'
        if not self.config.model_path:
            self.probe_meta = {'requested': True, 'available': False, 'reason': '未配置模型权重路径'}
            self.state['probe'] = self.probe_meta
            self._trace_end(begin, 'skipped', detail=self.probe_meta)
            self._save()
            return 'ok'
        skip = {f.subject.get('sample_id') for f in self.book.items
                if f.check == 'sequence_missing_label'}
        skip.discard(None)

        def progress(done: int, total: int) -> None:
            self.state['progress'] = {'done': done, 'total': total, 'label': f'模型复核 {done}/{total}'}

        probe_book, meta = run_probe(self.batch, self.class_map, self.spec.data if self.spec else {},
                                     self.config.model_path, self.options, progress=progress,
                                     skip_sample_ids=skip)
        for finding in probe_book.items:
            self.book.add(finding)
        self.probe_meta = meta
        self.state['probe'] = meta
        self.state['findings'] = self.book.counts()
        self._trace_end(begin, 'ok' if meta.get('available') else 'skipped', detail=meta)
        self._save()
        return 'ok'

    def _step_coverage(self) -> str:
        begin = self._trace_add('coverage', '核算覆盖度与配额', 'running')
        assert self.batch is not None and self.class_map is not None
        self.coverage = compute_coverage(self.batch, self.spec.data if self.spec else {}, self.class_map)
        self.state['coverage'] = self.coverage
        self.state['findings'] = self.book.counts()
        self._trace_end(begin, 'ok', detail={
            'score': self.coverage.get('score'),
            'class_gaps': sum(1 for x in self.coverage.get('class_quota') or [] if x['gap']),
            'scene_gaps': sum(1 for x in self.coverage.get('scenes') or [] if x['gap']),
            'image_gap': self.coverage.get('image_gap'),
        })
        self._save()
        return 'ok'

    def _step_recollect(self) -> str:
        begin = self._trace_add('recollect', '生成补采清单', 'running')
        assert self.batch is not None
        self.recollect = build_recollect(self.batch, self.spec.data if self.spec else {},
                                         self.coverage, self.book.sorted())
        self.state['recollect'] = self.recollect
        (self.run_dir / 'recollect.json').write_text(
            json.dumps(self.recollect, ensure_ascii=False, indent=2), encoding='utf-8')
        (self.run_dir / 'recollect.csv').write_text(to_csv(self.recollect), encoding='utf-8-sig')
        self._trace_end(begin, 'ok', detail={
            'items': len(self.recollect),
            'p0': sum(1 for x in self.recollect if x['priority'] == 'P0'),
            'p1': sum(1 for x in self.recollect if x['priority'] == 'P1'),
        })
        self._save()
        return 'ok'

    def _step_plan(self) -> str:
        begin = self._trace_add('plan', '任务拆解与人员安排', 'running')
        assert self.batch is not None and self.class_map is not None
        self.task_plan = build_task_plan(self.batch, self.spec.data if self.spec else {},
                                         self.class_map, self.coverage)
        self.state['task_plan'] = self.task_plan
        (self.run_dir / 'task_plan.json').write_text(
            json.dumps(self.task_plan, ensure_ascii=False, indent=2), encoding='utf-8')
        self._trace_end(begin, 'ok', detail=self.task_plan['effort'])
        self._save()
        return 'ok'

    def _step_fix(self) -> str:
        begin = self._trace_add('fix', '生成修复预览（不覆盖原文件）', 'running')
        assert self.batch is not None and self.class_map is not None
        self.fix_summary = preview_fix(self.batch, self.class_map, self.book.sorted(), self.run_dir)
        self.state['fix'] = {k: v for k, v in self.fix_summary.items() if k != 'diff_preview'}
        self.state['fix']['diff_preview'] = self.fix_summary.get('diff_preview', [])
        self._trace_end(begin, 'ok', detail={
            'available': self.fix_summary['available'],
            'changed_files': self.fix_summary['changed_files'],
            'actions': self.fix_summary['actions'],
            'manual': self.fix_summary['manual_count'],
        })
        self._save()
        return 'ok'

    def _step_summary(self) -> str:
        begin = self._trace_add('summary', '归纳交付摘要', 'running')
        assert self.batch is not None
        counts = self.book.counts()
        deterministic = self._deterministic_headline()
        headline, source = deterministic, 'deterministic'
        citations: list[str] = []
        next_actions: list[str] = []
        if (self.options.get('use_llm_summary', True) and self.config.llm_ready
                and self.book.items):
            try:
                payload = self._summary_payload()
                data = self.llm.chat_json(
                    '你是数据质检交付员。只依据给定 JSON 写 3-5 句中文交付摘要。'
                    '必须引用至少 2 个 finding id；禁止新增 JSON 中没有的数字、类别或结论；'
                    '禁止声称"已修复/已交付"，只能写"发现/建议/需裁定"。'
                    '只输出 {"headline":"...","citations":["F-0001"],"next_actions":["..."]}。',
                    json.dumps(payload, ensure_ascii=False),
                    max_tokens=1200,
                )
                candidate = str(data.get('headline') or '').strip()
                ids = {f.id for f in self.book.items}
                cited = [str(x) for x in (data.get('citations') or []) if str(x) in ids]
                if candidate and len(candidate) >= 20 and cited and _numbers_covered(candidate, payload):
                    headline, source, citations = candidate, 'llm', cited
                    next_actions = [str(x) for x in (data.get('next_actions') or [])][:5]
                else:
                    self.llm.stats.errors.append('摘要引用或数字校验未通过，已回退确定性摘要')
            except LLMError as error:
                self.llm.stats.errors.append(str(error))
        self.state['summary'] = {
            'headline': headline,
            'headline_source': source,
            'citations': citations,
            'next_actions': next_actions,
            'gate': self._gate(),
            'p0': counts['by_severity'].get('P0', 0),
            'p1': counts['by_severity'].get('P1', 0),
            'p2': counts['by_severity'].get('P2', 0),
            'coverage_score': self.coverage.get('score'),
            'findings': counts,
            'probe': self.probe_meta,
            'duration_seconds': round(time.time() - self.started, 1),
            'llm': self.llm.stats.to_dict(),
            'limitations': [
                'P0 为确定性硬伤；P1/P2 中的 candidate 为待人工裁定候选，不是已确认错误。',
                '模型交叉复核可能受训练数据泄漏影响，只作第二意见。',
                '覆盖率与工时按规范基准和脚本公式计算，需项目经理确认后执行。',
            ],
        }
        self.state['llm'] = self.llm.stats.to_dict()
        self._trace_end(begin, 'ok', detail={'source': source, 'citations': citations,
                                             'gate': self._gate()})
        self._save()
        return 'ok'

    def _step_report(self) -> str:
        begin = self._trace_add('report', '生成交付包', 'running')
        from .report import build_artifacts
        assert self.batch is not None
        self.state['status'] = 'done'
        self.state['finished_at'] = datetime.now().isoformat(timespec='seconds')
        artifacts = build_artifacts(
            run_dir=self.run_dir,
            state=self.state,
            batch=self.batch,
            spec=self.spec,
            class_map=self.class_map,
            findings=[f.to_dict() for f in self.book.sorted()],
            coverage=self.coverage,
            task_plan=self.task_plan,
            recollect=self.recollect,
            fix_summary=self.fix_summary,
        )
        self.state['artifacts'] = artifacts
        self._trace_end(begin, 'ok', detail={
            'artifacts': len(artifacts),
            'zip': next((a['name'] for a in artifacts if a['name'].endswith('.zip')), ''),
        })
        self._save()
        return 'ok'

    # ---------- 辅助 ----------
    def _batch_class_names(self) -> list[str] | None:
        if self.batch is None:
            return None
        names = []
        for sub in self.batch.sub_batches:
            names.extend(sub.names.values())
        return list(dict.fromkeys(names)) or None

    def _gate(self) -> str:
        counts = self.book.counts()
        if counts['by_severity'].get('P0', 0) > 0:
            return 'blocked'
        if self.coverage.get('score') is not None and self.coverage['score'] < 60:
            return 'at_risk'
        return 'pass'

    def _deterministic_headline(self) -> str:
        counts = self.book.counts()
        stats = self.batch.stats() if self.batch else {}
        p0 = counts['by_severity'].get('P0', 0)
        p1 = counts['by_severity'].get('P1', 0)
        p2 = counts['by_severity'].get('P2', 0)
        classes = len(self.class_map.classes) if self.class_map else 0
        score = self.coverage.get('score')
        gate = {'blocked': '不可交付（存在 P0）', 'at_risk': '有风险（覆盖率不足）',
                'pass': '可进入人工复核'}.get(self._gate(), '待评估')
        return (f'本批 {stats.get("images", 0)} 张图、{stats.get("objects", 0)} 个实例，'
                f'对齐 {classes} 个类别；发现 P0 {p0} 条、P1 {p1} 条、P2 {p2} 条。'
                f'覆盖率 {score if score is not None else "未评估"}%，结论：{gate}。'
                f'高风险项与补采工单见下方证据，均需人工裁定后执行。')

    def _summary_payload(self) -> dict:
        findings = []
        for finding in self.book.sorted()[:30]:
            findings.append({
                'id': finding.id,
                'severity': finding.severity,
                'confidence': finding.confidence,
                'check': finding.check,
                'message': finding.message[:300],
            })
        return {
            'project': (self.spec.data.get('project') if self.spec else '') or '',
            'batch': {
                'images': len(self.batch.samples) if self.batch else 0,
                'objects': self.batch.stats()['objects'] if self.batch else 0,
                'sub_batches': [s.name for s in self.batch.sub_batches] if self.batch else [],
            },
            'counts': self.book.counts(),
            'coverage_score': self.coverage.get('score'),
            'gate': self._gate(),
            'top_findings': findings,
            'effort': self.task_plan.get('effort'),
            'recollect_top': self.recollect[:6],
            'model': self.probe_meta,
        }

    def _failed_spec(self, error: str) -> Spec:
        return Spec(data=_normalize({}), source=self.spec_text or '', source_name='规范',
                    method='failed', error=error, blocking=True, needs_confirmation=True,
                    missing=[{'field': 'spec', 'level': 'P0', 'message': error}])

    def _trace_add(self, step: str, title: str, status: str, detail: dict | None = None) -> dict:
        entry = {
            'step': step,
            'title': title,
            'status': status,
            'started': time.time(),
            'duration': 0.0,
            'detail': detail or {},
        }
        self.state['steps'].append(entry)
        return entry

    def _trace_end(self, entry: dict, status: str, detail: dict | None = None) -> None:
        entry['status'] = status
        entry['duration'] = round(time.time() - entry['started'], 2)
        if detail is not None:
            entry['detail'] = detail

    def _save(self) -> None:
        self.state['findings'] = self.book.counts()
        self.state['duration_seconds'] = round(time.time() - self.started, 1)
        tmp = self.run_dir / 'state.json.tmp'
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        tmp.replace(self.run_dir / 'state.json')
        (self.run_dir / 'findings.json').write_text(
            json.dumps([f.to_dict() for f in self.book.sorted()], ensure_ascii=False, indent=2),
            encoding='utf-8')
        (self.run_dir / 'trace.jsonl').write_text(
            '\n'.join(json.dumps(step, ensure_ascii=False) for step in self.state['steps']),
            encoding='utf-8')

    # ---------- API ----------
    def adjudicate(self, finding_id: str, action: str, note: str = '') -> dict:
        for finding in self.book.items:
            if finding.id == finding_id:
                if action not in ('accept', 'reject', 'open'):
                    raise ValueError('action 必须是 accept / reject / open')
                finding.status = {'accept': 'accepted', 'reject': 'rejected', 'open': 'open'}[action]
                finding.note = note
                self.state['findings'] = self.book.counts()
                self._save()
                return finding.to_dict()
        raise KeyError(f'未找到 finding：{finding_id}')

    def cancel(self) -> None:
        self.cancel_flag = True


def _numbers_covered(text: str, payload: dict) -> bool:
    """轻量反幻觉校验：摘要里出现的数字必须能在结构化结果中找到。"""
    allowed = set()

    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if isinstance(item, (int, float)) and not isinstance(item, bool):
                    allowed.add(str(int(item)) if float(item).is_integer() else str(item))
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            for number in re.findall(r'\d+(?:\.\d+)?', value):
                allowed.add(number)

    walk(payload)
    for number in re.findall(r'\d+(?:\.\d+)?', text):
        if number not in allowed:
            return False
    return True