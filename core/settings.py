import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    llm_provider:str
    ollama_model: str
    ollama_embedding_model: str
    ollama_base_url: str = "http://localhost:11434"
    port: int = 8000
    groq_model: str
    groq_api_key: str
    open_router_api_key:str
    open_router_base_url:str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


settings = Settings()