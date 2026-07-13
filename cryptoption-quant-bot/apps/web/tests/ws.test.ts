import { describe, expect, it } from "vitest";
import { SequenceTracker } from "@/lib/sequence";
import { WsEnvelope, MarketTick } from "@/lib/ws-schemas";

describe("SequenceTracker", () => {
  it("accepts a monotonic increasing stream", () => {
    const t = new SequenceTracker();
    expect(t.observe(0)).toBe("ok");
    expect(t.observe(1)).toBe("ok");
    expect(t.observe(2)).toBe("ok");
    expect(t.lastSeq).toBe(2);
  });

  it("detects a gap when messages are missed", () => {
    const t = new SequenceTracker();
    t.observe(0);
    t.observe(1);
    expect(t.observe(5)).toBe("gap"); // missed 2,3,4
    expect(t.lastSeq).toBe(5);
  });

  it("flags duplicates/out-of-order without advancing", () => {
    const t = new SequenceTracker();
    t.observe(0);
    t.observe(1);
    t.observe(2);
    expect(t.observe(1)).toBe("duplicate");
    expect(t.lastSeq).toBe(2);
  });

  it("recognises a server reconnect (seq resets to 0)", () => {
    const t = new SequenceTracker();
    t.observe(10);
    expect(t.observe(0)).toBe("reset");
    expect(t.lastSeq).toBe(0);
  });
});

describe("ws schemas", () => {
  it("parses a valid envelope + tick payload", () => {
    const raw = {
      seq: 3,
      ts: "2024-01-01T00:00:00+00:00",
      type: "market.tick",
      payload: {
        asset: "BTCUSDT",
        market_type: "SYNTHETIC",
        ts_utc: "2024-01-01T00:00:00+00:00",
        price: 100.5,
      },
    };
    const env = WsEnvelope.parse(raw);
    expect(env.type).toBe("market.tick");
    const tick = MarketTick.parse(env.payload);
    expect(tick.price).toBe(100.5);
  });

  it("rejects an unknown event type", () => {
    expect(() =>
      WsEnvelope.parse({ seq: 1, ts: "x", type: "nope", payload: {} }),
    ).toThrow();
  });
});
