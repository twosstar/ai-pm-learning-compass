import hashlib
import json
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    AnswerEvaluation,
    Course,
    CrawlProgress,
    ImportanceRating,
    InterviewSession,
    InterviewSprint,
    InterviewSprintTask,
    KnowledgePoint,
    LearningPreference,
    LearningSession,
    Lesson,
    LessonStudySession,
    MasteryScore,
    MistakeItem,
    PDFImport,
    QuestionAttempt,
    ReviewHistory,
    StudyRecord,
    Weakness,
)
from app.schemas.learning import AnswerEvaluationOutput, ExtractedKnowledgePoint, GeneratedQuestion


class Repository:
    def __init__(self, db: Session):
        self.db = db

    def get_mistake(self, fingerprint: str) -> MistakeItem | None:
        return self.db.scalar(select(MistakeItem).where(MistakeItem.question_fingerprint == fingerprint))

    def upsert_mistake(self, *, attempt, evaluation, source_type: str = "SMART_LEARNING") -> MistakeItem | None:
        fingerprint = attempt.question_fingerprint_json or hashlib.sha256(attempt.question.encode()).hexdigest()
        item = self.get_mistake(fingerprint)
        if item is None and evaluation.total_score >= 60 and not evaluation.critical_misconception:
            return None
        now = datetime.now(UTC)
        payload = {
            "missing_points": json.loads(evaluation.missing_points_json or "[]"),
            "incorrect_points": json.loads(evaluation.incorrect_points_json or "[]"),
            "key_gaps": json.loads(evaluation.key_gaps_json or "[]"),
            "answer_framework": json.loads(evaluation.answer_framework_json or "[]"),
            "framework_version": evaluation.framework_version,
            "critical_misconception": evaluation.critical_misconception,
            "critical_misconception_detail": evaluation.critical_misconception_detail,
            "improved_answer": evaluation.improved_answer,
            "expert_answer": evaluation.expert_answer,
        }
        if not item:
            item = MistakeItem(question_id=attempt.id, question_fingerprint=fingerprint, question_text=attempt.question, source_type=source_type, knowledge_point_id=attempt.knowledge_point_id, topic=attempt.interview_category, target_role=attempt.target_role, question_type=attempt.question_type, first_wrong_at=now)
            self.db.add(item)
        item.question_id = attempt.id; item.latest_score = evaluation.total_score; item.best_score = max(item.best_score or 0, evaluation.total_score); item.attempt_count = (item.attempt_count or 0) + 1; item.last_attempt_at = now; item.latest_user_answer = attempt.user_answer or ""; item.evaluation_json = json.dumps(payload, ensure_ascii=False); item.status = "MASTERED" if evaluation.total_score >= 60 and not evaluation.critical_misconception else "UNRESOLVED"
        self.db.commit(); self.db.refresh(item)
        return item

    def list_mistakes(self, status: str | None = "UNRESOLVED", source_type: str | None = None) -> list[MistakeItem]:
        statement = select(MistakeItem)
        if status in {"UNRESOLVED", "MASTERED"}: statement = statement.where(MistakeItem.status == status)
        if source_type in {"SMART_LEARNING", "MOCK_INTERVIEW"}: statement = statement.where(MistakeItem.source_type == source_type)
        return list(self.db.scalars(statement.order_by(MistakeItem.dynamic_importance.desc(), MistakeItem.attempt_count.desc(), MistakeItem.last_attempt_at.desc())).all())

    def backfill_mistakes(self) -> None:
        """Import historical failed learning answers into the unified book once."""
        rows = self.db.execute(select(QuestionAttempt, AnswerEvaluation).join(AnswerEvaluation, AnswerEvaluation.question_attempt_id == QuestionAttempt.id)).all()
        for attempt, evaluation in rows:
            if evaluation.total_score < 60 or self.get_mistake(attempt.question_fingerprint_json or ""):
                fingerprint = attempt.question_fingerprint_json or hashlib.sha256(attempt.question.encode()).hexdigest()
                if self.get_mistake(fingerprint) is None:
                    item = MistakeItem(question_id=attempt.id, question_fingerprint=fingerprint, question_text=attempt.question, source_type="SMART_LEARNING", knowledge_point_id=attempt.knowledge_point_id, topic=attempt.interview_category, target_role=attempt.target_role, question_type=attempt.question_type, first_wrong_at=attempt.created_at)
                    self.db.add(item)
                    self.db.flush()
                    item.latest_score = evaluation.total_score; item.best_score = evaluation.total_score; item.attempt_count = 1; item.last_attempt_at = attempt.answered_at or attempt.created_at; item.latest_user_answer = attempt.user_answer or ""; item.evaluation_json = json.dumps({"missing_points": json.loads(evaluation.missing_points_json or "[]"), "incorrect_points": json.loads(evaluation.incorrect_points_json or "[]"), "critical_misconception": evaluation.critical_misconception, "critical_misconception_detail": evaluation.critical_misconception_detail, "improved_answer": evaluation.improved_answer, "expert_answer": evaluation.expert_answer}, ensure_ascii=False)
                    item.status = "MASTERED" if evaluation.total_score >= 60 and not evaluation.critical_misconception else "UNRESOLVED"
        self.db.commit()

    def get_or_create_course(self, name: str, start_url: str) -> Course:
        course = self.db.scalar(select(Course).where(Course.start_url == start_url))
        if course:
            if name and course.name != name:
                course.name = name
                self.db.commit()
            return course
        course = Course(name=name or "未命名课程", start_url=start_url)
        self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def get_target_role(self) -> str:
        preference = self.db.get(LearningPreference, 1)
        return preference.target_role if preference else "general_ai_pm"

    def get_learning_goal(self) -> str:
        preference = self.db.get(LearningPreference, 1)
        return preference.learning_goal if preference else "GENERAL_AI_PM"

    def set_target_role(self, target_role: str) -> LearningPreference:
        preference = self.db.get(LearningPreference, 1)
        if not preference:
            preference = LearningPreference(id=1, target_role=target_role)
            self.db.add(preference)
        else:
            preference.target_role = target_role
        self.db.commit()
        self.db.refresh(preference)
        return preference

    def set_learning_context(self, learning_goal: str, target_role: str) -> LearningPreference:
        preference = self.db.get(LearningPreference, 1)
        if not preference:
            preference = LearningPreference(
                id=1, target_role=target_role, learning_goal=learning_goal
            )
            self.db.add(preference)
        else:
            preference.target_role = target_role
            preference.learning_goal = learning_goal
        self.db.commit()
        self.db.refresh(preference)
        return preference

    def upsert_importance_rating(
        self,
        *,
        entity_type: str,
        entity_id: int,
        learning_goal: str,
        target_role: str,
        dynamic_score: int,
        dynamic_raw: float,
        priority_label: str,
        reason: str,
        learning_priority: float,
        mastery_snapshot: int,
    ) -> ImportanceRating:
        rating = self.db.scalar(
            select(ImportanceRating).where(
                ImportanceRating.entity_type == entity_type,
                ImportanceRating.entity_id == entity_id,
                ImportanceRating.learning_goal == learning_goal,
                ImportanceRating.target_role == target_role,
            )
        )
        if not rating:
            rating = ImportanceRating(
                entity_type=entity_type,
                entity_id=entity_id,
                learning_goal=learning_goal,
                target_role=target_role,
            )
            self.db.add(rating)
        rating.dynamic_importance_score = dynamic_score
        rating.dynamic_importance_raw = dynamic_raw
        rating.priority_label = priority_label
        rating.importance_reason = reason
        rating.learning_priority_score = learning_priority
        rating.mastery_snapshot = mastery_snapshot
        self.db.flush()
        return rating

    def importance_ratings(
        self, entity_type: str, learning_goal: str, target_role: str
    ) -> list[ImportanceRating]:
        return list(
            self.db.scalars(
                select(ImportanceRating).where(
                    ImportanceRating.entity_type == entity_type,
                    ImportanceRating.learning_goal == learning_goal,
                    ImportanceRating.target_role == target_role,
                )
            ).all()
        )

    def create_interview_sprint(
        self,
        *,
        target_role: str,
        preparation_days: int,
        daily_minutes: int,
        baseline_readiness: int,
        projected_readiness: int,
        highest_risks: list[str],
        skipped_ready_count: int,
        tasks: list[dict],
        learning_goal: str = "INTERVIEW_SPRINT",
        target_interview_readiness: int = 60,
        estimated_required_minutes: int = 0,
        start_date=None,
        current_day: int = 1,
    ) -> InterviewSprint:
        for existing in self.db.scalars(
            select(InterviewSprint).where(InterviewSprint.status == "active")
        ).all():
            existing.status = "replaced"
        sprint = InterviewSprint(
            target_role=target_role,
            learning_goal=learning_goal,
            start_date=start_date,
            total_days=preparation_days,
            current_day=current_day,
            preparation_days=preparation_days,
            daily_minutes=daily_minutes,
            baseline_readiness=baseline_readiness,
            projected_readiness=projected_readiness,
            target_interview_readiness=target_interview_readiness,
            target_score=target_interview_readiness,
            # Legacy column retained for migration compatibility; it is never
            # used as an actual score (the readiness service is authoritative).
            current_score=0,
            estimated_required_minutes=estimated_required_minutes,
            highest_risks_json=json.dumps(highest_risks, ensure_ascii=False),
            skipped_ready_count=skipped_ready_count,
        )
        self.db.add(sprint)
        self.db.flush()
        self.db.add_all(
            [InterviewSprintTask(sprint_id=sprint.id, **task) for task in tasks]
        )
        self.db.commit()
        self.db.refresh(sprint)
        return sprint

    def get_active_interview_sprint(
        self,
        target_role: str | None = None,
        learning_goal: str | None = None,
    ) -> InterviewSprint | None:
        statement = select(InterviewSprint).where(
            func.lower(InterviewSprint.status) == "active"
        )
        if target_role is not None:
            statement = statement.where(InterviewSprint.target_role == target_role)
        if learning_goal is not None:
            statement = statement.where(InterviewSprint.learning_goal == learning_goal)
        return self.db.scalar(statement.order_by(InterviewSprint.created_at.desc()))

    def list_interview_sprint_tasks(self, sprint_id: int) -> list[InterviewSprintTask]:
        return list(
            self.db.scalars(
                select(InterviewSprintTask)
                .where(InterviewSprintTask.sprint_id == sprint_id)
                .order_by(
                    InterviewSprintTask.day_number,
                    InterviewSprintTask.priority_rank,
                    InterviewSprintTask.id,
                )
            ).all()
        )

    def upsert_lesson(self, course_id: int, title: str, url: str, content: str) -> Lesson:
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        lesson = self.db.scalar(
            select(Lesson).where(Lesson.course_id == course_id, Lesson.url == url)
        )
        if lesson:
            lesson.title, lesson.content, lesson.content_hash = title, content, digest
        else:
            lesson = Lesson(
                course_id=course_id, title=title, url=url, content=content, content_hash=digest
            )
            self.db.add(lesson)
        self.db.commit()
        self.db.refresh(lesson)
        return lesson

    def list_courses(self) -> list[dict]:
        rows = self.db.execute(
            select(Course, func.count(Lesson.id))
            .outerjoin(Lesson)
            .group_by(Course.id)
            .order_by(Course.updated_at.desc())
        ).all()
        result = []
        for course, count in rows:
            pdf = self.db.scalar(select(PDFImport).where(PDFImport.course_id == course.id))
            if pdf and pdf.status != "READY":
                continue
            result.append({
                "id": course.id,
                "name": pdf.original_filename.rsplit(".", 1)[0] if pdf else course.name,
                "start_url": course.start_url,
                "lesson_count": count,
                "source_type": "PDF" if pdf else "WEB",
                "page_count": pdf.page_count if pdf else count,
                "original_filename": pdf.original_filename if pdf else None,
                "status": pdf.status if pdf else "READY",
                "text_page_count": pdf.text_page_count if pdf else count,
                "ocr_page_count": pdf.ocr_page_count if pdf else 0,
                "section_count": pdf.section_count if pdf else count,
            })
        return result

    def get_course(self, course_id: int) -> Course | None:
        return self.db.get(Course, course_id)

    def delete_course(self, course_id: int) -> dict:
        course = self.get_course(course_id)
        if not course:
            raise LookupError("课程不存在或已经删除。")
        lesson_ids = [item.id for item in course.lessons]
        lesson_id_set = set(lesson_ids)
        for record in self.db.scalars(select(StudyRecord)).all():
            source_ids = {
                int(value)
                for value in record.source_lesson_ids.split(",")
                if value.strip().isdigit()
            }
            if source_ids & lesson_id_set:
                self.db.delete(record)
        result = {
            "course_id": course.id,
            "course_name": course.name,
            "lessons_deleted": len(lesson_ids),
        }
        self.db.delete(course)
        self.db.commit()
        return result

    def list_lessons(self, course_id: int) -> list[dict]:
        lessons = self.db.scalars(
            select(Lesson).where(Lesson.course_id == course_id).order_by(Lesson.id)
        ).all()
        return [
            {"id": item.id, "title": item.title, "url": item.url, "captured_at": item.captured_at}
            for item in lessons
        ]

    def list_lessons_all(self) -> list[Lesson]:
        return list(self.db.scalars(select(Lesson).order_by(Lesson.id)).all())

    def list_lesson_records(self, course_id: int | None = None) -> list[Lesson]:
        statement = select(Lesson)
        if course_id is not None:
            statement = statement.where(Lesson.course_id == course_id)
        return list(self.db.scalars(statement.order_by(Lesson.id)).all())

    def get_crawl_progress(self, course_id: int) -> CrawlProgress | None:
        return self.db.get(CrawlProgress, course_id)

    def save_crawl_progress(
        self, course_id: int, pending_urls: list[str], visited_urls: set[str], completed: bool
    ) -> CrawlProgress:
        progress = self.get_crawl_progress(course_id)
        if not progress:
            progress = CrawlProgress(course_id=course_id)
            self.db.add(progress)
        progress.pending_urls_json = json.dumps(pending_urls, ensure_ascii=False)
        progress.visited_urls_json = json.dumps(sorted(visited_urls), ensure_ascii=False)
        progress.completed = completed
        self.db.commit()
        return progress

    def get_lesson(self, lesson_id: int) -> Lesson | None:
        return self.db.get(Lesson, lesson_id)

    def search_lessons_lexical(
        self,
        query: str,
        course_id: int | None = None,
        lesson_id: int | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Small-corpus Chinese-friendly lexical retrieval with strong title boosting."""
        statement = select(Lesson)
        if lesson_id is not None:
            statement = statement.where(Lesson.id == lesson_id)
        elif course_id is not None:
            statement = statement.where(Lesson.course_id == course_id)
        lessons = self.db.scalars(statement).all()
        terms = self._query_terms(query)
        scored: list[tuple[float, Lesson]] = []
        for lesson in lessons:
            title, content = lesson.title.lower(), lesson.content.lower()
            score = 1000.0 if lesson_id == lesson.id else 0.0
            for term in terms:
                weight = float(len(term) ** 2)
                score += title.count(term) * weight * 8
                score += min(content.count(term), 8) * weight
            if score > 0:
                scored.append((score, lesson))
        scored.sort(key=lambda item: (item[0], len(item[1].content)), reverse=True)
        return [
            {
                "text": self._relevant_excerpt(lesson.content, terms),
                "lesson_id": lesson.id,
                "course_id": lesson.course_id,
                "title": lesson.title,
                "url": lesson.url,
                "retrieval_score": score,
            }
            for score, lesson in scored[:limit]
        ]

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        query = query.lower()
        terms = re.findall(r"[a-z][a-z0-9_-]{1,}", query)
        stop_terms = {"什么", "如何", "具体", "说明", "请问", "哪些", "以及", "一个", "问题"}
        for run in re.findall(r"[\u4e00-\u9fff]{2,}", query):
            if len(run) <= 6:
                terms.append(run)
            for size in (4, 3, 2):
                terms.extend(run[index : index + size] for index in range(len(run) - size + 1))
        return list(dict.fromkeys(term for term in terms if term not in stop_terms))

    @staticmethod
    def _relevant_excerpt(content: str, terms: list[str], size: int = 1800) -> str:
        matches = [
            (content.lower().find(term), term)
            for term in sorted(terms, key=len, reverse=True)
            if term in content.lower()
        ]
        start = max(0, matches[0][0] - 250) if matches else 0
        return content[start : start + size]

    def save_study_record(self, question: str, answer: str, source_ids: list[int]) -> None:
        self.db.add(
            StudyRecord(
                question=question, answer=answer, source_lesson_ids=",".join(map(str, source_ids))
            )
        )
        self.db.commit()

    def create_lesson_study_session(
        self, lesson_id: int, summary: str, key_points: list[str], first_question: str
    ) -> LessonStudySession:
        record = LessonStudySession(
            lesson_id=lesson_id,
            summary=summary,
            key_points_json=json.dumps(key_points, ensure_ascii=False),
            history_json=json.dumps(
                [{"role": "coach", "question": first_question}], ensure_ascii=False
            ),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_lesson_study_session(self, session_id: int) -> LessonStudySession | None:
        return self.db.get(LessonStudySession, session_id)

    def update_lesson_study_session(
        self,
        record: LessonStudySession,
        history: list[dict],
        mastery_score: int,
        completed: bool,
    ) -> None:
        record.history_json = json.dumps(history, ensure_ascii=False)
        record.answered_count += 1
        record.mastery_score = mastery_score
        record.completed = completed
        self.db.commit()

    def replace_knowledge_points(
        self, lesson: Lesson, points: list[ExtractedKnowledgePoint]
    ) -> list[KnowledgePoint]:
        existing = {
            item.name: item
            for item in self.db.scalars(
                select(KnowledgePoint).where(KnowledgePoint.lesson_id == lesson.id)
            ).all()
        }
        saved: list[KnowledgePoint] = []
        for point in points:
            record = existing.get(point.name) or KnowledgePoint(
                lesson_id=lesson.id, name=point.name
            )
            record.description = point.description
            record.category = point.category
            record.difficulty = point.difficulty
            record.importance_for_ai_pm = point.importance_for_ai_pm
            record.importance_for_interview = point.importance_for_interview
            record.prerequisite = point.prerequisite
            record.source_page = lesson.title
            record.source_url = lesson.url
            record.core_explanation = point.core_explanation
            record.why_explanation = point.why_explanation
            record.teaching_example = point.teaching_example
            record.ai_pm_relevance = point.ai_pm_relevance
            record.extended_explanation = point.extended_explanation
            record.interview_depth = point.interview_depth
            record.interview_value = point.interview_value
            record.interview_requirements_json = json.dumps(
                point.interview_requirements, ensure_ascii=False
            )
            record.unnecessary_detail_json = json.dumps(
                point.unnecessary_detail, ensure_ascii=False
            )
            record.level_1 = point.core_explanation
            record.level_2_json = record.level_2_json or "{}"
            record.level_3_json = record.level_3_json or "{}"
            if record.id is None:
                self.db.add(record)
            saved.append(record)
        self.db.commit()
        for record in saved:
            self.db.refresh(record)
        return saved

    def update_compact_teaching(self, lesson_id: int, items: list) -> list[KnowledgePoint]:
        points = self.list_knowledge_points(lesson_id)
        by_name = {item.name: item for item in items}
        for point in points:
            teaching = by_name.get(point.name)
            if not teaching:
                continue
            point.core_explanation = teaching.core_explanation
            point.why_explanation = teaching.why_explanation
            point.teaching_example = teaching.teaching_example
            point.ai_pm_relevance = teaching.ai_pm_relevance
            point.extended_explanation = teaching.extended_explanation
            point.level_1 = teaching.core_explanation
            point.interview_depth = teaching.interview_depth
            point.interview_value = teaching.interview_value
            point.interview_requirements_json = json.dumps(
                teaching.interview_requirements, ensure_ascii=False
            )
            point.unnecessary_detail_json = json.dumps(
                teaching.unnecessary_detail, ensure_ascii=False
            )
        self.db.commit()
        return points

    def list_knowledge_points(self, lesson_id: int) -> list[KnowledgePoint]:
        return list(
            self.db.scalars(
                select(KnowledgePoint)
                .where(KnowledgePoint.lesson_id == lesson_id, KnowledgePoint.category != "RETIRED")
                .order_by(KnowledgePoint.id)
            ).all()
        )

    def get_knowledge_point(self, knowledge_point_id: int) -> KnowledgePoint | None:
        return self.db.get(KnowledgePoint, knowledge_point_id)

    def list_all_knowledge_points(self, course_id: int | None = None) -> list[KnowledgePoint]:
        statement = select(KnowledgePoint).join(Lesson, Lesson.id == KnowledgePoint.lesson_id)
        if course_id is not None:
            statement = statement.where(Lesson.course_id == course_id)
        statement = statement.where(KnowledgePoint.category != "RETIRED")
        return list(self.db.scalars(statement.order_by(KnowledgePoint.id)).all())

    def create_learning_session(
        self,
        lesson_id: int,
        knowledge_point_id: int,
        course_summary: str,
        target_role: str = "general_ai_pm",
        scope_type: str = "LESSON",
        source_pdf_id: int | None = None,
        page_start: int | None = None,
        page_end: int | None = None,
        section_id: str = "",
        learning_unit_id: int | None = None,
        knowledge_point_ids: list[int] | None = None,
    ) -> LearningSession:
        record = LearningSession(
            lesson_id=lesson_id,
            current_knowledge_point_id=knowledge_point_id,
            course_summary=course_summary,
            target_role=target_role,
            scope_type=scope_type, source_pdf_id=source_pdf_id,
            page_start=page_start, page_end=page_end, section_id=section_id,
            learning_unit_id=learning_unit_id,
            knowledge_point_ids_json=json.dumps(knowledge_point_ids or [], ensure_ascii=False),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_learning_session(self, session_id: int) -> LearningSession | None:
        return self.db.get(LearningSession, session_id)

    def update_learning_session(
        self,
        record: LearningSession,
        *,
        mode: str | None = None,
        knowledge_point_id: int | None = None,
        completed: bool | None = None,
        target_role: str | None = None,
        increment_answers: bool = False,
    ) -> None:
        if mode is not None:
            record.mode = mode
        if knowledge_point_id is not None:
            record.current_knowledge_point_id = knowledge_point_id
        if completed is not None:
            record.completed = completed
        if target_role is not None:
            record.target_role = target_role
        if increment_answers:
            record.answered_count += 1
        self.db.commit()

    def create_question_attempt(
        self,
        session_id: int,
        knowledge_point_id: int,
        question: GeneratedQuestion,
        stage: str,
    ) -> QuestionAttempt:
        record = QuestionAttempt(
            learning_session_id=session_id,
            knowledge_point_id=knowledge_point_id,
            question_type=question.question_type,
            difficulty=question.difficulty,
            stage=stage,
            question=question.question,
            assessment_focus_json=json.dumps(question.assessment_focus, ensure_ascii=False),
            interview_category=question.interview_category,
            target_role=question.target_role,
            interview_value=question.interview_value,
            interview_depth=question.interview_depth,
            why_interviewer_asks=question.why_interviewer_asks,
            must_have_points_json=json.dumps(question.must_have_points, ensure_ascii=False),
            bonus_points_json=json.dumps(question.bonus_points, ensure_ascii=False),
            unnecessary_detail=question.unnecessary_detail,
            question_fingerprint_json=json.dumps(
                question.question_fingerprint.model_dump(), ensure_ascii=False
            ),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_question_attempt(self, attempt_id: int) -> QuestionAttempt | None:
        return self.db.get(QuestionAttempt, attempt_id)

    def clone_question_attempt(self, original: QuestionAttempt) -> QuestionAttempt:
        """Create a fresh retry attempt while preserving the original rubric/config."""
        record = QuestionAttempt(
            learning_session_id=original.learning_session_id,
            knowledge_point_id=original.knowledge_point_id,
            question_type=original.question_type,
            difficulty=original.difficulty,
            stage="mistake_retry",
            question=original.question,
            assessment_focus_json=original.assessment_focus_json,
            interview_category=original.interview_category,
            target_role=original.target_role,
            interview_value=original.interview_value,
            interview_depth=original.interview_depth,
            why_interviewer_asks=original.why_interviewer_asks,
            must_have_points_json=original.must_have_points_json,
            bonus_points_json=original.bonus_points_json,
            unnecessary_detail=original.unnecessary_detail,
            question_fingerprint_json=original.question_fingerprint_json,
        )
        self.db.add(record); self.db.commit(); self.db.refresh(record)
        return record

    def answer_question_attempt(self, record: QuestionAttempt, answer: str) -> None:
        record.user_answer = answer
        record.answered_at = datetime.now(UTC)
        self.db.commit()

    def save_answer_evaluation(
        self, attempt: QuestionAttempt, result: AnswerEvaluationOutput, framework_version: int = 2
    ) -> AnswerEvaluation:
        record = AnswerEvaluation(
            question_attempt_id=attempt.id,
            concept_accuracy=result.concept_accuracy,
            technical_understanding=result.technical_understanding,
            product_thinking=result.product_thinking,
            application_scenario=result.application_scenario,
            communication_structure=result.communication_structure,
            total_score=result.total_score,
            correct_points_json=json.dumps(result.correct_points, ensure_ascii=False),
            missing_points_json=json.dumps(result.missing_points, ensure_ascii=False),
            incorrect_points_json=json.dumps(result.incorrect_points, ensure_ascii=False),
            imprecise_expressions_json=json.dumps(result.imprecise_expressions, ensure_ascii=False),
            interviewer_followups_json=json.dumps(result.interviewer_followups, ensure_ascii=False),
            key_gaps_json=json.dumps([item.model_dump() for item in result.key_gaps], ensure_ascii=False),
            improved_answer=result.improved_answer,
            expert_answer=result.expert_answer,
            answer_framework_json=json.dumps(result.answer_framework, ensure_ascii=False),
            framework_version=framework_version,
            critical_misconception=result.critical_misconception,
            critical_misconception_detail=result.critical_misconception_detail,
            weak_concepts_json=json.dumps(result.weak_concepts, ensure_ascii=False),
            weak_reasoning_json=json.dumps(result.weak_reasoning, ensure_ascii=False),
            weak_product_application_json=json.dumps(
                result.weak_product_application, ensure_ascii=False
            ),
            review_later_json=json.dumps(result.review_later, ensure_ascii=False),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def upsert_weakness(
        self,
        knowledge_point_id: int,
        weakness_type: str,
        evidence: str,
        severity: str,
        current_mastery: int,
    ) -> Weakness:
        record = self.db.scalar(
            select(Weakness).where(
                Weakness.knowledge_point_id == knowledge_point_id,
                Weakness.weakness_type == weakness_type,
            )
        )
        if record:
            record.evidence = evidence
            record.severity = severity
            record.mistake_count += 1
            record.last_seen = datetime.now(UTC)
            record.current_mastery = current_mastery
            record.resolved = False
        else:
            record = Weakness(
                knowledge_point_id=knowledge_point_id,
                weakness_type=weakness_type,
                evidence=evidence,
                severity=severity,
                current_mastery=current_mastery,
            )
            self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def list_weaknesses(
        self, knowledge_point_id: int, unresolved_only: bool = True
    ) -> list[Weakness]:
        statement = select(Weakness).where(Weakness.knowledge_point_id == knowledge_point_id)
        if unresolved_only:
            statement = statement.where(Weakness.resolved.is_(False))
        return list(self.db.scalars(statement.order_by(Weakness.last_seen.desc())).all())

    def resolve_weaknesses(self, knowledge_point_id: int, current_mastery: int) -> None:
        for record in self.list_weaknesses(knowledge_point_id):
            record.resolved = True
            record.current_mastery = current_mastery
        self.db.commit()

    def add_review_history(self, attempt: QuestionAttempt, score: int) -> ReviewHistory:
        record = ReviewHistory(
            knowledge_point_id=attempt.knowledge_point_id,
            question_attempt_id=attempt.id,
            score=score,
            review_type=attempt.stage,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def attempts_with_scores(self, knowledge_point_id: int) -> list[tuple[QuestionAttempt, int]]:
        rows = self.db.execute(
            select(QuestionAttempt, AnswerEvaluation.total_score)
            .join(AnswerEvaluation, AnswerEvaluation.question_attempt_id == QuestionAttempt.id)
            .where(QuestionAttempt.knowledge_point_id == knowledge_point_id)
            .order_by(QuestionAttempt.created_at)
        ).all()
        return [(attempt, score) for attempt, score in rows]

    def attempts_with_evaluations(
        self, knowledge_point_id: int
    ) -> list[tuple[QuestionAttempt, AnswerEvaluation]]:
        rows = self.db.execute(
            select(QuestionAttempt, AnswerEvaluation)
            .join(AnswerEvaluation, AnswerEvaluation.question_attempt_id == QuestionAttempt.id)
            .where(QuestionAttempt.knowledge_point_id == knowledge_point_id)
            .order_by(QuestionAttempt.created_at)
        ).all()
        return [(attempt, evaluation) for attempt, evaluation in rows]

    def question_category_counts(self, target_role: str | None = None) -> dict[str, int]:
        statement = select(
            QuestionAttempt.interview_category, func.count(QuestionAttempt.id)
        )
        if target_role is not None:
            statement = statement.where(QuestionAttempt.target_role == target_role)
        rows = self.db.execute(
            statement.group_by(QuestionAttempt.interview_category)
        ).all()
        return {category: count for category, count in rows}

    def review_rows(self, knowledge_point_id: int) -> list[ReviewHistory]:
        return list(
            self.db.scalars(
                select(ReviewHistory)
                .where(ReviewHistory.knowledge_point_id == knowledge_point_id)
                .order_by(ReviewHistory.tested_at)
            ).all()
        )

    def upsert_mastery_score(
        self,
        knowledge_point_id: int,
        coverage: int,
        assessment: int,
        transfer: int,
        stability: int,
        score: int,
        status: str,
        p1_core_score: int,
        interview_readiness: int,
        interview_ready: bool,
        interview_status: str = "NOT_TESTED",
    ) -> MasteryScore:
        record = self.db.scalar(
            select(MasteryScore).where(MasteryScore.knowledge_point_id == knowledge_point_id)
        )
        if not record:
            record = MasteryScore(knowledge_point_id=knowledge_point_id)
            self.db.add(record)
        record.knowledge_coverage = coverage
        record.assessment_score = assessment
        record.transfer_score = transfer
        record.review_stability = stability
        record.mastery_score = score
        record.status = status
        record.p1_core_score = p1_core_score
        record.interview_readiness = interview_readiness
        if interview_ready and not record.interview_ready:
            record.interview_ready_at = datetime.now(UTC)
        elif not interview_ready:
            record.interview_ready_at = None
        record.interview_ready = interview_ready
        record.interview_status = interview_status
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_mastery_score(self, knowledge_point_id: int) -> MasteryScore | None:
        return self.db.scalar(
            select(MasteryScore).where(MasteryScore.knowledge_point_id == knowledge_point_id)
        )

    def set_interview_status(self, knowledge_point_id: int, status: str) -> None:
        record = self.get_mastery_score(knowledge_point_id)
        if record:
            record.interview_status = status
            self.db.commit()

    def page_mastery(self, lesson_id: int) -> int:
        points = self.list_knowledge_points(lesson_id)
        if not points:
            return 0
        weighted_sum = 0
        total_weight = 0
        for point in points:
            weight = point.importance_for_ai_pm + point.importance_for_interview
            mastery = self.get_mastery_score(point.id)
            weighted_sum += (mastery.mastery_score if mastery else 0) * weight
            total_weight += weight
        return round(weighted_sum / total_weight) if total_weight else 0

    def page_interview_readiness(self, lesson_id: int) -> int:
        points = [
            point
            for point in self.list_knowledge_points(lesson_id)
            if point.interview_depth != "P3"
        ]
        if not points:
            return 0
        weighted_sum = 0
        total_weight = 0
        for point in points:
            weight = max(1, point.interview_value)
            mastery = self.get_mastery_score(point.id)
            weighted_sum += (mastery.interview_readiness if mastery else 0) * weight
            total_weight += weight
        return round(weighted_sum / total_weight) if total_weight else 0

    def create_interview(
        self,
        role_level: str,
        focus: str,
        first_question: str,
        bank_question_id: int | None = None,
    ) -> InterviewSession:
        record = InterviewSession(
            role_level=role_level,
            focus=focus,
            history_json=json.dumps(
                [
                    {
                        "role": "interviewer",
                        "content": first_question,
                        "bank_question_id": bank_question_id,
                    }
                ],
                ensure_ascii=False,
            ),
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_interview(self, session_id: int) -> InterviewSession | None:
        return self.db.get(InterviewSession, session_id)

    def update_interview_history(self, record: InterviewSession, history: list[dict]) -> None:
        record.history_json = json.dumps(history, ensure_ascii=False)
        self.db.commit()
