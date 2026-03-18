import json
import logging
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """당신은 R&D 기술 설명에서 관련 무역 상품을 추출하는 전문가입니다.
사용자가 제공하는 기술 설명을 분석하여, 해당 기술과 관련된 제품, 물질, 부품, 장비를 한국어와 영어로 추출하세요.
직접 언급되지 않았더라도 해당 기술로 생산되거나 사용되는 파생 제품도 포함하세요.
결과는 JSON 배열 형식으로만 반환하세요. 예: ["양극재", "cathode material", "리튬이온 배터리"]"""


class KeywordExtractor:
    def __init__(self, openai_api_key: str):
        self.client = AsyncOpenAI(api_key=openai_api_key)

    @staticmethod
    def build_prompt(description: str) -> str:
        return f"다음 R&D 기술 설명에서 관련 제품, 물질, 부품, 장비를 한국어와 영어로 추출하세요:\n\n{description}"

    @staticmethod
    def parse_keywords(raw: str) -> list[str]:
        raw = raw.strip()
        try:
            keywords = json.loads(raw)
            if isinstance(keywords, list):
                return [k.strip() for k in keywords if isinstance(k, str) and k.strip()]
        except json.JSONDecodeError:
            pass
        keywords = [k.strip().strip('"').strip("'") for k in raw.replace("\n", ",").split(",")]
        return [k for k in keywords if k]

    async def extract(self, description: str, max_retries: int = 2) -> list[str]:
        last_error = None
        for attempt in range(max_retries + 1):
            try:
                response = await self.client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": self.build_prompt(description)}],
                    temperature=0.2,
                )
                raw = response.choices[0].message.content or ""
                keywords = self.parse_keywords(raw)
                logger.info(f"키워드 추출 완료: {len(keywords)}개 — {keywords}")
                return keywords
            except Exception as e:
                last_error = e
                logger.warning(f"키워드 추출 재시도 {attempt + 1}/{max_retries + 1}: {e}")
        raise last_error
