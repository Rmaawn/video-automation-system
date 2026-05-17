"""Scene builder — composes Studio API scenes with variation and emotion mapping."""

import re
from dataclasses import dataclass, field

from config.settings import settings
from core.motion_director import MotionDirector
from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class Scene:
    index: int
    text: str
    variation: str = "medium"
    emotion: str = "Friendly"
    duration_estimate: float = 0.0

    @property
    def is_pause(self) -> bool:
        return self.variation == "pause"


@dataclass
class SceneSequence:
    scenes: list[Scene] = field(default_factory=list)

    @property
    def total_scenes(self) -> int:
        return len(self.scenes)

    @property
    def estimated_duration(self) -> float:
        return sum(s.duration_estimate for s in self.scenes)

    def to_studio_scenes(
        self,
        avatar_id: str,
        voice_id: str,
        subtitle: bool = True,
        character_type: str = "avatar",
        seed: str | int | None = None,
    ) -> list[dict]:
        """Convert to HeyGen V2 Studio API video_inputs format.

        Framing (avatar_style/scale/offset) and Avatar IV motion prompts
        are produced by MotionDirector per scene.
        """
        from services.heygen_v2 import HeyGenV2

        director = MotionDirector(seed=seed)
        bg_type = settings.get("heygen.background.type", "color")
        bg_value = settings.get("heygen.background.value", "#0a0a0a")
        matting = settings.get("heygen.matting", False)
        enhance = settings.get("heygen.enhance_motion_prompt", True)
        use_iv = settings.get("heygen.use_avatar_iv", True)
        talking_style = settings.get("heygen.talking_style")  # for talking_photo

        result = []
        total = len(self.scenes)

        for i, scene in enumerate(self.scenes):
            is_first = (i == 0)
            is_last = (i == total - 1)
            framing, motion_prompt = director.shot_for(
                index=i,
                total=total,
                variation=scene.variation,
                emotion=scene.emotion,
                is_first=is_first,
                is_last=is_last,
            )

            studio_scene = HeyGenV2.build_scene(
                text=scene.text,
                avatar_id=avatar_id,
                voice_id=voice_id,
                voice_emotion=scene.emotion,
                background_type=bg_type,
                background_value=bg_value,
                subtitle=subtitle,
                avatar_style=framing.avatar_style,
                scale=framing.scale,
                offset=framing.offset,
                matting=matting,
                circle_background_color=framing.circle_background_color,
                use_avatar_iv=use_iv,
                motion_prompt=motion_prompt,
                enhance_motion_prompt=enhance,
                character_type=character_type,
                talking_style=talking_style,
            )
            result.append(studio_scene)

        return result

    def to_scene_dicts(self) -> list[dict]:
        return [
            {
                "index": s.index,
                "text": s.text,
                "variation": s.variation,
                "emotion": s.emotion,
                "duration_estimate": s.duration_estimate,
            }
            for s in self.scenes
        ]


class SceneBuilder:
    """Splits processed script into varied Studio API scenes."""

    VARIATION_PATTERNS = [
        {"position": "first", "variations": ["wide", "medium"]},
        {"position": "middle", "variations": ["close", "medium", "emphasize"]},
        {"position": "pre_pause", "variations": ["emphasize", "close"]},
        {"position": "post_pause", "variations": ["wide", "medium"]},
        {"position": "last", "variations": ["close", "medium"]},
    ]

    EMOTION_MAP = {
        "educational": "Serious",
        "marketing": "Excited",
        "motivational": "Excited",
        "meditation": "Soothing",
        "storytelling": "Friendly",
        "default": "Friendly",
    }

    def __init__(self):
        self._max_len = settings.get("scenes.max_scene_length_chars", 500)
        self._min_len = settings.get("scenes.min_scene_length_chars", 80)
        self._max_scenes = settings.get("scenes.max_scenes_per_video", 8)
        self._min_scenes = settings.get("scenes.min_scenes_per_video", 2)
        self._content_type = settings.get("scenes.content_type", "storytelling")

    def build(self, processed_text: str) -> SceneSequence:
        segments = self._segment_text(processed_text)
        scenes = self._assign_attributes(segments)
        scenes = self._merge_short(scenes)
        scenes = self._enforce_limits(scenes)
        return SceneSequence(scenes=scenes)

    def _segment_text(self, text: str) -> list[str]:
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        final = []
        for seg in lines:
            if len(seg) <= self._max_len:
                final.append(seg)
            else:
                final.extend(self._split_at_sentences(seg))
        return final

    def _split_at_sentences(self, text: str) -> list[str]:
        pattern = r"(?<=[.!?؟۔۔])\s+"
        sentences = re.split(pattern, text)
        result = []
        buffer = ""

        for s in sentences:
            s = s.strip()
            if not s:
                continue
            if len(buffer) + len(s) <= self._max_len:
                buffer = buffer + (" " if buffer else "") + s
            else:
                if buffer:
                    result.append(buffer)
                buffer = s

        if buffer:
            result.append(buffer)

        return result if result else [text]

    def _assign_attributes(self, segments: list[str]) -> list[Scene]:
        scenes = []
        cycle = 0
        last_pause = False
        base_emotion = self.EMOTION_MAP.get(self._content_type, "Friendly")

        for i, seg in enumerate(segments):
            is_first = i == 0
            is_last = i == len(segments) - 1
            has_pause = "..." in seg
            is_pause = seg.strip() == "..."

            if is_pause:
                var = "pause"
                emotion = base_emotion
                last_pause = True
            elif is_first:
                var = self._get_variation("first", cycle)
                emotion = base_emotion
                last_pause = False
            elif is_last:
                var = self._get_variation("last", cycle)
                emotion = base_emotion
                last_pause = False
            elif last_pause:
                var = self._get_variation("post_pause", cycle)
                emotion = "Excited"
                last_pause = False
            elif has_pause:
                var = self._get_variation("pre_pause", cycle)
                emotion = "Serious"
                last_pause = False
            else:
                var = self._get_variation("middle", cycle)
                emotion = base_emotion

            clean = seg.replace("...", "")
            duration = max(2.0, len(clean) / 15)

            scenes.append(Scene(
                index=i,
                text=seg,
                variation=var,
                emotion=emotion,
                duration_estimate=round(duration, 1),
            ))

            if not is_pause:
                cycle += 1

        return scenes

    def _get_variation(self, position: str, cycle: int) -> str:
        for p in self.VARIATION_PATTERNS:
            if p["position"] == position:
                return p["variations"][cycle % len(p["variations"])]
        return "medium"

    def _merge_short(self, scenes: list[Scene]) -> list[Scene]:
        if len(scenes) <= self._min_scenes:
            return scenes

        merged = []
        buffer = None

        for scene in scenes:
            if scene.is_pause:
                if buffer:
                    merged.append(buffer)
                    buffer = None
                merged.append(scene)
                continue

            if buffer and len(buffer.text) + len(scene.text) <= self._max_len:
                buffer.text = buffer.text + " " + scene.text
                buffer.duration_estimate += scene.duration_estimate
                if scene.variation in ("close", "emphasize"):
                    buffer.variation = scene.variation
            else:
                if buffer:
                    merged.append(buffer)
                buffer = Scene(
                    index=len(merged),
                    text=scene.text,
                    variation=scene.variation,
                    emotion=scene.emotion,
                    duration_estimate=scene.duration_estimate,
                )

        if buffer:
            merged.append(buffer)

        for i, s in enumerate(merged):
            s.index = i

        return merged

    def _enforce_limits(self, scenes: list[Scene]) -> list[Scene]:
        if len(scenes) <= self._max_scenes:
            return scenes

        while len(scenes) > self._max_scenes:
            for i in range(len(scenes) - 1, 0, -1):
                if not scenes[i].is_pause and not scenes[i - 1].is_pause:
                    scenes[i - 1].text += " " + scenes[i].text
                    scenes[i - 1].duration_estimate += scenes[i].duration_estimate
                    scenes.pop(i)
                    break
            else:
                break

        for i, s in enumerate(scenes):
            s.index = i

        return scenes
