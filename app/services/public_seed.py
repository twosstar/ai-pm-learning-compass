"""Idempotent upgrades of the owned public curriculum, preserving progress."""
import hashlib
import json

from sqlalchemy.orm import Session

from app.db.models import Course, KnowledgePoint, Lesson
from app.db.session import SessionLocal
from app.services.public_curriculum import public_curriculum

PUBLIC_ROOT = "public://ai-pm-foundations"


def sync_public_curriculum(db: Session) -> None:
    payload = public_curriculum()
    course_data = payload["course"]
    course = db.get(Course, course_data["id"])
    if course and course.start_url != PUBLIC_ROOT:
        raise RuntimeError("公开课程 ID 与其他课程冲突；已停止更新以保护原数据。")
    if course is None:
        course = Course(id=course_data["id"], name=course_data["name"], start_url=PUBLIC_ROOT)
        db.add(course)
    course.name = course_data["name"]
    db.flush()
    for data in payload["lessons"]:
        url = f"{PUBLIC_ROOT}/{data['id']}"
        lesson = db.get(Lesson, data["id"])
        if lesson and (lesson.url != url or lesson.course_id != course.id):
            raise RuntimeError(f"公开课程第 {data['id']} 节的 ID 冲突；已停止更新。")
        if lesson is None:
            lesson = Lesson(id=data["id"], course_id=course.id, url=url)
            db.add(lesson)
        lesson.title = data["title"]
        teaching = "\n\n".join(
            f"{point['name']}：{point['core_explanation']}\n为什么：{point['why_explanation']}"
            f"\n原创教学例子：{point['teaching_example']}\n产品迁移：{point['ai_pm_relevance']}"
            for point in data["knowledge_points"]
        )
        expanded = '\n\n'.join(
            section['title'] + '\n' + '\n'.join(section.get('paragraphs', []) + section.get('steps', []))
            for point in data['knowledge_points'] for section in point.get('teaching_sections', [])
        )
        teaching += '\n\n' + expanded if expanded else ''
        source_labels = "; ".join(
            f"{payload['sources'][key]['title']} / {payload['sources'][key]['section']}"
            for key in data["source_ids"]
        )
        lesson.content = f"{data['content']}\n学习目标：{'；'.join(data['objectives'])}\n\n{teaching}\n\n依据：{source_labels}\n原创练习任务：{data['practice_task']}"
        lesson.content_hash = hashlib.sha256(lesson.content.encode("utf-8")).hexdigest()
        lesson.source_type = "WEB"
        lesson.structural_integrity = "PASS"
        lesson.chapter_title = data["chapter"]
        lesson.section_title = data["chapter"]
        lesson.importance_topic = data["topic"]
        db.flush()
        for item in data["knowledge_points"]:
            point = db.get(KnowledgePoint, item["id"])
            if point and (point.lesson_id != lesson.id or point.source_url != url):
                raise RuntimeError(f"公开知识点 {item['id']} 的 ID 冲突；已停止更新。")
            if point is None:
                point = KnowledgePoint(id=item["id"], lesson_id=lesson.id)
                db.add(point)
            for field in ("name", "description", "category", "core_explanation", "why_explanation", "teaching_example", "ai_pm_relevance"):
                setattr(point, field, item[field])
            point.difficulty = "基础"
            point.importance_for_ai_pm = 4
            point.importance_for_interview = 4
            point.prerequisite = item.get("prerequisite", "")
            point.source_page = lesson.title
            point.source_url = url
            point.interview_depth = "P1"
            point.interview_value = 4
            point.interview_requirements_json = json.dumps(item["interview_requirements"], ensure_ascii=False)
            point.level_1 = item["core_explanation"]
            db.flush()
    # No session, score, attempt or unrelated stored content is deleted.
    db.commit()


def seed_public_data() -> None:
    with SessionLocal() as db:
        sync_public_curriculum(db)
