"""RiskManager — anti-martingale by construction.

stake = capital * risk_fraction, where risk_fraction NEVER reads past trade
outcomes except to REDUCE exposure (drawdown scaling). There is no code path in
which a loss increases the next stake. This property is asserted by tests.

Guards: daily loss limit, consecutive-loss cool-off, session trade cap, kill
switch (programmatic or file), drawdown-based exposure reduction.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import RiskConfig


@dataclass
class RiskDecision:
    allowed: bool
    stake: float
    reason: str


class RiskManager:
    def __init__(self, cfg: RiskConfig, kill_switch_file: str | None = None):
        self.cfg = cfg
        self.capital = cfg.initial_capital
        self.peak_capital = cfg.initial_capital
        self.kill_switch_file = kill_switch_file
        self._session: str | None = None
        self._session_pnl = 0.0
        self._session_trades = 0
        self._consecutive_losses = 0
        self._cooldown_until_bar = -1
        self._killed = False

    # --- controls --------------------------------------------------------
    def kill(self) -> None:
        self._killed = True

    def _kill_active(self) -> bool:
        if self._killed:
            return True
        return bool(self.kill_switch_file and Path(self.kill_switch_file).exists())

    def _new_session(self, session: str) -> None:
        if session != self._session:
            self._session = session
            self._session_pnl = 0.0
            self._session_trades = 0
            self._consecutive_losses = 0

    # --- pre-trade gate --------------------------------------------------
    def pre_trade(self, session: str, bar_index: int) -> RiskDecision:
        self._new_session(session)
        c = self.cfg
        if self._kill_active():
            return RiskDecision(False, 0.0, "KILL_SWITCH")
        if bar_index < self._cooldown_until_bar:
            return RiskDecision(False, 0.0, "COOLDOWN")
        if self._session_trades >= c.max_trades_per_session:
            return RiskDecision(False, 0.0, "SESSION_TRADE_CAP")
        if self._session_pnl <= -c.daily_loss_limit * c.initial_capital:
            return RiskDecision(False, 0.0, "DAILY_LOSS_LIMIT")
        if self._consecutive_losses >= c.max_consecutive_losses:
            self._cooldown_until_bar = bar_index + c.cooldown_bars
            self._consecutive_losses = 0
            return RiskDecision(False, 0.0, "MAX_CONSECUTIVE_LOSSES")

        frac = min(c.risk_per_trade, c.max_risk_per_trade)
        drawdown = 1.0 - self.capital / self.peak_capital if self.peak_capital > 0 else 0.0
        if drawdown > c.drawdown_soft_limit:
            frac *= c.drawdown_scale  # REDUCE exposure; never increase
        stake = round(self.capital * frac, 2)
        if stake < c.min_stake or stake > self.capital:
            return RiskDecision(False, 0.0, "INSUFFICIENT_CAPITAL")
        return RiskDecision(True, stake, "OK")

    # --- settlement ------------------------------------------------------
    def settle(self, stake: float, pnl: float) -> None:
        """pnl: +stake*payout on win, -stake on loss, 0 on refund tie."""
        self.capital += pnl
        self.peak_capital = max(self.peak_capital, self.capital)
        self._session_pnl += pnl
        self._session_trades += 1
        if pnl < 0:
            self._consecutive_losses += 1
        elif pnl > 0:
            self._consecutive_losses = 0
        # tie: streak unchanged

    @property
    def consecutive_losses(self) -> int:
        return self._consecutive_losses
