from pathlib import Path

import pytest

from vikki_vision import config
from vikki_vision.config import ConfigError, Settings, load_settings

ENV_VARS = ["VIKKI_API_KEY", "VIKKI_MODEL", "VIKKI_CAMERA_INDEX", "VIKKI_FRAME_INTERVAL",
            "BARGE_IN_MIN_RMS", "VIKKI_DATA_DIR"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    # Don't pick up the developer's real .env
    monkeypatch.setattr(config, "load_dotenv", lambda *a, **k: None)


def test_defaults(monkeypatch):
    monkeypatch.setenv("VIKKI_API_KEY", "abc")
    settings = load_settings()
    assert settings.api_key == "abc"
    assert settings.camera_index == 0
    assert settings.barge_in_min_rms == 600.0
    settings.validate()


def test_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("VIKKI_API_KEY", "abc")
    monkeypatch.setenv("VIKKI_CAMERA_INDEX", "1")
    monkeypatch.setenv("BARGE_IN_MIN_RMS", "400")
    monkeypatch.setenv("VIKKI_DATA_DIR", str(tmp_path))
    settings = load_settings()
    assert settings.camera_index == 1
    assert settings.barge_in_min_rms == 400.0
    assert settings.log_dir == tmp_path / "logs"
    assert settings.conversations_dir == tmp_path / "conversations"


@pytest.mark.parametrize("key", ["", "your-api-key-here"])
def test_missing_api_key_is_rejected(key):
    with pytest.raises(ConfigError, match="VIKKI_API_KEY"):
        Settings(api_key=key).validate()


def test_non_numeric_value_is_rejected(monkeypatch):
    monkeypatch.setenv("VIKKI_CAMERA_INDEX", "front")
    with pytest.raises(ConfigError, match="VIKKI_CAMERA_INDEX"):
        load_settings()
