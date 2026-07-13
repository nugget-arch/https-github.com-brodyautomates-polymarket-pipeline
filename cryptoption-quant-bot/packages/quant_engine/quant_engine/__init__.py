"""
quant_engine — deterministic quantitative engine (features, labels, models,
validation, backtest, risk, metrics). Pure library: no network, no web
framework, no I/O side effects beyond what callers pass in.

Phase 1 status: STUB. The real implementation is ported across phases 3-7 from
the repo-root `otc_lab` project (already tested, ~3.6k LOC). This package
intentionally exposes only the invariants the rest of the system depends on so
Phase 1 can wire up the monorepo without importing math that isn't here yet.
"""

__version__ = "0.1.0"

# Hard guard mirrored by the API layer. Real-money execution is disabled in
# code; no adapter may place a real order while this is False.
EXECUTION_ENABLED: bool = False


def break_even_win_rate(payout: float) -> float:
    """Minimum win rate to break even on a binary option: 1 / (1 + payout).

    Payout 0.80 -> 0.5556. This is the single most important number in the whole
    system: below it, trading has negative expectancy no matter the model.
    """
    if payout <= 0:
        raise ValueError("payout must be > 0")
    return 1.0 / (1.0 + payout)
