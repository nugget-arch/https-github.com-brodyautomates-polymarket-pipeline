"use client";

import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { PricePoint } from "@/lib/useMarketFeed";

export function LivePriceChart({ points }: { points: PricePoint[] }) {
  const data = points.map((p) => ({
    t: new Date(p.ts).toLocaleTimeString(),
    price: p.price,
  }));

  return (
    <div className="h-72 w-full rounded-lg border border-border bg-panel p-3">
      {data.length === 0 ? (
        <div className="flex h-full items-center justify-center text-sm text-muted">
          Esperando datos del feed…
        </div>
      ) : (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
            <XAxis dataKey="t" hide tick={{ fontSize: 10 }} stroke="#8b97ad" />
            <YAxis
              domain={["auto", "auto"]}
              width={60}
              tick={{ fontSize: 10, fill: "#8b97ad" }}
              stroke="#232b3a"
            />
            <Tooltip
              contentStyle={{
                background: "#141924",
                border: "1px solid #232b3a",
                fontSize: 12,
              }}
              labelStyle={{ color: "#8b97ad" }}
            />
            <Line
              type="monotone"
              dataKey="price"
              stroke="#3b82f6"
              dot={false}
              isAnimationActive={false}
              strokeWidth={1.5}
            />
          </LineChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
