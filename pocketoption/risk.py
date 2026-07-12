"""
Risk / money management. Protecting capital is the only part of trading you can
actually control, so this module is deliberately strict.

Guards provided:
  * fixed-fraction or fixed-amount position sizing
  * daily loss limit (stops trading for the session)
  * daily profit target (locks in a good day)
  * max consecutive losses (cool-off)
  * optional martingale with a hard cap (OFF by default — it is dangerous and
    does NOT improve expectancy; it only trades a high win-rate for rare ruin).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RiskConfig:
    starting_balance: float = 1000.0
    # sizing
    stake_mode: str = "fraction"  # "fraction" | "fixed"
    stake_fraction: float = 0.02  # 2% of balance per trade
    fixed_stake: float = 10.0
    min_stake: float = 1.0
    # session guards (as fraction of starting balance)
    daily_loss_limit_pct: float = 0.10  # stop after losing 10%
    daily_profit_target_pct: float = 0.20  # stop after making 20%
    max_consecutive_losses: int = 4
    # martingale (dangerous)
    martingale: bool = False
    martingale_multiplier: float = 2.2  # >1/payout to recover; here for realism
    martingale_max_steps: int = 3


@dataclass
class RiskState:
    balance: float
    session_pnl: float = 0.0
    consecutive_losses: int = 0
    martingale_step: int = 0
    trades: int = 0
    halted: bool = False
    halt_reason: str = ""


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.state = RiskState(balance=cfg.starting_balance)

    # --- decisions -----------------------------------------------------------

    def can_trade(self) -> tuple[bool, str]:
        s, c = self.state, self.cfg
        if s.halted:
            return False, s.halt_reason
        start = c.starting_balance
        if s.session_pnl <= -c.daily_loss_limit_pct * start:
            return self._halt(f"daily loss limit hit ({s.session_pnl:.2f})")
        if s.session_pnl >= c.daily_profit_target_pct * start:
            return self._halt(f"daily profit target hit ({s.session_pnl:.2f})")
        if s.consecutive_losses >= c.max_consecutive_losses:
            return self._halt(f"{s.consecutive_losses} losses in a row — cooling off")
        if s.balance < c.min_stake:
            return self._halt("balance below minimum stake")
        return True, "ok"

    def next_stake(self) -> float:
        s, c = self.state, self.cfg
        if c.stake_mode == "fixed":
            base = c.fixed_stake
        else:
            base = s.balance * c.stake_fraction
        if c.martingale and s.martingale_step > 0:
            step = min(s.martingale_step, c.martingale_max_steps)
            base *= c.martingale_multiplier**step
        stake = max(c.min_stake, round(base, 2))
        return min(stake, s.balance)

    # --- outcome bookkeeping -------------------------------------------------

    def record_win(self, stake: float, payout: float) -> None:
        profit = stake * payout
        s = self.state
        s.balance += profit
        s.session_pnl += profit
        s.consecutive_losses = 0
        s.martingale_step = 0
        s.trades += 1

    def record_loss(self, stake: float) -> None:
        s, c = self.state, self.cfg
        s.balance -= stake
        s.session_pnl -= stake
        s.consecutive_losses += 1
        s.trades += 1
        if c.martingale:
            s.martingale_step = min(s.martingale_step + 1, c.martingale_max_steps)

    def record_tie(self) -> None:
        # broker refunds stake; no change beyond trade count
        self.state.trades += 1

    def _halt(self, reason: str) -> tuple[bool, str]:
        self.state.halted = True
        self.state.halt_reason = reason
        return False, reason
