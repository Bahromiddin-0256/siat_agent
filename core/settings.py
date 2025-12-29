from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

# Django-like project root (repo root): /.../siat_agent
BASE_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    llm_provider: str
    ollama_model: str
    ollama_embedding_model: str
    ollama_base_url: str = "http://localhost:11434"
    port: int = 8000
    groq_model: str
    groq_api_key: str
    open_router_api_key: str
    open_router_base_url: str
    deepinfra_api_key: str = ""
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    deepinfra_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # Common paths
    chroma_persist_dir: Path = BASE_DIR / "chroma_db"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )


settings = Settings()
