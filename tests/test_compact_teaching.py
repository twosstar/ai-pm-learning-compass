import copy
import json

from app.services.public_curriculum import CURRICULUM_FILE, public_curriculum, teaching_pilot
from scripts.check_curriculum import curriculum_failures


def test_every_point_has_short_specific_teaching_and_optional_depth():
    curriculum = public_curriculum()
    flows, boundaries = set(), set()
    for lesson in curriculum['lessons']:
        for point in lesson['knowledge_points']:
            quick = point.get('quick_study')
            assert quick, f"missing compact teaching: {point['id']}"
            assert len(quick['essentials']) == 3
            assert [text.split('：')[0] for text in quick['essentials']] == ['是什么', '怎么用', '边界']
            assert 4 <= len(quick['flow']) <= 5
            assert all(node['label'] and node['owner'] for node in quick['flow'])
            assert quick['branches'] and quick['example'] and quick['interview']
            required = ''.join(quick['essentials']) + quick['example'] + quick['interview']
            assert len(required) <= 350, point['id']
            assert len(point['teaching_sections']) >= 5
            assert any('边界' in section['title'] for section in point['teaching_sections'])
            assert any('误区' in section['title'] for section in point['teaching_sections'])
            flows.add(tuple(node['label'] for node in quick['flow']))
            boundaries.add(quick['essentials'][2])
    assert len(flows) == len(boundaries) == 120


def test_teaching_overlay_preserves_existing_identity_provenance_and_content():
    base = json.loads(CURRICULUM_FILE.read_text(encoding='utf-8'))
    effective = public_curriculum()
    assert effective['sources'] == base['sources']
    assert effective['modules'] == base['modules']
    for old, new in zip(base['lessons'], effective['lessons'], strict=True):
        assert (old['id'], old['source_ids']) == (new['id'], new['source_ids'])
        assert [row['id'] for row in old['knowledge_points']] == [row['id'] for row in new['knowledge_points']]
        if old['id'] == 102:
            assert new['knowledge_points'][0]['quick_study'] == teaching_pilot()['knowledge_points'][0]['quick_study']
            continue
        for before, after in zip(old['knowledge_points'], new['knowledge_points'], strict=True):
            for field in before:
                assert before[field] == after[field], (old['id'], before['id'], field)


def test_checker_rejects_missing_long_or_empty_compact_content():
    mutations = [
        lambda point: point.update(quick_study={'essentials': ['too little']}),
        lambda point: point['quick_study'].update(example='过长' * 300),
        lambda point: point['quick_study'].update(flow=[]),
        lambda point: point['quick_study'].update(branches=[]),
        lambda point: point.update(teaching_sections=[]),
    ]
    for mutation in mutations:
        broken = copy.deepcopy(public_curriculum())
        mutation(broken['lessons'][0]['knowledge_points'][0])
        assert any('compact teaching' in issue for issue in curriculum_failures(broken))


def test_missing_note_files_fail_loudly_instead_of_silently_showing_old_layout(monkeypatch, tmp_path):
    import pytest
    from app.services import compact_teaching
    monkeypatch.setattr(compact_teaching, 'TEACHING_DIR', tmp_path)
    with pytest.raises(ValueError, match='coverage mismatch'):
        compact_teaching.apply_compact_teaching(copy.deepcopy(public_curriculum()))


def test_catalog_exposes_compact_teaching_for_all_lessons():
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as client:
        catalog = client.get('/api/catalog').json()
    points = [point for lesson in catalog['items'][0]['lessons'] for point in lesson['knowledge_points']]
    assert len(points) == 120
    assert all(point['quick_study'] and point['teaching_sections'] for point in points)
