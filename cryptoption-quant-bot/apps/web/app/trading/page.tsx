"use client";

import { useState } from "react";
import { LivePriceChart } from "@/components/LivePriceChart";
import { useMarketFeed } from "@/lib/useMarketFeed";
import { money } from "@/lib/format";

const ASSETS = ["BTCUSDT", "ETHUSDT", "EURUSD_OTC"] as const;

const statusColor: Record<string, string> = {
  open: "text-pos",
  connecting: "text-warn",
  reconnecting: "text-warn",
  closed: "text-neg",
};

export default function TradingPage() {
  const [asset, setAsset] = useState<string>("BTCUSDT");
  const { points, status, lastPrice } = useMarketFeed(asset);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Trading — precio en tiempo real</h1>
        <div className="flex items-center gap-3 text-sm">
          <span className={statusColor[status] ?? "text-muted"}>● {status}</span>
          <select
            value={asset}
            onChange={(e) => setAsset(e.target.value)}
            className="rounded border border-border bg-panel2 px-2 py-1"
          >
            {ASSETS.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-semibold text-info">
          {lastPrice === null ? "—" : money(lastPrice)}
        </span>
        <span className="text-xs text-muted">{asset} · feed sintético</span>
      </div>

      <LivePriceChart points={points} />

      <p className="text-xs text-muted">
        Feed sintético determinista (Fase 2). Estos precios no son de mercado real y no
        constituyen ninguna señal ni evidencia. Reconexión automática y recuperación de
        estado vía REST ante huecos de secuencia.
      </p>
    </div>
  );
}
