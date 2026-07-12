"""The critical test: no feature may use future information."""
import numpy as np

from otc_lab.config import FeatureConfig
from otc_lab.features.engine import build_features, feature_columns


def test_no_lookahead_truncation_invariance(candles):
    """Features at bar t computed on the full series must equal features at
    bar t computed on the series truncated at t. If any feature peeked at the
    future, truncation would change it."""
    cfg = FeatureConfig()
    full = build_features(candles, cfg)
    fcols = feature_columns(full)

    for t in (500, 1500, 2500):
        truncated = build_features(candles.iloc[: t + 1].reset_index(drop=True), cfg)
        row_full = full.iloc[t][fcols].astype(float).to_numpy()
        row_trunc = truncated.iloc[t][fcols].astype(float).to_numpy()
        np.testing.assert_allclose(row_full, row_trunc, rtol=1e-9, atol=1e-12,
                                   err_msg=f"lookahead detected at bar {t}")


def test_features_do_not_cross_assets(candles_two_assets):
    cfg = FeatureConfig()
    both = build_features(candles_two_assets, cfg)
    single = build_features(
        candles_two_assets[candles_two_assets["asset"] == "GBPUSD"].reset_index(drop=True),
        cfg,
    )
    fcols = feature_columns(both)
    got = both[both["asset"] == "GBPUSD"].reset_index(drop=True)[fcols]
    np.testing.assert_allclose(
        got.to_numpy(dtype=float), single[fcols].to_numpy(dtype=float),
        rtol=1e-9, atol=1e-12, err_msg="feature leakage across asset boundary",
    )


def test_warmup_rows_are_nan(candles):
    full = build_features(candles, FeatureConfig())
    assert full.iloc[0][["f_mom_10", "f_bb_z", "f_realized_vol"]].isna().all()
