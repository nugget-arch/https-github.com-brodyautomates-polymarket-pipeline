"""Data-quality REST: validate an uploaded candle payload via the Polars engine."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from quant_engine.data import validate_candles

from ..auth.dependencies import current_user
from ..domain.models import User

router = APIRouter(prefix="/api/v1/data-quality", tags=["data-quality"])


class CandleIn(BaseModel):
    ts_utc: datetime
    asset: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    source: str = "upload"


class ValidateRequest(BaseModel):
    bar_seconds: int = 60
    candles: list[CandleIn]


@router.post("/validate")
async def validate(req: ValidateRequest, _user: User = Depends(current_user)) -> dict[str, Any]:
    import polars as pl

    if not req.candles:
        return {"ok": True, "rows_in": 0, "rows_out": 0, "bar_seconds": req.bar_seconds,
                "issues": []}
    df = pl.DataFrame([c.model_dump() for c in req.candles]).with_columns(
        pl.col("ts_utc").cast(pl.Datetime(time_zone="UTC"))
    )
    _, report = validate_candles(df, bar_seconds=req.bar_seconds)
    result: dict[str, Any] = report.to_dict()
    return result
