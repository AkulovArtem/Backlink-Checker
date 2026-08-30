import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Optional, TypedDict

from utils.resource_path import data_path

logger = logging.getLogger(__name__)

DB_PATH = data_path("backlink_checker.db")


def format_task_created(created_iso: str) -> str:
    """SQLite CURRENT_TIMESTAMP is UTC without tzinfo; show local wall time."""
    try:
        dt = datetime.fromisoformat(str(created_iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone().strftime("%d.%m.%Y %H:%M")
    except Exception:
        return str(created_iso)


class AddDonorsResult(TypedDict):
    added: int
    skipped_dup: int
    skipped_cap: int
    urls: list[str]


@contextmanager
def get_connection():
    """Yield a committed-and-closed SQLite connection."""
    conn = sqlite3.connect(str(DB_PATH), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript("""
            PRAGMA journal_mode = WAL;

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                user_agent TEXT DEFAULT 'desktop_chrome',
                custom_user_agent TEXT,
                threads INTEGER DEFAULT 5,
                timeout INTEGER DEFAULT 30,
                target_domains TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS donors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                http_status INTEGER,
                title TEXT,
                canonical_url TEXT,
                internal_links INTEGER DEFAULT 0,
                external_links INTEGER DEFAULT 0,
                index_google TEXT,
                index_yandex TEXT,
                index_bing TEXT,
                index_baidu TEXT,
                meta_robots TEXT,
                x_robots_tag TEXT,
                status TEXT DEFAULT 'pending',
                error_code TEXT,
                html_snippet TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS backlinks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                donor_id INTEGER NOT NULL,
                -- task_id is denormalised here for O(1) task-level backlink queries
                -- without a JOIN through donors; removing it would require a schema migration.
                task_id INTEGER NOT NULL,
                target_url TEXT NOT NULL,
                anchor_text TEXT,
                anchor_type TEXT,
                rel_type TEXT,
                context_html TEXT,
                FOREIGN KEY (donor_id) REFERENCES donors(id) ON DELETE CASCADE,
                FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_donors_task_id
                ON donors(task_id);
            CREATE INDEX IF NOT EXISTS idx_backlinks_task_id
                ON backlinks(task_id);
            CREATE INDEX IF NOT EXISTS idx_backlinks_donor_id
                ON backlinks(donor_id);
        """)
        _add_column_if_missing(
            conn, "tasks", "check_google_index", "INTEGER DEFAULT 0"
        )
        _add_column_if_missing(
            conn, "tasks", "index_provider", "TEXT DEFAULT ''"
        )
        _add_column_if_missing(conn, "donors", "google_indexed", "TEXT")
        _add_column_if_missing(conn, "donors", "google_index_error", "TEXT")
    logger.info("Database initialized at %s", DB_PATH)


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, decl: str
) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()  # nosec B608
    names = {r[1] for r in rows}
    if column not in names:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")  # nosec B608


# ── Tasks ──────────────────────────────────────────────────────────────────

def create_task(name: str, target_domains: list[str], user_agent: str = "desktop_chrome",
                custom_user_agent: Optional[str] = None, threads: int = 5,
                timeout: int = 30, check_google_index: bool = False,
                index_provider: str = "") -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (name, target_domains, user_agent, custom_user_agent,
                                  threads, timeout, check_google_index, index_provider)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, json.dumps(target_domains, ensure_ascii=False),
             user_agent, custom_user_agent, threads, timeout,
             1 if check_google_index else 0, index_provider or "")
        )
        return cur.lastrowid or 0


def get_all_tasks_with_counts() -> list[sqlite3.Row]:
    """Single-query alternative to get_all_tasks() + per-task count calls.

    Returns all task columns plus donor_count and backlink_count so callers
    don't need to issue two extra SELECT COUNT queries per row (N+1 problem).
    """
    with get_connection() as conn:
        return conn.execute("""
            SELECT t.*,
                   (SELECT COUNT(*) FROM donors    d WHERE d.task_id = t.id) AS donor_count,
                   (SELECT COUNT(*) FROM backlinks b WHERE b.task_id = t.id) AS backlink_count
            FROM   tasks t
            ORDER BY t.created_at DESC
        """).fetchall()


def get_task(task_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def parse_target_domains(raw) -> list[str]:
    """Parse tasks.target_domains JSON. Raises if missing or not a list."""
    domains = json.loads(raw)
    if not isinstance(domains, list):
        raise TypeError("target_domains is not a list")
    return [str(d) for d in domains if d]


def update_task_status(task_id: int, status: str, progress: int = 0) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE tasks SET status = ?, progress = ? WHERE id = ?",
            (status, progress, task_id)
        )


def delete_task(task_id: int) -> None:
    """Permanently delete a task and all its donors/backlinks (CASCADE)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))


def wipe_check_data() -> None:
    """Delete all tasks, donors and backlinks. Settings (API URLs, theme) stay.

    AUTOINCREMENT ids are left alone so a worker that still persists after
    stop cannot attach rows to a brand-new task that reused id 1.
    """
    with get_connection() as conn:
        conn.execute("DELETE FROM backlinks")
        conn.execute("DELETE FROM donors")
        conn.execute("DELETE FROM tasks")


_TASK_FIELDS = frozenset({
    "name", "user_agent", "custom_user_agent", "threads", "timeout",
    "check_google_index", "index_provider", "target_domains",
})


def update_task_fields(task_id: int, **kwargs) -> None:
    """Update allowed task metadata (name, UA, threads, timeout)."""
    if not kwargs:
        return
    invalid = set(kwargs) - _TASK_FIELDS
    if invalid:
        raise ValueError(f"Invalid task field(s): {invalid}")
    fields = ", ".join(f"{k} = ?" for k in kwargs)  # nosec B608
    values = list(kwargs.values()) + [task_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE tasks SET {fields} WHERE id = ?", values)  # nosec B608


def reset_task(task_id: int) -> None:
    """Reset task to pending: delete backlinks, reset donor fields (keep URLs)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM backlinks WHERE task_id = ?", (task_id,))
        conn.execute(
            """UPDATE donors SET
               status = 'pending', http_status = NULL, title = NULL,
               canonical_url = NULL, internal_links = 0, external_links = 0,
               index_google = NULL, index_yandex = NULL, index_bing = NULL,
               index_baidu = NULL, meta_robots = NULL, x_robots_tag = NULL,
               error_code = NULL, html_snippet = NULL,
               google_indexed = NULL, google_index_error = NULL
               WHERE task_id = ?""",
            (task_id,)
        )
        conn.execute(
            "UPDATE tasks SET status = 'pending', progress = 0 WHERE id = ?",
            (task_id,)
        )


def count_task_backlinks(task_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM backlinks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else 0


def count_task_donors(task_id: int) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM donors WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else 0


# ── Donors ─────────────────────────────────────────────────────────────────

def create_donors_bulk(task_id: int, urls: list[str]) -> None:
    with get_connection() as conn:
        conn.executemany(
            "INSERT INTO donors (task_id, url) VALUES (?, ?)",
            [(task_id, url) for url in urls]
        )


def add_donors_to_task(
    task_id: int, urls: list[str], max_total: int = 100_000
) -> AddDonorsResult:
    """Insert unique new donor URLs into an existing task.

    Existing rows are left untouched (results stay). Duplicates (already in
    the task or repeated in ``urls``) and URLs past ``max_total`` are skipped.

    Returns {"added": int, "skipped_dup": int, "skipped_cap": int, "urls": list[str]}.
    """
    with get_connection() as conn:
        existing = {
            row[0]
            for row in conn.execute(
                "SELECT url FROM donors WHERE task_id = ?", (task_id,)
            ).fetchall()
        }
        unique_new: list[str] = []
        skipped_dup = 0
        seen: set[str] = set()
        for url in urls:
            if url in existing or url in seen:
                skipped_dup += 1
                continue
            seen.add(url)
            unique_new.append(url)

        remaining = max(0, max_total - len(existing))
        skipped_cap = max(0, len(unique_new) - remaining)
        to_insert = unique_new[:remaining]
        if to_insert:
            conn.executemany(
                "INSERT INTO donors (task_id, url) VALUES (?, ?)",
                [(task_id, url) for url in to_insert],
            )
        return {
            "added": len(to_insert),
            "skipped_dup": skipped_dup,
            "skipped_cap": skipped_cap,
            "urls": to_insert,
        }


def get_donors_for_task(task_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM donors WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()


def get_failed_donors_for_task(task_id: int) -> list[sqlite3.Row]:
    """Return only donors whose last fetch failed (status = 'not_loaded')."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM donors WHERE task_id = ? AND status = 'not_loaded' ORDER BY id",
            (task_id,),
        ).fetchall()


def get_pending_donors_for_task(task_id: int) -> list[sqlite3.Row]:
    """Return donors that have not been checked yet (status = 'pending')."""
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM donors WHERE task_id = ? AND status = 'pending' ORDER BY id",
            (task_id,),
        ).fetchall()


def reset_failed_donors(task_id: int) -> None:
    """Reset only not_loaded donors to pending; leaves found/not_found rows intact."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE donors SET
               status = 'pending', http_status = NULL, title = NULL,
               canonical_url = NULL, internal_links = 0, external_links = 0,
               index_google = NULL, index_yandex = NULL, index_bing = NULL,
               index_baidu = NULL, meta_robots = NULL, x_robots_tag = NULL,
               error_code = NULL, html_snippet = NULL,
               google_indexed = NULL, google_index_error = NULL
               WHERE task_id = ? AND status = 'not_loaded'""",
            (task_id,),
        )


_DONOR_COLUMNS = frozenset({
    "http_status", "title", "canonical_url", "internal_links", "external_links",
    "index_google", "index_yandex", "index_bing", "index_baidu",
    "meta_robots", "x_robots_tag", "status", "error_code", "html_snippet",
    "google_indexed", "google_index_error",
})


def update_donor(donor_id: int, **kwargs) -> None:
    if not kwargs:
        return
    invalid = set(kwargs) - _DONOR_COLUMNS
    if invalid:
        raise ValueError(f"Invalid donor column(s): {invalid}")
    fields = ", ".join(f"{k} = ?" for k in kwargs)  # nosec B608
    values = list(kwargs.values()) + [donor_id]
    with get_connection() as conn:
        conn.execute(f"UPDATE donors SET {fields} WHERE id = ?", values)  # nosec B608


def get_donor_stats(task_id: int) -> dict:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM donors WHERE task_id = ? GROUP BY status",
            (task_id,)
        ).fetchall()
    stats = {"found": 0, "not_found": 0, "not_loaded": 0, "pending": 0}
    for row in rows:
        stats[row["status"]] = row["cnt"]
    return stats


# ── Backlinks ──────────────────────────────────────────────────────────────

def create_backlinks_bulk(donor_id: int, task_id: int, backlinks: list) -> None:
    """Insert all backlinks for one donor in a single transaction."""
    if not backlinks:
        return
    with get_connection() as conn:
        conn.executemany(
            """INSERT INTO backlinks
               (donor_id, task_id, target_url, anchor_text, anchor_type, rel_type, context_html)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            [(donor_id, task_id, bl.target_url, bl.anchor_text, bl.anchor_type,
              bl.rel_type, bl.context_html) for bl in backlinks],
        )


def get_backlinks_for_task(task_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM backlinks WHERE task_id = ? ORDER BY id", (task_id,)
        ).fetchall()


def get_backlinks_for_donor(donor_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM backlinks WHERE donor_id = ? ORDER BY id", (donor_id,)
        ).fetchall()


def get_anchor_stats(task_id: int) -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            """SELECT anchor_text, COUNT(*) as cnt
               FROM backlinks WHERE task_id = ?
               GROUP BY anchor_text ORDER BY cnt DESC""",
            (task_id,)
        ).fetchall()


# ── Settings ───────────────────────────────────────────────────────────────

def get_setting(key: str, default: str = "") -> str:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
