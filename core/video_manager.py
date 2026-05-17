"""Video manager — download and storage."""

import re
from datetime import datetime
from pathlib import Path

import requests

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class VideoManager:
    def __init__(self):
        self._output_dir = Path(settings.get("app.output_dir", "output/videos"))
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def generate_filename(self, book_id: str, chapter: str, section: str,
                          date: datetime | None = None) -> str:
        dt = date or datetime.now()
        ts = dt.strftime("%Y%m%d_%H%M%S")
        def sanitize(name: str) -> str:
            return re.sub(r"[^a-zA-Z0-9_\u0600-\u06FF-]", "_", name)
        return f"{sanitize(book_id)}_{sanitize(chapter)}_{sanitize(section)}_{ts}.mp4"

    def download_video(self, url: str, filename: str) -> str:
        file_path = self._output_dir / filename
        logger.info("Downloading: %s", file_path)

        response = requests.get(url, stream=True, timeout=300)
        response.raise_for_status()

        with open(file_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        size_mb = file_path.stat().st_size / (1024 * 1024)
        logger.info("Downloaded: %.2f MB", size_mb)
        return str(file_path.resolve())

    def list_videos(self) -> list[Path]:
        return sorted(self._output_dir.glob("*.mp4"))
