"""FeatureAvailabilityAudit.

For every feature we register: name, input columns, lookback (bars needed
before it is defined), shift (how far back the newest input sits — must be >= 0;
a negative shift would be look-ahead), first available timestamp, frequency,
leakage risk, and implementation version. The audit is data used by the
anti-leakage tests and shown in the experiment report.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .engine import FEATURE_PREFIX, feature_columns

AUDIT_VERSION = "1.0.0"


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    input_columns: tuple[str, ...]
    lookback: int
    shift: int              # newest input bar offset; 0 = current closed bar
    leakage_risk: str       # "none" | "low" | "review"
    version: str = AUDIT_VERSION


# Static registry of the shift/lookback characteristics of each feature family.
# shift is 0 for all: every feature reads only the current and older closed bars.
_SPECS: dict[str, FeatureSpec] = {
    "logret_1": FeatureSpec("logret_1", ("close",), 1, 0, "none"),
    "ema_dist": FeatureSpec("ema_dist", ("close",), 21, 0, "none"),
    "ema_fast_slope": FeatureSpec("ema_fast_slope", ("close",), 9, 0, "none"),
    "close_vs_ema_fast": FeatureSpec("close_vs_ema_fast", ("close",), 9, 0, "none"),
    "rsi": FeatureSpec("rsi", ("close",), 14, 0, "none"),
    "atr_norm": FeatureSpec("atr_norm", ("high", "low", "close"), 14, 0, "none"),
    "realized_vol": FeatureSpec("realized_vol", ("close",), 20, 0, "none"),
    "bb_z": FeatureSpec("bb_z", ("close",), 20, 0, "none"),
    "slope": FeatureSpec("slope", ("close",), 12, 0, "none"),
    "range_norm": FeatureSpec("range_norm", ("high", "low", "close"), 1, 0, "none"),
    "body_frac": FeatureSpec("body_frac", ("open", "close", "high", "low"), 1, 0, "none"),
    "upper_wick": FeatureSpec("upper_wick", ("open", "high", "low", "close"), 1, 0, "none"),
    "lower_wick": FeatureSpec("lower_wick", ("open", "high", "low", "close"), 1, 0, "none"),
    "close_pos_in_range": FeatureSpec("close_pos_in_range", ("high", "low", "close"), 1, 0, "none"),
    "volume_rel": FeatureSpec("volume_rel", ("volume",), 20, 0, "none"),
    "trade_imbalance_proxy": FeatureSpec(
        "trade_imbalance_proxy", ("open", "close", "high", "low"), 1, 0, "low"),
    "trade_intensity_proxy": FeatureSpec("trade_intensity_proxy", ("volume",), 20, 0, "low"),
    "spread_norm": FeatureSpec("spread_norm", ("bid", "ask", "close"), 1, 0, "none"),
    "spread_change": FeatureSpec("spread_change", ("bid", "ask", "close"), 1, 0, "none"),
    "tod_sin": FeatureSpec("tod_sin", ("ts_utc",), 0, 0, "none"),
    "tod_cos": FeatureSpec("tod_cos", ("ts_utc",), 0, 0, "none"),
    "dow_sin": FeatureSpec("dow_sin", ("ts_utc",), 0, 0, "none"),
    "dow_cos": FeatureSpec("dow_cos", ("ts_utc",), 0, 0, "none"),
    "vol_regime_z": FeatureSpec("vol_regime_z", ("close",), 80, 0, "none"),
    "trend_regime": FeatureSpec("trend_regime", ("close",), 21, 0, "none"),
}


@dataclass
class FeatureAvailabilityAudit:
    rows: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        # Any negative shift is look-ahead; any "review" risk fails the gate.
        return all(r["shift"] >= 0 and r["leakage_risk"] != "review" for r in self.rows)

    def to_dict(self) -> dict:
        return {"ok": self.ok, "version": AUDIT_VERSION, "features": self.rows}


def audit_features(df: pd.DataFrame, bar_seconds: int | None = None) -> FeatureAvailabilityAudit:
    """Build an availability audit from a features frame."""
    audit = FeatureAvailabilityAudit()
    for col in feature_columns(df):
        base = col[len(FEATURE_PREFIX):]
        # multi-horizon families share a spec key prefix (ret_/mom_)
        spec_key = base
        if base.startswith(("ret_", "mom_")):
            spec_key = "logret_1"
        spec = _SPECS.get(spec_key)
        series = df[col]
        first_valid = series.first_valid_index()
        first_ts = None
        if first_valid is not None and "ts_utc" in df.columns:
            first_ts = str(df.loc[first_valid, "ts_utc"])
        audit.rows.append({
            "name": col,
            "input_columns": list(spec.input_columns) if spec else [],
            "lookback": spec.lookback if spec else None,
            "shift": spec.shift if spec else 0,
            "first_available_ts": first_ts,
            "frequency_seconds": bar_seconds,
            "leakage_risk": spec.leakage_risk if spec else "review",
            "version": AUDIT_VERSION,
        })
    return audit
