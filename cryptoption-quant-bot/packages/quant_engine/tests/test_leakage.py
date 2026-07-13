"""Anti-leakage tests — the most important tests in the whole engine.

If any feature peeked at the future, mutating a later bar would change an
earlier feature row. These tests prove that cannot happen.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from quant_engine.config import FeatureConfig
from quant_engine.features import audit_features, build_features, feature_columns


def _synth_frame(n: int = 400, asset: str = "BTCUSDT", seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    price = 100.0
    rows = []
    for i in range(n):
        ret = rng.normal(0, 0.002)
        o = price
        c = max(0.01, o * (1 + ret))
        hi = max(o, c) * (1 + abs(rng.normal(0, 0.001)))
        lo = min(o, c) * (1 - abs(rng.normal(0, 0.001)))
        rows.append({"ts_utc": base + timedelta(minutes=i), "asset": asset,
                     "open": o, "high": hi, "low": lo, "close": c,
                     "volume": rng.uniform(10, 100), "session_id": "2024-01-01",
                     "is_otc": False})
        price = c
    return pd.DataFrame(rows)


def test_no_lookahead_truncation_invariance():
    cfg = FeatureConfig()
    df = _synth_frame()
    full = build_features(df, cfg)
    fcols = feature_columns(full)
    for t in (120, 250, 399):
        trunc = build_features(df.iloc[: t + 1].reset_index(drop=True), cfg)
        a = full.iloc[t][fcols].astype(float).to_numpy()
        b = trunc.iloc[t][fcols].astype(float).to_numpy()
        np.testing.assert_allclose(a, b, rtol=1e-9, atol=1e-12,
                                   err_msg=f"look-ahead at bar {t}")


def test_mutating_the_future_never_changes_the_past():
    """Directly perturb every bar after t and assert row t's features are
    byte-for-byte identical."""
    cfg = FeatureConfig()
    df = _synth_frame()
    t = 200
    full = build_features(df, cfg)
    fcols = feature_columns(full)
    before = full.iloc[t][fcols].astype(float).to_numpy()

    mutated = df.copy()
    mutated.loc[t + 1:, ["open", "high", "low", "close"]] *= 1.5  # wreck the future
    after = build_features(mutated, cfg).iloc[t][fcols].astype(float).to_numpy()
    np.testing.assert_array_equal(before, after)


def test_features_do_not_cross_assets():
    cfg = FeatureConfig()
    a = _synth_frame(asset="BTCUSDT", seed=1)
    b = _synth_frame(asset="ETHUSDT", seed=2)
    both = build_features(pd.concat([a, b], ignore_index=True), cfg)
    single = build_features(b.copy(), cfg)
    fcols = feature_columns(both)
    got = both[both["asset"] == "ETHUSDT"].reset_index(drop=True)[fcols]
    np.testing.assert_allclose(got.to_numpy(float), single[fcols].to_numpy(float),
                               rtol=1e-9, atol=1e-12)


def test_warmup_rows_are_nan_not_filled():
    full = build_features(_synth_frame(), FeatureConfig())
    assert full.iloc[0][["f_ret_60", "f_bb_z", "f_realized_vol"]].isna().all()


def test_feature_audit_reports_no_lookahead():
    full = build_features(_synth_frame(), FeatureConfig())
    audit = audit_features(full, bar_seconds=60)
    assert audit.ok  # no negative shift, no "review" risk
    names = {r["name"] for r in audit.rows}
    assert "f_rsi" in names and "f_ema_dist" in names
    assert all(r["shift"] >= 0 for r in audit.rows)
