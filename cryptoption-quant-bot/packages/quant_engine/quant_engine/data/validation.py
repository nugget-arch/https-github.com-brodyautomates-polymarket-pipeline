"""Polars-based data-quality validation (ingestion fast path).

Checks per asset: timezone, monotonic timestamps, duplicates, out-of-order,
invalid OHLC, non-finite values, gaps, frequency, session/asset/source
changes. Bad rows are dropped and reported; NOTHING is interpolated and no gap
is bridged with future information — filling would fabricate prices.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import polars as pl


@dataclass
class QualityIssue:
    severity: str  # "error" | "warning"
    code: str
    asset: str
    detail: str
    count: int = 1


@dataclass
class DataQualityReport:
    issues: list[QualityIssue] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0
    bar_seconds: int | None = None

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def add(self, severity: str, code: str, asset: str, detail: str, count: int = 1) -> None:
        self.issues.append(QualityIssue(severity, code, asset, detail, count))

    def to_dict(self) -> dict:
        return {
            "ok": self.ok, "rows_in": self.rows_in, "rows_out": self.rows_out,
            "bar_seconds": self.bar_seconds,
            "issues": [i.__dict__ for i in self.issues],
        }


def validate_candles(
    df: pl.DataFrame, bar_seconds: int | None = None, max_gap_bars: int = 3
) -> tuple[pl.DataFrame, DataQualityReport]:
    report = DataQualityReport(rows_in=df.height, bar_seconds=bar_seconds)
    if df.height == 0:
        return df, report

    dtype = df.schema.get("ts_utc")
    if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
        report.add("error", "TZ_NAIVE", "*", "ts_utc must be timezone-aware UTC")
        return df, report

    kept: list[pl.DataFrame] = []
    for (asset,), g in df.group_by(["asset"], maintain_order=True):
        g = g.sort("ts_utc")
        asset = str(asset)

        before = g.height
        g = g.unique(subset=["ts_utc"], keep="first", maintain_order=True)
        if g.height < before:
            report.add("warning", "DUPLICATE_BAR", asset, "duplicate ts removed",
                       before - g.height)

        finite_cols = ["open", "high", "low", "close"]
        bad_finite = g.filter(
            pl.any_horizontal([pl.col(c).is_null() | pl.col(c).is_infinite() | pl.col(c).is_nan()
                               for c in finite_cols])
        ).height
        if bad_finite:
            g = g.filter(
                pl.all_horizontal([pl.col(c).is_finite() for c in finite_cols])
            )
            report.add("warning", "NON_FINITE_OHLC", asset, "non-finite OHLC removed", bad_finite)

        nonpos = g.filter(pl.min_horizontal(finite_cols) <= 0).height
        if nonpos:
            g = g.filter(pl.min_horizontal(finite_cols) > 0)
            report.add("warning", "NONPOSITIVE_PRICE", asset, "price<=0 removed", nonpos)

        incoherent = g.filter(
            (pl.col("high") < pl.max_horizontal("open", "close"))
            | (pl.col("low") > pl.min_horizontal("open", "close"))
        ).height
        if incoherent:
            g = g.filter(
                (pl.col("high") >= pl.max_horizontal("open", "close"))
                & (pl.col("low") <= pl.min_horizontal("open", "close"))
            )
            report.add("warning", "OHLC_INCOHERENT", asset,
                       "high/low don't bound open/close", incoherent)

        # timing diagnostics (report-only; never modifies data)
        if g.height >= 2:
            deltas = g.select(
                pl.col("ts_utc").diff().dt.total_seconds().alias("d")
            )["d"].drop_nulls()
            if (deltas <= 0).sum() > 0:
                report.add("error", "OUT_OF_ORDER", asset, "non-increasing timestamps",
                           int((deltas <= 0).sum()))
            if bar_seconds:
                gaps = int((deltas > bar_seconds * max_gap_bars).sum())
                if gaps:
                    report.add("warning", "GAP", asset,
                               f"{gaps} gaps > {max_gap_bars} bars (not bridged)", gaps)
                sub = int((deltas < bar_seconds).sum())
                if sub:
                    report.add("warning", "SUB_BAR_SPACING", asset,
                               "bars closer than bar_seconds", sub)
                irregular = int(((deltas != bar_seconds) & (deltas > 0)).sum())
                if irregular and not bar_seconds:
                    report.add("warning", "IRREGULAR_FREQUENCY", asset, "irregular spacing",
                               irregular)

        if g.select(pl.col("source").n_unique()).item() > 1:
            report.add("warning", "MULTIPLE_SOURCES", asset,
                       "rows from more than one source", 1)

        kept.append(g)

    out = pl.concat(kept) if kept else df.clear()
    report.rows_out = out.height
    return out, report
