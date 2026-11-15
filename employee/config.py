"""运行配置：环境变量、演示批次、规范目录。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / 'fixtures'
SPECS_DIR = FIXTURES / 'specs'
REGRESSION_DIR = FIXTURES / 'regression'
REGRESSION_DATASETS_DIR = REGRESSION_DIR / 'datasets'
REGRESSION_PROFILES_DIR = REGRESSION_DIR / 'profiles'


def load_env(path: Path | None = None) -> None:
    """读取 .env（UTF-8 BOM 安全）；已存在的环境变量优先。"""
    path = path or (ROOT / '.env')
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _b(name: str, default):
    raw = os.environ.get(name)
    if raw is None or raw == '':
        return default
    return raw.strip().lower() in ('1', 'true', 'yes', 'on')


def _i(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, ''))
    except (TypeError, ValueError):
        return default


def _env(name: str, default: str = '') -> str:
    """读取 Aries QC 配置变量。"""
    return os.environ.get(f'ARIES_QC_{name}', default)


@dataclass
class BatchInfo:
    id: str
    name: str
    path: str
    classes: list[str] = field(default_factory=list)
    note: str = ''

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'path': self.path,
            'classes': self.classes,
            'note': self.note,
        }


@dataclass
class Config:
    data_root: str
    model_path: str
    base_url: str
    model: str
    api_key: str
    timeout: int
    max_llm_calls: int
    host: str = '127.0.0.1'
    port: int = 8765

    @classmethod
    def load(cls) -> 'Config':
        load_env()
        return cls(
            data_root=_env('DATA_ROOT'),
            model_path=_env('MODEL_PATH'),
            base_url=_env('BASE_URL').rstrip('/'),
            model=_env('MODEL'),
            api_key=_env('API_KEY'),
            timeout=_i('ARIES_QC_TIMEOUT', 120),
            max_llm_calls=_i('ARIES_QC_MAX_LLM_CALLS', 6),
            host=_env('HOST', '127.0.0.1'),
            port=_i('ARIES_QC_PORT', 8765),
        )

    @property
    def llm_ready(self) -> bool:
        return bool(self.base_url and self.model and self.api_key)

    def public(self) -> dict:
        return {
            'llm_ready': self.llm_ready,
            'model': self.model if self.llm_ready else '',
            'data_root': self.data_root,
            'model_path': self.model_path if Path(self.model_path).exists() else '',
            'model_available': bool(self.model_path and Path(self.model_path).exists()),
        }

    def batches(self) -> list[BatchInfo]:
        """发现数据根目录下的演示批次（只读，不复制）。"""
        root = Path(self.data_root) if self.data_root else None
        if not root or not root.exists():
            return []
        candidates: list[Path] = []
        if _looks_like_dataset(root):
            candidates = [root]
        else:
            for child in sorted(root.iterdir()):
                if child.is_dir() and _looks_like_dataset(child):
                    candidates.append(child)
        result: list[BatchInfo] = []
        for path in candidates:
            names = _read_names(path)
            label = _short_name(path)
            result.append(BatchInfo(
                id=path.name,
                name=label,
                path=str(path),
                classes=names,
                note=f'{len(names)} 类' if names else '未找到 dataset.yaml',
            ))
        if len(candidates) > 1:
            union: list[str] = []
            for item in result:
                union.extend(item.classes)
            result.insert(0, BatchInfo(
                id=root.name,
                name=f'{root.name} · 全部子批次',
                path=str(root),
                classes=list(dict.fromkeys(union)),
                note=f'{len(candidates)} 个子批次合并检查',
            ))
        return result

    def specs(self) -> list[dict]:
        items = []
        if not SPECS_DIR.exists():
            return items
        for path in sorted(SPECS_DIR.iterdir()):
            if path.suffix.lower() not in ('.yaml', '.yml', '.md', '.txt', '.json'):
                continue
            items.append({
                'id': path.name,
                'name': path.stem,
                'path': str(path),
                'kind': path.suffix.lower().lstrip('.'),
                'preview': path.read_text(encoding='utf-8-sig', errors='replace')[:400],
            })
        return items

    def regression_datasets(self) -> list[dict]:
        """发现回归门禁可用的旧展项数据集（只读模拟演示数据）。"""
        items = []
        if not REGRESSION_DATASETS_DIR.exists():
            return items
        for path in sorted(REGRESSION_DATASETS_DIR.iterdir()):
            data_yaml = path / 'dataset.yaml'
            if not path.is_dir() or not data_yaml.exists():
                continue
            names = _read_names(path)
            items.append({
                'id': path.name,
                'name': path.name,
                'path': str(data_yaml),
                'classes': names,
                'note': f'{len(names)} 类',
            })
        return items

    def regression_profiles(self) -> list[dict]:
        """发现回归门禁可用的模拟健康度档案（基线/候选）。"""
        items = []
        if not REGRESSION_PROFILES_DIR.exists():
            return items
        for path in sorted(REGRESSION_PROFILES_DIR.iterdir()):
            if path.suffix.lower() not in ('.yaml', '.yml', '.json') or path.stem == 'thresholds':
                continue
            try:
                import yaml
                data = yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}
            except Exception:
                data = {}
            items.append({
                'id': path.stem,
                'name': data.get('model_name', path.stem),
                'path': str(path),
            })
        return items

    def regression_thresholds(self) -> dict:
        """默认验收阈值；找不到档案时返回保守默认值。"""
        path = REGRESSION_PROFILES_DIR / 'thresholds.yaml'
        if not path.exists():
            return {'map50_min': 0.75, 'per_class_drop_max': 0.05, 'recall_drop_max': 0.1, 'critical_classes': []}
        import yaml
        return yaml.safe_load(path.read_text(encoding='utf-8-sig')) or {}


def _looks_like_dataset(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / 'images').is_dir() or (path / 'labels').is_dir()


def _short_name(path: Path) -> str:
    name = path.name
    for prefix in ('dataset(', 'dataset_', 'dataset-'):
        if name.lower().startswith(prefix) and name.endswith(')'):
            return name[len(prefix):-1]
    return name


def _read_names(root: Path) -> list[str]:
    for filename in ('dataset.yaml', 'data.yaml', 'dataset.yml'):
        candidate = root / filename
        if not candidate.exists():
            continue
        try:
            import yaml
            data = yaml.safe_load(candidate.read_text(encoding='utf-8-sig')) or {}
            raw = data.get('names')
            if isinstance(raw, dict):
                return [str(raw[k]) for k in sorted(raw, key=lambda x: int(x))]
            if isinstance(raw, list):
                return [str(x) for x in raw]
        except Exception:
            return []
    return []


def state_path() -> Path:
    return ROOT / 'runs'


def ensure_dirs() -> None:
    state_path().mkdir(parents=True, exist_ok=True)