from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model_writer: str = "qwen2.5:7b"
    ollama_model_analyzer: str = "qwen2.5:3b"
    ollama_model_cheap: str = "qwen2.5:1.5b"
    ollama_timeout_writer: int = 300
    ollama_timeout_analyzer: int = 180
    ollama_timeout_cheap: int = 120

    agent_model_scout: str = "qwen2.5:1.5b"
    agent_model_analyst: str = "llama3.2:3b"
    agent_model_architect: str = "qwen2.5:3b"
    agent_model_writer: str = "gemma2:2b"
    agent_model_editor: str = "qwen2.5:3b"
    agent_model_polisher: str = "qwen2.5:1.5b"

    agent_timeout_scout: int = 120
    agent_timeout_analyst: int = 180
    agent_timeout_architect: int = 180
    agent_timeout_writer: int = 300
    agent_timeout_editor: int = 180
    agent_timeout_polisher: int = 120

    agent_parallel_preload: bool = True

    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "llama-3.1-8b-instant"
    groq_timeout: int = 120
    groq_max_rpm: int = 25
    groq_max_tpm: int = 5000
    groq_source_limit: int = 15000

    agent_cloud_scout: bool = True
    agent_cloud_analyst: bool = True
    agent_cloud_architect: bool = True
    agent_cloud_condenser: bool = True
    agent_cloud_writer: bool = True
    agent_cloud_editor: bool = False
    agent_cloud_polisher: bool = False
    agent_cloud_document_architect: bool = True
    agent_cloud_chapter_architect: bool = True
    agent_cloud_chapter_editor: bool = True



    cache_dir: str = ".cache"
    cache_ttl: int = 3600
    search_cache_ttl: int = 1800
    max_source_chars: int = 80000
    retry_attempts: int = 3
    retry_delay: int = 2
    feeds_config_path: str = "feeds.json"
    feeds_state_path: str = ".feeds_state.json"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def writer_model(self) -> str:
        return self.ollama_model_writer

    @property
    def analyzer_model(self) -> str:
        return self.ollama_model_analyzer

    @property
    def cheap_model(self) -> str:
        return self.ollama_model_cheap

    @property
    def writer_timeout(self) -> int:
        return self.ollama_timeout_writer

    @property
    def analyzer_timeout(self) -> int:
        return self.ollama_timeout_analyzer

    @property
    def cheap_timeout(self) -> int:
        return self.ollama_timeout_cheap

    @property
    def cache_dir_path(self) -> Path:
        return Path(self.cache_dir)

    @property
    def feeds_config_path_obj(self) -> Path:
        return Path(self.feeds_config_path)

    @property
    def feeds_state_path_obj(self) -> Path:
        return Path(self.feeds_state_path)

    @property
    def groq_available(self) -> bool:
        return bool(self.groq_api_key)

    agent_force_local: bool = False

    def agent_uses_cloud(self, agent_name: str) -> bool:
        if self.agent_force_local or not self.groq_available:
            return False
        key = f"agent_cloud_{agent_name}"
        return getattr(self, key, False)

    def validate(self):
        pass


settings = Settings()
