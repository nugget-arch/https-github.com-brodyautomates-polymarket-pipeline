import { SequenceTracker } from "./sequence";
import { WsEnvelope } from "./ws-schemas";

const WS_BASE = process.env.NEXT_PUBLIC_WS_BASE ?? "ws://localhost:8000";

export type ConnStatus = "connecting" | "open" | "closed" | "reconnecting";

export interface MarketSocketHandlers {
  onEnvelope: (env: WsEnvelope) => void;
  onStatus?: (status: ConnStatus) => void;
  onGap?: () => void; // caller should recover state via REST
}

/**
 * Browser WebSocket wrapper: reconnection with backoff, heartbeat watchdog,
 * schema validation, and sequence-gap detection. Connects only to our backend.
 */
export class MarketSocket {
  private ws: WebSocket | null = null;
  private readonly seqTracker = new SequenceTracker();
  private closedByUser = false;
  private backoff = 1000;
  private readonly maxBackoff = 15000;
  private heartbeatTimer: ReturnType<typeof setTimeout> | null = null;
  private readonly heartbeatTimeoutMs = 30000;

  constructor(
    private readonly asset: string,
    private readonly handlers: MarketSocketHandlers,
  ) {}

  connect(): void {
    this.closedByUser = false;
    this.open();
  }

  private open(): void {
    this.handlers.onStatus?.(this.backoff === 1000 ? "connecting" : "reconnecting");
    const ws = new WebSocket(`${WS_BASE}/ws?asset=${encodeURIComponent(this.asset)}`);
    this.ws = ws;

    ws.onopen = () => {
      this.backoff = 1000;
      this.seqTracker.reset();
      this.handlers.onStatus?.("open");
      this.armHeartbeat();
    };

    ws.onmessage = (ev: MessageEvent) => {
      this.armHeartbeat();
      let parsed: unknown;
      try {
        parsed = JSON.parse(ev.data as string);
      } catch {
        return;
      }
      const result = WsEnvelope.safeParse(parsed);
      if (!result.success) return;
      const env = result.data;
      const rel = this.seqTracker.observe(env.seq);
      if (rel === "gap") this.handlers.onGap?.();
      if (rel === "duplicate") return;
      this.handlers.onEnvelope(env);
    };

    ws.onclose = () => {
      this.clearHeartbeat();
      if (this.closedByUser) {
        this.handlers.onStatus?.("closed");
        return;
      }
      this.scheduleReconnect();
    };

    ws.onerror = () => {
      ws.close();
    };
  }

  private scheduleReconnect(): void {
    this.handlers.onStatus?.("reconnecting");
    setTimeout(() => {
      if (!this.closedByUser) this.open();
    }, this.backoff);
    this.backoff = Math.min(this.backoff * 2, this.maxBackoff);
  }

  private armHeartbeat(): void {
    this.clearHeartbeat();
    // If no message (incl. server heartbeat) arrives in time, force a reconnect.
    this.heartbeatTimer = setTimeout(() => {
      this.ws?.close();
    }, this.heartbeatTimeoutMs);
  }

  private clearHeartbeat(): void {
    if (this.heartbeatTimer) clearTimeout(this.heartbeatTimer);
    this.heartbeatTimer = null;
  }

  close(): void {
    this.closedByUser = true;
    this.clearHeartbeat();
    this.ws?.close();
  }
}
