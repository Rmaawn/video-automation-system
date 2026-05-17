"""State manager — progress tracking and retry handling."""

from config.settings import settings
from models.database import content_repo, video_repo
from utils.logger import setup_logger

logger = setup_logger(__name__)


class StateManager:
    def __init__(self):
        self._max_retries = settings.get("state.max_retries_per_content", 3)

    def can_process(self, content_id: int) -> bool:
        content = content_repo.get_by_id(content_id)
        if not content:
            return False
        if content.get("retry_count", 0) >= self._max_retries:
            logger.warning("Content %d exceeded max retries", content_id)
            return False
        return True

    def mark_processing(self, content_id: int):
        content_repo.update_status(content_id, "processing")
        video_repo.create(content_id)
        logger.info("Content %d → processing", content_id)

    def mark_done(self, content_id: int):
        content_repo.update_status(content_id, "done")
        logger.info("Content %d → done", content_id)

    def mark_failed(self, content_id: int, error: str):
        content_repo.update_status(content_id, "failed", error)
        retry_count = content_repo.increment_retry(content_id)
        logger.error("Content %d failed (retry %d/%d): %s",
                     content_id, retry_count, self._max_retries, error)

    def mark_video_processing(self, video_id: int, heygen_id: str):
        video_repo.update_heygen_id(video_id, heygen_id, "processing")
        logger.info("Video %d → HeyGen: %s", video_id, heygen_id)

    def mark_video_completed(self, video_id: int, file_path: str, download_url: str):
        video_repo.update_completion(video_id, file_path, download_url)
        logger.info("Video %d completed: %s", video_id, file_path)

    def mark_video_failed(self, video_id: int, error: str):
        video_repo.update_status(video_id, "failed", error)
        retry_count = video_repo.increment_retry(video_id)
        logger.error("Video %d failed (retry %d): %s", video_id, retry_count, error)

    def get_system_summary(self) -> dict:
        all_content = content_repo.get_all()
        status_counts = {}
        for c in all_content:
            status_counts[c["status"]] = status_counts.get(c["status"], 0) + 1
        return {
            "total_content": len(all_content),
            "status_breakdown": status_counts,
            "processing_videos": len(video_repo.get_processing()),
        }
