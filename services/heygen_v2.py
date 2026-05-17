"""HeyGen V2 API client — Studio generation and Template API."""

import time

import requests

from config.settings import settings
from services.heygen_v3 import HeyGenError, HeyGenV3
from utils.logger import setup_logger

logger = setup_logger(__name__)


class HeyGenV2:
    """V2 API for Studio video generation and Template API."""

    def __init__(self):
        self._api_key = settings.get_required("heygen.api_key")
        self._base = settings.get("heygen.api_base_url", "https://api.heygen.com")
        self._v3 = HeyGenV3()

        self._session = requests.Session()
        self._session.headers.update({
            "accept": "application/json",
            "content-type": "application/json",
            "x-api-key": self._api_key,
        })

    # ─── STUDIO API ───

    def generate_video(self, video_inputs: list[dict], **kwargs) -> str:
        """
        POST /v2/video/generate — Studio API.

        Returns video_id.
        """
        payload = {
            "video_inputs": video_inputs,
            "test": kwargs.get("test_mode", False),
        }

        if kwargs.get("callback_url"):
            payload["callback_url"] = kwargs["callback_url"]

        if kwargs.get("dimension"):
            payload["dimension"] = kwargs["dimension"]
        else:
            ratio = kwargs.get("aspect_ratio", settings.get("heygen.video_ratio", "9:16"))
            if ratio == "9:16":
                payload["dimension"] = {"width": 1080, "height": 1920}
            elif ratio == "16:9":
                payload["dimension"] = {"width": 1920, "height": 1080}

        if kwargs.get("title"):
            payload["title"] = kwargs["title"]

        logger.info("Studio API: generating video with %d scenes", len(video_inputs))

        response = self._request_with_retry(
            "POST",
            f"{self._base}/v2/video/generate",
            json=payload,
        )

        data = response.json()
        video_id = data.get("data", {}).get("video_id")

        if not video_id:
            raise HeyGenError(f"No video_id in Studio response: {data}")

        logger.info("Studio video created: %s", video_id)
        return video_id

    def wait_for_video(self, video_id: str) -> str:
        """
        Wait for an already-created video to finish.
        Returns download URL.
        """
        logger.info("Waiting for video %s (timeout: %ds)...",
                     video_id, self._v3._poll_timeout)
        status_data = self._v3.wait_for_completion(video_id)

        download_url = status_data.get("video_url")
        if not download_url:
            raise HeyGenError(f"No download URL in status: {status_data}")

        logger.info("Video ready: %s", download_url)
        return download_url

    # ─── TEMPLATE API ───

    def generate_from_template(self, template_id: str, variables: dict, **kwargs) -> str:
        payload = {
            "variables": variables,
            "test": kwargs.get("test_mode", False),
        }

        if kwargs.get("callback_url"):
            payload["callback_url"] = kwargs["callback_url"]
        if kwargs.get("title"):
            payload["title"] = kwargs["title"]

        logger.info("Template API: generating from %s", template_id)

        response = self._request_with_retry(
            "POST",
            f"{self._base}/v2/template/{template_id}/generate",
            json=payload,
        )

        data = response.json()
        video_id = data.get("data", {}).get("video_id")

        if not video_id:
            raise HeyGenError(f"No video_id in template response: {data}")

        logger.info("Template video created: %s", video_id)
        return video_id

    # ─── SCENE BUILDERS ───

    VALID_AVATAR_STYLES = {"normal", "closeUp", "circle"}

    @staticmethod
    def build_scene(
        text: str,
        avatar_id: str,
        voice_id: str,
        voice_emotion: str | None = None,
        background_type: str = "color",
        background_value: str = "#000000",
        speed: float = 1.0,
        subtitle: bool = True,
        # framing
        avatar_style: str = "normal",
        scale: float = 1.0,
        offset: dict | None = None,
        matting: bool = False,
        circle_background_color: str | None = None,
        # Avatar IV (motion)
        use_avatar_iv: bool = False,
        motion_prompt: str | None = None,
        enhance_motion_prompt: bool = True,
        # talking photo only
        character_type: str = "avatar",
        talking_style: str | None = None,
        expression: str | None = None,
    ) -> dict:
        """
        Build a single HeyGen /v2/video/generate scene.

        Framing controls (avatar_style, scale, offset) are the ONLY way
        HeyGen exposes to vary camera framing — there is no real camera angle API.

        Avatar IV (use_avatar_iv=True + motion_prompt) is the path to
        AI-generated hand gestures on Photo / Instant avatars.
        """
        if avatar_style not in HeyGenV2.VALID_AVATAR_STYLES:
            raise ValueError(
                f"avatar_style must be one of {HeyGenV2.VALID_AVATAR_STYLES}, got {avatar_style!r}"
            )

        character: dict = {
            "type": character_type,
            "avatar_style": avatar_style,
            "scale": scale,
        }
        if character_type == "talking_photo":
            character["talking_photo_id"] = avatar_id
            if talking_style:
                character["talking_style"] = talking_style
        else:
            character["avatar_id"] = avatar_id

        if offset:
            character["offset"] = offset
        if matting:
            character["matting"] = True
        if circle_background_color and avatar_style == "circle":
            character["circle_background_color"] = circle_background_color
        if use_avatar_iv:
            character["use_avatar_iv_model"] = True
            if motion_prompt:
                character["custom_motion_prompt"] = motion_prompt
                character["enhance_custom_motion_prompt"] = enhance_motion_prompt
        if expression:
            character["expression"] = expression

        voice: dict = {
            "type": "text",
            "voice_id": voice_id,
            "input_text": text,
            "speed": speed,
        }
        if voice_emotion:
            voice["emotion"] = voice_emotion

        scene = {
            "character": character,
            "voice": voice,
            "background": {"type": background_type, "value": background_value},
        }

        if subtitle:
            scene["subtitle"] = {"enable": True, "position": "bottom"}

        return scene

    @staticmethod
    def build_talking_photo_scene(
        text: str,
        talking_photo_id: str,
        voice_id: str,
        talking_style: str = "expressive",
        voice_emotion: str | None = None,
        subtitle: bool = True,
        avatar_style: str = "normal",
        scale: float = 1.0,
        offset: dict | None = None,
        use_avatar_iv: bool = True,
        motion_prompt: str | None = None,
    ) -> dict:
        return HeyGenV2.build_scene(
            text=text,
            avatar_id=talking_photo_id,
            voice_id=voice_id,
            voice_emotion=voice_emotion,
            subtitle=subtitle,
            avatar_style=avatar_style,
            scale=scale,
            offset=offset,
            use_avatar_iv=use_avatar_iv,
            motion_prompt=motion_prompt,
            character_type="talking_photo",
            talking_style=talking_style,
        )

    # ─── EMOTION MAPPING ───

    @staticmethod
    def map_emotion(content_type: str) -> str:
        mapping = {
            "educational": "Serious",
            "marketing": "Excited",
            "news": "Serious",
            "motivational": "Excited",
            "meditation": "Soothing",
            "storytelling": "Friendly",
            "default": "Friendly",
        }
        return mapping.get(content_type, "Friendly")

    # ─── INTERNAL ───

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", settings.get("heygen.request_timeout_seconds", 30))
        max_retries = settings.get("heygen.max_retries", 3)
        retry_delay = settings.get("heygen.retry_delay_seconds", 5)
        last_error = None

        for attempt in range(max_retries):
            try:
                response = self._session.request(method, url, **kwargs)
                self._handle_http_error(response)
                return response

            except requests.exceptions.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response else None
                if status == 429:
                    retry_after = int(e.response.headers.get("Retry-After", retry_delay * 2))
                    logger.warning("Rate limited, waiting %ds", retry_after)
                    time.sleep(retry_after)
                elif status >= 500:
                    delay = retry_delay * (2 ** attempt)
                    logger.warning("Server %d, retry %d/%d", status, attempt + 1, max_retries)
                    time.sleep(delay)
                else:
                    raise HeyGenError(str(e), status_code=status)

            except requests.exceptions.SSLError as e:
                last_error = e
                delay = retry_delay * (2 ** attempt)
                logger.warning("SSLError, retry %d/%d", attempt + 1, max_retries)
                time.sleep(delay)

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_error = e
                delay = retry_delay * (2 ** attempt)
                logger.warning("%s, retry %d/%d", type(e).__name__, attempt + 1, max_retries)
                time.sleep(delay)

        raise HeyGenError(f"Max retries ({max_retries}) exceeded: {last_error}")

    @staticmethod
    def _handle_http_error(response: requests.Response):
        if response.status_code < 400:
            return
        error_map = {
            400: "invalid_parameter",
            401: "unauthorized",
            402: "insufficient_credit",
            403: "forbidden",
            404: "not_found",
            409: "conflict",
            429: "rate_limit_exceeded",
            500: "internal_error",
            504: "gateway_timeout",
        }
        code = error_map.get(response.status_code, "unknown")
        try:
            body = response.json()
            message = body.get("error", {}).get("message", body.get("message", str(body)))
        except Exception:
            message = response.text
        if response.status_code in (401, 402, 403, 400, 404, 409):
            raise HeyGenError(message, status_code=response.status_code, code=code)
        response.raise_for_status()

    def close(self):
        self._v3.close()
        self._session.close()
