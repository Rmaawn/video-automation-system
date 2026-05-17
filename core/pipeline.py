"""Pipeline orchestrator — content → script → scenes → HeyGen → download."""

from config.settings import settings
from core.content_manager import ContentManager
from core.script_processor import ScriptProcessor
from core.scene_builder import SceneBuilder
from core.state_manager import StateManager
from core.video_manager import VideoManager
from models.database import content_repo, video_repo
from services.book_loader import BookLoader
from services.heygen_v2 import HeyGenV2, HeyGenError
from utils.logger import setup_logger

logger = setup_logger(__name__)


class VideoPipeline:
    """Orchestrates the full video generation pipeline."""

    def __init__(self, book_id: str | None = None):
        self._book_id = book_id or settings.get("content.default_book_id", "sample_book")
        self._content_mgr = ContentManager()
        self._script_proc = ScriptProcessor()
        self._scene_builder = SceneBuilder()
        self._state_mgr = StateManager()
        self._video_mgr = VideoManager()
        self._book_loader = BookLoader()
        self._heygen: HeyGenV2 | None = None

    @property
    def heygen(self) -> HeyGenV2:
        if self._heygen is None:
            self._heygen = HeyGenV2()
        return self._heygen

    def _sync_book(self) -> None:
        """Sync book.json → DB. Silent when nothing changed."""
        counts = self._book_loader.load(self._book_id)
        added, updated = counts.get("added", 0), counts.get("updated", 0)
        if added or updated:
            logger.info("book.json sync: %d added, %d updated", added, updated)

    def run_single(self) -> dict:
        """Sync book.json, then process one pending section → video."""
        logger.info("=" * 60)
        logger.info("Pipeline start — book: %s", self._book_id)

        self._sync_book()

        content = self._content_mgr.get_next_section(self._book_id)
        if not content:
            logger.info("No pending content for: %s", self._book_id)
            return {"status": "no_content"}

        content_id = content["id"]
        logger.info("Processing: %d | %s/%s", content_id, content["chapter"], content["section"])

        if not self._state_mgr.can_process(content_id):
            return {"status": "retry_exceeded"}

        self._state_mgr.mark_processing(content_id)
        video_record = video_repo.get_by_content_id(content_id)

        try:
            processed = self._script_proc.process(content["text"])
            content_repo.update_processed_text(content_id, processed)

            sequence = self._scene_builder.build(processed)

            avatar_id = settings.get_required("heygen.avatar_id")
            voice_id = settings.get_required("heygen.voice_id")

            character_type = settings.get("heygen.character_type", "avatar")
            studio_scenes = sequence.to_studio_scenes(
                avatar_id, voice_id,
                character_type=character_type,
                seed=f"{content['book_id']}/{content['chapter']}/{content['section']}",
            )

            heygen_id = self.heygen.generate_video(
                studio_scenes,
                test_mode=settings.get("heygen.test_mode", False),
                aspect_ratio=settings.get("heygen.video_ratio", "9:16"),
                title=f"{content['book_id']}/{content['chapter']}/{content['section']}",
            )

            if video_record:
                self._state_mgr.mark_video_processing(video_record["id"], heygen_id)

            for i, scene in enumerate(sequence.scenes):
                video_repo.upsert_scene(video_record["id"], i, {
                    "avatar_id": avatar_id,
                    "voice_id": voice_id,
                    "voice_emotion": scene.emotion,
                    "script": scene.text,
                    "background_type": "color",
                    "duration_estimate": scene.duration_estimate,
                })

            download_url = self.heygen.wait_for_video(heygen_id)

            filename = self._video_mgr.generate_filename(
                content["book_id"], content["chapter"], content["section"],
            )
            file_path = self._video_mgr.download_video(download_url, filename)

            if video_record:
                self._state_mgr.mark_video_completed(video_record["id"], file_path, download_url)
            self._state_mgr.mark_done(content_id)

            logger.info("DONE — %d scenes, saved: %s", sequence.total_scenes, file_path)

            return {
                "status": "success",
                "content_id": content_id,
                "file_path": file_path,
                "scenes": sequence.total_scenes,
                "duration": sequence.estimated_duration,
            }

        except HeyGenError as e:
            error_msg = f"HeyGen error: {e}"
            logger.error(error_msg)
            if video_record:
                self._state_mgr.mark_video_failed(video_record["id"], error_msg)
            self._state_mgr.mark_failed(content_id, error_msg)
            return {"status": "heygen_error", "error": str(e)}

        except Exception as e:
            error_msg = f"Pipeline error: {e}"
            logger.error(error_msg, exc_info=True)
            if video_record:
                self._state_mgr.mark_video_failed(video_record["id"], error_msg)
            self._state_mgr.mark_failed(content_id, error_msg)
            return {"status": "error", "error": str(e)}

    def run_batch(self, max_videos: int | None = None) -> list[dict]:
        results = []
        count = 0
        while True:
            if max_videos and count >= max_videos:
                break
            result = self.run_single()
            results.append(result)
            if result["status"] == "no_content":
                break
            count += 1
        return results

    def get_status(self) -> dict:
        return self._state_mgr.get_system_summary()

    def cleanup(self):
        if self._heygen:
            self._heygen.close()
