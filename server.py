"""Aries QC Web 服务：接单、实时轨迹、证据查看、人工裁定、交付下载。"""
from __future__ import annotations

import argparse
import io
import json
import mimetypes
import re
import shutil
import threading
import time
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np

from employee.config import Config, ROOT
from employee.regression.pipeline import RegressionRunner
from employee.runner import Runner

STATIC = ROOT / 'static'
UPLOADS = ROOT / 'uploads'
CONFIG = Config.load()
RUNNERS: dict[str, Runner] = {}
REG_RUNNERS: dict[str, RegressionRunner] = {}
LOCK = threading.Lock()
STARTED = time.time()


def _json(handler, data, status=200):
    payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(payload)))
    handler.send_header('Cache-Control', 'no-store')
    handler.end_headers()
    handler.wfile.write(payload)


def _error(handler, message, status=400):
    _json(handler, {'error': message}, status)


def _read_json(handler) -> dict:
    length = int(handler.headers.get('Content-Length') or 0)
    if length > 4_000_000:
        raise ValueError('请求体过大')
    raw = handler.rfile.read(length) if length else b'{}'
    data = json.loads(raw.decode('utf-8') or '{}')
    if not isinstance(data, dict):
        raise ValueError('请求体必须是 JSON 对象')
    return data


def _safe_child(root: Path, target: Path) -> bool:
    try:
        target.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _run(run_id: str) -> Runner | None:
    with LOCK:
        return RUNNERS.get(run_id)


def _reg_run(run_id: str) -> RegressionRunner | None:
    with LOCK:
        return REG_RUNNERS.get(run_id)


class Handler(BaseHTTPRequestHandler):
    server_version = 'Aries QC/0.1'

    def log_message(self, fmt, *args):
        if '/api/runs/' in (args[0] if args else '') and 'GET' in str(args[0]):
            return
        print(f'[{self.log_date_time_string()}] {fmt % args}')

    # ---------- 路由 ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == '/':
            return self._serve_file(STATIC / 'index.html')
        if path.startswith('/static/'):
            return self._serve_file(STATIC / path[len('/static/'):])
        if path == '/favicon.ico':
            self.send_response(204)
            self.end_headers()
            return
        if path == '/api/health':
            return _json(self, {
                'ok': True,
                'version': '0.1.0',
                'config': CONFIG.public(),
                'uptime': round(time.time() - STARTED, 1),
                'runs': len(RUNNERS),
                'regression_runs': len(REG_RUNNERS),
            })
        if path == '/api/batches':
            return _json(self, {'items': [b.to_dict() for b in CONFIG.batches()]})
        if path == '/api/specs':
            return _json(self, {'items': CONFIG.specs()})
        if path == '/api/runs':
            return _json(self, {'items': [self._run_brief(r) for r in RUNNERS.values()]})
        match = re.match(r'^/api/runs/([^/]+)$', path)
        if match:
            return self._get_run(match.group(1))
        match = re.match(r'^/api/runs/([^/]+)/findings$', path)
        if match:
            return self._get_findings(match.group(1), parse_qs(parsed.query))
        match = re.match(r'^/api/runs/([^/]+)/sample/(\d+)$', path)
        if match:
            return self._get_sample(match.group(1), int(match.group(2)))
        match = re.match(r'^/api/runs/([^/]+)/image/(\d+)$', path)
        if match:
            return self._get_image(match.group(1), int(match.group(2)))
        match = re.match(r'^/api/runs/([^/]+)/thumb/(\d+)$', path)
        if match:
            return self._get_thumb(match.group(1), int(match.group(2)))
        match = re.match(r'^/api/runs/([^/]+)/artifact/([^/]+)$', path)
        if match:
            return self._get_artifact(match.group(1), match.group(2))
        match = re.match(r'^/api/runs/([^/]+)/download$', path)
        if match:
            return self._download(match.group(1))
        match = re.match(r'^/api/runs/([^/]+)/fixed\.zip$', path)
        if match:
            return self._download_fixed(match.group(1))
        if path == '/api/regression/options':
            return _json(self, {
                'datasets': CONFIG.regression_datasets(),
                'profiles': CONFIG.regression_profiles(),
                'thresholds': CONFIG.regression_thresholds(),
            })
        if path == '/api/regression/runs':
            return _json(self, {'items': [self._reg_run_brief(r) for r in REG_RUNNERS.values()]})
        match = re.match(r'^/api/regression/runs/([^/]+)$', path)
        if match:
            return self._get_reg_run(match.group(1))
        match = re.match(r'^/api/regression/runs/([^/]+)/cases$', path)
        if match:
            return self._get_reg_cases(match.group(1), parse_qs(parsed.query))
        match = re.match(r'^/api/regression/runs/([^/]+)/image$', path)
        if match:
            return self._get_reg_image(match.group(1), parse_qs(parsed.query))
        match = re.match(r'^/api/regression/runs/([^/]+)/artifact/([^/]+)$', path)
        if match:
            return self._get_reg_artifact(match.group(1), match.group(2))
        match = re.match(r'^/api/regression/runs/([^/]+)/download$', path)
        if match:
            return self._download_reg(match.group(1))
        return _error(self, 'not found', 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == '/api/runs':
                return self._create_run()
            match = re.match(r'^/api/runs/([^/]+)/adjudicate$', path)
            if match:
                return self._adjudicate(match.group(1))
            match = re.match(r'^/api/runs/([^/]+)/resume$', path)
            if match:
                return self._resume(match.group(1))
            match = re.match(r'^/api/runs/([^/]+)/cancel$', path)
            if match:
                return self._cancel(match.group(1))
            if path == '/api/upload/spec':
                return self._upload('spec')
            if path == '/api/upload/batch':
                return self._upload('batch')
            if path == '/api/regression/runs':
                return self._create_reg_run()
            match = re.match(r'^/api/regression/runs/([^/]+)/cancel$', path)
            if match:
                return self._cancel_reg(match.group(1))
            return _error(self, 'not found', 404)
        except ValueError as error:
            return _error(self, str(error), 400)
        except KeyError as error:
            return _error(self, str(error), 404)
        except Exception as error:
            return _error(self, f'{type(error).__name__}: {error}', 500)

    # ---------- 运行 ----------
    def _run_brief(self, runner: Runner) -> dict:
        state = runner.state
        return {
            'id': state.get('id'),
            'status': state.get('status'),
            'created_at': state.get('created_at'),
            'finished_at': state.get('finished_at'),
            'project': ((state.get('spec') or {}).get('data') or {}).get('project', ''),
            'headline': (state.get('summary') or {}).get('headline', ''),
            'gate': (state.get('summary') or {}).get('gate'),
            'findings': state.get('findings'),
        }

    def _create_run(self):
        body = _read_json(self)
        batch_path = body.get('batch_path') or ''
        batch_id = body.get('batch_id') or ''
        spec_path = body.get('spec_path') or ''
        spec_id = body.get('spec_id') or ''
        spec_text = body.get('spec_text') or ''
        if not batch_path and batch_id:
            match = next((b for b in CONFIG.batches() if b.id == batch_id), None)
            if match:
                batch_path = match.path
        if not batch_path:
            raise ValueError('请选择批次')
        batch = Path(batch_path)
        if not batch.exists():
            raise ValueError(f'批次路径不存在：{batch_path}')
        allowed = [Path(CONFIG.data_root), UPLOADS]
        if not any(_safe_child(root, batch) for root in allowed if root and str(root) != '.'):
            raise ValueError('批次必须位于配置的数据根目录或上传目录内')
        if not spec_text.strip():
            if not spec_path and spec_id:
                match = next((s for s in CONFIG.specs() if s['id'] == spec_id), None)
                if match:
                    spec_path = match['path']
            if not spec_path:
                raise ValueError('请选择或粘贴规范')
            if not Path(spec_path).exists():
                raise ValueError(f'规范文件不存在：{spec_path}')
        options = {
            'use_model': bool(body.get('use_model', True)),
            'strict_spec': bool(body.get('strict_spec', False)),
            'probe_max_images': int(body.get('probe_max_images') or 0),
            'use_llm_summary': bool(body.get('use_llm_summary', True)),
            'max_per_check': int(body.get('max_per_check') or 200),
        }
        runner = Runner(CONFIG, str(batch), spec_path=spec_path or None,
                        spec_text=spec_text or None, options=options)
        with LOCK:
            RUNNERS[runner.run_id] = runner
        thread = threading.Thread(target=runner.start, name=f'run-{runner.run_id}', daemon=True)
        thread.start()
        _json(self, {'id': runner.run_id, 'status': 'queued'})

    def _get_run(self, run_id: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        state = dict(runner.state)
        state['findings'] = runner.book.counts()
        batch = runner.batch
        if batch is not None:
            state['batch_names'] = [{'batch': s.name, 'names': dict(s.names)} for s in batch.sub_batches]
        _json(self, state)

    def _get_findings(self, run_id: str, query: dict):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        severity = (query.get('severity') or [''])[0]
        check = (query.get('check') or [''])[0]
        confidence = (query.get('confidence') or [''])[0]
        offset = int((query.get('offset') or ['0'])[0])
        limit = min(500, int((query.get('limit') or ['200'])[0]))
        items = runner.book.sorted()
        if severity:
            items = [x for x in items if x.severity == severity]
        if check:
            items = [x for x in items if x.check == check]
        if confidence:
            items = [x for x in items if x.confidence == confidence]
        _json(self, {
            'total': len(items),
            'offset': offset,
            'items': [x.to_dict() for x in items[offset:offset + limit]],
            'checks': runner.book.counts().get('by_check', {}),
        })

    def _get_sample(self, run_id: str, sample_id: int):
        runner = _run(run_id)
        if runner is None or runner.batch is None:
            return _error(self, '运行不存在', 404)
        sample = next((s for s in runner.batch.samples if s.id == sample_id), None)
        if sample is None:
            return _error(self, '样本不存在', 404)
        names = runner.batch.names_for(sample.batch)
        findings = [f.to_dict() for f in runner.book.items
                    if f.subject.get('sample_id') == sample_id]
        _json(self, {
            'sample': sample.to_dict(),
            'image_url': f'/api/runs/{run_id}/image/{sample_id}',
            'names': {str(k): v for k, v in names.items()},
            'objects': [
                {'cls': o.cls_id, 'name': names.get(o.cls_id, f'class_{o.cls_id}'),
                 'kind': o.kind, 'coords': o.coords, 'bbox': o.bbox}
                for o in sample.objects
            ],
            'findings': findings,
        })

    def _get_image(self, run_id: str, sample_id: int):
        runner = _run(run_id)
        if runner is None or runner.batch is None:
            return _error(self, '运行不存在', 404)
        sample = next((s for s in runner.batch.samples if s.id == sample_id), None)
        if sample is None:
            return _error(self, '样本不存在', 404)
        self._serve_file(Path(sample.image_path))

    def _get_thumb(self, run_id: str, sample_id: int):
        runner = _run(run_id)
        if runner is None or runner.batch is None:
            return _error(self, '运行不存在', 404)
        sample = next((s for s in runner.batch.samples if s.id == sample_id), None)
        if sample is None:
            return _error(self, '样本不存在', 404)
        cache = runner.run_dir / 'thumbs' / f'{sample_id}.jpg'
        if not cache.exists():
            cache.parent.mkdir(exist_ok=True)
            image = _load(sample.image_path)
            if image is None:
                return _error(self, '图片不可读', 404)
            height, width = image.shape[:2]
            scale = 360 / max(1, width)
            thumb = cv2.resize(image, (360, max(1, int(height * scale))), interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode('.jpg', thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
            if not ok:
                return _error(self, '缩略图生成失败', 500)
            cache.write_bytes(buf.tobytes())
        self._serve_file(cache)

    def _get_artifact(self, run_id: str, name: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        allowed = {a['name'] for a in runner.state.get('artifacts') or []}
        allowed.update({'report.html', 'report.md', 'delivery.zip', 'fix_diff.json'})
        if name not in allowed:
            return _error(self, 'artifact 不在白名单', 403)
        path = runner.run_dir / name
        if not path.exists():
            return _error(self, 'artifact 不存在', 404)
        self._serve_file(path, download=name.endswith('.zip'))

    def _download(self, run_id: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        path = runner.run_dir / 'delivery.zip'
        if not path.exists():
            return _error(self, '交付包尚未生成', 404)
        self._serve_file(path, download=True, filename=f'aries_qc_{run_id}.zip')

    def _download_fixed(self, run_id: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        fixed = runner.run_dir / 'fixed'
        if not fixed.exists():
            return _error(self, '没有可导出的修复文件', 404)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in fixed.rglob('*'):
                if path.is_file():
                    archive.write(path, str(path.relative_to(fixed)).replace('\\', '/'))
            for name in ('class_map.json', 'fix_diff.json'):
                path = runner.run_dir / name
                if path.exists():
                    archive.write(path, name)
        payload = buffer.getvalue()
        self.send_response(200)
        self.send_header('Content-Type', 'application/zip')
        self.send_header('Content-Disposition', f'attachment; filename="aries_qc_fixed_{run_id}.zip"')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    # ---------- 人工介入 ----------
    def _adjudicate(self, run_id: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        body = _read_json(self)
        finding = runner.adjudicate(str(body.get('finding_id') or ''),
                                    str(body.get('action') or ''), str(body.get('note') or ''))
        _json(self, finding)

    def _resume(self, run_id: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        if runner.state.get('status') != 'needs_input':
            return _error(self, '该运行不在待确认状态', 409)
        body = _read_json(self)
        answers = body.get('answers') if isinstance(body.get('answers'), dict) else body
        thread = threading.Thread(target=runner.resume, args=(answers,), daemon=True)
        thread.start()
        _json(self, {'id': run_id, 'status': 'running'})

    def _cancel(self, run_id: str):
        runner = _run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        runner.cancel()
        _json(self, {'id': run_id, 'cancelled': True})

    # ---------- 模型回归门禁 ----------
    def _reg_run_brief(self, runner: RegressionRunner) -> dict:
        state = runner.state
        return {
            'id': state.get('id'),
            'status': state.get('status'),
            'created_at': state.get('created_at'),
            'finished_at': state.get('finished_at'),
            'dataset': (state.get('dataset') or {}),
            'verdict': (state.get('decision') or {}).get('verdict'),
        }

    def _create_reg_run(self):
        body = _read_json(self)
        dataset_id = body.get('dataset_id') or ''
        baseline_id = body.get('baseline_id') or ''
        candidate_id = body.get('candidate_id') or ''
        dataset_path = next((d['path'] for d in CONFIG.regression_datasets() if d['id'] == dataset_id), '')
        baseline_path = next((p['path'] for p in CONFIG.regression_profiles() if p['id'] == baseline_id), '')
        candidate_path = next((p['path'] for p in CONFIG.regression_profiles() if p['id'] == candidate_id), '')
        if not dataset_path:
            raise ValueError('请选择旧展项数据集')
        if not baseline_path or not candidate_path:
            raise ValueError('请选择基线模型和候选模型档案')
        thresholds = body.get('thresholds') if isinstance(body.get('thresholds'), dict) else None
        runner = RegressionRunner(CONFIG, dataset_path, baseline_path, candidate_path, thresholds=thresholds)
        with LOCK:
            REG_RUNNERS[runner.run_id] = runner
        thread = threading.Thread(target=runner.start, name=f'reg-{runner.run_id}', daemon=True)
        thread.start()
        _json(self, {'id': runner.run_id, 'status': 'queued'})

    def _get_reg_run(self, run_id: str):
        runner = _reg_run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        _json(self, runner.state)

    def _get_reg_cases(self, run_id: str, query: dict):
        runner = _reg_run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        comparison = runner.state.get('comparison') or {}
        kind = (query.get('type') or ['missed'])[0]
        cls_filter = (query.get('class') or [''])[0]
        offset = int((query.get('offset') or ['0'])[0])
        limit = min(200, int((query.get('limit') or ['50'])[0]))
        field = 'missed_cases' if kind == 'missed' else 'false_positive_cases'
        items = comparison.get(field) or []
        if cls_filter:
            box_field = 'gt_box' if kind == 'missed' else 'pred_box'
            items = [c for c in items if c[box_field]['cls_name'] == cls_filter]
        _json(self, {'total': len(items), 'offset': offset, 'items': items[offset:offset + limit]})

    def _get_reg_image(self, run_id: str, query: dict):
        runner = _reg_run(run_id)
        if runner is None or runner.dataset is None:
            return _error(self, '运行不存在', 404)
        rel = (query.get('path') or [''])[0]
        if not rel:
            return _error(self, '缺少 path 参数', 400)
        target = runner.dataset.root / rel
        if not _safe_child(runner.dataset.root, target):
            return _error(self, '路径越界', 403)
        self._serve_file(target)

    def _get_reg_artifact(self, run_id: str, name: str):
        runner = _reg_run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        allowed = {a['name'] for a in runner.state.get('artifacts') or []}
        if name not in allowed:
            return _error(self, 'artifact 不在白名单', 403)
        path = runner.run_dir / name
        if not path.exists():
            return _error(self, 'artifact 不存在', 404)
        self._serve_file(path, download=name.endswith('.zip'))

    def _download_reg(self, run_id: str):
        runner = _reg_run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        path = runner.run_dir / 'delivery.zip'
        if not path.exists():
            return _error(self, '交付包尚未生成', 404)
        self._serve_file(path, download=True, filename=f'regression_{run_id}.zip')

    def _cancel_reg(self, run_id: str):
        runner = _reg_run(run_id)
        if runner is None:
            return _error(self, '运行不存在', 404)
        runner.cancel()
        _json(self, {'id': run_id, 'cancelled': True})

    # ---------- 上传 ----------
    def _upload(self, kind: str):
        length = int(self.headers.get('Content-Length') or 0)
        limit = 320 * 1024 * 1024 if kind == 'batch' else 12 * 1024 * 1024
        if length <= 0 or length > limit:
            raise ValueError(f'文件大小超出限制（上限 {limit // 1024 // 1024} MB）')
        content_type = self.headers.get('Content-Type', '')
        if 'boundary=' not in content_type:
            raise ValueError('不是 multipart/form-data')
        body = self.rfile.read(length)
        files = _parse_multipart(content_type, body)
        if not files:
            raise ValueError('没有读到文件')
        filename, payload = files[0]
        UPLOADS.mkdir(exist_ok=True)
        token = uuid.uuid4().hex[:10]
        safe_name = re.sub(r'[^\w\u4e00-\u9fa5.\-]+', '_', Path(filename).name) or 'upload'
        if kind == 'spec':
            target = UPLOADS / f'spec_{token}_{safe_name}'
            target.write_bytes(payload)
            _json(self, {'path': str(target), 'name': filename, 'size': len(payload)})
            return
        if not safe_name.lower().endswith('.zip'):
            raise ValueError('批次上传目前只支持 zip')
        archive_path = UPLOADS / f'batch_{token}.zip'
        archive_path.write_bytes(payload)
        target_dir = UPLOADS / f'batch_{token}'
        target_dir.mkdir(parents=True, exist_ok=True)
        _extract_zip(archive_path, target_dir)
        dataset_root = _dataset_root(target_dir)
        _json(self, {'path': str(dataset_root), 'name': filename, 'size': len(payload)})

    # ---------- 静态文件 ----------
    def _serve_file(self, path: Path, download: bool = False, filename: str = ''):
        if not path.exists() or not path.is_file():
            return _error(self, '文件不存在', 404)
        ctype = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if path.suffix.lower() in ('.md', '.txt', '.json', '.csv'):
            ctype = 'text/plain; charset=utf-8'
        if path.suffix.lower() == '.html':
            ctype = 'text/html; charset=utf-8'
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(payload)))
        if download:
            name = filename or path.name
            self.send_header('Content-Disposition', f'attachment; filename="{name}"')
        self.send_header('Cache-Control', 'no-store' if path.suffix == '.html' else 'max-age=300')
        self.end_headers()
        self.wfile.write(payload)


def _load(path: str):
    try:
        buf = np.fromfile(path, dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _parse_multipart(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    match = re.search(r'boundary=([^;]+)', content_type)
    if not match:
        return []
    boundary = match.group(1).strip('"').encode()
    results = []
    for chunk in body.split(b'--' + boundary):
        if not chunk or chunk in (b'--\r\n', b'--'):
            continue
        chunk = chunk.lstrip(b'\r\n')
        if chunk.startswith(b'--'):
            break
        header_blob, sep, payload = chunk.partition(b'\r\n\r\n')
        if not sep:
            continue
        headers = header_blob.decode('utf-8', 'replace')
        name_match = re.search(r'filename="([^"]*)"', headers)
        if not name_match:
            continue
        payload = payload.rstrip(b'\r\n')
        results.append((name_match.group(1), payload))
    return results


def _extract_zip(path: Path, target: Path) -> None:
    total = 0
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace('\\', '/')
            if name.startswith('/') or '..' in Path(name).parts:
                continue
            if info.file_size > 200 * 1024 * 1024:
                continue
            total += info.file_size
            if total > 2 * 1024 * 1024 * 1024:
                raise ValueError('解压后体积超过 2GB')
            destination = target / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, destination.open('wb') as output:
                shutil.copyfileobj(source, output)


def _dataset_root(root: Path) -> Path:
    candidates = []
    if (root / 'images').is_dir() or (root / 'labels').is_dir():
        candidates.append(root)
    for child in root.iterdir():
        if child.is_dir() and ((child / 'images').is_dir() or (child / 'labels').is_dir()):
            candidates.append(child)
    return candidates[0] if len(candidates) == 1 else root


def main() -> None:
    parser = argparse.ArgumentParser(description='Aries QC Web 服务')
    parser.add_argument('--port', type=int, default=CONFIG.port)
    parser.add_argument('--host', default=CONFIG.host)
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    url = f'http://{args.host}:{args.port}/'
    print(f'Aries QC Web 服务已启动：{url}')
    print(f'模型：{CONFIG.model or "未配置"} | 数据根目录：{CONFIG.data_root}')
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n正在关闭…')
        server.shutdown()


if __name__ == '__main__':
    main()