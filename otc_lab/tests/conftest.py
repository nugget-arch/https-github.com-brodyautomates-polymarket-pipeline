import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from otc_lab.data.synthetic import make_asset_frame  # noqa: E402


@pytest.fixture(scope="session")
def candles():
    """Small deterministic OTC-like series for unit tests."""
    return make_asset_frame("EURUSD_OTC", n_bars=3000, seed=11, is_otc=True)


@pytest.fixture(scope="session")
def candles_two_assets():
    import pandas as pd

    a = make_asset_frame("EURUSD_OTC", n_bars=3000, seed=11, is_otc=True)
    b = make_asset_frame("GBPUSD", n_bars=3000, seed=12, is_otc=False, start_price=1.27)
    return pd.concat([a, b], ignore_index=True)
