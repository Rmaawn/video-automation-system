"""Settings loader with environment variable override."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


class Settings:
    _instance = None
    _config: dict[str, Any] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, config_path: str | None = None):
        if self._initialized:
            return
        self._initialized = True

        base_dir = Path(__file__).parent.parent
        config_path = config_path or str(base_dir / "config" / "settings.yaml")

        with open(config_path, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

        self._apply_env_overrides()

    def _apply_env_overrides(self):
        env_map = {
            "heygen.api_key": "HEYGEN_API_KEY",
            "heygen.avatar_id": "HEYGEN_AVATAR_ID",
            "heygen.avatar_ids": "HEYGEN_AVATAR_IDS",
            "heygen.voice_id": "HEYGEN_VOICE_ID",
            "heygen.video_ratio": "HEYGEN_VIDEO_RATIO",
            "heygen.api_base_url": "HEYGEN_API_BASE_URL",
            "heygen.test_mode": "HEYGEN_TEST_MODE",
            "app.log_level": "APP_LOG_LEVEL",
            "app.db_path": "APP_DB_PATH",
            "app.output_dir": "APP_OUTPUT_DIR",
            "app.data_dir": "APP_DATA_DIR",
            "webhook.secret": "WEBHOOK_SECRET",
        }
        for dotted_key, env_var in env_map.items():
            value = os.environ.get(env_var)
            if value:
                if value.lower() in ("true", "1", "yes"):
                    value = True
                elif value.lower() in ("false", "0", "no"):
                    value = False
                self._set_nested(dotted_key, value)

    def _set_nested(self, dotted_key: str, value: Any):
        keys = dotted_key.split(".")
        d = self._config
        for key in keys[:-1]:
            d = d.setdefault(key, {})
        d[keys[-1]] = value

    def get(self, dotted_key: str, default: Any = None) -> Any:
        keys = dotted_key.split(".")
        d = self._config
        for key in keys:
            if isinstance(d, dict) and key in d:
                d = d[key]
            else:
                return default
        return d

    def get_required(self, dotted_key: str) -> Any:
        value = self.get(dotted_key)
        if value is None:
            raise ValueError(f"Required config '{dotted_key}' not set. Add it to .env file.")
        return value

    def get_section(self, section: str) -> dict[str, Any]:
        return self.get(section, {})

    def get_avatar_pool(self) -> list[str]:
        """Resolve the avatar pool used to rotate camera angles across scenes.

        Prefers `heygen.avatar_ids` (comma-separated → multiple looks/angles),
        falling back to the single required `heygen.avatar_id`. Rotating
        through several avatar looks is the ONLY way to get real angle/outfit
        variety within one HeyGen video — there is no camera API.
        """
        avatar_ids_csv = self.get("heygen.avatar_ids")
        if avatar_ids_csv:
            pool = [a.strip() for a in str(avatar_ids_csv).split(",") if a.strip()]
            if pool:
                return pool
        return [self.get_required("heygen.avatar_id")]


settings = Settings()
