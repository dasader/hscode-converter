import sqlite3
import logging
from typing import Iterator
from openai import OpenAI
import chromadb

logger = logging.getLogger(__name__)


class HskEmbedder:
    EMBEDDING_MODEL = "text-embedding-3-small"
    BATCH_SIZE = 100

    def __init__(self, openai_api_key: str, chroma_db_path: str):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def build_embedding_text(name_kr: str, name_en: str | None) -> str:
        if name_en:
            return f"{name_kr} ({name_en})"
        return name_kr

    @staticmethod
    def chunk_list(items: list, size: int) -> Iterator[list]:
        for i in range(0, len(items), size):
            yield items[i : i + size]

    def embed_from_sqlite(self, sqlite_db_path: str) -> None:
        conn = sqlite3.connect(sqlite_db_path)
        cursor = conn.cursor()
        rows = cursor.execute("SELECT code, name_kr, name_en, level, parent_code FROM hsk_codes").fetchall()
        conn.close()
        collection = self.chroma_client.get_or_create_collection(name="hsk_codes", metadata={"hnsw:space": "cosine"})
        self.chroma_client.delete_collection("hsk_codes")
        collection = self.chroma_client.create_collection(name="hsk_codes", metadata={"hnsw:space": "cosine"})
        for batch in self.chunk_list(rows, self.BATCH_SIZE):
            texts = [self.build_embedding_text(row[1], row[2]) for row in batch]
            embeddings = self._get_embeddings(texts)
            collection.add(
                ids=[row[0] for row in batch], embeddings=embeddings, documents=texts,
                metadatas=[{"code": row[0], "level": row[3], "parent_code": row[4] or ""} for row in batch],
            )
        logger.info(f"ChromaDB 임베딩 완료: 총 {len(rows)}건")

    def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        response = self.openai_client.embeddings.create(model=self.EMBEDDING_MODEL, input=texts)
        return [item.embedding for item in response.data]
