"""规范编译器：把 PDF/MD/DOCX/YAML 规范编译成可执行规则与配额。

防幻觉原则：
- YAML/JSON 走确定性解析；
- 自由文本走模型编译，但必须回引原文，引用不实会被记录；
- 规范没写的数字保持 null，不替客户拍脑袋。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .provider import LLMClient, LLMError

PALETTE = ['#7bd88f', '#6ec6ff', '#ffd166', '#ff8a65', '#c792ea', '#4dd0e1',
           '#f06292', '#aed581', '#ffb74d', '#9575cd']

DEFAULTS: dict = {
    'project': '',
    'label_format': 'either',
    'classes': [],
    'scenes': [],
    'requirements': {
        'min_images': 0,
        'min_per_class': 0,
        'min_resolution': [0, 0],
        'max_blur_ratio': 1.0,
        'orientation': 'any',
    },
    'qc': {
        'sample_rate': 0.1,
        'overlap_iou': 0.5,
        'duplicate_iou': 0.98,
        'model_conf': 0.5,
    },
    'delivery': {'format': 'YOLO', 'acceptance': ''},
    'norms': {
        'annotate_boxes_per_hour': 80,
        'review_boxes_per_hour': 250,
        'qa_images_per_hour': 200,
        'workday_hours': 8,
        'deadline_days': 3,
    },
    'notes': '',
}

SYSTEM_PROMPT = '''你是「Aries QC」数据采集与标注质检员工的规范编译器。
只输出一个 JSON 对象，不要 markdown，不要解释，不要思考过程。

任务：把客户给的采集/标注规范编译成可执行 JSON，供程序做质检与任务拆解。
铁律：
1. 只提取规范里明确写出的类别、数字、配额、场景；没写就填 null 或 []，并在 missing 里说明，禁止按常识补造。
2. 每个关键字段尽量给 evidence：{"field":"classes[0].min_boxes","quote":"原文逐字摘录"}；quote 必须是原文连续片段，不能改写。
3. 类别名必须来自原文；不要合并、翻译或新增类别。
4. 如果规范自相矛盾，写进 conflicts，不要自行裁决。

输出结构：
{
  "project": "项目名或空字符串",
  "label_format": "detection|segmentation|either",
  "classes": [
    {"name":"类别名","definition":"判定标准","include":["包含什么"],"exclude":["不包含什么"],"min_boxes":null}
  ],
  "scenes": [{"name":"场景名","min_images":null}],
  "requirements": {"min_images":null,"min_per_class":null,"min_resolution":null,"max_blur_ratio":null,"orientation":null},
  "qc": {"sample_rate":null,"overlap_iou":null,"duplicate_iou":null,"model_conf":null},
  "delivery": {"format":"YOLO","acceptance":"验收说明"},
  "norms": {"annotate_boxes_per_hour":null,"review_boxes_per_hour":null,"qa_images_per_hour":null,"workday_hours":null,"deadline_days":null},
  "evidence": [{"field":"...","quote":"..."}],
  "missing": ["规范未写明的关键项"],
  "conflicts": ["规范内部的矛盾点"]
}
'''


@dataclass
class Spec:
    data: dict
    source: str
    source_name: str
    method: str                       # yaml | llm | heuristic
    evidence: list[dict] = field(default_factory=list)
    evidence_check: dict = field(default_factory=dict)
    missing: list[dict] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    questions: list[dict] = field(default_factory=list)
    needs_confirmation: bool = False
    blocking: bool = False
    error: str = ''

    def to_dict(self, include_source: bool = False) -> dict:
        data = {
            'data': self.data,
            'source_name': self.source_name,
            'method': self.method,
            'evidence': self.evidence,
            'evidence_check': self.evidence_check,
            'missing': self.missing,
            'conflicts': self.conflicts,
            'questions': self.questions,
            'needs_confirmation': self.needs_confirmation,
            'blocking': self.blocking,
            'error': self.error,
        }
        if include_source:
            data['source'] = self.source[:200_000]
        return data

    @property
    def class_names(self) -> list[str]:
        return [c['name'] for c in self.data.get('classes', []) if c.get('name')]


def compile_spec(path_or_text: str | None = None, *, path: str | Path | None = None,
                 client: LLMClient | None = None, source_name: str = '',
                 batch_names: list[str] | None = None,
                 options: dict | None = None) -> Spec:
    options = options or {}
    path_obj = Path(path) if path else None
    if path_obj and path_obj.exists():
        text = _extract_text(path_obj)
        source_name = source_name or path_obj.name
        if path_obj.suffix.lower() in ('.yaml', '.yml', '.json'):
            try:
                raw = yaml.safe_load(text) or {}
                if not isinstance(raw, dict):
                    raise ValueError('YAML 顶层必须是对象')
            except Exception as error:
                return _failed(source_name, f'规范 YAML 解析失败：{error}', text)
            spec = _normalize_and_check(raw, text, source_name, 'yaml', batch_names)
            return spec
    else:
        text = path_or_text or ''
        source_name = source_name or '粘贴的规范文本'

    if not text.strip():
        return _failed(source_name, '没有读到规范内容', '')

    if client is not None and client.available:
        try:
            raw = client.chat_json(SYSTEM_PROMPT, text[:24_000], max_tokens=3000)
            spec = _normalize_and_check(raw, text, source_name, 'llm', batch_names)
            if spec.class_names:
                return spec
            spec.error = '模型未编译出任何类别'
            # 继续走启发式，保留模型给出的缺失项
            fallback = _heuristic(text, source_name, batch_names)
            fallback.missing.extend(spec.missing)
            fallback.conflicts.extend(spec.conflicts)
            fallback.error = spec.error
            return fallback
        except LLMError as error:
            fallback = _heuristic(text, source_name, batch_names)
            fallback.error = f'模型编译失败：{error}'
            return fallback
    return _heuristic(text, source_name, batch_names)


def _failed(source_name: str, error: str, text: str) -> Spec:
    return Spec(data=json.loads(json.dumps(DEFAULTS)), source=text, source_name=source_name,
                method='failed', error=error, blocking=True, needs_confirmation=True,
                missing=[{'field': 'spec', 'level': 'P0', 'message': error}])


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        try:
            from pypdf import PdfReader
        except ImportError as error:
            raise RuntimeError('读取 PDF 需要 pypdf：pip install pypdf') from error
        reader = PdfReader(str(path))
        pages = []
        for index, page in enumerate(reader.pages, 1):
            pages.append(f'---PAGE {index}---\n' + (page.extract_text() or ''))
        return '\n'.join(pages)
    if suffix == '.docx':
        try:
            import docx
        except ImportError as error:
            raise RuntimeError('读取 DOCX 需要 python-docx：pip install python-docx') from error
        document = docx.Document(str(path))
        return '\n'.join(p.text for p in document.paragraphs)
    return path.read_text(encoding='utf-8-sig', errors='replace')


def _normalize_and_check(raw: dict, source_text: str, source_name: str,
                         method: str, batch_names: list[str] | None) -> Spec:
    data = _normalize(raw)
    enriched = _enrich_from_text(data, source_text)
    missing: list[dict] = []
    conflicts: list[str] = []
    questions: list[dict] = []

    if not data['project']:
        missing.append({'field': 'project', 'level': 'P1', 'message': '未识别项目名称'})
    if not data['classes']:
        missing.append({'field': 'classes', 'level': 'P0', 'message': '规范没有给出任何类别定义'})
    for index, cls in enumerate(data['classes']):
        if not cls.get('definition'):
            missing.append({'field': f'classes[{index}].definition', 'level': 'P1',
                            'message': f'类别「{cls["name"]}」缺少判定标准'})
            questions.append({
                'id': f'class_definition_{index}',
                'field': f'classes[{index}].definition',
                'level': 'P1',
                'question': f'类别「{cls["name"]}」的包含/排除边界是什么？',
                'why': '类别定义缺失会导致标注员各自理解，质检也无法判定错标',
            })
    if data['label_format'] == 'either':
        missing.append({'field': 'label_format', 'level': 'P1',
                        'message': '规范未明确检测框还是分割多边形'})
        questions.append({
            'id': 'label_format',
            'field': 'label_format',
            'level': 'P1',
            'question': '交付标签用检测框（bbox）还是分割多边形（polygon）？',
            'why': '两种格式的质检规则不同，混用会造成返工',
            'options': ['detection', 'segmentation', 'either'],
        })
    if not data['requirements']['min_images']:
        missing.append({'field': 'requirements.min_images', 'level': 'P2',
                        'message': '规范未写明本批次最少图像数'})

    # 证据回引校验
    evidence = []
    raw_evidence = raw.get('evidence') if isinstance(raw, dict) else None
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if not isinstance(item, dict):
                continue
            quote = str(item.get('quote') or '').strip()
            field_name = str(item.get('field') or '').strip()
            if not quote:
                continue
            evidence.append({'field': field_name, 'quote': quote,
                             'verified': _quote_exists(quote, source_text)})
    verified = sum(1 for item in evidence if item['verified'])
    invalid = [item for item in evidence if not item['verified']]
    ratio = (verified / len(evidence)) if evidence else 0.0
    evidence_check = {
        'total': len(evidence),
        'verified': verified,
        'invalid': len(invalid),
        'ratio': round(ratio, 3),
        'invalid_examples': [item['quote'][:60] for item in invalid[:3]],
        'enriched': enriched,
    }
    if invalid:
        conflicts.append(f'{len(invalid)} 条证据引用未能在原文中找到，已标记待人工复核')
    if evidence and ratio < 0.5:
        conflicts.append('超过一半的证据引用未通过原文校验，规范编译结果不可直接交付')

    # 规范缺失判断
    conflicts.extend(str(x) for x in (raw.get('conflicts') or []) if str(x).strip())
    llm_missing = [str(x) for x in (raw.get('missing') or []) if str(x).strip()]
    for item in llm_missing:
        if not any(item in m['message'] for m in missing):
            missing.append({'field': 'llm_reported', 'level': 'P2', 'message': item})

    blocking = not data['classes']
    needs_confirmation = blocking or (bool(evidence) and ratio < 0.5)
    if batch_names:
        normalized = {_norm_name(x) for x in batch_names}
        spec_norm = {_norm_name(x) for x in [c['name'] for c in data['classes']]}
        if spec_norm and normalized and not (spec_norm & normalized):
            conflicts.append('规范类别名与数据类别表完全对不上，禁止自动映射')
            needs_confirmation = True
    return Spec(data=data, source=source_text, source_name=source_name, method=method,
                evidence=evidence, evidence_check=evidence_check, missing=missing,
                conflicts=conflicts, questions=questions,
                needs_confirmation=needs_confirmation, blocking=blocking)


def _quote_exists(quote: str, text: str) -> bool:
    def clean(value: str) -> str:
        return re.sub(r'\s+', '', value)
    needle = clean(quote)
    if not needle:
        return False
    if len(needle) < 4:
        return bool(re.search(r'(?<!\d)' + re.escape(needle) + r'(?!\d)', text))
    return needle in clean(text)


def _norm_name(name: str) -> str:
    return re.sub(r'[\s_\-]+', ' ', str(name).strip().lower())


def _enrich_from_text(data: dict, text: str) -> list[str]:
    """用确定性正则补齐规范里格式稳定的字段，避免模型漏读简单数字。"""
    enriched: list[str] = []
    req = data['requirements']
    if req.get('min_resolution') in ([0, 0], None):
        match = re.search(r'(\d{3,4})\s*[×xX*]\s*(\d{3,4})', text)
        if match:
            req['min_resolution'] = [int(match.group(1)), int(match.group(2))]
            enriched.append('requirements.min_resolution')
    if float(req.get('max_blur_ratio') if req.get('max_blur_ratio') is not None else 1.0) >= 1.0:
        match = re.search(r'(?:模糊|失焦)[^。\n]{0,40}?(?:不超过|不得超过|≤|<=|低于)\s*(\d{1,3})\s*%', text)
        if match:
            req['max_blur_ratio'] = min(1.0, int(match.group(1)) / 100)
            enriched.append('requirements.max_blur_ratio')
    if int(req.get('min_images') or 0) <= 0:
        match = re.search(r'(?:不少于|至少|≥|>=)\s*(\d{2,6})\s*(?:张|幅)', text)
        if match:
            req['min_images'] = int(match.group(1))
            enriched.append('requirements.min_images')
    if data.get('label_format') == 'either':
        if re.search(r'分割|polygon|segmentation', text, re.I):
            data['label_format'] = 'segmentation'
            enriched.append('label_format')
        elif re.search(r'检测框|bounding box|bbox|detection', text, re.I):
            data['label_format'] = 'detection'
            enriched.append('label_format')
    return enriched


def _num(value, default=None, low=None, high=None):
    if value is None or value == '':
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if low is not None and number < low:
        number = low
    if high is not None and number > high:
        number = high
    return number


def _int(value, default=0, low=0):
    number = _num(value, default, low)
    try:
        return int(number)
    except (TypeError, ValueError):
        return default


def _normalize(raw: dict) -> dict:
    data = json.loads(json.dumps(DEFAULTS))
    data['project'] = str(raw.get('project') or '').strip()
    label_format = str(raw.get('label_format') or 'either').lower()
    if label_format not in ('detection', 'segmentation', 'either'):
        label_format = 'either'
    data['label_format'] = label_format

    classes = []
    for index, item in enumerate(raw.get('classes') or []):
        if isinstance(item, str):
            item = {'name': item}
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if not name:
            continue
        classes.append({
            'name': name,
            'definition': str(item.get('definition') or '').strip(),
            'include': [str(x) for x in (item.get('include') or []) if str(x).strip()],
            'exclude': [str(x) for x in (item.get('exclude') or []) if str(x).strip()],
            'min_boxes': _int(item.get('min_boxes'), 0, 0) if item.get('min_boxes') is not None else None,
            'color': str(item.get('color') or PALETTE[index % len(PALETTE)]),
        })
    data['classes'] = classes

    scenes = []
    for item in raw.get('scenes') or []:
        if isinstance(item, str):
            item = {'name': item}
        if not isinstance(item, dict):
            continue
        name = str(item.get('name') or '').strip()
        if name:
            scenes.append({'name': name,
                           'min_images': _int(item.get('min_images'), 0, 0) if item.get('min_images') is not None else None})
    data['scenes'] = scenes

    req = raw.get('requirements') or {}
    resolution = req.get('min_resolution')
    if isinstance(resolution, (int, float)):
        resolution = [int(resolution), int(resolution)]
    if not isinstance(resolution, (list, tuple)) or len(resolution) < 2:
        resolution = [0, 0]
    data['requirements'].update({
        'min_images': _int(req.get('min_images'), 0, 0),
        'min_per_class': _int(req.get('min_per_class'), 0, 0),
        'min_resolution': [max(0, int(resolution[0])), max(0, int(resolution[1]))],
        'max_blur_ratio': _num(req.get('max_blur_ratio'), 1.0, 0.0, 1.0),
        'orientation': str(req.get('orientation') or 'any').lower(),
    })

    qc = raw.get('qc') or {}
    data['qc'].update({
        'sample_rate': _num(qc.get('sample_rate'), 0.1, 0.0, 1.0),
        'overlap_iou': _num(qc.get('overlap_iou'), 0.5, 0.0, 1.0),
        'duplicate_iou': _num(qc.get('duplicate_iou'), 0.98, 0.0, 1.0),
        'model_conf': _num(qc.get('model_conf'), 0.5, 0.0, 1.0),
    })

    delivery = raw.get('delivery') or {}
    data['delivery'] = {
        'format': str(delivery.get('format') or 'YOLO'),
        'acceptance': str(delivery.get('acceptance') or ''),
    }

    norms = raw.get('norms') or {}
    for key, default in DEFAULTS['norms'].items():
        value = norms.get(key)
        if key == 'workday_hours':
            data['norms'][key] = _num(value, default, 1, 24)
        elif key == 'deadline_days':
            data['norms'][key] = _num(value, default, 0.5, 60)
        else:
            data['norms'][key] = _int(value, default, 1)
    data['notes'] = str(raw.get('notes') or '')
    return data


def _heuristic(text: str, source_name: str, batch_names: list[str] | None) -> Spec:
    """模型不可用时的确定性兜底：只认结构化写法，不猜。"""
    classes: list[dict] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 2:
            continue
        name = re.sub(r'[`*]', '', cells[0]).strip()
        if not name or name in ('类别', 'ClassName', 'class', '---') or set(name) <= set('-: '):
            continue
        key = _norm_name(name)
        if key in seen:
            continue
        definition = re.sub(r'[`*]', '', cells[1]).strip()
        quota = None
        for cell in cells[1:]:
            match = re.search(r'\b(\d{2,6})\b', cell)
            if match:
                quota = int(match.group(1))
                break
        if key:
            seen.add(key)
            classes.append({
                'name': name,
                'definition': definition if definition not in ('—', '-', '') else '',
                'min_boxes': quota,
            })
    label_format = 'either'
    if re.search(r'分割|polygon|segmentation', text, re.I):
        label_format = 'segmentation'
    elif re.search(r'检测框|bounding box|bbox|detection', text, re.I):
        label_format = 'detection'
    min_images = 0
    match = re.search(r'(?:不少于|至少|≥|>=)\s*(\d{2,6})\s*(?:张|幅|images?)', text)
    if match:
        min_images = int(match.group(1))
    raw = {
        'project': _first_heading(text),
        'label_format': label_format,
        'classes': classes,
        'requirements': {'min_images': min_images or None},
        'missing': ['规范未按可执行结构书写，已使用确定性兜底解析'] if classes else ['未解析出类别'],
        'conflicts': [],
        'evidence': [],
    }
    spec = _normalize_and_check(raw, text, source_name, 'heuristic', batch_names)
    if not classes:
        spec.error = '模型不可用，且规范中没有可解析的类别表；请补齐规范或使用 YAML'
        spec.blocking = True
    return spec


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        line = line.strip().lstrip('#').strip()
        if line and len(line) < 80:
            return line
    return ''