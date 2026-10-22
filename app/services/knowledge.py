import hashlib
import math
import re
from pathlib import Path

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from chromadb.utils.embedding_functions import register_embedding_function

from app.core.config import get_settings


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    if not text.strip():
        return []
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


@register_embedding_function
class LocalHashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Deterministic local fallback; replace with API embeddings for production quality."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def name() -> str:
        return "local-hash-v1"

    def __call__(self, input: Documents) -> Embeddings:
        vectors = []
        for text in input:
            vector = [0.0] * 384
            tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
            for token in tokens:
                digest = hashlib.sha256(token.encode()).digest()
                index = int.from_bytes(digest[:2], "big") % len(vector)
                vector[index] += 1 if digest[2] % 2 else -1
            norm = math.sqrt(sum(value * value for value in vector)) or 1.0
            vectors.append([value / norm for value in vector])
        return vectors

    @staticmethod
    def build_from_config(config: dict) -> "LocalHashEmbeddingFunction":
        LocalHashEmbeddingFunction.validate_config(config)
        return LocalHashEmbeddingFunction()

    def get_config(self) -> dict:
        return {"dimensions": 384}

    @staticmethod
    def validate_config(config: dict) -> None:
        if config.get("dimensions", 384) != 384:
            raise ValueError("LocalHashEmbeddingFunction only supports 384 dimensions")

    def default_space(self) -> str:
        return "cosine"


class KnowledgeBase:
    def __init__(self) -> None:
        path: Path = get_settings().chroma_path
        path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(path))
        self.collection = self.client.get_or_create_collection(
            name="course_lessons",
            embedding_function=LocalHashEmbeddingFunction(),
            metadata={"hnsw:space": "cosine"},
        )

    def index_lesson(self, lesson_id: int, course_id: int, title: str, url: str, text: str) -> None:
        chunks = chunk_text(text)
        if not chunks:
            return
        ids = [f"lesson-{lesson_id}-chunk-{index}" for index in range(len(chunks))]
        self.collection.upsert(
            ids=ids,
            documents=chunks,
            metadatas=[
                {"lesson_id": lesson_id, "course_id": course_id, "title": title, "url": url}
                for _ in chunks
            ],
        )

    def search(self, query: str, course_id: int | None = None, limit: int = 5) -> list[dict]:
        where = {"course_id": course_id} if course_id is not None else None
        result = self.collection.query(query_texts=[query], n_results=limit, where=where)
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        return [{"text": text, **meta} for text, meta in zip(documents, metadatas, strict=False)]

    def delete_course(self, course_id: int) -> None:
        self.collection.delete(where={"course_id": course_id})


knowledge_base = KnowledgeBase()
