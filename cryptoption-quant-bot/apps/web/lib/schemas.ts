import { z } from "zod";

// Mirrors the backend DashboardState DTO. Zod validates every payload the
// browser receives so the UI never renders unchecked data.
export const ExecutionMode = z.enum(["PAPER", "SHADOW", "MANUAL", "OFFICIAL_DISABLED"]);
export const Action = z.enum(["CALL", "PUT", "NO_TRADE"]);

export const DashboardState = z.object({
  bot_status: z.string(),
  mode: ExecutionMode,
  balance: z.number(),
  pnl_day: z.number(),
  pnl_total: z.number(),
  win_rate: z.number().nullable(),
  break_even: z.number(),
  edge: z.number().nullable(),
  expected_value: z.number().nullable(),
  drawdown: z.number(),
  consecutive_losses: z.number(),
  n_trades: z.number(),
  data_status: z.string(),
  model_status: z.string(),
  kill_switch: z.boolean(),
  asset: z.string(),
  price: z.number().nullable(),
  payout: z.number(),
  p_up: z.number().nullable(),
  threshold_call: z.number(),
  threshold_put: z.number(),
  current_action: Action,
  no_trade_reason: z.string().nullable(),
  proposed_stake: z.number(),
  countdown_seconds: z.number().nullable(),
});

export type DashboardState = z.infer<typeof DashboardState>;

export const HealthOut = z.object({
  status: z.string(),
  version: z.string(),
  execution_enabled: z.boolean(),
});
export type HealthOut = z.infer<typeof HealthOut>;
