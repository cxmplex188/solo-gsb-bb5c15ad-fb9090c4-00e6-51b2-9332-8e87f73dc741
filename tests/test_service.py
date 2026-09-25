"""核心逻辑测试（仅标准库）：python3 tests/test_service.py"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")

from app import db, service  # noqa: E402

db.init_db(seed_demo=False)
conn_ctx = db.get_conn()
conn = conn_ctx.__enter__()


def results(runner):
    return service.get_runner_results(conn, runner)


def seg(r, i):
    return r["segments"][i]


# 1. 乱序补传：先发后站再补前站，缺段应被填补
service.create_punch(conn, "E1", "R1", 1, datetime(2026, 9, 25, 8, 0, 0))
service.create_punch(conn, "E2", "R1", 3, datetime(2026, 9, 25, 9, 0, 0))
r = results("R1")
assert seg(r, 0)["status"] == "pending" and "CP1" in seg(r, 0)["reason"]
assert seg(r, 1)["status"] == "pending"
service.create_punch(conn, "E3", "R1", 2, datetime(2026, 9, 25, 8, 30, 0))
r = results("R1")
assert seg(r, 0)["status"] == "ok" and seg(r, 0)["duration_seconds"] == 1800
assert seg(r, 1)["status"] == "ok" and seg(r, 1)["duration_seconds"] == 1800

# 2. 同站多条有效打卡取最早
service.create_punch(conn, "E4", "R1", 2, datetime(2026, 9, 25, 8, 20, 0))
r = results("R1")
assert seg(r, 0)["duration_seconds"] == 1200  # 8:00 -> 8:20
assert seg(r, 1)["duration_seconds"] == 2400  # 8:20 -> 9:00

# 3. 更正：把 E4 改到更早（8:10），最早时间变化，分段随之更新
service.correct_punch(conn, "E4", occurred_at=datetime(2026, 9, 25, 8, 10, 0))
r = results("R1")
assert seg(r, 0)["duration_seconds"] == 600   # 8:00 -> 8:10
assert seg(r, 1)["duration_seconds"] == 3000  # 8:10 -> 9:00

# 4. 撤销 E4 后把 E3 改到 9:30（晚于 CP2 的 9:00）-> 时间倒退待定
service.revoke_punch(conn, "E4")
service.correct_punch(conn, "E3", occurred_at=datetime(2026, 9, 25, 9, 30, 0))
r = results("R1")
assert seg(r, 0)["status"] == "ok" and seg(r, 0)["duration_seconds"] == 5400
assert seg(r, 1)["status"] == "pending" and "时间倒退" in seg(r, 1)["reason"]
assert r["total_duration_seconds"] is None and r["pending_count"] >= 1

# 5. 更正回正常时间后恢复
service.correct_punch(conn, "E3", occurred_at=datetime(2026, 9, 25, 8, 30, 0))
r = results("R1")
assert seg(r, 0)["duration_seconds"] == 1800
assert seg(r, 1)["duration_seconds"] == 1800

# 6. 更正到其他选手：旧选手段消失、新选手出现
service.create_punch(conn, "E5", "R1", 4, datetime(2026, 9, 25, 9, 50, 0))
service.correct_punch(conn, "E5", runner_id="R2")
r1, r2 = results("R1"), results("R2")
assert seg(r1, 2)["status"] == "pending" and "CP3" in seg(r1, 2)["reason"]
assert seg(r2, 2)["status"] == "pending"  # R2 只有 CP3，前后皆缺
assert r2["station_times"][0]["station_seq"] == 4

# 7. 撤销不存在的/重复事件号
try:
    service.revoke_punch(conn, "NOPE")
    raise AssertionError("应当抛 NotFoundError")
except service.NotFoundError:
    pass
service.revoke_punch(conn, "E5")  # 幂等
service.revoke_punch(conn, "E5")

# 8. 重复事件号冲突
try:
    service.create_punch(conn, "E1", "R9", 1, datetime(2026, 9, 25, 8, 0, 0))
    raise AssertionError("应当抛 ConflictError")
except service.ConflictError:
    pass

# 9. 全部到齐后总成绩为各段之和
for i, t in enumerate(["10:40", "11:30"], start=4):
    h, m = map(int, t.split(":"))
    service.create_punch(conn, f"E9{i}", "R1", i, datetime(2026, 9, 25, h, m))
r = results("R1")
assert r["pending_count"] == 0
assert r["total_duration_seconds"] == 3.5 * 3600  # 8:00 -> 11:30

conn_ctx.__exit__(None, None, None)
print("全部核心逻辑测试通过 ✔")
