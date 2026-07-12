"""Risk manager.

Anti-martingale by construction:
  * stake = capital * risk_fraction, where risk_fraction NEVER reads past
    trade outcomes except to *reduce* exposure (drawdown scaling);
  * there is no code path in which a loss increases the next stake — this
    property is asserted by tests/test_risk.py.

Guards: daily loss limit, consecutive-loss pause, session trade cap, kill
switch (file or programmatic), drawdown-based exposure reduction.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import RiskConfig
from ..logging_setup import get_logger

log = get_logger("risk")


@dataclass
class RiskDecision:
    allowed: bool
    stake: float
    reason: str


class RiskManager:
    def __init__(self, cfg: RiskConfig):
        self.cfg = cfg
        self.capital = cfg.initial_capital
        self.peak_capital = cfg.initial_capital
        self._session: str | None = None
        self._session_pnl = 0.0
        self._session_trades = 0
        self._consecutive_losses = 0
        self._cooldown_until_bar = -1
        self._killed = False

    # --- controls -------------------------------------------------------

    def kill(self, reason: str = "manual") -> None:
        self._killed = True
        log.warning("kill switch engaged", extra={"ctx_reason": reason})

    def _kill_file_present(self) -> bool:
        return Path(self.cfg.kill_switch_file).exists()

    def new_session(self, session: str) -> None:
        if session != self._session:
            self._session = session
            self._session_pnl = 0.0
            self._session_trades = 0
            self._consecutive_losses = 0

    # --- pre-trade gate ---------------------------------------------------

    def pre_trade(self, session: str, bar_index: int) -> RiskDecision:
        self.new_session(session)
        c = self.cfg

        if self._killed or self._kill_file_present():
            return RiskDecision(False, 0.0, "kill_switch")
        if bar_index < self._cooldown_until_bar:
            return RiskDecision(False, 0.0, "cooldown")
        if self._session_trades >= c.max_trades_per_session:
            return RiskDecision(False, 0.0, "session_trade_cap")
        if self._session_pnl <= -c.daily_loss_limit * c.initial_capital:
            return RiskDecision(False, 0.0, "daily_loss_limit")
        if self._consecutive_losses >= c.max_consecutive_losses:
            self._cooldown_until_bar = bar_index + c.cooldown_bars
            self._consecutive_losses = 0  # reset streak; cooldown enforced
            return RiskDecision(False, 0.0, "max_consecutive_losses")

        frac = min(c.risk_per_trade, c.max_risk_per_trade)
        # drawdown-based exposure REDUCTION (never an increase)
        drawdown = 1.0 - self.capital / self.peak_capital if self.peak_capital > 0 else 0.0
        if drawdown > c.drawdown_soft_limit:
            frac *= c.drawdown_scale
        stake = round(self.capital * frac, 2)
        if stake <= 0 or stake > self.capital:
            return RiskDecision(False, 0.0, "insufficient_capital")
        return RiskDecision(True, stake, "ok")

    # --- settlement -------------------------------------------------------

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
