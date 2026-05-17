#!/usr/bin/env python3
"""
Detect what type of avatar is configured in .env (HEYGEN_AVATAR_ID).

Run:
    python scripts/detect_avatar.py

Reports:
    - Avatar id, name, type (avatar / talking_photo / instant / interactive)
    - Whether it supports Avatar IV motion prompts
    - Whether it has Gesture Control captures
    - Suggested config for this avatar
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from services.heygen_v3 import HeyGenV3, HeyGenError


def classify(avatar: dict) -> tuple[str, list[str]]:
    """Return (type_label, capability_notes)."""
    notes = []

    is_talking_photo = avatar.get("type") == "talking_photo" or "talking_photo_id" in avatar
    is_instant = bool(avatar.get("is_instant_avatar") or avatar.get("instant_avatar"))
    is_realistic = bool(avatar.get("is_hyper_realistic") or avatar.get("hyper_realistic"))
    has_gestures = bool(avatar.get("gestures") or avatar.get("gesture_list"))
    supports_iv = bool(avatar.get("support_avatar_iv", True))

    if is_talking_photo:
        label = "Photo Avatar (Talking Photo)"
        notes.append("Static torso by default — needs Avatar IV motion prompts for hand gestures.")
    elif is_realistic:
        label = "Hyper-Realistic / Digital Twin"
        notes.append("Best gesture quality. Can use Gesture Control if gestures were recorded.")
    elif is_instant:
        label = "Instant Avatar"
        notes.append("Limited gestures (only what was captured during 2-min recording).")
    else:
        label = "Studio / Stock Avatar"

    if has_gestures:
        notes.append(f"Has {len(avatar.get('gestures', avatar.get('gesture_list', [])))} captured gestures.")
    if supports_iv:
        notes.append("Supports Avatar IV motion prompts.")

    return label, notes


def main():
    avatar_id = settings.get_required("heygen.avatar_id")
    voice_id = settings.get("heygen.voice_id", "<not set>")
    client = HeyGenV3()

    print(f"\nConfigured avatar_id: {avatar_id}")
    print(f"Configured voice_id : {voice_id}\n")

    try:
        avatar = client.get_avatar(avatar_id)
    except HeyGenError as e:
        print(f"get_avatar failed: {e}")
        print("Falling back to list_avatars...\n")
        avatars = client.list_avatars()
        match = next(
            (a for a in avatars if a.get("avatar_id") == avatar_id or a.get("id") == avatar_id),
            None,
        )
        if match is None:
            print(f"Avatar {avatar_id} not found in account.")
            print(f"You have {len(avatars)} avatars. First 5:")
            for a in avatars[:5]:
                print(f"  - {a.get('avatar_id') or a.get('id')} | {a.get('avatar_name') or a.get('name')}")
            client.close()
            return 1
        avatar = match

    name = avatar.get("avatar_name") or avatar.get("name") or "<unnamed>"
    label, notes = classify(avatar)

    print(f"Name : {name}")
    print(f"Type : {label}")
    print()
    print("Capabilities:")
    for n in notes:
        print(f"  - {n}")
    print()
    print("Raw fields (debug):")
    for k in ("avatar_id", "type", "is_instant_avatar", "is_hyper_realistic",
              "support_avatar_iv", "talking_photo_id", "premium", "gender"):
        if k in avatar:
            print(f"  {k}: {avatar[k]}")

    print()
    if "Talking Photo" in label or "Instant" in label:
        print("RECOMMENDATION:")
        print("  Enable heygen.use_avatar_iv: true in settings.yaml")
        print("  This is the only path to hand gestures for this avatar type.")
    elif "Hyper-Realistic" in label:
        print("RECOMMENDATION:")
        print("  You already have the best avatar type.")
        print("  Avatar IV motion prompts will override captured gestures — prefer Gesture Control.")

    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
