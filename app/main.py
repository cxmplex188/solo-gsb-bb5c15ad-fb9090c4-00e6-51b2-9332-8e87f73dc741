"""FastAPI 入口：越野赛分段计时 API。"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

from . import db, service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 容器启动时初始化数据库与演示数据（SEED_DEMO_DATA=0 可关闭演示数据）
    db.init_db(seed_demo=os.environ.get("SEED_DEMO_DATA", "1") != "0")
    yield


app = FastAPI(
    title="越野赛分段计时 API",
    version="1.0.0",
    lifespan=lifespan,
)


class PunchIn(BaseModel):
    event_no: str = Field(..., description="唯一事件号")
    runner_id: str = Field(..., description="选手号")
    station_seq: int = Field(..., description="站点序号")
    occurred_at: datetime = Field(..., description="发生时间 ISO 8601")


class PunchCorrection(BaseModel):
    runner_id: str | None = None
    station_seq: int | None = None
    occurred_at: datetime | None = None


@app.get("/api/stations")
def list_stations():
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT seq, name FROM stations ORDER BY seq")]


@app.post("/api/punches", status_code=status.HTTP_201_CREATED)
def create_punch(p: PunchIn):
    with db.get_conn() as conn:
        try:
            return service.create_punch(
                conn, p.event_no, p.runner_id, p.station_seq, p.occurred_at)
        except service.ConflictError as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
        except service.NotFoundError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@app.get("/api/punches/{event_no}")
def get_punch(event_no: str):
    with db.get_conn() as conn:
        try:
            return service.get_punch(conn, event_no)
        except service.NotFoundError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@app.put("/api/punches/{event_no}")
def correct_punch(event_no: str, c: PunchCorrection):
    """按事件号更正打卡（可改选手、站点、时间），自动重算受影响结果。"""
    with db.get_conn() as conn:
        try:
            return service.correct_punch(
                conn, event_no, c.runner_id, c.station_seq, c.occurred_at)
        except service.NotFoundError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@app.delete("/api/punches/{event_no}")
def revoke_punch(event_no: str):
    """按事件号撤销打卡，自动重算受影响结果。"""
    with db.get_conn() as conn:
        try:
            return service.revoke_punch(conn, event_no)
        except service.NotFoundError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@app.get("/api/runners/{runner_id}/results")
def runner_results(runner_id: str):
    """查询选手分段结果：各站通过时间、相邻站分段用时、待定段及原因。"""
    with db.get_conn() as conn:
        try:
            return service.get_runner_results(conn, runner_id)
        except service.NotFoundError as e:
            raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))
