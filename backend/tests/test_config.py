import os
import pytest


def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test")
    from app.core.config import Settings
    settings = Settings()
    assert settings.openai_api_key == "test-key"
    assert settings.admin_api_key == "admin-test"


def test_settings_defaults(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ADMIN_API_KEY", "admin-test")
    from app.core.config import Settings
    settings = Settings()
    assert settings.chroma_db_path == "./data/chromadb"
    assert settings.sqlite_db_path == "./data/hsk.db"
    assert settings.max_input_length == 2000
    assert settings.max_top_n == 20
    assert settings.vector_search_limit == 50
    assert settings.similarity_threshold == 0.3
