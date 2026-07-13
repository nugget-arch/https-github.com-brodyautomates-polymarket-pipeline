import { z } from "zod";

// Envelope + payloads mirror the backend cryptoption_api.ws.events models.
export const WsEnvelope = z.object({
  seq: z.number(),
  ts: z.string(),
  type: z.enum([
    "connection.status",
    "market.tick",
    "market.candle",
    "heartbeat",
    "data_quality.alert",
    "error",
  ]),
  payload: z.record(z.string(), z.unknown()),
});
export type WsEnvelope = z.infer<typeof WsEnvelope>;

export const MarketTick = z.object({
  asset: z.string(),
  market_type: z.string(),
  ts_utc: z.string(),
  price: z.number(),
  bid: z.number().nullable().optional(),
  ask: z.number().nullable().optional(),
  spread: z.number().nullable().optional(),
});
export type MarketTick = z.infer<typeof MarketTick>;

export const MarketCandle = z.object({
  asset: z.string(),
  market_type: z.string(),
  ts_utc: z.string(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number(),
  closed: z.boolean(),
});
export type MarketCandle = z.infer<typeof MarketCandle>;
