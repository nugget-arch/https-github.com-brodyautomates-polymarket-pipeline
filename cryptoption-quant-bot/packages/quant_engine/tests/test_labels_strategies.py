"""Label timing/tie/gap tests and baseline/model sanity + positive control."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from quant_engine.config import FeatureConfig, LabelConfig
from quant_engine.features import build_features, feature_columns
from quant_engine.labels import build_labels
from quant_engine.strategies import make_model


def _frame(n=300, asset="X", seed=5, edge=0.0):
    rng = np.random.default_rng(seed)
    base = datetime(2024, 1, 1, tzinfo=UTC)
    price, prev = 100.0, 0.0
    rows = []
    for i in range(n):
        eps = rng.normal(0, 0.002)
        ret = edge * prev + eps
        prev = ret
        o = price
        c = max(0.01, o * (1 + ret))
        hi = max(o, c) * 1.001
        lo = min(o, c) * 0.999
        rows.append({"ts_utc": base + timedelta(minutes=i), "asset": asset,
                     "open": o, "high": hi, "low": lo, "close": c, "volume": 10.0,
                     "session_id": "2024-01-01", "is_otc": False})
        price = c
    return pd.DataFrame(rows)


def test_label_timing_and_direction():
    df = _frame()
    ls = build_labels(df, expiry_bars=2, cfg=LabelConfig(latency_bars=1), bar_seconds=60)
    f = ls.frame
    for _, row in f.sample(15, random_state=1).iterrows():
        t, e, x = int(row["signal_idx"]), int(row["entry_idx"]), int(row["horizon_end"])
        assert e == t + 1 and x == e + 1
        assert row["entry_price"] == df["open"].iloc[e]
        assert row["expiry_price"] == df["close"].iloc[x]
        assert bool(row["y_up"]) == (row["expiry_price"] > row["entry_price"])


def test_labels_never_bridge_gaps():
    df = _frame().drop(index=range(100, 108)).reset_index(drop=True)  # hole
    ls = build_labels(df, expiry_bars=3, cfg=LabelConfig(latency_bars=1), bar_seconds=60)
    sec = df["ts_utc"].dt.as_unit("s").astype("int64").to_numpy()
    for _, row in ls.frame.iterrows():
        t, x = int(row["signal_idx"]), int(row["horizon_end"])
        assert sec[x] - sec[t] == (x - t) * 60


def test_tie_policy_exclude_drops_ties():
    df = _frame()
    df.loc[51, "open"] = 1.5
    df.loc[51, "close"] = 1.5  # entry==expiry for signal 50, lat1, exp1
    ls = build_labels(df, 1, LabelConfig(latency_bars=1, tie_policy="EXCLUDE"), 60)
    assert not (ls.frame["signal_idx"] == 50).any()


def _xy(df, expiry=1):
    feats = build_features(df, FeatureConfig())
    fcols = feature_columns(feats)
    ls = build_labels(feats, expiry, LabelConfig(latency_bars=1), 60)
    m = ls.frame.dropna(subset=[])
    x = feats.iloc[m["signal_idx"].to_numpy()][fcols].reset_index(drop=True).dropna()
    y = m["y_up"].to_numpy()[: len(x)]
    return x, y[: len(x)], fcols


def test_models_expose_version_and_schema():
    df = _frame()
    x, y, _ = _xy(df)
    for name in ("random", "trend", "meanrev", "logistic"):
        m = make_model(name, seed=1).fit(x, y)
        p = m.predict_proba(x)
        assert p.shape[0] == len(x)
        assert ((p >= 0) & (p <= 1)).all()
        assert m.get_version().startswith(name)
        assert isinstance(m.get_feature_schema(), list)
        assert "n_train" in m.get_training_metadata()


def test_positive_control_logistic_beats_random_in_sample():
    # Injected AR(1) signal -> a fitted model should classify better than random.
    df = _frame(n=1500, edge=0.4)
    x, y, _ = _xy(df)
    logi = make_model("logistic", seed=1).fit(x, y)
    rand = make_model("random", seed=1).fit(x, y)
    acc_l = ((logi.predict_proba(x) >= 0.5).astype(int) == y).mean()
    acc_r = ((rand.predict_proba(x) >= 0.5).astype(int) == y).mean()
    assert acc_l > acc_r + 0.03
