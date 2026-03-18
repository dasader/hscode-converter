import sqlite3
import logging
from typing import Iterator
from openai import OpenAI
import chromadb

logger = logging.getLogger(__name__)


class HskEmbedder:
    """SQLite의 HSK 코드를 임베딩하여 ChromaDB에 저장.

    full_name 컬럼을 임베딩 텍스트로 사용.
    예: "제85류 전기기기 > 축전지 > 리튬이온 축전지 > 반도체 제조용 [자본재 > 전기·전자기기 > 반도체]"
    """

    EMBEDDING_MODEL = "text-embedding-3-small"
    BATCH_SIZE = 100

    def __init__(self, openai_api_key: str, chroma_db_path: str):
        self.openai_client = OpenAI(api_key=openai_api_key)
        self.chroma_client = chromadb.PersistentClient(path=chroma_db_path)

    @staticmethod
    def build_embedding_text(name_kr: str, name_en: str | None, full_name: str | None = None) -> str:
        """임베딩용 텍스트 생성. full_name이 있으면 우선 사용."""
        if full_name and full_name.strip():
            return full_name.strip()
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

        # full_name 컬럼이 있는지 확인
        columns = [col[1] for col in cursor.execute("PRAGMA table_info(hsk_codes)").fetchall()]
        has_full_name = "full_name" in columns

        if has_full_name:
            rows = cursor.execute(
                "SELECT code, name_kr, name_en, level, parent_code, full_name FROM hsk_codes"
            ).fetchall()
        else:
            rows = cursor.execute(
                "SELECT code, name_kr, name_en, level, parent_code FROM hsk_codes"
            ).fetchall()
        conn.close()

        # 기존 컬렉션 삭제 후 재생성
        try:
            self.chroma_client.delete_collection("hsk_codes")
        except Exception:
            pass
        collection = self.chroma_client.create_collection(
            name="hsk_codes",
            metadata={"hnsw:space": "cosine"},
        )

        for batch in self.chunk_list(rows, self.BATCH_SIZE):
            if has_full_name:
                texts = [self.build_embedding_text(row[1], row[2], row[5]) for row in batch]
            else:
                texts = [self.build_embedding_text(row[1], row[2]) for row in batch]

            embeddings = self._get_embeddings(texts)
            collection.add(
                ids=[row[0] for row in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=[
                    {"code": row[0], "level": row[3], "parent_code": row[4] or ""}
                    for row in batch
                ],
            )
            logger.info(f"임베딩 배치 저장: {len(batch)}건")

        logger.info(f"ChromaDB 임베딩 완료: 총 {len(rows)}건")

    def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        response = self.openai_client.embeddings.create(model=self.EMBEDDING_MODEL, input=texts)
        return [item.embedding for item in response.data]
