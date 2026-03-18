from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    openai_api_key: str
    admin_api_key: str
    chroma_db_path: str = "./data/chromadb"
    sqlite_db_path: str = "./data/hsk.db"
    max_input_length: int = 2000
    max_top_n: int = 20
    vector_search_limit: int = 50
    similarity_threshold: float = 1.5
    pipeline_timeout: int = 30
    excel_dir: str = "./data"

    model_config = {"env_file": ".env", "extra": "ignore"}
