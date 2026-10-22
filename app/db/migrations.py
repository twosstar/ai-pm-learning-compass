from sqlalchemy import Engine, inspect, text


def ensure_schema_compatibility(engine: Engine) -> None:
    """Apply small additive SQLite migrations without touching existing user data."""
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    additions = {
        "lessons": {
            "source_type": "VARCHAR(10) NOT NULL DEFAULT 'WEB'",
            "source_file": "TEXT NOT NULL DEFAULT ''",
            "source_page_start": "INTEGER",
            "source_page_end": "INTEGER",
            "chapter_title": "VARCHAR(500) NOT NULL DEFAULT ''",
            "section_title": "VARCHAR(500) NOT NULL DEFAULT ''",
            "importance_topic": "VARCHAR(100) NOT NULL DEFAULT 'Other'",
            "base_importance_score": "INTEGER NOT NULL DEFAULT -1",
            "interview_value": "INTEGER NOT NULL DEFAULT -1",
            "practical_product_value": "INTEGER NOT NULL DEFAULT -1",
            "prerequisite_importance": "INTEGER NOT NULL DEFAULT -1",
            "base_importance_reason": "TEXT NOT NULL DEFAULT ''",
            "parser_version": "VARCHAR(40) NOT NULL DEFAULT 'legacy_gitbook_v1'",
            "structural_integrity": "VARCHAR(30) NOT NULL DEFAULT 'UNVERIFIED'",
            "migration_status": "VARCHAR(30) NOT NULL DEFAULT ''",
            "content_pipeline_version": "VARCHAR(40) NOT NULL DEFAULT 'learning_content_v3'",
        },
        "pdf_imports": {
            "text_page_count": "INTEGER NOT NULL DEFAULT 0",
            "ocr_page_count": "INTEGER NOT NULL DEFAULT 0",
            "section_count": "INTEGER NOT NULL DEFAULT 0",
            "status": "VARCHAR(30) NOT NULL DEFAULT 'PROCESSING'",
            "error_message": "TEXT NOT NULL DEFAULT ''",
            "reason_code": "VARCHAR(60) NOT NULL DEFAULT ''",
            "page_quality_score": "INTEGER NOT NULL DEFAULT 0",
            "section_quality_score": "INTEGER NOT NULL DEFAULT 0",
            "knowledge_quality_score": "INTEGER NOT NULL DEFAULT 0",
        },
        "knowledge_points": {
            "core_explanation": "TEXT NOT NULL DEFAULT ''",
            "why_explanation": "TEXT NOT NULL DEFAULT ''",
            "teaching_example": "TEXT NOT NULL DEFAULT ''",
            "ai_pm_relevance": "TEXT NOT NULL DEFAULT ''",
            "extended_explanation": "TEXT NOT NULL DEFAULT ''",
            "interview_depth": "VARCHAR(10) NOT NULL DEFAULT 'P1'",
            "interview_value": "INTEGER NOT NULL DEFAULT 3",
            "interview_requirements_json": "TEXT NOT NULL DEFAULT '[]'",
            "unnecessary_detail_json": "TEXT NOT NULL DEFAULT '[]'",
            "importance_topic": "VARCHAR(100) NOT NULL DEFAULT 'Other'",
            "base_importance_score": "INTEGER NOT NULL DEFAULT -1",
            "practical_product_value": "INTEGER NOT NULL DEFAULT -1",
            "prerequisite_importance": "INTEGER NOT NULL DEFAULT -1",
            "base_importance_reason": "TEXT NOT NULL DEFAULT ''",
            "source_course_id": "INTEGER",
            "source_section_id": "VARCHAR(120) NOT NULL DEFAULT ''",
            "source_kp_id": "INTEGER",
            "source_page_start": "INTEGER",
            "source_page_end": "INTEGER",
            "source_evidence_json": "TEXT NOT NULL DEFAULT '[]'",
            "required_capabilities_json": "TEXT NOT NULL DEFAULT '[]'",
            "covered_capabilities_json": "TEXT NOT NULL DEFAULT '[]'",
            "coverage_gap_json": "TEXT NOT NULL DEFAULT '[]'",
            "mechanism_chain_json": "TEXT NOT NULL DEFAULT '[]'",
            "trigger_signals_json": "TEXT NOT NULL DEFAULT '[]'",
            "tradeoff_compare_json": "TEXT NOT NULL DEFAULT '[]'",
            "application_bridge_json": "TEXT NOT NULL DEFAULT '{}'",
            "transfer_score": "INTEGER NOT NULL DEFAULT 0",
        },
        "learning_preferences": {
            "learning_goal": "VARCHAR(60) NOT NULL DEFAULT 'GENERAL_AI_PM'",
        },
        "learning_goals": {
            "target_readiness": "INTEGER NOT NULL DEFAULT 60",
            "daily_minutes": "INTEGER NOT NULL DEFAULT 30",
            "deadline": "DATE",
            "goal_snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "learning_units": {
            "capability_tags_json": "TEXT NOT NULL DEFAULT '[]'",
            "aggregation_type": "VARCHAR(30) NOT NULL DEFAULT 'STANDALONE_UNIT'",
            "canonical_topic_id": "VARCHAR(200) NOT NULL DEFAULT ''",
            "summary": "TEXT NOT NULL DEFAULT ''",
            "learning_objective": "TEXT NOT NULL DEFAULT ''",
            "importance": "INTEGER NOT NULL DEFAULT 3",
            "goal_relevance": "FLOAT NOT NULL DEFAULT 0",
            "difficulty": "INTEGER NOT NULL DEFAULT 1",
            "source_quality": "FLOAT NOT NULL DEFAULT 0",
            "source_section_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "primary_source_id": "INTEGER",
            "supplementary_source_ids_json": "TEXT NOT NULL DEFAULT '[]'",
            "estimated_minutes": "INTEGER NOT NULL DEFAULT 15",
        },
        "learning_goal_compile_reports": {
            "cycle_break_count": "INTEGER NOT NULL DEFAULT 0",
        },
        "interview_sprints": {
            "learning_goal": "VARCHAR(60) NOT NULL DEFAULT 'INTERVIEW_SPRINT'",
            "target_interview_readiness": "INTEGER NOT NULL DEFAULT 60",
            "estimated_required_minutes": "INTEGER NOT NULL DEFAULT 0",
            "total_days": "INTEGER NOT NULL DEFAULT 14",
            "start_date": "DATE",
            "current_day": "INTEGER NOT NULL DEFAULT 1",
            "target_score": "INTEGER NOT NULL DEFAULT 60",
            "current_score": "INTEGER NOT NULL DEFAULT 0",
        },
        "interview_sprint_tasks": {
            "target_type": "VARCHAR(40) NOT NULL DEFAULT 'knowledge_point'",
            "target_id": "VARCHAR(80)",
            "target_title": "VARCHAR(500) NOT NULL DEFAULT ''",
            "target_module": "VARCHAR(40) NOT NULL DEFAULT 'learning'",
            "action_label": "VARCHAR(80) NOT NULL DEFAULT '开始学习'",
            "deep_link": "VARCHAR(1000) NOT NULL DEFAULT ''",
        },
        "learning_sessions": {
            "course_summary": "TEXT NOT NULL DEFAULT ''",
            "target_role": "VARCHAR(60) NOT NULL DEFAULT 'general_ai_pm'",
            "scope_type": "VARCHAR(20) NOT NULL DEFAULT 'LESSON'",
            "source_pdf_id": "INTEGER",
            "page_start": "INTEGER",
            "page_end": "INTEGER",
            "section_id": "VARCHAR(120) NOT NULL DEFAULT ''",
            "learning_unit_id": "INTEGER",
            "knowledge_point_ids_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "question_attempts": {
            "assessment_focus_json": "TEXT NOT NULL DEFAULT '[]'",
            "interview_category": "VARCHAR(60) NOT NULL DEFAULT 'AI技术理解'",
            "target_role": "VARCHAR(60) NOT NULL DEFAULT 'general_ai_pm'",
            "interview_value": "INTEGER NOT NULL DEFAULT 3",
            "interview_depth": "VARCHAR(10) NOT NULL DEFAULT 'P1'",
            "why_interviewer_asks": "TEXT NOT NULL DEFAULT ''",
            "must_have_points_json": "TEXT NOT NULL DEFAULT '[]'",
            "bonus_points_json": "TEXT NOT NULL DEFAULT '[]'",
            "unnecessary_detail": "TEXT NOT NULL DEFAULT ''",
            "question_fingerprint_json": "TEXT NOT NULL DEFAULT '{}'",
        },
        "interview_import_batches": {
            "source_type": "VARCHAR(30) NOT NULL DEFAULT 'local_file'",
            "source_cursor": "INTEGER NOT NULL DEFAULT 0",
            "scroll_count": "INTEGER NOT NULL DEFAULT 0",
            "max_questions": "INTEGER NOT NULL DEFAULT 100",
            "stop_reason": "VARCHAR(80) NOT NULL DEFAULT ''",
        },
        "answer_evaluations": {
            "key_gaps_json": "TEXT NOT NULL DEFAULT '[]'",
            "framework_version": "INTEGER NOT NULL DEFAULT 0",
            "critical_misconception": "BOOLEAN NOT NULL DEFAULT 0",
            "critical_misconception_detail": "TEXT NOT NULL DEFAULT ''",
            "weak_concepts_json": "TEXT NOT NULL DEFAULT '[]'",
            "weak_reasoning_json": "TEXT NOT NULL DEFAULT '[]'",
            "weak_product_application_json": "TEXT NOT NULL DEFAULT '[]'",
            "review_later_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "mastery_scores": {
            "p1_core_score": "INTEGER NOT NULL DEFAULT 0",
            "interview_readiness": "INTEGER NOT NULL DEFAULT 0",
            "interview_ready": "BOOLEAN NOT NULL DEFAULT 0",
            "interview_ready_at": "DATETIME",
            "interview_status": "VARCHAR(30) NOT NULL DEFAULT 'NOT_TESTED'",
        },
        "concepts": {
            "category": "VARCHAR(60) NOT NULL DEFAULT 'FOUNDATION'",
            "source_type": "VARCHAR(40) NOT NULL DEFAULT 'COURSE_DISCOVERED'",
            "recommended_concept": "BOOLEAN NOT NULL DEFAULT 0",
            "course_coverage_count": "INTEGER NOT NULL DEFAULT 0",
            "recommendation_reason": "TEXT NOT NULL DEFAULT ''",
            "course_evidence_json": "TEXT NOT NULL DEFAULT '[]'",
            "card_status": "VARCHAR(30) NOT NULL DEFAULT 'PLACEHOLDER'",
            "quality_score": "INTEGER NOT NULL DEFAULT 0",
            "concept_value_score": "INTEGER NOT NULL DEFAULT 0",
            "concept_level": "VARCHAR(20) NOT NULL DEFAULT 'SUPPLEMENTARY'",
            "card_version": "VARCHAR(30) NOT NULL DEFAULT 'concept_card_v1'",
            "card_sections_json": "TEXT NOT NULL DEFAULT '[]'",
        },
        "concept_relations": {
            "relation_source": "VARCHAR(40) NOT NULL DEFAULT 'CANONICAL_KNOWLEDGE'",
        },
    }
    with engine.begin() as connection:
        for table_name, columns in additions.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name not in existing:
                    connection.execute(
                        text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
                    )
        if inspector.has_table("interview_sprints"):
            # Repair legacy rows once and prevent duplicate active plans for a
            # role/goal pair. Stored timestamps are UTC-naive in older SQLite DBs.
            connection.execute(
                text(
                    "UPDATE interview_sprints SET start_date = date(datetime(created_at, '+8 hours')) "
                    "WHERE start_date IS NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_active_sprint_context "
                    "ON interview_sprints(target_role, learning_goal) "
                    "WHERE lower(status) = 'active'"
                )
            )
