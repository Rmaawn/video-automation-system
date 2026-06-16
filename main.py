#!/usr/bin/env python3
"""
Video Automation System — CLI entry point.

Commands
--------
    python main.py                 Quick test: generate ONE fresh video from the
                                   first non-empty section of book.json (no DB,
                                   always regenerates — good for checking your
                                   avatar / voice / framing setup).
    python main.py load            Sync book.json → database (skips unchanged).
    python main.py run             Process the next PENDING section via the
                                   full pipeline (DB-tracked, won't repeat).
    python main.py batch           Process ALL pending sections via the pipeline.
    python main.py status          Show system status (content + videos).

Every generated video is multi-scene (≥3 scenes), portrait 9:16 by default,
with burned-in captions — optimized for Instagram Reels.
"""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.scene_builder import SceneBuilder
from core.script_processor import ScriptProcessor
from core.video_manager import VideoManager
from services.heygen_v2 import HeyGenError, HeyGenV2


def read_first_section() -> tuple[str, str, str, str]:
    """Return (book_id, chapter_id, section_id, text) of the first non-empty section."""
    data_dir = PROJECT_ROOT / settings.get("app.data_dir", "data/content")
    book_path = data_dir / "book.json"
    if not book_path.exists():
        raise FileNotFoundError(f"book.json not found at {book_path}")

    with open(book_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    book_id = data.get("book_id", "book")
    for chapter in data.get("chapters", []):
        chapter_id = chapter.get("chapter", "ch")
        for sec in chapter.get("sections", []):
            text = sec.get("text", "").strip()
            if text:
                section_id = sec.get("section", "sec")
                return book_id, chapter_id, section_id, text

    raise ValueError(f"No non-empty section found in {book_path}")


def quick_test() -> int:
    """Generate one fresh video from the first section — no DB, always runs."""
    book_id, chapter_id, section_id, raw_text = read_first_section()
    title = f"{book_id}/{chapter_id}/{section_id}"
    print(f"Content : {title}")
    print(f"Length  : {len(raw_text)} chars")

    processed = ScriptProcessor().process(raw_text)
    sequence = SceneBuilder().build(processed)
    print(f"Scenes  : {sequence.total_scenes} (~{sequence.estimated_duration:.0f}s)")

    voice_id = settings.get_required("heygen.voice_id")
    character_type = settings.get("heygen.character_type", "avatar")
    avatar_pool = settings.get_avatar_pool()
    print(f"Avatars : {len(avatar_pool)} in pool")

    studio_scenes = sequence.to_studio_scenes(
        avatar_pool, voice_id,
        character_type=character_type,
        seed=title,
    )

    client = HeyGenV2()
    try:
        video_id = client.generate_video(
            studio_scenes,
            test_mode=settings.get("heygen.test_mode", False),
            aspect_ratio=settings.get("heygen.video_ratio", "9:16"),
            title=title,
        )
        print(f"HeyGen  : {video_id} (waiting for completion...)")

        download_url = client.wait_for_video(video_id)

        vm = VideoManager()
        filename = vm.generate_filename(book_id, chapter_id, section_id)
        file_path = vm.download_video(download_url, filename)

        print(f"\n✓ Saved : {file_path}")
        return 0
    except HeyGenError as e:
        print(f"\n✗ HeyGen error: {e}")
        return 1
    finally:
        client.close()


def cmd_load() -> int:
    from services.book_loader import BookLoader

    counts = BookLoader().load()
    print(f"book.json synced → added: {counts['added']}, "
          f"updated: {counts['updated']}, unchanged: {counts['unchanged']}")
    return 0


def cmd_run() -> int:
    from core.pipeline import VideoPipeline

    pipeline = VideoPipeline()
    try:
        result = pipeline.run_single()
    finally:
        pipeline.cleanup()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") in ("success", "no_content") else 1


def cmd_batch() -> int:
    from core.pipeline import VideoPipeline

    pipeline = VideoPipeline()
    try:
        results = pipeline.run_batch()
    finally:
        pipeline.cleanup()
    ok = sum(1 for r in results if r.get("status") == "success")
    print(f"\nBatch done — {ok}/{len(results)} succeeded")
    return 0


def cmd_status() -> int:
    from core.pipeline import VideoPipeline

    summary = VideoPipeline().get_status()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


COMMANDS = {
    "load": cmd_load,
    "run": cmd_run,
    "batch": cmd_batch,
    "status": cmd_status,
}


def main() -> int:
    if len(sys.argv) < 2:
        return quick_test()

    command = sys.argv[1].lower()
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"Unknown command: {command!r}")
        print(f"Available: {', '.join(COMMANDS)} (or no argument for a quick test run)")
        return 2
    return handler()


if __name__ == "__main__":
    sys.exit(main())
