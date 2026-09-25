# 越野赛分段计时 API

基于 FastAPI + SQLite 的越野赛分段计时服务：接收选手在各站点的打卡，按站点顺序计算相邻站分段用时，支持按事件号更正与撤销，结果自动重算。

## 启动

```bash
docker compose up --build
```

一条命令即可启动。容器启动时自动建表并初始化站点与演示数据（库非空时跳过）。

- API 地址：http://localhost:8000
- 交互式文档（Swagger UI）：http://localhost:8000/docs

## 配置

通过环境变量配置（见 `docker-compose.yml`）：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_PATH` | `/data/race.db` | SQLite 数据库文件路径（本地裸跑默认 `./data/race.db`） |
| `SEED_DEMO_DATA` | `1` | 首次启动写入演示站点与打卡；设为 `0` 关闭 |

内置站点：1 起点 → 2 CP1 → 3 CP2 → 4 CP3 → 5 终点。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/punches` | 上报打卡：`event_no`、`runner_id`、`station_seq`、`occurred_at` |
| GET | `/api/punches/{event_no}` | 查询单条打卡 |
| PUT | `/api/punches/{event_no}` | 按事件号更正（可改选手/站点/时间），自动重算 |
| DELETE | `/api/punches/{event_no}` | 按事件号撤销，自动重算 |
| GET | `/api/runners/{runner_id}/results` | 选手分段结果 |
| GET | `/api/stations` | 站点列表 |

### 计时规则

- 事件号唯一，重复上报返回 409。
- 同一选手同站多条有效打卡，取**最早**时间。
- 按站点序号顺序计算相邻站分段；乱序补传会自动填补缺段。
- 相邻站缺打卡或时间倒退（后站早于前站）时，该段标记为 `pending` 并在 `reason` 中说明原因；全部分段正常时 `total_duration_seconds` 为总用时，否则为 `null`。
- 更正/撤销后，受影响选手的全部分段立即重算。

### 示例

```bash
# 上报打卡
curl -X POST http://localhost:8000/api/punches \
  -H 'Content-Type: application/json' \
  -d '{"event_no":"EVT-1001","runner_id":"A001","station_seq":3,"occurred_at":"2026-09-25T09:41:00"}'

# 更正（把该打卡改到 CP2）
curl -X PUT http://localhost:8000/api/punches/EVT-1001 \
  -H 'Content-Type: application/json' \
  -d '{"station_seq":2,"occurred_at":"2026-09-25T08:46:00"}'

# 撤销
curl -X DELETE http://localhost:8000/api/punches/EVT-1001

# 查询选手分段结果
curl http://localhost:8000/api/runners/A001/results
```

## 本地开发

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload          # http://localhost:8000
python3 tests/test_service.py          # 核心逻辑测试（仅标准库）
```
