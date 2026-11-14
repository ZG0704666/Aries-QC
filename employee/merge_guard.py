"""跨批次类别表对齐：发现同名不同 ID、同 ID 不同名，并给出规范映射。"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from .dataset import Batch, SubBatch


def norm(name: str) -> str:
    return re.sub(r'[\s_\-]+', ' ', str(name).strip().lower())


@dataclass
class ClassEntry:
    canonical_id: int
    name: str
    sources: list[dict] = field(default_factory=list)
    in_spec: bool = True

    def to_dict(self) -> dict:
        return {
            'canonical_id': self.canonical_id,
            'name': self.name,
            'sources': self.sources,
            'in_spec': self.in_spec,
        }


@dataclass
class ClassMap:
    batches: dict[str, dict[int, int]]
    classes: list[ClassEntry]
    conflicts: list[dict]
    unexpected: list[dict]
    missing_in_data: list[str]

    def to_dict(self) -> dict:
        return {
            'batches': {b: {str(k): v for k, v in m.items()} for b, m in self.batches.items()},
            'classes': [c.to_dict() for c in self.classes],
            'conflicts': self.conflicts,
            'unexpected': self.unexpected,
            'missing_in_data': self.missing_in_data,
            'canonical_names': {c.canonical_id: c.name for c in self.classes},
        }

    def canonical_name(self, batch: str, cls_id: int) -> str:
        new_id = self.batches.get(batch, {}).get(cls_id)
        if new_id is None:
            return f'class_{cls_id}'
        for entry in self.classes:
            if entry.canonical_id == new_id:
                return entry.name
        return f'class_{cls_id}'

    def remap(self, batch: str, cls_id: int) -> int:
        return self.batches.get(batch, {}).get(cls_id, cls_id)


def build_class_map(batch: Batch, spec_classes: Iterable[str] | None = None) -> ClassMap:
    spec_names = [str(x).strip() for x in (spec_classes or []) if str(x).strip()]
    spec_norm = {norm(name): name for name in spec_names}
    conflicts: list[dict] = []

    canonical: list[ClassEntry] = []
    by_norm: dict[str, ClassEntry] = {}
    taken_ids: set[int] = set()

    # 1) 规范类别优先占位，保证 canonical ID 与规范顺序一致
    for index, name in enumerate(spec_names):
        key = norm(name)
        if key in by_norm:
            conflicts.append({
                'kind': 'spec_duplicate_name',
                'severity': 'P0',
                'message': f'规范中类别名重复：{name}',
                'names': [name, name],
            })
            continue
        entry = ClassEntry(index, name, [], True)
        canonical.append(entry)
        by_norm[key] = entry
        taken_ids.add(index)

    # 2) 数据类别：优先复用同名规范 ID；规范外类别按出现顺序追加
    for sub in batch.sub_batches:
        for cls_id, name in sorted(sub.names.items()):
            key = norm(name)
            if key in by_norm:
                entry = by_norm[key]
                entry.sources.append({'batch': sub.name, 'old_id': cls_id, 'name': name})
                continue
            next_id = 0
            while next_id in taken_ids:
                next_id += 1
            entry = ClassEntry(next_id, name, [{'batch': sub.name, 'old_id': cls_id, 'name': name}],
                               key in spec_norm)
            canonical.append(entry)
            by_norm[key] = entry
            taken_ids.add(next_id)

    # 3) 每个批次建立 old_id -> canonical_id
    maps: dict[str, dict[int, int]] = {}
    for sub in batch.sub_batches:
        mapping: dict[int, int] = {}
        for cls_id, name in sorted(sub.names.items()):
            entry = by_norm.get(norm(name))
            if entry is not None:
                mapping[cls_id] = entry.canonical_id
        maps[sub.name] = mapping

    # 4) 冲突检测
    seen_id_names: dict[int, dict[str, str]] = {}
    for sub in batch.sub_batches:
        for cls_id, name in sorted(sub.names.items()):
            seen_id_names.setdefault(cls_id, {})
            if norm(name) not in {norm(v) for v in seen_id_names[cls_id].values()}:
                seen_id_names[cls_id][sub.name] = name
    for cls_id, per_batch in sorted(seen_id_names.items()):
        unique = {norm(v) for v in per_batch.values()}
        if len(unique) > 1:
            conflicts.append({
                'kind': 'same_id_different_name',
                'severity': 'P0',
                'class_id': cls_id,
                'message': f'类别 ID {cls_id} 在不同批次含义不同：' +
                           '；'.join(f'{b}={n}' for b, n in per_batch.items()),
                'per_batch': per_batch,
            })
    name_ids: dict[str, dict[str, int]] = {}
    for sub in batch.sub_batches:
        for cls_id, name in sorted(sub.names.items()):
            name_ids.setdefault(norm(name), {})[sub.name] = cls_id
    for key, per_batch in sorted(name_ids.items()):
        if len(set(per_batch.values())) > 1:
            conflicts.append({
                'kind': 'same_name_different_id',
                'severity': 'P1',
                'class_name': next((sub.names[i] for sub in batch.sub_batches
                                    for i in sub.names if norm(sub.names[i]) == key), key),
                'message': '同一类别在不同批次使用了不同 ID：' +
                           '；'.join(f'{b}={i}' for b, i in per_batch.items()),
                'per_batch': per_batch,
            })
    for sub in batch.sub_batches:
        values = [norm(v) for v in sub.names.values()]
        if len(values) != len(set(values)):
            conflicts.append({
                'kind': 'duplicate_name_in_batch',
                'severity': 'P0',
                'batch': sub.name,
                'message': f'{sub.name} 的类别表存在重名类别',
            })
        if sub.nc is not None and sub.nc != len(sub.names):
            conflicts.append({
                'kind': 'nc_mismatch',
                'severity': 'P0',
                'batch': sub.name,
                'message': f'{sub.name} 的 nc={sub.nc} 与 names 数量 {len(sub.names)} 不一致',
            })

    unexpected = [
        {'batch': entry.sources[0]['batch'], 'name': entry.name,
         'canonical_id': entry.canonical_id}
        for entry in canonical
        if not entry.in_spec and spec_names
    ]
    present = {norm(entry.name) for entry in canonical if entry.sources}
    missing_in_data = [name for name in spec_names if norm(name) not in present]

    return ClassMap(maps, canonical, conflicts, unexpected, missing_in_data)


def conflict_findings(class_map: ClassMap):
    from .findings import Finding
    findings = []
    for conflict in class_map.conflicts:
        findings.append(Finding(
            check=f"class_{conflict['kind']}",
            severity=conflict.get('severity', 'P1'),
            confidence='deterministic',
            title='类别表冲突',
            message=conflict['message'],
            subject={
                'batch': conflict.get('batch', ''),
                'class_id': conflict.get('class_id'),
                'class_name': conflict.get('class_name', ''),
            },
            evidence=conflict,
            suggested_fix={
                'kind': 'class_remap',
                'description': '按规范类别表重映射后再合并，禁止直接拼接',
                'map': {batch: {str(k): v for k, v in mapping.items()}
                        for batch, mapping in class_map.batches.items()},
            },
            requires_human=True,
        ))
    for item in class_map.unexpected:
        findings.append(Finding(
            check='class_outside_spec',
            severity='P1',
            confidence='deterministic',
            title='规范外类别',
            message=f"数据中出现规范未定义的类别「{item['name']}」（批次 {item['batch']}）",
            subject={'batch': item['batch'], 'class_name': item['name']},
            evidence=item,
            suggested_fix={'kind': 'human_confirm', 'description': '确认是新增类别还是误标'},
            requires_human=True,
        ))
    for name in class_map.missing_in_data:
        findings.append(Finding(
            check='spec_class_missing',
            severity='P2',
            confidence='deterministic',
            title='规范类别无样本',
            message=f'规范要求类别「{name}」，但本批次没有任何标注实例',
            subject={'class_name': name},
            evidence={'class_name': name},
            suggested_fix={'kind': 'recollect', 'description': '纳入补采清单'},
        ))
    return findings