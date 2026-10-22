import copy

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.models import Course, KnowledgePoint, LearningSession, Lesson, MasteryScore, QuestionAttempt
from app.db.session import Base
from app.services.public_curriculum import public_curriculum
from app.services.public_seed import sync_public_curriculum
from scripts.check_curriculum import curriculum_failures


def test_full_curriculum_has_teaching_and_traceable_sources():
    data = public_curriculum()
    assert curriculum_failures(data) == []
    assert len(data['lessons']) == 60
    assert len(data['modules']) == 10
    assert sum(len(row['knowledge_points']) for row in data['lessons']) == 120
    assert [point['id'] for lesson in data['lessons'][:3] for point in lesson['knowledge_points']] == list(range(1001, 1007))
    broken = copy.deepcopy(data)
    broken['lessons'][0]['knowledge_points'][0]['core_explanation'] = ''
    broken['lessons'][1]['source_ids'] = []
    assert any('core_explanation' in issue for issue in curriculum_failures(broken))
    assert any('missing lesson source' in issue for issue in curriculum_failures(broken))


def test_upgrade_preserves_old_scores_sessions_attempts_and_unrelated_content():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([
            Course(id=1, name='old public course', start_url='public://ai-pm-foundations'),
            Course(id=901, name='private fixture', start_url='https://private.example'),
        ])
        db.flush()
        db.add_all([
            Lesson(id=101, course_id=1, title='legacy public', url='public://ai-pm-foundations/101', content='old public text', content_hash='old'),
            Lesson(id=901, course_id=901, title='private fixture', url='https://private.example/901', content='untouched private text', content_hash='private'),
        ])
        db.flush()
        for point_id in (1001, 1007):
            db.add(KnowledgePoint(id=point_id, lesson_id=101, name=f'legacy {point_id}', description='old', category='AI_PRODUCT', source_page='legacy', source_url='public://ai-pm-foundations/101', level_1='old'))
        db.flush()
        db.add(MasteryScore(knowledge_point_id=1001, mastery_score=67, interview_readiness=73))
        session = LearningSession(lesson_id=101, current_knowledge_point_id=1007, answered_count=4)
        db.add(session)
        db.flush()
        attempt = QuestionAttempt(learning_session_id=session.id, knowledge_point_id=1007, question_type='original', question='old question', user_answer='my saved answer')
        db.add(attempt)
        db.commit()
        session_id, attempt_id = session.id, attempt.id
        sync_public_curriculum(db)
        sync_public_curriculum(db)
        assert db.query(Lesson).count() == 61
        assert db.query(KnowledgePoint).count() == 121
        score = db.query(MasteryScore).filter_by(knowledge_point_id=1001).one()
        assert (score.mastery_score, score.interview_readiness) == (67, 73)
        assert db.get(LearningSession, session_id).current_knowledge_point_id == 1007
        assert db.get(LearningSession, session_id).answered_count == 4
        assert db.get(QuestionAttempt, attempt_id).user_answer == 'my saved answer'
        assert db.get(KnowledgePoint, 1007).name == 'legacy 1007'
        assert db.get(KnowledgePoint, 1001).core_explanation == public_curriculum()['lessons'][0]['knowledge_points'][0]['core_explanation']
        assert db.get(Lesson, 901).content == 'untouched private text'
    engine.dispose()


def test_private_course_id_conflict_does_not_overwrite():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Course(id=1, name='private original', start_url='https://private.example'))
        db.commit()
        with pytest.raises(RuntimeError, match='ID'):
            sync_public_curriculum(db)
        db.rollback()
        assert db.get(Course, 1).name == 'private original'
    engine.dispose()
