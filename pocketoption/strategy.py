"""
Trading strategy: a multi-indicator *confluence* model that outputs a discrete
binary-options signal (CALL / PUT / NONE) plus a confidence score in [0, 1].

The idea is to only fire when several independent read-outs agree, which raises
the directional win-rate at the cost of trading less often. Two regimes are
supported:

  * "trend"     — trade in the direction of the EMA trend on momentum pushes.
  * "reversion" — fade stretched moves back to the mean (Bollinger + Stoch/RSI).

Nothing here is magic. Whether it is profitable on a given asset/timeframe is an
empirical question — run `BinaryBacktester` and let the numbers decide.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from . import indicators as ind
from .data import Candles

Direction = Literal["CALL", "PUT", "NONE"]


@dataclass
class Signal:
    direction: Direction
    confidence: float  # 0..1
    reasons: list[str] = field(default_factory=list)

    @property
    def is_trade(self) -> bool:
        return self.direction != "NONE"


@dataclass
class StrategyConfig:
    regime: Literal["trend", "reversion"] = "trend"
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    bb_period: int = 20
    bb_mult: float = 2.0
    stoch_k: int = 14
    stoch_d: int = 3
    atr_period: int = 14
    # only trade when volatility (ATR / price) is within this band, to avoid dead
    # or chaotic markets. Set min to 0 / max to a big number to disable.
    min_vol_pct: float = 0.0
    max_vol_pct: float = 1.0
    # minimum confidence required to actually place a trade
    min_confidence: float = 0.6


class ConfluenceStrategy:
    """Precomputes indicators once, then evaluates a signal per candle index."""

    def __init__(self, candles: Candles, cfg: StrategyConfig | None = None):
        self.candles = candles
        self.cfg = cfg or StrategyConfig()
        c = candles.closes
        self.ema_fast = ind.ema(c, self.cfg.ema_fast)
        self.ema_slow = ind.ema(c, self.cfg.ema_slow)
        self.rsi = ind.rsi(c, self.cfg.rsi_period)
        self.bb_up, self.bb_mid, self.bb_lo = ind.bollinger(
            c, self.cfg.bb_period, self.cfg.bb_mult
        )
        self.k, self.d = ind.stochastic(
            candles.highs, candles.lows, c, self.cfg.stoch_k, self.cfg.stoch_d
        )
        self.atr = ind.atr(candles.highs, candles.lows, c, self.cfg.atr_period)
        self._min_i = max(
            self.cfg.ema_slow,
            self.cfg.rsi_period,
            self.cfg.bb_period,
            self.cfg.stoch_k,
            self.cfg.atr_period,
        ) + 2

    def ready_from(self) -> int:
        """First index at which every indicator is defined."""
        return self._min_i

    def evaluate(self, i: int) -> Signal:
        cfg = self.cfg
        if i < self._min_i or i >= len(self.candles):
            return Signal("NONE", 0.0, ["warm-up"])

        # volatility gate
        price = self.candles.closes[i]
        atr_v = self.atr[i]
        if atr_v is not None and price > 0:
            vol_pct = atr_v / price
            if not (cfg.min_vol_pct <= vol_pct <= cfg.max_vol_pct):
                return Signal("NONE", 0.0, [f"vol {vol_pct:.4f} out of band"])

        if cfg.regime == "trend":
            sig = self._trend(i)
        else:
            sig = self._reversion(i)

        if sig.confidence < cfg.min_confidence:
            return Signal("NONE", sig.confidence, sig.reasons + ["below min_confidence"])
        return sig

    # --- regimes -------------------------------------------------------------

    def _trend(self, i: int) -> Signal:
        c = self.candles.closes
        ef, es = self.ema_fast[i], self.ema_slow[i]
        rsi_v = self.rsi[i]
        k, d = self.k[i], self.d[i]
        macd_ok_up = c[i] > c[i - 1]  # simple momentum confirm
        macd_ok_dn = c[i] < c[i - 1]

        up_votes: list[str] = []
        dn_votes: list[str] = []

        if ef is not None and es is not None:
            if ef > es:
                up_votes.append("EMA fast>slow")
            elif ef < es:
                dn_votes.append("EMA fast<slow")
        if rsi_v is not None:
            if 50 <= rsi_v < self.cfg.rsi_overbought:
                up_votes.append(f"RSI {rsi_v:.0f} bullish")
            elif self.cfg.rsi_oversold < rsi_v <= 50:
                dn_votes.append(f"RSI {rsi_v:.0f} bearish")
        if k is not None and d is not None:
            if k > d and k < 80:
                up_votes.append("Stoch %K>%D")
            elif k < d and k > 20:
                dn_votes.append("Stoch %K<%D")
        if macd_ok_up:
            up_votes.append("last candle up")
        if macd_ok_dn:
            dn_votes.append("last candle down")

        return self._resolve(up_votes, dn_votes, total=4)

    def _reversion(self, i: int) -> Signal:
        c = self.candles.closes
        up, mid, lo = self.bb_up[i], self.bb_mid[i], self.bb_lo[i]
        rsi_v = self.rsi[i]
        k, d = self.k[i], self.d[i]
        price = c[i]

        up_votes: list[str] = []  # expect bounce up (CALL)
        dn_votes: list[str] = []  # expect drop (PUT)

        if lo is not None and price <= lo:
            up_votes.append("price<=lower BB")
        if up is not None and price >= up:
            dn_votes.append("price>=upper BB")
        if rsi_v is not None:
            if rsi_v <= self.cfg.rsi_oversold:
                up_votes.append(f"RSI {rsi_v:.0f} oversold")
            elif rsi_v >= self.cfg.rsi_overbought:
                dn_votes.append(f"RSI {rsi_v:.0f} overbought")
        if k is not None and d is not None:
            if k <= 20 and k > d:
                up_votes.append("Stoch turning up from oversold")
            elif k >= 80 and k < d:
                dn_votes.append("Stoch turning down from overbought")

        return self._resolve(up_votes, dn_votes, total=3)

    def _resolve(self, up_votes: list[str], dn_votes: list[str], total: int) -> Signal:
        up, dn = len(up_votes), len(dn_votes)
        if up > dn and up > 0:
            return Signal("CALL", min(1.0, up / total), up_votes)
        if dn > up and dn > 0:
            return Signal("PUT", min(1.0, dn / total), dn_votes)
        return Signal("NONE", 0.0, ["no confluence"])
