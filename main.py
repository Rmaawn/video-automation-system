#!/usr/bin/env python3
"""
Video Automation System — test entry point.

Reads data/content/book.json, takes the first non-empty section, and
generates ONE HeyGen video from it. No database checks, no pending
state, no "already done" logic — every run produces a fresh video.

Usage:
    python video_automation/main.py
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


def main() -> int:
    book_id, chapter_id, section_id, raw_text = read_first_section()
    title = f"{book_id}/{chapter_id}/{section_id}"
    print(f"Content : {title}")
    print(f"Length  : {len(raw_text)} chars")

    processed = ScriptProcessor().process(raw_text)
    sequence = SceneBuilder().build(processed)
    print(f"Scenes  : {sequence.total_scenes} (~{sequence.estimated_duration:.0f}s)")

    avatar_id = settings.get_required("heygen.avatar_id")
    voice_id = settings.get_required("heygen.voice_id")
    character_type = settings.get("heygen.character_type", "avatar")

    studio_scenes = sequence.to_studio_scenes(
        avatar_id, voice_id,
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


if __name__ == "__main__":
    sys.exit(main())
