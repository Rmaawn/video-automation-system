"""
Motion Director — picks framing + Avatar IV motion prompts per scene.

Why this exists: HeyGen has no real "camera angle" API. The only knobs are
`avatar_style` (normal/closeUp/circle) + `scale` + `offset`. Combined with
Avatar IV `custom_motion_prompt`, this module produces the variety the user
sees as different "shots" within a single video.

All framings and prompt pools are config-driven (settings.yaml). Choices are
deterministic per content_id (seeded RNG) so re-generating the same content
produces the same shot list — avoids drift between dry-run and real run.
"""

import hashlib
import random
from dataclasses import dataclass

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass(frozen=True)
class Framing:
    name: str
    avatar_style: str  # "normal" | "closeUp" | "circle"
    scale: float
    offset_x: float = 0.0
    offset_y: float = 0.0
    circle_background_color: str | None = None

    @property
    def offset(self) -> dict | None:
        if self.offset_x == 0 and self.offset_y == 0:
            return None
        return {"x": self.offset_x, "y": self.offset_y}


# Built-in framing presets. Overridable per-key in settings.yaml under
# `framings:`. Each preset maps to specific HeyGen character params.
#
# NOTE: offsets are kept at 0 by default. Non-zero offsets push the avatar
# off-center and frequently cause "avatar in the corner" framing for
# portrait (9:16) Photo Avatars whose source image is already cropped.
# Variety here comes from avatar_style (normal/closeUp/circle) + scale.
DEFAULT_FRAMINGS: dict[str, dict] = {
    "wide":     {"avatar_style": "normal",  "scale": 0.90},
    "medium":   {"avatar_style": "normal",  "scale": 1.00},
    "close":    {"avatar_style": "closeUp", "scale": 1.00},
    "tight":    {"avatar_style": "closeUp", "scale": 1.20},
    "circle":   {"avatar_style": "circle",  "scale": 1.00,
                 "circle_background_color": "#1a1a2e"},
}

# Built-in motion prompt pool, keyed by intent. Used round-robin per video
# (seeded) so a single video doesn't repeat the same gesture twice.
DEFAULT_MOTION_PROMPTS: dict[str, list[str]] = {
    "opening": [
        "Avatar looks confidently at the camera with a subtle welcoming nod.",
        "Avatar takes a small breath and opens both hands naturally to begin.",
        "Avatar greets with a small smile and a slight head tilt.",
    ],
    "calm": [
        "Avatar maintains a relaxed posture with subtle hand movements.",
        "Avatar speaks gently, hands resting near chest area.",
        "Avatar nods slowly while explaining, hands moving softly.",
    ],
    "emphasis": [
        "Right hand gestures outward to emphasize the key point.",
        "Both hands move forward to highlight the importance.",
        "Avatar raises eyebrows slightly and opens one hand to stress the idea.",
        "Avatar leans in subtly and gestures with the right hand for emphasis.",
    ],
    "excited": [
        "Avatar gestures enthusiastically with both hands open wide.",
        "Right hand raises in an energetic explanatory motion.",
        "Avatar smiles broadly while both hands animate excitement.",
    ],
    "question": [
        "Avatar tilts head with a curious expression, both hands open in inquiry.",
        "Avatar raises one eyebrow and opens a hand questioningly.",
    ],
    "transition": [
        "Avatar pauses briefly, then opens a hand to introduce the next idea.",
        "Avatar nods and gestures sideways to transition to the next point.",
    ],
    "closing": [
        "Avatar smiles warmly while bringing hands together in a closing gesture.",
        "Avatar concludes with a gentle nod and a confident look at the camera.",
        "Avatar takes a soft breath, places hands down, and ends with a smile.",
    ],
}


# Maps the legacy variation labels emitted by SceneBuilder onto framing keys.
# Keeps SceneBuilder semantics ("close" = intimate shot, "wide" = pulled back)
# while routing them through real HeyGen params.
VARIATION_TO_FRAMING: dict[str, str] = {
    "wide":      "wide",
    "medium":    "medium",
    "close":     "close",
    "emphasize": "tight",
    "pause":     "circle",
}


# Emotion → motion intent. Used when no explicit intent is provided.
EMOTION_TO_INTENT: dict[str, str] = {
    "Excited":     "excited",
    "Friendly":    "calm",
    "Serious":     "emphasis",
    "Soothing":    "calm",
    "Broadcaster": "emphasis",
}


class MotionDirector:
    """
    Produces (Framing, motion_prompt) tuples per scene.

    Deterministic per `seed` (typically content_id or video title) so the same
    content always yields the same shot list.
    """

    def __init__(self, seed: str | int | None = None):
        self._framings = self._load_framings()
        self._prompts = self._load_prompts()
        self._enabled = settings.get("heygen.use_avatar_iv", True)

        seed_int = self._seed_to_int(seed) if seed is not None else None
        self._rng = random.Random(seed_int)
        self._used_prompts: dict[str, set[str]] = {}

    # ─── PUBLIC ───

    def shot_for(
        self,
        index: int,
        total: int,
        variation: str,
        emotion: str,
        is_first: bool = False,
        is_last: bool = False,
    ) -> tuple[Framing, str | None]:
        framing = self._pick_framing(variation, index)
        if not self._enabled:
            return framing, None

        intent = self._pick_intent(is_first, is_last, variation, emotion)
        prompt = self._pick_prompt(intent)
        return framing, prompt

    # ─── INTERNAL ───

    def _pick_framing(self, variation: str, index: int) -> Framing:
        key = VARIATION_TO_FRAMING.get(variation, "medium")
        params = self._framings.get(key)
        if params is None:
            logger.warning("Framing %r missing in config — falling back to 'medium'", key)
            params = self._framings.get("medium", DEFAULT_FRAMINGS["medium"])
        return Framing(name=key, **params)

    def _pick_intent(
        self, is_first: bool, is_last: bool, variation: str, emotion: str,
    ) -> str:
        if is_first:
            return "opening"
        if is_last:
            return "closing"
        if variation == "pause":
            return "transition"
        if variation == "emphasize":
            return "emphasis"
        return EMOTION_TO_INTENT.get(emotion, "calm")

    def _pick_prompt(self, intent: str) -> str | None:
        pool = self._prompts.get(intent) or self._prompts.get("calm") or []
        if not pool:
            return None

        used = self._used_prompts.setdefault(intent, set())
        available = [p for p in pool if p not in used]
        if not available:
            used.clear()
            available = pool

        choice = self._rng.choice(available)
        used.add(choice)
        return choice

    def _load_framings(self) -> dict[str, dict]:
        user = settings.get("framings", {}) or {}
        merged = {**DEFAULT_FRAMINGS}
        for key, params in user.items():
            if isinstance(params, dict):
                merged[key] = {**DEFAULT_FRAMINGS.get(key, {}), **params}
        return merged

    def _load_prompts(self) -> dict[str, list[str]]:
        user = settings.get("motion_prompts", {}) or {}
        merged = {k: list(v) for k, v in DEFAULT_MOTION_PROMPTS.items()}
        for key, pool in user.items():
            if isinstance(pool, list) and pool:
                merged[key] = list(pool)
        return merged

    @staticmethod
    def _seed_to_int(seed: str | int) -> int:
        if isinstance(seed, int):
            return seed
        return int(hashlib.sha256(str(seed).encode()).hexdigest()[:16], 16)
