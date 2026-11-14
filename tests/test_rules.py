from __future__ import annotations

from pathlib import Path

from employee.dataset import parse_label, scan_batch
from employee.merge_guard import build_class_map, conflict_findings
from employee.rules import run_all


def test_scan_and_rules(rules_batch: Path) -> None:
    batch = scan_batch(rules_batch)
    stats = batch.stats()
    assert stats['images'] == 10
    assert stats['empty_labels'] == 1
    assert stats['missing_labels'] == 1
    assert stats['malformed_labels'] == 1
    class_map = build_class_map(batch)
    book = run_all(batch, class_map)
    checks = {finding.check for finding in book.items}
    for expected in (
        'coord_out_of_range', 'class_id_out_of_range', 'label_malformed',
        'box_zero_area', 'duplicate_box', 'duplicate_image', 'label_missing',
        'sequence_missing_label',
    ):
        assert expected in checks, expected
    assert book.counts()['by_severity'].get('P0', 0) >= 3


def test_parse_label_polygon_and_box() -> None:
    objects, errors = parse_label('0 0.1 0.1 0.9 0.1 0.9 0.9\n1 0.5 0.5 0.2 0.2\n')
    assert not errors
    assert [obj.kind for obj in objects] == ['polygon', 'box']
    assert objects[0].bbox == (0.5, 0.5, 0.8, 0.8)


def test_cross_batch_class_conflict(merge_batch: Path) -> None:
    batch = scan_batch(merge_batch)
    class_map = build_class_map(batch, ['agv', 'rail door'])
    kinds = [item['kind'] for item in class_map.conflicts]
    assert 'same_id_different_name' in kinds
    assert class_map.batches['alpha'][0] == 0
    assert class_map.batches['beta'][0] == 2  # sliding door 不在规范中，追加到 2
    findings = conflict_findings(class_map)
    assert any(f.severity == 'P0' for f in findings)
    assert any(f.check == 'class_outside_spec' for f in findings)


def test_sequence_candidate_is_not_deterministic(rules_batch: Path) -> None:
    batch = scan_batch(rules_batch)
    book = run_all(batch, build_class_map(batch))
    sequence = [f for f in book.items if f.check == 'sequence_missing_label']
    assert sequence
    assert all(f.confidence == 'candidate' and f.requires_human for f in sequence)
    assert all(f.subject.get('sample_id') is not None for f in sequence)