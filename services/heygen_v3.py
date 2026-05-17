"""HeyGen V3 API client — status polling, avatars, voices, webhooks."""

import hashlib
import time
from pathlib import Path

import requests

from config.settings import settings
from models.database import asset_repo
from utils.logger import setup_logger

logger = setup_logger(__name__)

ALLOWED_MIME_TYPES = {
    "image/png": "png",
    "image/jpeg": "jpeg",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "application/pdf": "pdf",
}
MAX_ASSET_SIZE = 32 * 1024 * 1024


class HeyGenError(Exception):
    def __init__(self, message: str, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


class HeyGenV3:
    def __init__(self):
        self._api_key = settings.get_required("heygen.api_key")
        self._base = settings.get("heygen.api_base_url", "https://api.heygen.com")
        self._max_retries = settings.get("heygen.max_retries", 3)
        self._retry_delay = settings.get("heygen.retry_delay_seconds", 5)
        self._timeout = settings.get("heygen.request_timeout_seconds", 30)
        self._poll_interval = settings.get("heygen.polling_interval_seconds", 15)
        self._poll_timeout = settings.get("heygen.polling_timeout_seconds", 600)

        self._session = requests.Session()
        self._session.headers.update({
            "accept": "application/json",
            "x-api-key": self._api_key,
        })

    # ─── VIDEO STATUS ───

    def get_video_status(self, video_id: str) -> dict:
        """Check video status via HeyGen's GET /v1/video_status.get."""
        url = f"{self._base}/v1/video_status.get"
        response = self._request_with_retry(
            "GET", url, params={"video_id": video_id},
        )
        return response.json().get("data", {})

    def wait_for_completion(self, video_id: str) -> dict:
        start = time.time()
        while True:
            elapsed = time.time() - start
            if elapsed > self._poll_timeout:
                raise HeyGenError(f"Video {video_id} timed out after {self._poll_timeout}s")

            status_data = self.get_video_status(video_id)
            status = status_data.get("status", "unknown")
            logger.debug("Video %s status: %s (%.0fs)", video_id, status, elapsed)

            if status in ("completed", "success"):
                return status_data
            elif status == "failed":
                error = status_data.get("error", "Unknown error")
                raise HeyGenError(f"Video generation failed: {error}")
            else:
                time.sleep(self._poll_interval)

    # ─── ASSETS ───

    def upload_asset(self, file_path: str) -> str:
        path = Path(file_path)
        if not path.exists():
            raise HeyGenError(f"File not found: {file_path}")

        size = path.stat().st_size
        if size > MAX_ASSET_SIZE:
            raise HeyGenError(f"File too large: {size} bytes (max {MAX_ASSET_SIZE})")

        checksum = self._sha256(file_path)
        existing = asset_repo.get_by_checksum(checksum)
        if existing and existing.get("asset_id"):
            logger.info("Asset already uploaded: %s", existing["asset_id"])
            return existing["asset_id"]

        mime = self._detect_mime(path)
        if mime not in ALLOWED_MIME_TYPES:
            raise HeyGenError(f"Unsupported file type: {path.suffix}")

        db_id = asset_repo.create(str(path), path.name, mime, size, checksum)

        with open(file_path, "rb") as f:
            files = {"file": (path.name, f, mime)}
            response = self._request_with_retry(
                "POST", f"{self._base}/v3/assets", files=files,
            )

        data = response.json()
        asset_id = data.get("data", {}).get("asset_id")
        if not asset_id:
            asset_repo.mark_failed(db_id, str(data))
            raise HeyGenError(f"No asset_id in response: {data}")

        asset_repo.update_asset_id(db_id, asset_id)
        logger.info("Asset uploaded: %s", asset_id)
        return asset_id

    # ─── AVATARS ───

    def list_avatars(self) -> list[dict]:
        response = self._request_with_retry("GET", f"{self._base}/v3/avatars")
        return response.json().get("data", {}).get("list", [])

    def get_avatar(self, avatar_id: str) -> dict:
        response = self._request_with_retry("GET", f"{self._base}/v3/avatars/{avatar_id}")
        return response.json().get("data", {})

    # ─── VOICES ───

    def list_voices(self) -> list[dict]:
        response = self._request_with_retry("GET", f"{self._base}/v3/voices")
        return response.json().get("data", {}).get("list", [])

    # ─── WEBHOOKS ───

    def create_webhook(self, callback_url: str, events: list[str] | None = None) -> dict:
        if events is None:
            events = ["video.completed", "video.failed"]
        response = self._request_with_retry(
            "POST", f"{self._base}/v3/webhooks",
            json={"callback_url": callback_url, "events": events},
        )
        return response.json().get("data", {})

    # ─── CREDITS ───

    def get_credits(self) -> dict:
        response = self._request_with_retry("GET", f"{self._base}/v3/user/credits")
        return response.json().get("data", {})

    # ─── INTERNAL ───

    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self._timeout)
        last_error = None

        for attempt in range(self._max_retries):
            try:
                response = self._session.request(method, url, **kwargs)
                self._handle_http_error(response)
                return response

            except requests.exceptions.HTTPError as e:
                last_error = e
                status = e.response.status_code if e.response else None
                if status == 429:
                    retry_after = int(e.response.headers.get("Retry-After", self._retry_delay * 2))
                    logger.warning("Rate limited, waiting %ds", retry_after)
                    time.sleep(retry_after)
                elif status >= 500:
                    delay = self._retry_delay * (2 ** attempt)
                    logger.warning("Server %d, retry %d/%d (%ds)", status, attempt + 1, self._max_retries, delay)
                    time.sleep(delay)
                else:
                    code = None
                    try:
                        code = e.response.json().get("code")
                    except Exception:
                        pass
                    raise HeyGenError(str(e), status_code=status, code=code)

            except requests.exceptions.SSLError as e:
                last_error = e
                delay = self._retry_delay * (2 ** attempt)
                logger.warning("SSLError, retry %d/%d (%ds)", attempt + 1, self._max_retries, delay)
                time.sleep(delay)

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                last_error = e
                delay = self._retry_delay * (2 ** attempt)
                logger.warning("%s, retry %d/%d (%ds)", type(e).__name__, attempt + 1, self._max_retries, delay)
                time.sleep(delay)

        raise HeyGenError(f"Max retries ({self._max_retries}) exceeded: {last_error}")

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

    @staticmethod
    def _sha256(file_path: str) -> str:
        h = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _detect_mime(path: Path) -> str:
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".mp4": "video/mp4",
            ".webm": "video/webm",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".pdf": "application/pdf",
        }
        return mime_map.get(path.suffix.lower(), "application/octet-stream")

    def close(self):
        self._session.close()
