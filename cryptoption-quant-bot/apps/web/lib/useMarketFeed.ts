"use client";

import { useEffect, useRef, useState } from "react";
import { apiGet } from "./api";
import { MarketSocket, type ConnStatus } from "./ws-client";
import { MarketCandle, MarketTick } from "./ws-schemas";
import { z } from "zod";

export interface PricePoint {
  ts: string;
  price: number;
}

const CandlesResponse = z.object({
  asset: z.string(),
  candles: z.array(MarketCandle),
  last_price: z.number().nullable(),
});

const MAX_POINTS = 240;

/** Subscribes to the live feed for `asset`, recovering history via REST on
 * connect and on any detected sequence gap. Returns a rolling price series. */
export function useMarketFeed(asset: string) {
  const [points, setPoints] = useState<PricePoint[]>([]);
  const [status, setStatus] = useState<ConnStatus>("connecting");
  const [lastPrice, setLastPrice] = useState<number | null>(null);
  const socketRef = useRef<MarketSocket | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function recover() {
      try {
        const data = await apiGet(`/api/v1/market/candles?asset=${asset}&limit=120`, CandlesResponse);
        if (cancelled) return;
        setPoints(data.candles.map((c) => ({ ts: c.ts_utc, price: c.close })));
        if (data.last_price !== null) setLastPrice(data.last_price);
      } catch {
        /* backend may be down; the socket will keep retrying */
      }
    }

    void recover();

    const socket = new MarketSocket(asset, {
      onStatus: setStatus,
      onGap: () => void recover(),
      onEnvelope: (env) => {
        if (env.type === "market.tick") {
          const t = MarketTick.safeParse(env.payload);
          if (!t.success) return;
          setLastPrice(t.data.price);
          setPoints((prev) => {
            const next = [...prev, { ts: t.data.ts_utc, price: t.data.price }];
            return next.length > MAX_POINTS ? next.slice(next.length - MAX_POINTS) : next;
          });
        }
      },
    });
    socket.connect();
    socketRef.current = socket;

    return () => {
      cancelled = true;
      socket.close();
    };
  }, [asset]);

  return { points, status, lastPrice };
}
