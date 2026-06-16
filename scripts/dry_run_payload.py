#!/usr/bin/env python3
"""
Dry-run: build the exact HeyGen /v2/video/generate payload for the next
pending content section, print it as JSON, and DO NOT send it.

Use this before spending credits to verify framings + motion prompts.

Run:
    python scripts/dry_run_payload.py                  # next pending section
    python scripts/dry_run_payload.py --text "..."     # arbitrary text
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from core.content_manager import ContentManager
from core.scene_builder import SceneBuilder
from core.script_processor import ScriptProcessor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", help="Use this raw text instead of a pending section")
    parser.add_argument("--book", help="Book id override")
    parser.add_argument("--no-process", action="store_true",
                        help="Skip ScriptProcessor (treat --text as already processed)")
    args = parser.parse_args()

    if args.text:
        raw = args.text
        title = "dry-run/inline-text"
    else:
        book_id = args.book or settings.get("content.default_book_id", "sample_book")
        section = ContentManager().get_next_section(book_id)
        if not section:
            print(f"No pending content for book: {book_id}")
            return 1
        raw = section["text"]
        title = f"{section['book_id']}/{section['chapter']}/{section['section']}"

    processed = raw if args.no_process else ScriptProcessor().process(raw)
    sequence = SceneBuilder().build(processed)

    avatar_pool = settings.get_avatar_pool()
    voice_id = settings.get_required("heygen.voice_id")
    character_type = settings.get("heygen.character_type", "avatar")

    studio_scenes = sequence.to_studio_scenes(
        avatar_pool, voice_id,
        character_type=character_type,
        seed=title,
    )

    ratio = settings.get("heygen.video_ratio", "9:16")
    dim = {"width": 1080, "height": 1920} if ratio == "9:16" else {"width": 1920, "height": 1080}

    payload = {
        "title": title,
        "dimension": dim,
        "caption": settings.get("heygen.caption", True),
        "test": settings.get("heygen.test_mode", False),
        "video_inputs": studio_scenes,
    }

    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print()
    print(f"# Total scenes: {sequence.total_scenes}", file=sys.stderr)
    print(f"# Estimated duration: {sequence.estimated_duration:.1f}s", file=sys.stderr)
    print(f"# Shot list:", file=sys.stderr)
    for i, (s, scene) in enumerate(zip(sequence.scenes, studio_scenes)):
        ch = scene["character"]
        gesture = ch.get("custom_motion_prompt", "—")
        print(f"#   [{i}] {ch.get('avatar_style')}/scale={ch.get('scale'):.2f}  "
              f"emotion={s.emotion}  gesture={gesture[:60]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
