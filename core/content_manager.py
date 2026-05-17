"""Content manager — gets next unprocessed section."""

from models.database import content_repo
from utils.logger import setup_logger

logger = setup_logger(__name__)


class ContentManager:
    def __init__(self, book_id: str | None = None):
        self._book_id = book_id

    def get_next_section(self, book_id: str | None = None) -> dict | None:
        bid = book_id or self._book_id
        content = content_repo.get_next_pending(bid)
        if not content:
            return None
        return content

    def get_all_pending(self, book_id: str | None = None) -> list[dict]:
        bid = book_id or self._book_id
        return content_repo.get_pending(bid)
