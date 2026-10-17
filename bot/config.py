"""Application configuration loaded from environment variables / .env."""

from __future__ import annotations

import shutil
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """All runtime settings.

    Every value can be provided through an environment variable with the same
    name (case insensitive) or through the ``.env`` file.
    """

    model_config = SettingsConfigDict(
        env_file=(BASE_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Telegram ---------------------------------------------------------
    bot_token: SecretStr = SecretStr("")
    bot_name: str = "TELRO"
    bot_username: str = "Rwinro_bot"
    owner_ids: str = ""
    admin_ids: str = ""
    api_server: str = ""
    proxy: str = ""

    # --- Storage ----------------------------------------------------------
    data_dir: Path = BASE_DIR / "data"
    db_path: Path = BASE_DIR / "data" / "telro.db"
    download_dir: Path = BASE_DIR / "data" / "downloads"
    generated_dir: Path = BASE_DIR / "data" / "generated"
    log_file: Path = BASE_DIR / "data" / "telro.log"
    cookies_file: str = ""

    # --- Downloads --------------------------------------------------------
    max_upload_mb: int = 0  # 0 = auto (50 MB cloud / 2000 MB local API)
    max_concurrent_downloads: int = 2
    ytdlp_fragments: int = 8
    download_timeout: int = 900
    auto_compress: bool = True
    send_as_document: bool = False
    extract_timeout: int = 45

    # --- Quotas -----------------------------------------------------------
    free_downloads_per_day: int = 25
    free_ai_per_day: int = 60
    referral_target: int = 5
    referral_reward_days: int = 7

    # --- AI ---------------------------------------------------------------
    ai_base_url: str = "https://text.pollinations.ai/openai"
    ai_api_key: SecretStr = SecretStr("")
    ai_model: str = "openai"
    ai_system_prompt: str = ""
    ai_max_tokens: int = 1200
    ai_timeout: int = 120
    ai_history_messages: int = 18
    ai_history_chars: int = 12000
    ai_vision: bool = True
    ai_stream: bool = True
    ai_transcribe: bool = False

    # --- Images -----------------------------------------------------------
    image_provider: str = "pollinations"  # pollinations | openai | disabled
    image_base_url: str = "https://image.pollinations.ai/prompt"
    image_api_url: str = "https://api.openai.com/v1/images/generations"
    image_api_key: SecretStr = SecretStr("")
    image_model: str = "flux"
    image_timeout: int = 150

    # --- Access -----------------------------------------------------------
    force_join_channels: str = ""
    support_username: str = ""
    channel_username: str = ""
    enable_groups: bool = False
    throttle_messages: int = 8
    throttle_callbacks: int = 15
    throttle_window: int = 10

    # --- Misc -------------------------------------------------------------
    log_level: str = "INFO"
    health_host: str = "0.0.0.0"
    health_port: int = 8080
    timezone: str = "UTC"
    shutdown_timeout: int = 10

    @field_validator("data_dir", "db_path", "download_dir", "generated_dir", "log_file", mode="before")
    @classmethod
    def _expand_path(cls, value: object) -> object:
        if isinstance(value, str) and value.startswith("~"):
            return Path(value).expanduser()
        return value

    # ------------------------------------------------------------------ helpers
    @property
    def admins(self) -> set[int]:
        raw = f"{self.owner_ids},{self.admin_ids}"
        result: set[int] = set()
        for chunk in raw.replace(" ", "").split(","):
            if chunk.lstrip("-").isdigit():
                result.add(int(chunk))
        return result

    @property
    def join_channels(self) -> list[str]:
        return [part.strip() for part in self.force_join_channels.replace(",", " ").split() if part.strip()]

    @property
    def use_local_api(self) -> bool:
        return bool(self.api_server.strip())

    @property
    def upload_limit(self) -> int:
        if self.max_upload_mb > 0:
            return self.max_upload_mb * 1024 * 1024
        return 2000 * 1024 * 1024 if self.use_local_api else 50 * 1024 * 1024

    @property
    def max_upload_label(self) -> str:
        return f"{self.upload_limit // (1024 * 1024)} MB"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.ai_base_url.strip())

    @property
    def image_enabled(self) -> bool:
        return self.image_provider.lower().strip() not in {"", "disabled", "off", "none"}

    @property
    def ffmpeg_available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    @property
    def deno_available(self) -> bool:
        return shutil.which("deno") is not None

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.download_dir, self.generated_dir):
            Path(path).mkdir(parents=True, exist_ok=True)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.log_file).parent.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings


settings = get_settings()
