from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

# Django-like project root (repo root): /.../siat_agent
BASE_DIR = Path(__file__).resolve().parents[1]

_VALID_PROVIDERS = {"ollama", "groq", "open_router", "deepinfra"}


class Settings(BaseSettings):
    llm_provider: str
    ollama_model: str
    ollama_embedding_model: str = ""  # No longer used; BGE-M3 handles embeddings
    ollama_base_url: str = "http://localhost:11434"
    port: int = 8000
    groq_model: str = ""
    groq_api_key: str = ""
    open_router_api_key: str = ""
    open_router_base_url: str = ""
    deepinfra_api_key: str = ""
    deepinfra_base_url: str = "https://api.deepinfra.com/v1/openai"
    deepinfra_model: str = "meta-llama/Llama-3.3-70B-Instruct-Turbo"

    # BGE-M3 embedding model (HuggingFace model ID or local path)
    bge_m3_model: str = "BAAI/bge-m3"

    # Vector store path (Qdrant local, both collections share one directory)
    qdrant_persist_dir: Path = BASE_DIR / "vector" / "qdrant"

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
    )

    def validate_config(self) -> List[str]:
        """
        Validate critical configuration values.

        Returns:
            List of error messages; empty list means configuration is valid.
        """
        errors: List[str] = []

        if self.llm_provider not in _VALID_PROVIDERS:
            errors.append(
                f"Invalid LLM_PROVIDER '{self.llm_provider}'. "
                f"Must be one of: {', '.join(sorted(_VALID_PROVIDERS))}"
            )

        if not (1024 <= self.port <= 65535):
            errors.append(f"Invalid PORT {self.port}. Must be between 1024 and 65535.")

        main_json = BASE_DIR / "jsons" / "main.json"
        if not main_json.exists():
            errors.append(f"Missing required data file: {main_json}")

        # Provider-specific key checks
        if self.llm_provider == "groq" and not self.groq_api_key.strip():
            errors.append("GROQ_API_KEY is required when LLM_PROVIDER=groq")

        if self.llm_provider == "open_router" and not self.open_router_api_key.strip():
            errors.append("OPEN_ROUTER_API_KEY is required when LLM_PROVIDER=open_router")

        if self.llm_provider == "deepinfra" and not self.deepinfra_api_key.strip():
            errors.append("DEEPINFRA_API_KEY is required when LLM_PROVIDER=deepinfra")

        return errors


settings = Settings()
