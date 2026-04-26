import sqlite3
import json
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "backlink_checker.db"


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
    logger.info("Database initialized at %s", DB_PATH)


# ── Tasks ──────────────────────────────────────────────────────────────────

def create_task(name: str, target_domains: list[str], user_agent: str = "desktop_chrome",
                custom_user_agent: Optional[str] = None, threads: int = 5,
                timeout: int = 30) -> int:
    with get_connection() as conn:
        cur = conn.execute(
            """INSERT INTO tasks (name, target_domains, user_agent, custom_user_agent, threads, timeout)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (name, json.dumps(target_domains, ensure_ascii=False),
             user_agent, custom_user_agent, threads, timeout)
        )
        return cur.lastrowid or 0


def get_all_tasks() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC"
        ).fetchall()


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
               error_code = NULL, html_snippet = NULL
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


def reset_failed_donors(task_id: int) -> None:
    """Reset only not_loaded donors to pending; leaves found/not_found rows intact."""
    with get_connection() as conn:
        conn.execute(
            """UPDATE donors SET
               status = 'pending', http_status = NULL, title = NULL,
               canonical_url = NULL, internal_links = 0, external_links = 0,
               index_google = NULL, index_yandex = NULL, index_bing = NULL,
               index_baidu = NULL, meta_robots = NULL, x_robots_tag = NULL,
               error_code = NULL, html_snippet = NULL
               WHERE task_id = ? AND status = 'not_loaded'""",
            (task_id,),
        )


_DONOR_COLUMNS = frozenset({
    "http_status", "title", "canonical_url", "internal_links", "external_links",
    "index_google", "index_yandex", "index_bing", "index_baidu",
    "meta_robots", "x_robots_tag", "status", "error_code", "html_snippet",
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
