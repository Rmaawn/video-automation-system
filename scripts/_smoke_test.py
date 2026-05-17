"""Internal smoke test (no API calls). Run: python scripts/_smoke_test.py"""
import io
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("HEYGEN_API_KEY", "dummy")
os.environ.setdefault("HEYGEN_AVATAR_ID", "avatar-x")
os.environ.setdefault("HEYGEN_VOICE_ID", "voice-y")

from core.scene_builder import SceneBuilder

text = (
    "سلام رفقا. امروز می‌خوام درباره یه نکته خیلی مهم باهاتون صحبت کنم که شاید زندگیتون رو تغییر بده.\n"
    "این موضوع شاید ساده به نظر برسه اما در واقع کلید موفقیت محسوب میشه و خیلی ها از کنارش رد میشن.\n\n"
    "اولین قدم اینه که تو ذهنت یه تصویر واضح بسازی از چیزی که می‌خوای بهش برسی.\n"
    "دومین قدم تعهد روزانه است که بدون اون هیچ تصویری به واقعیت تبدیل نمیشه.\n\n"
    "سومین قدم اینه که از اشتباهاتت یاد بگیری و اون‌ها رو فرصت ببینی نه شکست.\n"
    "چهارمین قدم صبر و پشتکاره چون نتایج بزرگ معمولا زود به دست نمیان.\n\n"
    "پس از فردا شروع کن و عقب نشینی نکن. این رو فراموش نکن که هر روزت یه فرصت تازه است."
)

seq = SceneBuilder().build(text)
scenes = seq.to_studio_scenes("avatar-x", "voice-y", seed="test/ch1/sec1")
print(f"Total scenes: {len(scenes)}")
for i, s in enumerate(scenes):
    c = s["character"]
    style = c["avatar_style"]
    scale = c["scale"]
    iv = c.get("use_avatar_iv_model", False)
    prompt = (c.get("custom_motion_prompt") or "")[:60]
    offset = c.get("offset")
    print(f"[{i}] style={style:8s} scale={scale:.2f} offset={offset} iv={iv}")
    print(f"     prompt={prompt}")
    print(f"     emotion={s['voice'].get('emotion')}")
    print(f"     text={s['voice']['input_text'][:60]}...")

scenes2 = SceneBuilder().build(text).to_studio_scenes(
    "avatar-x", "voice-y", seed="test/ch1/sec1",
)
same = all(
    a["character"].get("custom_motion_prompt") == b["character"].get("custom_motion_prompt")
    for a, b in zip(scenes, scenes2)
)
print(f"\nDeterminism (same seed -> same prompts): {same}")

scenes3 = SceneBuilder().build(text).to_studio_scenes(
    "avatar-x", "voice-y", seed="different/seed",
)
diff = any(
    a["character"].get("custom_motion_prompt") != b["character"].get("custom_motion_prompt")
    for a, b in zip(scenes, scenes3)
)
print(f"Variety (different seed -> different prompts): {diff}")
