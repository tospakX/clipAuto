from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("data")
    export_dir: Path = Path.home() / "Downloads"
    worker_count: int = 1
    max_batch_urls: int = 200
    whisper_model: str = "small"
    ollama_url: str = "http://127.0.0.1:11434"
    host: str = "127.0.0.1"
    port: int = 8765

    model_config = SettingsConfigDict(env_prefix="CLIPAUTO_", env_file=".env")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "clipauto.db"
