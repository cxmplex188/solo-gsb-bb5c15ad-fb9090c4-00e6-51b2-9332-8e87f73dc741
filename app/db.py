"""SQLite 访问层：连接管理、建表与种子数据。"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

DATABASE_PATH = os.environ.get("DATABASE_PATH", "./data/race.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS stations (
    seq  INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS punches (
    event_no    TEXT PRIMARY KEY,          -- 唯一事件号
    runner_id   TEXT NOT NULL,             -- 选手号
    station_seq INTEGER NOT NULL,          -- 站点序号
    occurred_at TEXT NOT NULL,             -- 发生时间 ISO 8601
    status      TEXT NOT NULL DEFAULT 'active',  -- active | revoked
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_punches_runner
    ON punches (runner_id, station_seq, status);

CREATE TABLE IF NOT EXISTS segment_results (
    runner_id        TEXT NOT NULL,
    from_seq         INTEGER NOT NULL,
    to_seq           INTEGER NOT NULL,
    duration_seconds REAL,                 -- NULL 表示待定
    status           TEXT NOT NULL,        -- ok | pending
    reason           TEXT,
    PRIMARY KEY (runner_id, from_seq, to_seq)
);
"""

DEFAULT_STATIONS = [
    (1, "起点"),
    (2, "CP1"),
    (3, "CP2"),
    (4, "CP3"),
    (5, "终点"),
]

# 演示数据：A001 全程正常；A002 缺 CP2（待定段）；A003 在 CP2 时间倒退。
DEMO_PUNCHES = [
    ("EVT-A001-1", "A001", 1, "2026-09-25T08:00:00"),
    ("EVT-A001-2", "A001", 2, "2026-09-25T08:45:30"),
    ("EVT-A001-3", "A001", 3, "2026-09-25T09:40:10"),
    ("EVT-A001-4", "A001", 4, "2026-09-25T10:30:00"),
    ("EVT-A001-5", "A001", 5, "2026-09-25T11:20:45"),
    ("EVT-A002-1", "A002", 1, "2026-09-25T08:02:00"),
    ("EVT-A002-2", "A002", 2, "2026-09-25T08:50:00"),
    ("EVT-A002-4", "A002", 4, "2026-09-25T10:05:00"),
    ("EVT-A002-5", "A002", 5, "2026-09-25T11:00:00"),
    ("EVT-A003-1", "A003", 1, "2026-09-25T08:05:00"),
    ("EVT-A003-2", "A003", 2, "2026-09-25T09:00:00"),
    ("EVT-A003-3", "A003", 3, "2026-09-25T08:55:00"),  # 早于上一站 -> 时间倒退
]


@contextmanager
def get_conn():
    path = Path(DATABASE_PATH)
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
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


def init_db(seed_demo: bool = True) -> None:
    """建表；库为空时写入站点与演示打卡，并重算结果。"""
    from . import service  # 延迟导入避免循环依赖

    with get_conn() as conn:
        conn.executescript(SCHEMA)
        if conn.execute("SELECT COUNT(*) FROM stations").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO stations (seq, name) VALUES (?, ?)", DEFAULT_STATIONS
            )
        if (
            seed_demo
            and conn.execute("SELECT COUNT(*) FROM punches").fetchone()[0] == 0
        ):
            now = datetime.now().isoformat(timespec="seconds")
            conn.executemany(
                "INSERT INTO punches (event_no, runner_id, station_seq, occurred_at,"
                " status, created_at, updated_at) VALUES (?,?,?,?,'active',?,?)",
                [(e, r, s, t, now, now) for e, r, s, t in DEMO_PUNCHES],
            )
            for runner in {r for _, r, _, _ in DEMO_PUNCHES}:
                service.recompute_runner(conn, runner)
