"""Versioned, independently authored public concepts; no remote/model calls."""
import json
from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Concept

LIBRARY_FILE = Path(__file__).parents[1] / "data" / "concept_library.json"


@lru_cache(maxsize=1)
def public_concept_library() -> dict:
    return json.loads(LIBRARY_FILE.read_text(encoding="utf-8"))


def sync_public_concepts(db: Session) -> None:
    """Add/update owned cards on every startup, preserving unrelated data."""
    for data in public_concept_library()["concepts"]:
        canonical = f"public-concept-{data['id']}"
        record = db.query(Concept).filter_by(canonical_name=canonical).first()
        if record is not None and record.source_type != "PUBLIC_SAMPLE":
            raise RuntimeError("公开概念标识发生冲突，请检查本地概念数据。")
        if record is None:
            # Upgrade the original three sample cards without changing IDs.
            record = db.query(Concept).filter_by(
                display_name=data["name"], source_type="PUBLIC_SAMPLE"
            ).first()
        if record is None:
            record = Concept(canonical_name=canonical, source_type="PUBLIC_SAMPLE")
            if db.get(Concept, data["id"]) is None:
                record.id = data["id"]
            db.add(record)
        record.canonical_name = canonical
        record.display_name = data["name"]
        record.aliases_json = json.dumps(data["aliases"], ensure_ascii=False)
        record.category = data["category"]
        record.card_status = "READY"
        record.short_definition = data["definition"]
        record.core_mechanism = data["mechanism"]
        record.when_to_use = data["when_to_use"]
        record.when_not_to_use = data["when_not_to_use"]
        record.ai_pm_relevance = data["ai_pm_relevance"]
        record.example = data["example"]
        record.concept_level = "CORE"
        record.card_version = public_concept_library()["version"]
        db.flush()
    db.commit()
