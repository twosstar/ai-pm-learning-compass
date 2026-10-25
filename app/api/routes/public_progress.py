"""Local learning checkpoints. Reads/resume never generate questions or call models."""
import ipaddress
import json
from datetime import UTC
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import (AnswerEvaluation, KnowledgePoint, LearningSession, MasteryScore,
                           PublicAnswerDraft, PublicReadingBookmark, QuestionAttempt, utcnow)
from app.db.session import get_db
from app.services.public_curriculum import lesson_definition, public_curriculum


def local_progress_access(request: Request):
    try:
        local = request.client and ipaddress.ip_address(request.client.host).is_loopback
    except ValueError:
        local = False
    expected = f'{request.url.scheme}://{request.headers.get("host", "")}'.lower()
    if (not local or request.url.hostname not in {'localhost', '127.0.0.1', '::1'}
            or request.headers.get('origin', expected).lower() != expected
            or request.headers.get('sec-fetch-site') == 'cross-site'):
        raise HTTPException(403, '学习位置仅供本机同站点访问。')
    if request.method == 'POST' and request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(415, '请使用页面保存学习位置。')


router = APIRouter(prefix='/progress', tags=['local-learning-progress'], dependencies=[Depends(local_progress_access)])
DbSession = Annotated[Session, Depends(get_db)]


def stamp(value):
    return value.replace(tzinfo=UTC).timestamp() if value else 0


def array(value):
    try:
        result = json.loads(value or '[]')
        return result if isinstance(result, list) else []
    except (TypeError, ValueError):
        return []


def definition(lesson_id):
    lesson = lesson_definition(lesson_id)
    if not lesson:
        raise HTTPException(404, '未找到公开课程。')
    return lesson


def valid_sessions(db, lesson):
    ids = [point['id'] for point in lesson['knowledge_points']]
    return db.query(LearningSession).filter(LearningSession.lesson_id == lesson['id'],
        LearningSession.current_knowledge_point_id.in_(ids), LearningSession.scope_type != 'MISTAKE_REVIEW'
        ).order_by(LearningSession.updated_at.desc(), LearningSession.id.desc()).all()


def touch(db, lesson_id, point_id, view='practice', position=0):
    record = db.get(PublicReadingBookmark, lesson_id)
    if not record:
        record = PublicReadingBookmark(lesson_id=lesson_id, point_id=point_id)
        db.add(record)
    record.point_id, record.position, record.view, record.updated_at = point_id, position, view, utcnow()
    return record


@router.get('')
def progress(db: DbSession):
    lessons = []
    latest = None
    scores = {row.knowledge_point_id: row.mastery_score for row in db.query(MasteryScore).all()}
    for lesson in public_curriculum()['lessons']:
        ids = {point['id'] for point in lesson['knowledge_points']}
        sessions = valid_sessions(db, lesson)
        recent = sessions[0] if sessions else None
        active = recent if recent and not recent.completed else None
        bookmark = db.get(PublicReadingBookmark, lesson['id'])
        read_ids = set(array(bookmark.read_point_ids_json)) & ids if bookmark else set()
        practiced = db.query(QuestionAttempt.knowledge_point_id).join(AnswerEvaluation,
            AnswerEvaluation.question_attempt_id == QuestionAttempt.id).join(LearningSession,
            LearningSession.id == QuestionAttempt.learning_session_id).filter(
            LearningSession.lesson_id == lesson['id'], QuestionAttempt.knowledge_point_id.in_(ids)).distinct().count()
        completed = any(session.completed for session in sessions)
        status = 'completed' if completed else 'practice' if sessions else 'reading' if bookmark else 'not_started'
        time_value = max(stamp(bookmark.updated_at) if bookmark else 0, stamp(recent.updated_at) if recent else 0)
        reading = bool(bookmark and (not recent or stamp(bookmark.updated_at) >= stamp(recent.updated_at)) and bookmark.view == 'reading')
        point_id = bookmark.point_id if bookmark and (reading or not recent) else recent.current_knowledge_point_id if recent else None
        entry = {'lesson_id': lesson['id'], 'title': lesson['title'], 'status': status,
                 'read_count': len(read_ids), 'read_point_ids': sorted(read_ids), 'point_count': len(ids),
                 'practiced_count': practiced, 'mastery': round(sum(scores.get(key, 0) for key in ids) / len(ids)),
                 'session_id': active.id if active else None, 'updated_at': time_value,
                 'point_id': point_id if time_value else None, 'view': 'reading' if reading or not recent else 'practice'}
        lessons.append(entry)
        if time_value and (latest is None or time_value > latest['updated_at']):
            latest = dict(entry, point_name=next((p['name'] for p in lesson['knowledge_points'] if p['id'] == point_id), '本节内容'))
    return {'lessons': lessons, 'last_resume': latest,
            'summary': {'total_lessons': len(lessons), 'completed_lessons': sum(p['status'] == 'completed' for p in lessons),
                        'started_lessons': sum(p['status'] != 'not_started' for p in lessons),
                        'read_points': sum(p['read_count'] for p in lessons),
                        'practiced_points': sum(p['practiced_count'] for p in lessons),
                        'mastery_percent': round(sum(p['mastery'] for p in lessons) / len(lessons))}}


class Checkpoint(BaseModel):
    lesson_id: int
    point_id: int
    position: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    view: Literal['reading', 'practice'] = 'reading'
    read: bool | None = None


@router.post('/checkpoint')
def checkpoint(payload: Checkpoint, db: DbSession):
    lesson = definition(payload.lesson_id)
    ids = {point['id'] for point in lesson['knowledge_points']}
    if payload.point_id not in ids:
        raise HTTPException(422, '知识点不属于这节公开课程。')
    record = touch(db, payload.lesson_id, payload.point_id, payload.view, payload.position)
    read_ids = set(array(record.read_point_ids_json)) & ids
    if payload.read is True:
        read_ids.add(payload.point_id)
    elif payload.read is False:
        read_ids.discard(payload.point_id)
    record.read_point_ids_json = json.dumps(sorted(read_ids))
    db.commit()
    return {'saved': True, 'read_point_ids': sorted(read_ids)}


class Draft(BaseModel):
    session_id: int
    attempt_id: int
    text: str = Field(max_length=10000)


@router.post('/draft')
def draft(payload: Draft, db: DbSession):
    session = db.get(LearningSession, payload.session_id)
    attempt = db.get(QuestionAttempt, payload.attempt_id)
    if not session or not attempt or attempt.learning_session_id != session.id:
        raise HTTPException(404, '未找到对应练习。')
    lesson = definition(session.lesson_id)
    if attempt.knowledge_point_id not in {p['id'] for p in lesson['knowledge_points']}:
        raise HTTPException(422, '该练习不属于公开课程。')
    if db.query(AnswerEvaluation).filter_by(question_attempt_id=attempt.id).first():
        raise HTTPException(409, '已评分回答不再保存草稿，也不会覆盖历史回答。')
    record = db.get(PublicAnswerDraft, attempt.id)
    if record is None:
        record = PublicAnswerDraft(attempt_id=attempt.id)
        db.add(record)
    record.text, record.updated_at = payload.text, utcnow()
    touch(db, session.lesson_id, attempt.knowledge_point_id)
    db.commit()
    return {'saved': True}


@router.get('/lessons/{lesson_id}/resume')
def resume(lesson_id: int, db: DbSession):
    lesson = definition(lesson_id)
    bookmark = db.get(PublicReadingBookmark, lesson_id)
    sessions = valid_sessions(db, lesson)
    session = sessions[0] if sessions else None
    bookmark_is_latest = bool(bookmark and (not session or stamp(bookmark.updated_at) >= stamp(session.updated_at)))
    result = {'lesson_id': lesson_id, 'view': bookmark.view if bookmark_is_latest else 'practice' if session else 'reading',
              'point_id': bookmark.point_id if bookmark_is_latest else session.current_knowledge_point_id if session else lesson['knowledge_points'][0]['id'],
              'position': bookmark.position if bookmark_is_latest else 0, 'practice': None}
    if not session:
        return result
    attempt = db.query(QuestionAttempt).filter_by(learning_session_id=session.id,
        knowledge_point_id=session.current_knowledge_point_id).order_by(QuestionAttempt.id.desc()).first()
    if not attempt:
        return result
    point = db.get(KnowledgePoint, attempt.knowledge_point_id)
    evaluation = db.query(AnswerEvaluation).filter_by(question_attempt_id=attempt.id).first()
    saved_draft = db.get(PublicAnswerDraft, attempt.id)
    answer = saved_draft.text if saved_draft and not evaluation and stamp(saved_draft.updated_at) > stamp(attempt.answered_at) else attempt.user_answer
    question = {name: getattr(attempt, name) for name in (
        'question', 'question_type', 'difficulty', 'target_role', 'interview_depth'
    )}
    feedback = None
    if evaluation:
        feedback = {'total_score': evaluation.total_score, 'pass_label': '已保存的历史评价', 'evaluation_source': 'saved',
                    'score_explanation': '恢复已保存评价，未重新调用模型或重复计分。',
                    'correct_points': array(evaluation.correct_points_json), 'missing_points': array(evaluation.missing_points_json),
                    'key_gaps': array(evaluation.key_gaps_json), 'improved_answer': evaluation.improved_answer,
                    'expert_answer': evaluation.expert_answer, 'answer_framework': array(evaluation.answer_framework_json),
                    'dimensions': {name: getattr(evaluation, name) for name in ('concept_accuracy', 'technical_understanding', 'product_thinking', 'application_scenario', 'communication_structure')},
                    'evaluated_question': attempt.question, 'user_answer': attempt.user_answer}
    result['practice'] = {'lesson_id': lesson_id, 'lesson_title': lesson['title'], 'course_summary': session.course_summary,
                          'session_id': session.id, 'question_attempt_id': attempt.id, 'question': question,
                          'current_knowledge_point': {'id': point.id, 'name': point.name, 'core_explanation': point.core_explanation},
                          'draft_answer': answer, 'evaluated': bool(evaluation), 'can_continue': session.mode == 'advance' and not session.completed,
                          'completed': session.completed, 'saved_feedback': feedback}
    return result
