import json
from pathlib import Path

from scripts.release_check import failures


ROOT = Path(__file__).resolve().parents[1]


def test_public_curriculum_ids_are_unique_and_stable():
    data = json.loads((ROOT / "app/data/sample_curriculum.json").read_text(encoding="utf-8"))
    lesson_ids = [lesson["id"] for lesson in data["lessons"]]
    point_ids = [point["id"] for lesson in data["lessons"] for point in lesson["knowledge_points"]]
    concept_ids = [concept["id"] for concept in data["concepts"]]
    assert len(lesson_ids) == len(set(lesson_ids))
    assert len(point_ids) == len(set(point_ids))
    assert len(concept_ids) == len(set(concept_ids))
    assert point_ids == [1001, 1002, 1003, 1004, 1005, 1006]


def test_public_release_check_passes_on_clean_tree():
    assert failures() == []


def test_public_app_does_not_mount_private_features():
    source = (ROOT / "app/main.py").read_text(encoding="utf-8")
    assert "public_catalog.router" in source
    assert "public_study.router" in source
    assert "public_concepts.router" in source
    for route in ("browser.router", "courses.router", "interview.router", "v2.router"):
        assert route not in source


def test_windows_distribution_uses_desktop_installer():
    installer = (ROOT / "packaging/windows/installer.iss").read_text(encoding="utf-8")
    assert "AI PM Learning Compass.exe" in installer
    assert "{autodesktop}" in installer
    assert not (ROOT / "Start Learning Copilot.bat").exists()
    assert not (ROOT / "scripts/start_local.py").exists()


def test_public_ui_separates_lesson_brief_from_practice():
    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'id="catalog-view"' in html
    assert 'id="lesson-view"' in html
    assert 'id="knowledge-point-list"' in html
    assert 'id="start-practice"' in html
    assert 'id="review-knowledge"' in html
    assert "function openLesson" in script
    assert '$("#start-practice").addEventListener("click", startPractice)' in script
    assert 'button.textContent = "查看本节"' in script


def test_lesson_reader_hides_reference_panels_but_retains_source_records():
    from app.services.public_curriculum import public_curriculum

    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    script = (ROOT / "app/static/app.js").read_text(encoding="utf-8")
    assert 'lesson-source-panel' not in html
    assert 'lesson-sources-list' not in html + script
    assert '核对知识依据' not in script
    assert 'sources.className = "point-sources"' not in script
    assert public_curriculum()['sources']
    assert all(lesson['source_ids'] and all(point['source_ids'] for point in lesson['knowledge_points'])
               for lesson in public_curriculum()['lessons'])


def test_public_app_starts_and_serves_only_public_features(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.db.models import Concept, Course, Lesson
    from app.db.session import SessionLocal
    from app.services import study as study_module
    from tests.test_mastery_loop import FakeStructuredLLM

    from app.schemas.learning import GeneratedQuestion, KnowledgeExtractionOutput
    from app.services.public_curriculum import public_curriculum

    class PublicTestLLM(FakeStructuredLLM):
        async def complete_structured(self, schema, system, user, fallback, retries=2, **kwargs):
            assert schema is not KnowledgeExtractionOutput, 'Curated lessons must not be re-extracted'
            if schema is GeneratedQuestion:
                return fallback()
            return await super().complete_structured(schema, system, user, fallback, retries, **kwargs)

    def reject_private_bank(*args, **kwargs):
        raise AssertionError('Public study must not access the private question bank')

    monkeypatch.setattr(study_module, "llm_service", PublicTestLLM())
    monkeypatch.setattr(study_module.interview_bank_service, "select_for_learning", reject_private_bank)

    paths = set(app.openapi()["paths"])
    assert {"/api/health", "/api/catalog", "/api/concepts", "/api/study/start", "/api/study/answer", "/api/study/continue"} <= paths
    assert not any(path.startswith(("/api/crawl", "/api/browser", "/api/interview", "/api/v2", "/v2")) for path in paths)

    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}

        with SessionLocal() as db:
            private_course = Course(id=901, name="private test corpus", start_url="https://private.example")
            db.add(private_course)
            db.flush()
            db.add(Lesson(
                id=901,
                course_id=private_course.id,
                title="private lesson",
                url="https://private.example/lesson",
                content="private fixture text",
                content_hash="private-fixture",
            ))
            db.add(Concept(
                id=9901,
                canonical_name="private-fixture",
                display_name="private concept",
                category="PRIVATE",
                source_type="COURSE_DISCOVERED",
                card_status="READY",
            ))
            db.commit()

        catalog = client.get("/api/catalog").json()["items"]
        assert len(catalog) == 1
        assert catalog[0]["name"] == "AI 产品经理公开学习路径"
        assert [lesson["id"] for lesson in catalog[0]["lessons"]] == list(range(101, 161))
        assert client.get("/api/catalog").json()["total_knowledge_points"] == 120
        assert client.get("/api/catalog").json()["textbook_lessons"] >= 40
        first_lesson = catalog[0]["lessons"][0]
        assert first_lesson["summary"]
        assert first_lesson["sources"]
        assert first_lesson["objectives"]
        assert first_lesson["practice_task"]
        first_point = first_lesson["knowledge_points"][0]
        assert first_point["core_explanation"]
        assert first_point["why_explanation"]
        assert first_point["teaching_example"]
        concepts = client.get("/api/concepts").json()
        assert len(concepts["items"]) == 150
        assert concepts["total"] == 150
        assert concepts["items"][0]["name"] == "人工智能"
        assert len(concepts["categories"]) == 10
        assert all(category["count"] == 15 for category in concepts["categories"])
        rag = client.get("/api/concepts", params={"q": "RAG"}).json()["items"]
        assert rag[0]["id"] == 2002
        assert rag[0]["sources"]
        assert rag[0]["related_names"]
        mcp = client.get("/api/concepts", params={"q": "mcp"}).json()["items"]
        assert mcp[0]["name"] == "模型上下文协议"
        assert len(client.get("/api/concepts", params={"category": "RAG"}).json()["items"]) == 15
        assert client.get("/api/concepts", params={"q": "not-a-concept-XYZ"}).json()["items"] == []
        assert client.get("/api/concepts/9901").status_code == 404
        assert client.get("/api/interview/start").status_code == 404
        assert client.get("/api/crawl").status_code == 404
        assert client.post("/api/study/start", json={"lesson_id": 999999}).status_code == 404
        assert client.post("/api/study/start", json={"lesson_id": 901}).status_code == 404

        started = client.post("/api/study/start", json={"lesson_id": 101})
        assert started.status_code == 200, started.text
        first = started.json()
        assert first["knowledge_points"]
        assert first_lesson['practice_task'] in first['question']['question']
        assert [point["id"] for point in first["knowledge_points"]] == [1001, 1002]
        assert [point["name"] for point in first["knowledge_points"]] == [
            "用户任务与问题证据", "AI 适用性与基线比较"
        ]
        first_answer = client.post("/api/study/answer", json={
            "session_id": first["session_id"],
            "question_attempt_id": first["question_attempt_id"],
            "answer": "阈值需要结合任务目标和错误代价来选择。",
        })
        assert first_answer.status_code == 200, first_answer.text
        feedback = first_answer.json()
        assert feedback["total_score"] == 50
        assert feedback["next_question"] is not None

        second_answer = client.post("/api/study/answer", json={
            "session_id": first["session_id"],
            "question_attempt_id": feedback["next_attempt_id"],
            "answer": "应根据验证数据和业务损失比较误报、漏报，再持续监控。",
        })
        assert second_answer.status_code == 200, second_answer.text
        assert second_answer.json()["interview_ready"] is True, second_answer.json()
        progress = client.get("/api/catalog").json()["items"][0]["lessons"][0]["knowledge_points"]
        assert any(point["mastery"] > 0 for point in progress), progress
        next_point = client.post("/api/study/continue", json={"session_id": first["session_id"]})
        assert next_point.status_code == 200, next_point.text
        next_point_data = next_point.json()
        assert next_point_data["completed"] is False
        assert next_point_data["current_knowledge_point"]["id"] == 1002
        last_answer = client.post("/api/study/answer", json={
            "session_id": first["session_id"],
            "question_attempt_id": next_point_data["question_attempt_id"],
            "answer": "先判断任务是否需要语言理解，再与规则和搜索基线比较质量、成本及风险。",
        })
        assert last_answer.status_code == 200, last_answer.text
        next_lesson = client.post("/api/study/continue", json={"session_id": first["session_id"]})
        assert next_lesson.status_code == 200, next_lesson.text
        assert next_lesson.json()["scope_label"] == "下一節", next_lesson.json()
        assert next_lesson.json()["lesson_id"] == 102
        assert next_lesson.json()["lesson_title"] == "工作流、模型与知识检索的组合"

        for lesson in public_curriculum()['lessons']:
            response = client.post('/api/study/start', json={'lesson_id': lesson['id']})
            assert response.status_code == 200, (lesson['id'], response.text)
            result = response.json()
            assert {point['id'] for point in result['knowledge_points']} == {point['id'] for point in lesson['knowledge_points']}
            if lesson['id'] == 102:
                assert '应聘' in result['question']['question']
                assert result['question']['must_have_points']
            else:
                assert lesson['practice_task'] in result['question']['question']
        # At the last lesson, the same loop reaches completion instead of a private row.
        for _ in range(2):
            answered = client.post('/api/study/answer', json={
                'session_id': result['session_id'], 'question_attempt_id': result['question_attempt_id'],
                'answer': '先明确目标、依据与边界，比较基线并验证风险，再按证据作出上线取舍。',
            })
            assert answered.status_code == 200, answered.text
            continued = client.post('/api/study/continue', json={'session_id': result['session_id']})
            assert continued.status_code == 200, continued.text
            result = continued.json()
        assert result['completed'] is True


def test_public_concept_library_has_150_complete_unique_cards():
    from collections import Counter
    from app.services.public_concept_library import public_concept_library

    library = public_concept_library()
    cards = library["concepts"]
    assert len(cards) == 150
    assert len({card["id"] for card in cards}) == 150
    names = {card["name"] for card in cards}
    assert len(names) == 150
    assert set(Counter(card["category"] for card in cards).values()) == {15}
    assert {card["id"]: card["name"] for card in cards if card["id"] <= 2003} == {
        2001: "基线方案", 2002: "检索增强生成", 2003: "回归评估"
    }
    for card in cards:
        for field in ("definition", "mechanism", "when_to_use", "when_not_to_use", "ai_pm_relevance", "example"):
            assert len(card[field].strip()) >= 6, (card["name"], field)
        assert card["aliases"]
        assert set(card["related_names"]) <= names
        assert card["name"] not in card["related_names"]
        assert card["source_ids"]
        assert all(library["sources"][key]["url"].startswith("https://") for key in card["source_ids"])


def test_concept_upgrade_is_idempotent_and_preserves_unrelated_data(monkeypatch):
    import copy
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.models import Concept, Course, KnowledgePoint, Lesson, MasteryScore
    from app.db.session import Base
    from app.services.public_concept_library import sync_public_concepts
    from app.services import public_concept_library as library_module

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Course(id=501, name="existing course", start_url="public://fixture"))
        db.flush()
        db.add(Lesson(id=501, course_id=501, title="existing lesson", url="public://fixture/501", content="original lesson", content_hash="fixture"))
        db.flush()
        db.add(KnowledgePoint(id=501, lesson_id=501, name="existing point", description="original teaching", category="AI_PRODUCT", source_page="existing lesson", source_url="public://fixture/501", level_1="original teaching"))
        db.flush()
        db.add(MasteryScore(knowledge_point_id=501, mastery_score=67))
        db.add(Concept(id=2001, canonical_name="基线方案", display_name="基线方案", source_type="PUBLIC_SAMPLE", short_definition="legacy text"))
        db.add(Concept(id=2004, canonical_name="private-fixture", display_name="private concept", source_type="COURSE_DISCOVERED", short_definition="private text"))
        db.commit()
        sync_public_concepts(db)
        first_ids = {row.display_name: row.id for row in db.query(Concept).filter_by(source_type="PUBLIC_SAMPLE")}
        sync_public_concepts(db)
        second_ids = {row.display_name: row.id for row in db.query(Concept).filter_by(source_type="PUBLIC_SAMPLE")}
        assert first_ids == second_ids
        assert len(first_ids) == 150
        assert first_ids["基线方案"] == 2001
        revised = copy.deepcopy(library_module.public_concept_library())
        legacy = next(card for card in revised["concepts"] if card["id"] == 2001)
        legacy["name"] = "基线方案（修订）"
        monkeypatch.setattr(library_module, "public_concept_library", lambda: revised)
        sync_public_concepts(db)
        assert db.get(Concept, 2001).display_name == "基线方案（修订）"
        assert db.query(Concept).filter_by(source_type="PUBLIC_SAMPLE").count() == 150
        assert db.get(Concept, 2004).short_definition == "private text"
        assert db.get(Concept, 2004).source_type == "COURSE_DISCOVERED"
        assert db.get(Lesson, 501).content == "original lesson"
        assert db.query(MasteryScore).filter_by(knowledge_point_id=501).one().mastery_score == 67
    engine.dispose()
