#!/usr/bin/env python3
"""
List all your HeyGen avatar groups and their looks.

Each "look" inside a HeyGen avatar has its own avatar_id (or
talking_photo_id) — that's what you paste into HEYGEN_AVATAR_IDS
to make the pipeline rotate between camera angles / outfits.

Run:
    python video_automation/scripts/list_looks.py
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from services.heygen_v3 import HeyGenError, HeyGenV3


def main() -> int:
    client = HeyGenV3()
    base = client._base
    session = client._session

    print("Fetching avatar groups...\n")

    # List all groups
    resp = session.get(f"{base}/v2/avatar.group.list", timeout=30)
    if resp.status_code != 200:
        print(f"Failed to list groups: HTTP {resp.status_code} — {resp.text[:200]}")
        return 1

    groups = resp.json().get("data", {}).get("avatar_group_list", [])
    if not groups:
        groups = resp.json().get("data", {}).get("list", [])  # fallback shape

    if not groups:
        print("No avatar groups found. Raw response:")
        print(resp.text[:500])
        client.close()
        return 1

    for g in groups:
        gid = g.get("id") or g.get("group_id") or g.get("avatar_group_id")
        name = g.get("name") or g.get("group_name") or "<unnamed>"
        gtype = g.get("group_type") or g.get("type") or "?"
        print(f"━━━ Group: {name}  (type={gtype})")
        print(f"    group_id: {gid}")

        # List looks in this group
        looks_resp = session.get(
            f"{base}/v2/avatar_group/{gid}/avatars", timeout=30,
        )
        if looks_resp.status_code != 200:
            print(f"    (failed to list looks: HTTP {looks_resp.status_code})\n")
            continue

        data = looks_resp.json().get("data", {})
        looks = (data.get("avatar_list")
                 or data.get("list")
                 or data.get("avatars")
                 or [])

        if not looks:
            print("    (no looks)\n")
            continue

        for look in looks:
            look_id = (look.get("avatar_id")
                       or look.get("talking_photo_id")
                       or look.get("id"))
            look_name = look.get("avatar_name") or look.get("name") or "<unnamed>"
            preview = look.get("preview_image_url") or look.get("image_url") or ""
            kind = ("talking_photo" if look.get("talking_photo_id")
                    else "avatar")
            print(f"      • {look_name:<30} [{kind}] id={look_id}")
            if preview:
                print(f"        preview: {preview}")
        print()

    print("─" * 60)
    print("Pick the IDs of the looks you want and add to .env:")
    print()
    print("    HEYGEN_AVATAR_IDS=id1,id2,id3")
    print()
    print("If your looks are 'talking_photo' type, also set in settings.yaml:")
    print("    heygen.character_type: \"talking_photo\"")

    client.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except HeyGenError as e:
        print(f"HeyGen error: {e}")
        sys.exit(1)
