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

# Editorial learning order for the public concept map. The rest are IMPORTANT:
# useful vocabulary for interviews, but not prerequisites for every beginner.
CORE_CONCEPT_IDS = {
    2001, 2002, 2004, 2005, 2007, 2008, 2013,
    2019, 2020, 2021, 2022, 2031, 2034, 2039, 2041,
    2043, 2049, 2050, 2055, 2056, 2059, 2060, 2064, 2067,
    2069, 2073, 2077, 2078, 2079, 2080, 2082, 2083, 2084,
    2086, 2091, 2093, 2095, 2096, 2097, 2103, 2105,
    2122, 2129, 2130, 2133, 2137, 2141, 2142, 2144, 2146,
    2147, 2149, 2150,
}
SUPPLEMENTARY_CONCEPT_IDS = {
    2011, 2012, 2025, 2026, 2027, 2028, 2029, 2037, 2038,
    2042, 2046, 2047, 2048, 2057, 2058, 2070, 2071,
    2072, 2074, 2075, 2085, 2087, 2089, 2099, 2100, 2101, 2102,
    2108, 2109, 2110, 2111, 2112, 2113, 2117, 2118, 2124, 2125,
    2126, 2136, 2138, 2139, 2140, 2143, 2145, 2148,
}


def _priority_for(concept_id: int, metadata: dict) -> str:
    # Preserve the three hand-reviewed pilot labels while consistently
    # classifying every other public card by this editorial map.
    existing = metadata.get("priority")
    if existing in {"CORE", "IMPORTANT", "SUPPLEMENTARY"}:
        return existing
    if concept_id in CORE_CONCEPT_IDS:
        return "CORE"
    if concept_id in SUPPLEMENTARY_CONCEPT_IDS:
        return "SUPPLEMENTARY"
    return "IMPORTANT"


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
        "typical_scenario": metadata.get("typical_scenario", item.example),
        "interview_questions": metadata.get("interview_questions", []),
        "priority": _priority_for(item.id, metadata),
    }
