import pytest
from app.services.keyword_extractor import KeywordExtractor


def test_build_prompt():
    prompt = KeywordExtractor.build_prompt("리튬이온 배터리 양극재 제조 기술")
    assert "리튬이온 배터리 양극재 제조 기술" in prompt
    assert "제품" in prompt or "물질" in prompt


def test_parse_keywords():
    raw = '["양극재", "cathode material", "리튬이온 배터리", "NCM"]'
    keywords = KeywordExtractor.parse_keywords(raw)
    assert "양극재" in keywords
    assert "cathode material" in keywords
    assert len(keywords) == 4


def test_parse_keywords_handles_malformed():
    raw = "양극재, cathode material, 리튬이온 배터리"
    keywords = KeywordExtractor.parse_keywords(raw)
    assert len(keywords) >= 2
