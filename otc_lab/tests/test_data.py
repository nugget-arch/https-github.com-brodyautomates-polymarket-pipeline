import numpy as np
import pandas as pd
import pytest

from otc_lab.config import DataConfig
from otc_lab.data.loader import load_candles, split_holdout
from otc_lab.data.resample import resample_ohlc
from otc_lab.data.validate import validate_candles


def test_validate_clean_data_ok(candles):
    out, report = validate_candles(candles, DataConfig())
    assert report.ok
    assert len(out) == len(candles)


def test_validate_catches_duplicates_and_bad_ohlc(candles):
    df = candles.copy()
    df = pd.concat([df, df.iloc[[10]]], ignore_index=True)  # duplicate ts
    df.loc[20, "high"] = df.loc[20, ["open", "close"]].min() - 1  # incoherent
    out, report = validate_candles(df, DataConfig())
    codes = {i.code for i in report.issues}
    assert "DUPLICATE_BAR" in codes
    assert "OHLC_INCOHERENT" in codes
    assert len(out) == len(candles) - 1  # dup dropped + bad bar dropped


def test_validate_reports_gaps(candles):
    df = candles.drop(index=range(100, 120)).reset_index(drop=True)  # 20-bar hole
    _, report = validate_candles(df, DataConfig())
    assert any(i.code == "GAP" for i in report.issues)


def test_otc_flag_from_asset_name(tmp_path, candles):
    p = tmp_path / "eurusd_otc.csv"
    candles.drop(columns=["is_otc", "session"]).to_csv(p, index=False)
    df = load_candles([p], DataConfig())
    assert df["is_otc"].all()


def test_holdout_split_is_final_segment(candles):
    cfg = DataConfig(holdout_fraction=0.2)
    research, holdout = split_holdout(candles, cfg)
    assert len(holdout) == pytest.approx(len(candles) * 0.2, abs=1)
    assert research["timestamp"].max() < holdout["timestamp"].min()


def test_resample_drops_partial_bars(candles):
    df = candles.iloc[:1003]  # not a multiple of 5
    out = resample_ohlc(df, target_seconds=300, source_seconds=60)
    assert len(out) == 200  # 1000 // 5, trailing partial dropped
    assert (out["available_at"] - out["timestamp"]).dt.total_seconds().eq(300).all()
    # OHLC coherence preserved
    assert (out["high"] >= out[["open", "close"]].max(axis=1)).all()
