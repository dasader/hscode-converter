import json
import re
import logging
from google import genai
from google.genai import types
from app.services.vector_search import SearchCandidate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 HS 코드 분류 전문가입니다.
사용자가 제공하는 R&D 기술 설명과 후보 HSK 코드 목록을 비교하여,
관련도가 높은 순서대로 코드를 선정하고 신뢰도 점수와 선정 사유를 제시하세요.

반드시 후보 목록에 있는 코드만 선택하세요. 새로운 코드를 만들지 마세요.

결과는 JSON 배열로만 반환하세요:
[{"code": "코드", "confidence": 0.0~1.0, "reason": "선정 사유"}, ...]"""


class Reranker:
    def __init__(self, api_key: str, model: str):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    @staticmethod
    def build_candidates_text(candidates: list[SearchCandidate]) -> str:
        lines = [f"- {c.code}: {c.name}" for c in candidates]
        return "\n".join(lines)

    @staticmethod
    def parse_response(raw: str) -> list[dict]:
        raw = raw.strip()
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", raw, re.DOTALL)
        if match:
            raw = match.group(1).strip()
        try:
            results = json.loads(raw)
            if isinstance(results, list):
                return results
        except json.JSONDecodeError:
            logger.warning(f"리랭킹 응답 JSON 파싱 실패: {raw[:200]}")
        return []

    async def rerank(self, description: str, candidates: list[SearchCandidate], top_n: int, max_retries: int = 2) -> list[dict]:
        candidates_text = self.build_candidates_text(candidates)
        user_prompt = f"## R&D 기술 설명\n{description}\n\n## 후보 HSK 코드 목록\n{candidates_text}\n\n위 기술 설명과 가장 관련 있는 HSK 코드를 최대 {top_n}개 선정하세요."
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model,
                    contents=user_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
                raw = response.text or ""
                results = self.parse_response(raw)
                logger.info(f"리랭킹 완료: {len(results)}개 선정")
                return results[:top_n]
            except Exception as e:
                last_error = e
                logger.warning(f"리랭킹 재시도 {attempt + 1}/{max_retries + 1}: {e}")
        raise last_error
