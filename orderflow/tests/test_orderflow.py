"""Offline unit tests for OrderFlow Pro server math (no network).

Run:  python3 -m unittest discover -s orderflow/tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server  # noqa: E402


def kline(open_t, o, h, l, c, vol, taker_buy):
    """Build a Binance-shaped kline row."""
    return [open_t, str(o), str(h), str(l), str(c), str(vol),
            open_t + 59_999, "0", 100, str(taker_buy), "0", "0"]


class ParseCandlesTest(unittest.TestCase):
    def test_delta_is_taker_buy_minus_sell(self):
        raw = [kline(0, 100, 101, 99, 100.5, 10.0, 7.0)]
        c = server.parse_candles(raw)[0]
        self.assertAlmostEqual(c["v"], 10.0)
        self.assertAlmostEqual(c["delta"], 2 * 7.0 - 10.0)  # +4.0
        self.assertEqual(c["o"], 100.0)
        self.assertEqual(c["c"], 100.5)


class VolumeProfileTest(unittest.TestCase):
    def test_profile_sums_to_total_volume(self):
        raw = [kline(0, 100, 110, 90, 105, 20.0, 12.0),
               kline(60000, 105, 115, 100, 108, 30.0, 10.0)]
        candles = server.parse_candles(raw)
        prof = server.volume_profile(candles, bins=50)
        total = sum(p["vol"] for p in prof["profile"])
        self.assertAlmostEqual(total, 50.0, places=3)
        self.assertLessEqual(prof["val"], prof["vpoc"])
        self.assertLessEqual(prof["vpoc"], prof["vah"])

    def test_buy_sell_split_matches_delta(self):
        raw = [kline(0, 100, 110, 90, 105, 20.0, 15.0)]  # taker buy 15 -> delta +10
        candles = server.parse_candles(raw)
        prof = server.volume_profile(candles, bins=40)
        buy = sum(p["buy"] for p in prof["profile"])
        sell = sum(p["sell"] for p in prof["profile"])
        self.assertAlmostEqual(buy, 15.0, places=3)
        self.assertAlmostEqual(sell, 5.0, places=3)


class ValueAreaTest(unittest.TestCase):
    def test_poc_is_highest_volume_level(self):
        prof = [{"price": 10, "vol": 1, "buy": 1, "sell": 0},
                {"price": 11, "vol": 9, "buy": 5, "sell": 4},
                {"price": 12, "vol": 2, "buy": 1, "sell": 1}]
        vpoc, vah, val = server.value_area(prof, share=0.70)
        self.assertEqual(vpoc, 11)
        self.assertLessEqual(val, vpoc)
        self.assertLessEqual(vpoc, vah)


class BasetickTest(unittest.TestCase):
    def test_scales_with_price(self):
        self.assertEqual(server.suggest_basetick(77000), 1.0)      # BTC
        self.assertAlmostEqual(server.suggest_basetick(3000), 0.1)  # ETH
        self.assertAlmostEqual(server.suggest_basetick(150), 0.01)  # SOL
        self.assertGreater(server.suggest_basetick(0.5), 0)         # never zero


class IntervalTest(unittest.TestCase):
    def test_known_intervals(self):
        self.assertEqual(server.INTERVAL_MS["1m"], 60_000)
        self.assertEqual(server.INTERVAL_MS["1h"], 3_600_000)


if __name__ == "__main__":
    unittest.main()
