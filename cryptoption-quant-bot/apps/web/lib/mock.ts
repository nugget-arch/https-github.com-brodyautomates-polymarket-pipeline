import { DashboardState } from "./schemas";

/** Phase 1 placeholder state. These numbers are NOT evidence of any edge; they
 * exist only so the UI contract renders before the backend runtime is wired. */
export function mockDashboardState(): DashboardState {
  const payout = 0.8;
  const breakEven = 1 / (1 + payout);
  return DashboardState.parse({
    bot_status: "idle",
    mode: "PAPER",
    balance: 10000,
    pnl_day: 0,
    pnl_total: 0,
    win_rate: null,
    break_even: breakEven,
    edge: null,
    expected_value: null,
    drawdown: 0,
    consecutive_losses: 0,
    n_trades: 0,
    data_status: "disconnected",
    model_status: "not_loaded",
    kill_switch: false,
    asset: "BTCUSDT",
    price: null,
    payout,
    p_up: null,
    threshold_call: breakEven + 0.02,
    threshold_put: 1 - (breakEven + 0.02),
    current_action: "NO_TRADE",
    no_trade_reason: "MODEL_UNAVAILABLE",
    proposed_stake: 0,
    countdown_seconds: null,
  });
}
