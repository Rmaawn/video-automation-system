"""Database layer with full HeyGen production schema."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger(__name__)


class Database:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        db_path = settings.get("app.db_path", "output/video_automation.db")
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self.get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS books (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    language TEXT DEFAULT 'fa',
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS contents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    chapter TEXT NOT NULL,
                    section TEXT NOT NULL,
                    text TEXT NOT NULL,
                    processed_text TEXT,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'processing', 'done', 'failed')),
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (book_id) REFERENCES books(id),
                    UNIQUE(book_id, chapter, section)
                );

                CREATE TABLE IF NOT EXISTS videos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id INTEGER NOT NULL,
                    heygen_video_id TEXT,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('queued', 'pending', 'processing', 'completed', 'failed')),
                    file_path TEXT,
                    download_url TEXT,
                    duration_seconds REAL,
                    credits_used REAL,
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (content_id) REFERENCES contents(id)
                );

                CREATE TABLE IF NOT EXISTS video_scenes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id INTEGER NOT NULL,
                    scene_index INTEGER NOT NULL,
                    avatar_id TEXT,
                    voice_id TEXT,
                    voice_emotion TEXT,
                    script TEXT NOT NULL,
                    background_type TEXT DEFAULT 'color',
                    background_value TEXT,
                    duration_estimate REAL,
                    subtitle_enabled INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (video_id) REFERENCES videos(id)
                );

                CREATE TABLE IF NOT EXISTS assets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    asset_id TEXT UNIQUE,
                    local_path TEXT,
                    original_filename TEXT,
                    mime_type TEXT,
                    size_bytes INTEGER,
                    checksum TEXT,
                    status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'uploaded', 'failed')),
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    template_id TEXT NOT NULL,
                    name TEXT,
                    category TEXT DEFAULT 'general',
                    aspect_ratio TEXT DEFAULT '9:16',
                    variables_schema TEXT,
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT DEFAULT (datetime('now'))
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_type TEXT NOT NULL,
                    status TEXT DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'completed', 'failed')),
                    payload TEXT,
                    result TEXT,
                    retries INTEGER DEFAULT 0,
                    error_message TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_contents_status ON contents(status);
                CREATE INDEX IF NOT EXISTS idx_contents_book ON contents(book_id);
                CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
                CREATE INDEX IF NOT EXISTS idx_videos_content ON videos(content_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            """)
        logger.info("Database initialized: %s", self._db_path)

    def ensure_book(self, book_id: str, title: str | None = None, language: str = "fa"):
        with self.get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO books (id, title, language) VALUES (?, ?, ?)",
                (book_id, title or book_id, language),
            )


class ContentRepository:
    def __init__(self, db: Database):
        self._db = db

    def add(self, book_id: str, chapter: str, section: str, text: str) -> tuple[int, bool]:
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO contents (book_id, chapter, section, text) VALUES (?, ?, ?, ?)",
                (book_id, chapter, section, text),
            )
            if cursor.rowcount == 0:
                row = conn.execute(
                    "SELECT id FROM contents WHERE book_id=? AND chapter=? AND section=?",
                    (book_id, chapter, section),
                ).fetchone()
                return row["id"], False
            return cursor.lastrowid, True

    def upsert(self, book_id: str, chapter: str, section: str, text: str) -> tuple[int, str]:
        """
        Insert or update a section.

        Returns (content_id, action) where action is one of:
          - "added"     section was new
          - "updated"   text changed → text replaced and status reset to pending
                        (only if previous status was done/failed; in-flight rows
                        are left alone to avoid breaking active runs)
          - "unchanged" text identical to what's in DB
        """
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT id, text, status FROM contents WHERE book_id=? AND chapter=? AND section=?",
                (book_id, chapter, section),
            ).fetchone()

            if row is None:
                cursor = conn.execute(
                    "INSERT INTO contents (book_id, chapter, section, text) VALUES (?, ?, ?, ?)",
                    (book_id, chapter, section, text),
                )
                return cursor.lastrowid, "added"

            if row["text"] == text:
                return row["id"], "unchanged"

            if row["status"] in ("pending", "processing"):
                conn.execute(
                    "UPDATE contents SET text=?, updated_at=datetime('now') WHERE id=?",
                    (text, row["id"]),
                )
                return row["id"], "updated"

            conn.execute(
                """UPDATE contents SET text=?, processed_text=NULL, status='pending',
                   retry_count=0, error_message=NULL, updated_at=datetime('now') WHERE id=?""",
                (text, row["id"]),
            )
            return row["id"], "updated"

    def reset_pending(self, content_id: int):
        """Force a content row back to pending status (for ops/admin)."""
        with self._db.get_connection() as conn:
            conn.execute(
                """UPDATE contents SET status='pending', retry_count=0,
                   error_message=NULL, updated_at=datetime('now') WHERE id=?""",
                (content_id,),
            )

    def get_next_pending(self, book_id: str | None = None) -> dict | None:
        with self._db.get_connection() as conn:
            if book_id:
                row = conn.execute(
                    "SELECT * FROM contents WHERE book_id=? AND status='pending' ORDER BY created_at LIMIT 1",
                    (book_id,),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM contents WHERE status='pending' ORDER BY created_at LIMIT 1",
                ).fetchone()
        if not row:
            return None
        return dict(row)

    def get_pending(self, book_id: str | None = None) -> list[dict]:
        with self._db.get_connection() as conn:
            if book_id:
                rows = conn.execute(
                    "SELECT * FROM contents WHERE book_id=? AND status='pending' ORDER BY created_at",
                    (book_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM contents WHERE status='pending' ORDER BY created_at",
                ).fetchall()
        return [dict(r) for r in rows]

    def get_by_id(self, content_id: int) -> dict | None:
        with self._db.get_connection() as conn:
            row = conn.execute("SELECT * FROM contents WHERE id=?", (content_id,)).fetchone()
        return dict(row) if row else None

    def update_status(self, content_id: int, status: str, error_message: str | None = None):
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE contents SET status=?, error_message=?, updated_at=datetime('now') WHERE id=?",
                (status, error_message, content_id),
            )

    def update_processed_text(self, content_id: int, processed_text: str):
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE contents SET processed_text=?, updated_at=datetime('now') WHERE id=?",
                (processed_text, content_id),
            )

    def increment_retry(self, content_id: int) -> int:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE contents SET retry_count=retry_count+1, updated_at=datetime('now') WHERE id=?",
                (content_id,),
            )
            row = conn.execute("SELECT retry_count FROM contents WHERE id=?", (content_id,)).fetchone()
            return row["retry_count"]

    def get_all(self, book_id: str | None = None) -> list[dict]:
        with self._db.get_connection() as conn:
            if book_id:
                rows = conn.execute(
                    "SELECT * FROM contents WHERE book_id=? ORDER BY chapter, section",
                    (book_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM contents ORDER BY book_id, chapter, section",
                ).fetchall()
        return [dict(r) for r in rows]


class VideoRepository:
    def __init__(self, db: Database):
        self._db = db

    def create(self, content_id: int) -> int:
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO videos (content_id) VALUES (?)", (content_id,),
            )
            return cursor.lastrowid

    def update_heygen_id(self, video_id: int, heygen_video_id: str, status: str = "processing"):
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE videos SET heygen_video_id=?, status=?, updated_at=datetime('now') WHERE id=?",
                (heygen_video_id, status, video_id),
            )

    def update_status(self, video_id: int, status: str, error_message: str | None = None):
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE videos SET status=?, error_message=?, updated_at=datetime('now') WHERE id=?",
                (status, error_message, video_id),
            )

    def update_completion(self, video_id: int, file_path: str, download_url: str,
                          duration: float | None = None, credits: float | None = None):
        with self._db.get_connection() as conn:
            conn.execute(
                """UPDATE videos SET status='completed', file_path=?, download_url=?,
                   duration_seconds=?, credits_used=?, updated_at=datetime('now') WHERE id=?""",
                (file_path, download_url, duration, credits, video_id),
            )

    def get_by_content_id(self, content_id: int) -> dict | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM videos WHERE content_id=? ORDER BY created_at DESC LIMIT 1",
                (content_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_by_id(self, video_id: int) -> dict | None:
        with self._db.get_connection() as conn:
            row = conn.execute("SELECT * FROM videos WHERE id=?", (video_id,)).fetchone()
        return dict(row) if row else None

    def get_queued(self) -> list[dict]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE status='queued' ORDER BY created_at",
            ).fetchall()
        return [dict(r) for r in rows]

    def get_processing(self) -> list[dict]:
        with self._db.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM videos WHERE status='processing' ORDER BY created_at",
            ).fetchall()
        return [dict(r) for r in rows]

    def increment_retry(self, video_id: int) -> int:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE videos SET retry_count=retry_count+1, updated_at=datetime('now') WHERE id=?",
                (video_id,),
            )
            row = conn.execute("SELECT retry_count FROM videos WHERE id=?", (video_id,)).fetchone()
            return row["retry_count"]

    def upsert_scene(self, video_id: int, scene_index: int, scene_data: dict):
        with self._db.get_connection() as conn:
            existing = conn.execute(
                "SELECT id FROM video_scenes WHERE video_id=? AND scene_index=?",
                (video_id, scene_index),
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE video_scenes SET avatar_id=?, voice_id=?, voice_emotion=?,
                       script=?, background_type=?, background_value=?, duration_estimate=?,
                       subtitle_enabled=? WHERE video_id=? AND scene_index=?""",
                    (
                        scene_data.get("avatar_id"),
                        scene_data.get("voice_id"),
                        scene_data.get("voice_emotion"),
                        scene_data.get("script"),
                        scene_data.get("background_type", "color"),
                        scene_data.get("background_value"),
                        scene_data.get("duration_estimate"),
                        scene_data.get("subtitle_enabled", 1),
                        video_id, scene_index,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO video_scenes (video_id, scene_index, avatar_id, voice_id,
                       voice_emotion, script, background_type, background_value, duration_estimate, subtitle_enabled)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        video_id, scene_index,
                        scene_data.get("avatar_id"),
                        scene_data.get("voice_id"),
                        scene_data.get("voice_emotion"),
                        scene_data.get("script"),
                        scene_data.get("background_type", "color"),
                        scene_data.get("background_value"),
                        scene_data.get("duration_estimate"),
                        scene_data.get("subtitle_enabled", 1),
                    ),
                )


class AssetRepository:
    def __init__(self, db: Database):
        self._db = db

    def get_by_checksum(self, checksum: str) -> dict | None:
        with self._db.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM assets WHERE checksum=?", (checksum,),
            ).fetchone()
        return dict(row) if row else None

    def create(self, local_path: str, filename: str, mime_type: str,
               size: int, checksum: str, asset_id: str | None = None) -> int:
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                """INSERT INTO assets (asset_id, local_path, original_filename,
                   mime_type, size_bytes, checksum) VALUES (?, ?, ?, ?, ?, ?)""",
                (asset_id, local_path, filename, mime_type, size, checksum),
            )
            return cursor.lastrowid

    def update_asset_id(self, db_id: int, asset_id: str):
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE assets SET asset_id=?, status='uploaded' WHERE id=?",
                (asset_id, db_id),
            )

    def mark_failed(self, db_id: int, error: str):
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE assets SET status='failed' WHERE id=?",
                (db_id,),
            )


class JobRepository:
    def __init__(self, db: Database):
        self._db = db

    def create(self, job_type: str, payload: dict) -> int:
        import json
        with self._db.get_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO jobs (job_type, payload) VALUES (?, ?)",
                (job_type, json.dumps(payload)),
            )
            return cursor.lastrowid

    def update_status(self, job_id: int, status: str, result: str | None = None,
                      error: str | None = None):
        import json
        with self._db.get_connection() as conn:
            if result:
                conn.execute(
                    "UPDATE jobs SET status=?, result=?, updated_at=datetime('now') WHERE id=?",
                    (status, json.dumps(result), job_id),
                )
            elif error:
                conn.execute(
                    "UPDATE jobs SET status=?, error_message=?, updated_at=datetime('now') WHERE id=?",
                    (status, error, job_id),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status=?, updated_at=datetime('now') WHERE id=?",
                    (status, job_id),
                )

    def increment_retry(self, job_id: int) -> int:
        with self._db.get_connection() as conn:
            conn.execute(
                "UPDATE jobs SET retries=retries+1, updated_at=datetime('now') WHERE id=?",
                (job_id,),
            )
            row = conn.execute("SELECT retries FROM jobs WHERE id=?", (job_id,)).fetchone()
            return row["retries"]


db = Database()
content_repo = ContentRepository(db)
video_repo = VideoRepository(db)
asset_repo = AssetRepository(db)
job_repo = JobRepository(db)
