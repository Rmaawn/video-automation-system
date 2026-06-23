#!/usr/bin/env python3
"""
سازندهٔ ریلِ ۳ صحنه‌ای — هر تکه متن روی یک آواتار مشخص، به ترتیب.

طرز کار
-------
۱) متن‌هایت را در فایل  data/content/reel.json  بگذار (آرایهٔ "scenes").
   - تکهٔ اول  → آواتار شمارهٔ ۱ (اولین id در HEYGEN_AVATAR_IDS)
   - تکهٔ دوم  → آواتار شمارهٔ ۲
   - تکهٔ سوم  → آواتار شمارهٔ ۳
   هر تکه دقیقاً یک صحنه می‌شود (بدون شکستن/ادغام خودکار).

۲) اجرا:
       python make_reel.py            # حالت تست (واترمارک، بدونِ مصرف کردیت)
       python make_reel.py --real     # ویدیوی واقعیِ آمادهٔ اینستاگرام (کردیت مصرف می‌شود)
       python make_reel.py --dry       # فقط payload را چاپ کن، هیچ درخواستی نفرست

خروجی: ویدیوی عمودی ۱۰۸۰x۱۹۲۰، با زیرنویسِ روشن، در پوشهٔ output/videos.
ترنزیشنِ نرم لازم نیست؛ کاتِ بین سه آواتار + تغییرِ قابِ هر صحنه نقشِ برش را دارد.
"""

import argparse
import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

# روی کنسولِ ویندوز، چاپِ فارسی با codec پیش‌فرض (cp1252) کرش می‌کند.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

from config.settings import settings
from core.scene_builder import Scene, SceneBuilder, SceneSequence
from services.heygen_v2 import HeyGenError, HeyGenV2
from core.video_manager import VideoManager

# هر صحنه یک قابِ متفاوت می‌گیرد تا کاتِ بین آواتارها دیده شود.
FRAMING_CYCLE = ["medium", "close", "wide", "emphasize"]


def _normalize_fa(text: str) -> str:
    """فقط حروفِ عربیِ رایج را به فارسی استاندارد تبدیل می‌کند؛ متن دست‌نخورده می‌ماند."""
    return (
        text.replace("ك", "ک")  # ك → ک
            .replace("ي", "ی")  # ي → ی
            .replace("ى", "ی")  # ى → ی
            .strip()
    )


def load_scenes(path: Path) -> tuple[str, list[str]]:
    if not path.exists():
        raise FileNotFoundError(f"فایل پیدا نشد: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    title = str(data.get("title", "reel")).strip() or "reel"
    raw_scenes = data.get("scenes", [])
    texts = [_normalize_fa(str(t)) for t in raw_scenes if str(t).strip()]
    if not texts:
        raise ValueError(f"هیچ متنی در {path} نیست. آرایهٔ \"scenes\" را پر کن.")
    return title, texts


def build_sequence(texts: list[str]) -> SceneSequence:
    """یک صحنه به ازای هر تکه متن — بدون شکستن یا ادغام."""
    scenes = []
    for i, text in enumerate(texts):
        scenes.append(Scene(
            index=i,
            text=text,
            variation=FRAMING_CYCLE[i % len(FRAMING_CYCLE)],
            emotion="Friendly",
            duration_estimate=SceneBuilder._estimate_duration(text),
        ))
    return SceneSequence(scenes=scenes)


def main() -> int:
    parser = argparse.ArgumentParser(description="سازندهٔ ریلِ ۳ صحنه‌ای (هر تکه روی یک آواتار)")
    parser.add_argument("--real", action="store_true",
                        help="ویدیوی واقعیِ بدون واترمارک (کردیت مصرف می‌شود)")
    parser.add_argument("--dry", action="store_true",
                        help="فقط payload را چاپ کن؛ هیچ درخواستی به HeyGen نفرست")
    parser.add_argument("--file", default=None,
                        help="مسیرِ فایل json متن‌ها (پیش‌فرض: data/content/reel.json)")
    args = parser.parse_args()

    data_dir = PROJECT_ROOT / settings.get("app.data_dir", "data/content")
    reel_path = Path(args.file) if args.file else (data_dir / "reel.json")

    title, texts = load_scenes(reel_path)
    avatar_pool = settings.get_avatar_pool()
    voice_id = settings.get_required("heygen.voice_id")
    character_type = settings.get("heygen.character_type", "avatar")

    print("=" * 56)
    print(f"عنوان       : {title}")
    print(f"تعداد متن    : {len(texts)} تکه")
    print(f"تعداد آواتار : {len(avatar_pool)}")
    if len(texts) > len(avatar_pool):
        print(f"⚠ متن‌ها بیشتر از آواتارهاست؛ آواتارها دوباره از اول تکرار می‌شوند.")
    for i, t in enumerate(texts):
        a = avatar_pool[i % len(avatar_pool)]
        print(f"  صحنه {i + 1} → آواتار {a[:8]}…  «{t[:40]}…»")
    print("=" * 56)

    sequence = build_sequence(texts)
    studio_scenes = sequence.to_studio_scenes(
        avatar_pool, voice_id,
        character_type=character_type,
        seed=title,
    )

    test_mode = not args.real  # پیش‌فرض: تست (امن، بدونِ کردیت). با --real واقعی می‌شود.

    if args.dry:
        payload = {
            "title": title,
            "dimension": HeyGenV2.ASPECT_RATIOS["9:16"],
            "caption": settings.get("heygen.caption", True),
            "test": test_mode,
            "video_inputs": studio_scenes,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        print(f"\n[DRY-RUN] هیچ درخواستی فرستاده نشد. test={test_mode}")
        return 0

    if test_mode:
        print("» حالتِ تست: ویدیو واترمارک دارد و کردیت مصرف نمی‌شود.")
        print("  برای نسخهٔ واقعیِ آمادهٔ اینستاگرام دوباره با  --real  اجرا کن.")
    else:
        print("» حالتِ واقعی: ویدیوی بدونِ واترمارک ساخته می‌شود و کردیت مصرف می‌شود.")

    client = HeyGenV2()
    try:
        video_id = client.generate_video(
            studio_scenes,
            test_mode=test_mode,
            aspect_ratio="9:16",
            title=title,
        )
        print(f"HeyGen video_id: {video_id}  (در حال رندر…)")

        download_url = client.wait_for_video(video_id)

        vm = VideoManager()
        filename = vm.generate_filename(title, "reel", str(len(texts)))
        file_path = vm.download_video(download_url, filename)

        print(f"\n✓ ذخیره شد: {file_path}")
        return 0
    except HeyGenError as e:
        print(f"\n✗ خطای HeyGen: {e}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
