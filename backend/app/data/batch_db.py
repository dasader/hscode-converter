import sqlite3
import threading
import uuid
from datetime import datetime, timezone

MAX_RETRIES = 3


class BatchDB:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._write_lock = threading.Lock()
        self._init_tables()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _execute(self, sql: str, params: tuple = ()):
        with self._write_lock:
            conn = self._connect()
            conn.execute(sql, params)
            conn.commit()
            conn.close()

    def _init_tables(self):
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS batch_jobs (
                job_id TEXT PRIMARY KEY,
                file_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                total_items INTEGER NOT NULL,
                completed_items INTEGER DEFAULT 0,
                failed_items INTEGER DEFAULT 0,
                top_n INTEGER DEFAULT 5,
                confidence_threshold REAL,
                model TEXT DEFAULT 'chatgpt-5.4-mini',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS batch_items (
                item_id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES batch_jobs(job_id),
                row_index INTEGER NOT NULL,
                task_name TEXT,
                description TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result_json TEXT,
                error_message TEXT,
                retry_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_batch_items_job_id ON batch_items(job_id);
            CREATE INDEX IF NOT EXISTS idx_batch_items_status ON batch_items(status);
        """)
        conn.close()

    def create_job(self, file_name, total_items, top_n, confidence_threshold, model):
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO batch_jobs (job_id, file_name, total_items, top_n, confidence_threshold, model, created_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, file_name, total_items, top_n, confidence_threshold, model, now),
            )
            conn.commit()
            conn.close()
        return job_id

    def create_items(self, job_id, items):
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            conn = self._connect()
            for item in items:
                item_id = str(uuid.uuid4())
                conn.execute(
                    "INSERT INTO batch_items (item_id, job_id, row_index, task_name, description, created_at) VALUES (?,?,?,?,?,?)",
                    (item_id, job_id, item["row_index"], item.get("task_name"), item["description"], now),
                )
            conn.commit()
            conn.close()

    def get_job(self, job_id):
        conn = self._connect()
        row = conn.execute("SELECT * FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_item(self, item_id):
        conn = self._connect()
        row = conn.execute("SELECT * FROM batch_items WHERE item_id=?", (item_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_items(self, job_id):
        conn = self._connect()
        rows = conn.execute("SELECT * FROM batch_items WHERE job_id=? ORDER BY row_index", (job_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_pending_items(self, job_id):
        conn = self._connect()
        rows = conn.execute("SELECT * FROM batch_items WHERE job_id=? AND status='pending' ORDER BY row_index", (job_id,)).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_item_status(self, item_id, status, result_json=None, error_message=None):
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            conn = self._connect()
            if status == "completed":
                conn.execute("UPDATE batch_items SET status=?, result_json=?, completed_at=? WHERE item_id=?", (status, result_json, now, item_id))
            elif status == "failed":
                conn.execute("UPDATE batch_items SET status=?, error_message=?, retry_count=retry_count+1 WHERE item_id=?", (status, error_message, item_id))
            else:
                conn.execute("UPDATE batch_items SET status=? WHERE item_id=?", (status, item_id))
            conn.commit()
            conn.close()

    def refresh_job_progress(self, job_id):
        with self._write_lock:
            conn = self._connect()
            completed = conn.execute("SELECT COUNT(*) FROM batch_items WHERE job_id=? AND status='completed'", (job_id,)).fetchone()[0]
            failed = conn.execute("SELECT COUNT(*) FROM batch_items WHERE job_id=? AND status='failed'", (job_id,)).fetchone()[0]
            total = conn.execute("SELECT total_items FROM batch_jobs WHERE job_id=?", (job_id,)).fetchone()[0]
            new_status = "completed" if (completed + failed) >= total else "processing"
            now = datetime.now(timezone.utc).isoformat() if new_status == "completed" else None
            conn.execute(
                "UPDATE batch_jobs SET completed_items=?, failed_items=?, status=?, completed_at=COALESCE(?, completed_at) WHERE job_id=?",
                (completed, failed, new_status, now, job_id),
            )
            conn.commit()
            conn.close()

    def reset_failed_items(self, job_id):
        with self._write_lock:
            conn = self._connect()
            cursor = conn.execute(
                "UPDATE batch_items SET status='pending', error_message=NULL WHERE job_id=? AND status='failed' AND retry_count<?",
                (job_id, MAX_RETRIES),
            )
            count = cursor.rowcount
            if count > 0:
                conn.execute("UPDATE batch_jobs SET status='processing' WHERE job_id=?", (job_id,))
            conn.commit()
            conn.close()
        return count

    def recover_incomplete_items(self):
        with self._write_lock:
            conn = self._connect()
            conn.execute(f"UPDATE batch_items SET status='failed', error_message='서버 재시작으로 인한 실패' WHERE status='processing' AND retry_count>={MAX_RETRIES}")
            conn.execute("UPDATE batch_items SET status='pending' WHERE status='processing'")
            conn.commit()
            rows = conn.execute("SELECT * FROM batch_items WHERE status='pending' ORDER BY row_index").fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def list_jobs(self):
        conn = self._connect()
        rows = conn.execute("SELECT * FROM batch_jobs ORDER BY created_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
