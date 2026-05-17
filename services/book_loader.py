"""Book loader — reads book.json and syncs with database."""

import json
from pathlib import Path

from config.settings import settings
from models.database import content_repo, db
from utils.logger import setup_logger

logger = setup_logger(__name__)


class BookLoader:
    """
    Syncs book.json with the database.

    Behavior per section:
      - New (book/chapter/section) tuple → inserted as pending.
      - Same tuple, same text             → no-op.
      - Same tuple, different text        → text replaced; if previous
                                            status was done/failed, status
                                            is reset to pending so the new
                                            text gets re-generated.
    """

    def __init__(self):
        self._data_dir = Path(settings.get("app.data_dir", "data/content"))

    def load(self, book_id: str | None = None) -> dict:
        json_path = self._data_dir / "book.json"
        if not json_path.exists():
            logger.warning("book.json not found at %s — nothing to sync", json_path)
            return {"added": 0, "updated": 0, "unchanged": 0}

        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        file_book_id = data.get("book_id", book_id or settings.get("content.default_book_id"))
        title = data.get("title", file_book_id)
        language = data.get("language", "fa")

        db.ensure_book(file_book_id, title, language)

        counts = {"added": 0, "updated": 0, "unchanged": 0}

        for chapter in data.get("chapters", []):
            chapter_id = chapter.get("chapter", "")
            for sec in chapter.get("sections", []):
                section_id = sec.get("section", "")
                text = sec.get("text", "").strip()
                if not text:
                    continue

                _, action = content_repo.upsert(file_book_id, chapter_id, section_id, text)
                counts[action] = counts.get(action, 0) + 1

        return counts
