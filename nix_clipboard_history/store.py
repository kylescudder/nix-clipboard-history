"""Private SQLite storage. No Wayland or GTK dependency, even for image entries."""

from __future__ import annotations

import fcntl
import hashlib
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from .config import Config, data_path


@dataclass(frozen=True)
class Entry:
    id: int
    kind: str
    mime_type: str
    title: str
    source: str
    byte_count: int
    created_at: float
    updated_at: float
    pinned: bool


def image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith((b"II\x2a\x00", b"MM\x00\x2a")):
        return "image/tiff"
    if data.startswith(b"BM"):
        return "image/bmp"
    return None


class Store:
    def __init__(self, directory: Path | None = None, config: Config | None = None):
        self.config = config or Config()
        self.directory = directory or data_path()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        # SQLite's WAL/SHM files inherit the mode of the database.
        path = self.directory / "history.sqlite3"
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        path.chmod(0o600)
        self.db = sqlite3.connect(path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                digest TEXT NOT NULL UNIQUE,
                kind TEXT NOT NULL CHECK(kind IN ('text', 'image')),
                mime_type TEXT NOT NULL,
                body BLOB NOT NULL,
                title TEXT NOT NULL,
                search_text TEXT NOT NULL,
                source TEXT NOT NULL,
                byte_count INTEGER NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS entries_order ON entries(pinned DESC, updated_at DESC);
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
            INSERT OR IGNORE INTO state VALUES ('paused', 0), ('revision', 0);
        """)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("UPDATE state SET value=value+1 WHERE key='revision'")
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    @property
    def paused(self) -> bool:
        return bool(self.db.execute("SELECT value FROM state WHERE key='paused'").fetchone()[0])

    @property
    def revision(self) -> int:
        return self.db.execute("SELECT value FROM state WHERE key='revision'").fetchone()[0]

    def set_paused(self, paused: bool | None = None) -> bool:
        with self._transaction():
            paused = not self.paused if paused is None else paused
            self.db.execute("UPDATE state SET value=? WHERE key='paused'", (int(paused),))
        return paused

    def add(self, data: bytes, kind: str, source: str = "") -> int | None:
        if not data or len(data) > self.config.max_item_bytes:
            return None
        if kind == "text":
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                return None
            if "\0" in text or not text.strip():
                return None
            title = " ".join(text.split())[:140]
            mime = "text/plain;charset=utf-8"
        elif kind == "image" and self.config.capture_images:
            mime = image_mime(data)
            if mime is None:
                return None
            title = f"{mime.split('/')[-1].upper()} image"
            text = title
        else:
            return None
        digest = hashlib.sha256(kind.encode() + b"\0" + data).hexdigest()
        now = time.time()
        with self._transaction():
            if self.paused:
                return None
            self.db.execute(
                """
                INSERT INTO entries
                    (digest,kind,mime_type,body,title,search_text,source,byte_count,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(digest) DO UPDATE SET updated_at=excluded.updated_at,
                    search_text=CASE WHEN excluded.source='' THEN entries.search_text
                        ELSE excluded.search_text END,
                    source=CASE WHEN excluded.source='' THEN entries.source ELSE excluded.source END
            """,
                (
                    digest,
                    kind,
                    mime,
                    data,
                    title,
                    (text + " " + source).casefold(),
                    source,
                    len(data),
                    now,
                    now,
                ),
            )
            entry_id = self.db.execute(
                "SELECT id FROM entries WHERE digest=?", (digest,)
            ).fetchone()[0]
            self._prune(now)
            exists = self.db.execute("SELECT 1 FROM entries WHERE id=?", (entry_id,)).fetchone()
        return entry_id if exists else None

    def list(self, query: str = "", kind: str = "all", limit: int = 500) -> list[Entry]:
        clauses, params = [], []
        if kind == "pinned":
            clauses.append("pinned=1")
        elif kind in ("text", "image"):
            clauses.append("kind=?")
            params.append(kind)
        for token in query.casefold().split():
            clauses.append("instr(search_text, ?) > 0")
            params.append(token)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        rows = self.db.execute(
            "SELECT id,kind,mime_type,title,source,byte_count,created_at,updated_at,pinned "
            "FROM entries" + where + " ORDER BY pinned DESC,updated_at DESC,id DESC LIMIT ?",
            (*params, limit),
        )
        return [Entry(**{**dict(row), "pinned": bool(row["pinned"])}) for row in rows]

    def get(self, entry_id: int) -> tuple[bytes, str]:
        row = self.db.execute(
            "SELECT body,mime_type FROM entries WHERE id=?", (entry_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Clipboard item {entry_id} no longer exists")
        return bytes(row[0]), row[1]

    def pin(self, entry_id: int):
        with self._transaction():
            self.db.execute("UPDATE entries SET pinned=1-pinned WHERE id=?", (entry_id,))
            self._prune(time.time())

    def delete(self, entry_id: int):
        with self._transaction():
            self.db.execute("DELETE FROM entries WHERE id=?", (entry_id,))

    def clear(self, include_pinned: bool = False):
        with self._transaction():
            self.db.execute("DELETE FROM entries" + ("" if include_pinned else " WHERE pinned=0"))
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    def stats(self) -> dict:
        row = self.db.execute(
            "SELECT count(*) AS items,coalesce(sum(pinned),0) AS pinned,"
            "coalesce(sum(byte_count),0) AS bytes FROM entries"
        ).fetchone()
        return {**dict(row), "paused": self.paused}

    def daemon_running(self) -> bool:
        with (self.directory / "daemon.lock").open("a") as lock:
            (self.directory / "daemon.lock").chmod(0o600)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return True
        return False

    def prune(self):
        with self._transaction():
            self._prune(time.time())

    def _prune(self, now: float):
        self.db.execute(
            "DELETE FROM entries WHERE pinned=0 AND updated_at < ?",
            (now - self.config.retention_days * 86400,),
        )
        rows = self.db.execute(
            "SELECT id,byte_count,pinned FROM entries ORDER BY pinned DESC,updated_at DESC,id DESC"
        ).fetchall()
        total = sum(row["byte_count"] for row in rows if row["pinned"])
        count = sum(row["pinned"] for row in rows)
        remove = []
        for row in rows:
            if row["pinned"]:
                continue
            count += 1
            total += row["byte_count"]
            if count > self.config.max_items or total > self.config.max_total_bytes:
                remove.append((row["id"],))
        self.db.executemany("DELETE FROM entries WHERE id=?", remove)
