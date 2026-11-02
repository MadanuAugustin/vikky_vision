"""
Application settings.

Values come from environment variables, which are loaded from a `.env` file in the current
working directory (or a parent directory) when present. See `.env.example`.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

API_KEY_PLACEHOLDER = "your-api-key-here"
DEFAULT_MODEL = "models/gemini-3.8-live"


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str = DEFAULT_MODEL
    assistant_name: str = "Vikki"
    voice_name: str = "Zephyr"
    camera_index: int = 0
    frame_interval_seconds: float = 1.0
    show_preview: bool = True
    barge_in_min_rms: float = 600.0
    data_dir: Path = Path.cwd()

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def conversations_dir(self) -> Path:
        return self.data_dir / "conversations"

    def validate(self) -> None:
        if not self.api_key or self.api_key == API_KEY_PLACEHOLDER:
            raise ConfigError("VIKKI_API_KEY is not set. Add it to the .env file (see .env.example).")
        if self.frame_interval_seconds <= 0:
            raise ConfigError("VIKKI_FRAME_INTERVAL must be greater than 0.")


def _env_number(name: str, default, cast):
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return cast(raw)
    except ValueError as e:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from e


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


def load_settings() -> Settings:
    """Load settings from the environment (and .env). Call Settings.validate() before use."""
    load_dotenv(find_dotenv(usecwd=True))
    return Settings(
        api_key=os.environ.get("VIKKI_API_KEY", "").strip(),
        model=os.environ.get("VIKKI_MODEL", DEFAULT_MODEL),
        camera_index=_env_number("VIKKI_CAMERA_INDEX", 0, int),
        frame_interval_seconds=_env_number("VIKKI_FRAME_INTERVAL", 1.0, float),
        show_preview=_env_bool("VIKKI_SHOW_PREVIEW", True),
        barge_in_min_rms=_env_number("BARGE_IN_MIN_RMS", 600.0, float),
        data_dir=Path(os.environ.get("VIKKI_DATA_DIR") or Path.cwd()),
    )
