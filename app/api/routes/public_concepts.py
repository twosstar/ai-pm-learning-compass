import json
from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import Concept
from app.db.session import get_db
from app.services.public_concept_library import public_concept_library

router = APIRouter(prefix="/concepts", tags=["concept-map"])
DbSession = Annotated[Session, Depends(get_db)]


@router.get("")
def list_concepts(db: DbSession, q: str = "", category: str = "") -> dict:
    library = public_concept_library()
    query = db.query(Concept).filter(
        Concept.card_status == "READY",
        Concept.source_type == "PUBLIC_SAMPLE",
        Concept.card_version == library["version"],
    )
    rows = query.order_by(Concept.category, Concept.display_name).all()
    counts = Counter(item.category for item in rows)
    views = [_view(item) for item in rows]
    reading_order = {item["name"]: index for index, item in enumerate(library["concepts"])}
    views.sort(key=lambda item: reading_order.get(item["name"], len(reading_order)))
    term = q.strip().casefold()
    if term:
        views = [item for item in views if term in " ".join([
            item["name"], *item["aliases"], item["category_label"],
            item["definition"], item["mechanism"],
        ]).casefold()]
        views.sort(key=lambda item: term not in [
            item["name"].casefold(), *(alias.casefold() for alias in item["aliases"])
        ])
    if category:
        views = [item for item in views if item["category"] == category]
    return {
        "items": views,
        "total": len(rows),
        "matched": len(views),
        "categories": [dict(item, count=counts[item["id"]]) for item in library["categories"]],
        "version": library["version"],
        "editorial_note": library["editorial_note"],
    }


@router.get("/{concept_id}")
def get_concept(concept_id: int, db: DbSession) -> dict:
    item = db.get(Concept, concept_id)
    if (not item or item.card_status != "READY" or item.source_type != "PUBLIC_SAMPLE"
            or item.card_version != public_concept_library()["version"]):
        raise HTTPException(status_code=404, detail="Concept not found")
    return _view(item)


def _view(item: Concept) -> dict:
    library = public_concept_library()
    metadata = next((row for row in library["concepts"] if row["name"] == item.display_name), {})
    category_label = next((row["label"] for row in library["categories"]
                           if row["id"] == item.category), item.category)
    return {
        "id": item.id,
        "name": item.display_name,
        "category": item.category,
        "category_label": category_label,
        "aliases": json.loads(item.aliases_json or "[]"),
        "related_names": metadata.get("related_names", []),
        "sources": [library["sources"][key] for key in metadata.get("source_ids", [])],
        "definition": item.short_definition,
        "mechanism": item.core_mechanism,
        "when_to_use": item.when_to_use,
        "when_not_to_use": item.when_not_to_use,
        "ai_pm_relevance": item.ai_pm_relevance,
        "example": item.example,
    }
