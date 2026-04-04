from pydantic import BaseModel, Field, field_validator


class ClassifyRequest(BaseModel):
    description: str = Field(..., min_length=10, max_length=2000)
    top_n: int = Field(default=5, ge=1, le=30)
    confidence_threshold: float | None = Field(default=None, ge=0.0, le=1.0)

    @field_validator("description")
    @classmethod
    def description_not_too_short(cls, v: str) -> str:
        if len(v.strip()) < 10:
            raise ValueError("기술 설명은 최소 10자 이상이어야 합니다")
        return v.strip()


class ClassifyResult(BaseModel):
    rank: int
    hsk_code: str
    name_kr: str
    name_en: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ClassifyResponse(BaseModel):
    results: list[ClassifyResult]
    keywords_extracted: list[str]
    processing_time_ms: int


class HskCodeDetail(BaseModel):
    code: str
    formatted_code: str = ""
    name_kr: str
    name_en: str | None = None
    level: int
    parent_code: str | None = None
    description: str | None = None
    children: list["HskCodeDetail"] = []


class HskSearchResult(BaseModel):
    results: list[HskCodeDetail]
    total: int


class ErrorResponse(BaseModel):
    detail: str
