import numpy as np
import pandas as pd

from otc_lab.config import LabelConfig
from otc_lab.labels.binary import build_labels


def test_label_timing_and_direction(candles):
    cfg = LabelConfig(latency_bars=1, tie_policy="refund")
    ls = build_labels(candles, expiry_bars=2, cfg=cfg)
    f = ls.frame

    # spot-check a few samples against raw candles
    for _, row in f.sample(20, random_state=1).iterrows():
        t, e, x = int(row["signal_idx"]), int(row["entry_idx"]), int(row["horizon_end"])
        assert e == t + 1          # latency 1
        assert x == e + 1          # expiry 2 bars -> close of e+1
        assert row["entry_price"] == candles["open"].iloc[e]
        assert row["expiry_price"] == candles["close"].iloc[x]
        assert bool(row["y_up"]) == (row["expiry_price"] > row["entry_price"])


def test_latency_zero_vs_two(candles):
    l0 = build_labels(candles, 1, LabelConfig(latency_bars=0)).frame
    l2 = build_labels(candles, 1, LabelConfig(latency_bars=2)).frame
    assert (l0["entry_idx"] == l0["signal_idx"]).all()
    assert (l2["entry_idx"] == l2["signal_idx"] + 2).all()


def test_tie_policy_drop(candles):
    df = candles.copy()
    # force a tie: entry open == expiry close for signal at idx 50, latency 1, expiry 1
    df.loc[51, "open"] = 1.2345
    df.loc[51, "close"] = 1.2345
    ls = build_labels(df, 1, LabelConfig(latency_bars=1, tie_policy="drop"))
    assert not ((ls.frame["signal_idx"] == 50)).any()
    ls2 = build_labels(df, 1, LabelConfig(latency_bars=1, tie_policy="refund"))
    tie_row = ls2.frame[ls2.frame["signal_idx"] == 50]
    assert len(tie_row) == 1 and bool(tie_row["is_tie"].iloc[0])


def test_labels_never_bridge_gaps(candles):
    df = candles.drop(index=range(100, 110)).reset_index(drop=True)  # hole
    ls = build_labels(df, expiry_bars=3, cfg=LabelConfig(latency_bars=1))
    f = ls.frame
    # no sample's window may span the gap (positions 97..99 signal into it)
    ts = df["timestamp"].dt.as_unit("s").astype("int64").to_numpy()
    for _, row in f.iterrows():
        t, x = int(row["signal_idx"]), int(row["horizon_end"])
        assert ts[x] - ts[t] == (x - t) * 60, "label bridged a data gap"
