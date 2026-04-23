import sqlite3
import logging
import time
from typing import Iterator
from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
import chromadb

logger = logging.getLogger(__name__)


class HskEmbedder:
    """SQLite의 HSK 코드를 임베딩하여 ChromaDB에 저장.

    full_name 컬럼을 임베딩 텍스트로 사용.
    예: "제85류 전기기기 > 축전지 > 리튬이온 축전지 > 반도체 제조용 [자본재 > 전기·전자기기 > 반도체]"
    """

    EMBEDDING_DIMENSIONALITY = 1536
    BATCH_SIZE = 100
    MAX_RETRIES = 5

    def __init__(self, api_key: str, chroma_db_path: str, embedding_model: str):
        self.client = genai.Client(api_key=api_key)
        self.embedding_model = embedding_model
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

        # 임시 컬렉션에 먼저 쓰고 성공 후 교체 (기존 DB 보호)
        tmp_name = "hsk_codes_tmp"
        try:
            self.chroma_client.delete_collection(tmp_name)
        except Exception:
            pass
        tmp_collection = self.chroma_client.create_collection(
            name=tmp_name,
            metadata={"hnsw:space": "cosine"},
        )

        try:
            for batch in self.chunk_list(rows, self.BATCH_SIZE):
                if has_full_name:
                    texts = [self.build_embedding_text(row[1], row[2], row[5]) for row in batch]
                else:
                    texts = [self.build_embedding_text(row[1], row[2]) for row in batch]

                embeddings = self._get_embeddings(texts)
                tmp_collection.add(
                    ids=[row[0] for row in batch],
                    embeddings=embeddings,
                    documents=texts,
                    metadatas=[
                        {"code": row[0], "level": row[3], "parent_code": row[4] or ""}
                        for row in batch
                    ],
                )
                logger.info(f"임베딩 배치 저장: {len(batch)}건")
        except Exception:
            self.chroma_client.delete_collection(tmp_name)
            raise

        # 모든 배치 성공 후 교체
        try:
            self.chroma_client.delete_collection("hsk_codes")
        except Exception:
            pass
        self.chroma_client.create_collection(
            name="hsk_codes",
            metadata={"hnsw:space": "cosine"},
        )
        # ChromaDB는 rename을 지원하지 않으므로 데이터 복사
        data = tmp_collection.get(include=["embeddings", "documents", "metadatas"])
        if data["ids"]:
            collection = self.chroma_client.get_collection("hsk_codes")
            for chunk_ids, chunk_embs, chunk_docs, chunk_metas in zip(
                self.chunk_list(data["ids"], self.BATCH_SIZE),
                self.chunk_list(data["embeddings"], self.BATCH_SIZE),
                self.chunk_list(data["documents"], self.BATCH_SIZE),
                self.chunk_list(data["metadatas"], self.BATCH_SIZE),
            ):
                collection.add(
                    ids=chunk_ids,
                    embeddings=chunk_embs,
                    documents=chunk_docs,
                    metadatas=chunk_metas,
                )
        self.chroma_client.delete_collection(tmp_name)

        logger.info(f"ChromaDB 임베딩 완료: 총 {len(rows)}건")

    def _get_embeddings(self, texts: list[str]) -> list[list[float]]:
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.client.models.embed_content(
                    model=self.embedding_model,
                    contents=texts,
                    config=types.EmbedContentConfig(output_dimensionality=self.EMBEDDING_DIMENSIONALITY),
                )
                return [list(e.values) for e in response.embeddings]
            except (ClientError, ServerError) as e:
                code = getattr(e, "code", None) or getattr(e, "status_code", None)
                retryable = code in (429, 503) or isinstance(e, ServerError)
                if retryable and attempt < self.MAX_RETRIES - 1:
                    wait = min(2 ** attempt * 5, 60)
                    logger.warning(f"API 오류 ({code}), {wait}초 후 재시도 ({attempt + 1}/{self.MAX_RETRIES}): {e}")
                    time.sleep(wait)
                else:
                    raise
