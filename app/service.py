"""核心业务逻辑：打卡写入/更正/撤销与分段结果重算。"""
from __future__ import annotations

from datetime import datetime, timezone


class NotFoundError(Exception):
    """事件号或选手不存在。"""


class ConflictError(Exception):
    """事件号已存在。"""


def normalize_dt(dt: datetime) -> datetime:
    """带时区时间统一转为 UTC 朴素时间，便于比较与存储。"""
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_punch(conn, event_no: str, runner_id: str, station_seq: int,
                 occurred_at: datetime) -> dict:
    if conn.execute("SELECT 1 FROM punches WHERE event_no = ?",
                    (event_no,)).fetchone():
        raise ConflictError(f"事件号 {event_no} 已存在")
    if not conn.execute("SELECT 1 FROM stations WHERE seq = ?",
                        (station_seq,)).fetchone():
        raise NotFoundError(f"站点序号 {station_seq} 不存在")
    ts = normalize_dt(occurred_at).isoformat(timespec="seconds")
    now = _now()
    conn.execute(
        "INSERT INTO punches (event_no, runner_id, station_seq, occurred_at,"
        " status, created_at, updated_at) VALUES (?,?,?,?,'active',?,?)",
        (event_no, runner_id, station_seq, ts, now, now),
    )
    recompute_runner(conn, runner_id)
    return get_punch(conn, event_no)


def correct_punch(conn, event_no: str, runner_id=None, station_seq=None,
                  occurred_at=None) -> dict:
    row = conn.execute("SELECT * FROM punches WHERE event_no = ?",
                       (event_no,)).fetchone()
    if not row:
        raise NotFoundError(f"事件号 {event_no} 不存在")
    if station_seq is not None and not conn.execute(
            "SELECT 1 FROM stations WHERE seq = ?", (station_seq,)).fetchone():
        raise NotFoundError(f"站点序号 {station_seq} 不存在")

    old_runner = row["runner_id"]
    new_runner = runner_id if runner_id is not None else old_runner
    new_seq = station_seq if station_seq is not None else row["station_seq"]
    new_ts = (normalize_dt(occurred_at).isoformat(timespec="seconds")
              if occurred_at is not None else row["occurred_at"])
    conn.execute(
        "UPDATE punches SET runner_id=?, station_seq=?, occurred_at=?,"
        " updated_at=? WHERE event_no=?",
        (new_runner, new_seq, new_ts, _now(), event_no),
    )
    # 更正影响新、旧两名选手（选手号未变时两者相同）
    recompute_runner(conn, new_runner)
    if old_runner != new_runner:
        recompute_runner(conn, old_runner)
    return get_punch(conn, event_no)


def revoke_punch(conn, event_no: str) -> dict:
    row = conn.execute("SELECT * FROM punches WHERE event_no = ?",
                       (event_no,)).fetchone()
    if not row:
        raise NotFoundError(f"事件号 {event_no} 不存在")
    if row["status"] != "revoked":
        conn.execute(
            "UPDATE punches SET status='revoked', updated_at=? WHERE event_no=?",
            (_now(), event_no),
        )
        recompute_runner(conn, row["runner_id"])
    return get_punch(conn, event_no)


def get_punch(conn, event_no: str) -> dict:
    row = conn.execute("SELECT * FROM punches WHERE event_no = ?",
                       (event_no,)).fetchone()
    if not row:
        raise NotFoundError(f"事件号 {event_no} 不存在")
    return dict(row)


def recompute_runner(conn, runner_id: str) -> None:
    """按站点顺序重算某选手全部相邻站分段，结果落库。

    - 同站多条有效打卡取最早时间；
    - 相邻站缺打卡或时间倒退 -> 该段 pending 并写明原因；
    - 乱序补传/更正/撤销后调用本函数即可刷新受影响结果。
    """
    stations = conn.execute(
        "SELECT seq, name FROM stations ORDER BY seq").fetchall()
    rows = conn.execute(
        "SELECT station_seq, MIN(occurred_at) AS t FROM punches"
        " WHERE runner_id = ? AND status = 'active' GROUP BY station_seq",
        (runner_id,),
    ).fetchall()
    times = {r["station_seq"]: r["t"] for r in rows}

    conn.execute("DELETE FROM segment_results WHERE runner_id = ?", (runner_id,))
    for a, b in zip(stations, stations[1:]):
        ta, tb = times.get(a["seq"]), times.get(b["seq"])
        duration, status, reason = None, "ok", None
        if ta is None or tb is None:
            missing = [s["name"] for s, t in ((a, ta), (b, tb)) if t is None]
            status = "pending"
            reason = "缺少站点打卡: " + ", ".join(missing)
        else:
            da, db_ = datetime.fromisoformat(ta), datetime.fromisoformat(tb)
            if db_ < da:
                status = "pending"
                reason = (f"时间倒退: {b['name']}({tb}) 早于"
                          f" {a['name']}({ta})")
            else:
                duration = (db_ - da).total_seconds()
        conn.execute(
            "INSERT INTO segment_results"
            " (runner_id, from_seq, to_seq, duration_seconds, status, reason)"
            " VALUES (?,?,?,?,?,?)",
            (runner_id, a["seq"], b["seq"], duration, status, reason),
        )


def get_runner_results(conn, runner_id: str) -> dict:
    if not conn.execute(
            "SELECT 1 FROM punches WHERE runner_id = ? AND status = 'active'",
            (runner_id,)).fetchone():
        raise NotFoundError(f"选手 {runner_id} 没有有效打卡记录")

    stations = {r["seq"]: r["name"] for r in conn.execute(
        "SELECT seq, name FROM stations")}
    station_times = [
        {"station_seq": r["station_seq"],
         "station_name": stations.get(r["station_seq"], str(r["station_seq"])),
         "time": r["t"]}
        for r in conn.execute(
            "SELECT station_seq, MIN(occurred_at) AS t FROM punches"
            " WHERE runner_id = ? AND status = 'active'"
            " GROUP BY station_seq ORDER BY station_seq", (runner_id,))
    ]
    segments = [
        {"from_seq": r["from_seq"], "to_seq": r["to_seq"],
         "from_name": stations.get(r["from_seq"], str(r["from_seq"])),
         "to_name": stations.get(r["to_seq"], str(r["to_seq"])),
         "duration_seconds": r["duration_seconds"],
         "status": r["status"], "reason": r["reason"]}
        for r in conn.execute(
            "SELECT * FROM segment_results WHERE runner_id = ?"
            " ORDER BY from_seq", (runner_id,))
    ]
    pending = [s for s in segments if s["status"] == "pending"]
    total = (None if pending else
             sum(s["duration_seconds"] for s in segments))
    return {
        "runner_id": runner_id,
        "station_times": station_times,
        "segments": segments,
        "total_duration_seconds": total,
        "pending_count": len(pending),
    }
