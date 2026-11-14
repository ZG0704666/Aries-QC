"""Finding 与几何工具：所有结论都必须携带可复核证据。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict


SEVERITY_ORDER = {'P0': 0, 'P1': 1, 'P2': 2}
CONFIDENCE_ORDER = {'deterministic': 0, 'candidate': 1}


def box_to_xyxy(bbox: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    cx, cy, w, h = bbox
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = box_to_xyxy(a)
    bx1, by1, bx2, by2 = box_to_xyxy(b)
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = max(0.0, a[2]) * max(0.0, a[3]) + max(0.0, b[2]) * max(0.0, b[3]) - inter
    return inter / union if union > 0 else 0.0


def area(bbox: tuple[float, float, float, float]) -> float:
    return max(0.0, bbox[2]) * max(0.0, bbox[3])


def aspect(bbox: tuple[float, float, float, float]) -> float:
    w, h = bbox[2], bbox[3]
    if w <= 0 or h <= 0:
        return 0.0
    return max(w / h, h / w)


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def mad(values: list[float]) -> float:
    if not values:
        return 0.0
    center = median(values)
    return median([abs(v - center) for v in values])


def robust_z(value: float, values: list[float]) -> float:
    center = median(values)
    spread = mad(values)
    if spread <= 1e-12:
        return 0.0
    return 0.6745 * (value - center) / spread


def hamming(a: int, b: int) -> int:
    return int(a ^ b).bit_count()


@dataclass
class Finding:
    check: str
    severity: str                 # P0 | P1 | P2
    confidence: str               # deterministic | candidate
    title: str
    message: str
    subject: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)
    suggested_fix: dict | None = None
    requires_human: bool = False
    status: str = 'open'          # open | accepted | rejected
    note: str = ''
    id: str = ''

    def to_dict(self) -> dict:
        data = asdict(self)
        data['severity_rank'] = SEVERITY_ORDER.get(self.severity, 9)
        data['confidence_rank'] = CONFIDENCE_ORDER.get(self.confidence, 9)
        return data


class FindingBook:
    def __init__(self) -> None:
        self.items: list[Finding] = []
        self._seq = 0
        self._dedupe: set[tuple] = set()

    def add(self, finding: Finding, dedupe_key: tuple | None = None) -> Finding | None:
        if dedupe_key is not None:
            if dedupe_key in self._dedupe:
                return None
            self._dedupe.add(dedupe_key)
        self._seq += 1
        finding.id = f'F-{self._seq:04d}'
        self.items.append(finding)
        return finding

    def extend(self, findings: list[Finding], prefix: str = '') -> None:
        for finding in findings:
            self.add(finding, dedupe_key=(prefix, finding.check, finding.subject.get('sample_id'),
                                          tuple(finding.subject.get('bbox') or []), finding.subject.get('line')))

    def counts(self) -> dict:
        by_severity: dict[str, int] = {}
        by_check: dict[str, int] = {}
        by_confidence: dict[str, int] = {}
        for item in self.items:
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
            by_check[item.check] = by_check.get(item.check, 0) + 1
            by_confidence[item.confidence] = by_confidence.get(item.confidence, 0) + 1
        return {
            'total': len(self.items),
            'by_severity': by_severity,
            'by_check': by_check,
            'by_confidence': by_confidence,
            'open': sum(1 for x in self.items if x.status == 'open'),
            'accepted': sum(1 for x in self.items if x.status == 'accepted'),
            'rejected': sum(1 for x in self.items if x.status == 'rejected'),
        }

    def sorted(self) -> list[Finding]:
        return sorted(self.items, key=lambda f: (
            SEVERITY_ORDER.get(f.severity, 9),
            CONFIDENCE_ORDER.get(f.confidence, 9),
            f.check,
            f.subject.get('sample_id') or 0,
        ))