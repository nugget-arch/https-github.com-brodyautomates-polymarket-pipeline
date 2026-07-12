"""Data-quality validation: timestamps, OHLC coherence, duplicates, gaps, tz."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import DataConfig
from ..logging_setup import get_logger

log = get_logger("data.validate")


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning"
    code: str
    asset: str
    detail: str
    count: int = 1


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)
    rows_in: int = 0
    rows_out: int = 0

    @property
    def ok(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def summary(self) -> str:
        lines = [f"rows in={self.rows_in} out={self.rows_out} ok={self.ok}"]
        for i in self.issues:
            lines.append(f"  [{i.severity}] {i.code} {i.asset}: {i.detail} (x{i.count})")
        return "\n".join(lines)


def validate_candles(
    df: pd.DataFrame, cfg: DataConfig | None = None, drop_bad: bool = True
) -> tuple[pd.DataFrame, ValidationReport]:
    """Validate the canonical candle frame per asset.

    Checks: tz-aware UTC, monotonic timestamps, duplicates, NaNs, OHLC sanity
    (high >= max(o,c), low <= min(o,c), positive prices), and gaps larger than
    `max_gap_bars`. Gaps are *reported*, never forward-filled: filling gaps
    would fabricate prices.
    """
    cfg = cfg or DataConfig()
    report = ValidationReport(rows_in=len(df))
    issues = report.issues

    if df["timestamp"].dt.tz is None:  # pragma: no cover - loader always sets tz
        issues.append(ValidationIssue("error", "TZ_NAIVE", "*", "timestamps lack timezone"))
        return df, report

    keep_parts: list[pd.DataFrame] = []
    for asset, g in df.groupby("asset", sort=False):
        g = g.sort_values("timestamp", kind="stable")

        dup = g.duplicated(subset=["timestamp"], keep="first")
        if dup.any():
            issues.append(ValidationIssue("warning", "DUPLICATE_BAR", asset,
                                          "duplicate timestamps removed", int(dup.sum())))
            g = g[~dup]

        nan_rows = g[["open", "high", "low", "close"]].isna().any(axis=1)
        if nan_rows.any():
            issues.append(ValidationIssue("warning", "NAN_OHLC", asset,
                                          "rows with NaN OHLC removed", int(nan_rows.sum())))
            g = g[~nan_rows]

        nonpos = (g[["open", "high", "low", "close"]] <= 0).any(axis=1)
        if nonpos.any():
            issues.append(ValidationIssue("warning", "NONPOSITIVE_PRICE", asset,
                                          "rows with price <= 0 removed", int(nonpos.sum())))
            g = g[~nonpos]

        bad_hl = (g["high"] < g[["open", "close"]].max(axis=1)) | (
            g["low"] > g[["open", "close"]].min(axis=1)
        )
        if bad_hl.any():
            issues.append(ValidationIssue("warning", "OHLC_INCOHERENT", asset,
                                          "bars where high/low don't bound open/close removed",
                                          int(bad_hl.sum())))
            g = g[~bad_hl]

        if not g["timestamp"].is_monotonic_increasing:
            issues.append(ValidationIssue("error", "NON_MONOTONIC", asset,
                                          "timestamps not sorted after dedup"))

        deltas = g["timestamp"].diff().dt.total_seconds().dropna()
        expected = float(cfg.bar_seconds)
        gaps = deltas[deltas > expected * cfg.max_gap_bars]
        if len(gaps):
            issues.append(ValidationIssue(
                "warning", "GAP", asset,
                f"{len(gaps)} gaps > {cfg.max_gap_bars} bars (max {gaps.max():.0f}s); "
                "kept as-is, features/labels must not bridge them", len(gaps)))
        sub_bar = deltas[deltas < expected]
        if len(sub_bar):
            issues.append(ValidationIssue("warning", "SUB_BAR_SPACING", asset,
                                          "bars closer together than bar_seconds", len(sub_bar)))

        keep_parts.append(g)

    out = pd.concat(keep_parts, ignore_index=True) if keep_parts else df.iloc[0:0]
    if not drop_bad:
        out = df
    report.rows_out = len(out)
    log.info("validation done", extra={"ctx_ok": report.ok, "ctx_issues": len(issues)})
    return out, report
