import { StatCard } from "@/components/StatCard";
import { money, pct, num, toneForSigned } from "@/lib/format";
import { mockDashboardState } from "@/lib/mock";

// Phase 1: renders a typed static snapshot. Later phases fetch the same shape
// from GET /api/v1/dashboard/state and subscribe to WebSocket deltas.
export default function DashboardPage() {
  const s = mockDashboardState();
  const edgeTone = toneForSigned(s.edge);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <div className="text-sm text-muted">
          Modo <span className="text-info">{s.mode}</span> · Activo{" "}
          <span className="text-white">{s.asset}</span>
        </div>
      </div>

      <section className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="Balance" value={money(s.balance)} tone="info" />
        <StatCard label="PnL día" value={money(s.pnl_day)} tone={toneForSigned(s.pnl_day)} />
        <StatCard label="PnL total" value={money(s.pnl_total)} tone={toneForSigned(s.pnl_total)} />
        <StatCard label="Operaciones" value={num(s.n_trades)} />
        <StatCard label="Win rate" value={pct(s.win_rate)} hint="requiere operaciones" />
        <StatCard label="Break-even" value={pct(s.break_even)} hint={`payout ${pct(s.payout, 0)}`} />
        <StatCard
          label="Edge sobre break-even"
          value={s.edge === null ? "—" : pct(s.edge)}
          tone={edgeTone}
          hint="win rate − break-even"
        />
        <StatCard label="Drawdown" value={pct(s.drawdown)} tone={s.drawdown > 0 ? "neg" : "muted"} />
      </section>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <div className="rounded-lg border border-border bg-panel p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
            Señal actual
          </h2>
          <div className="grid grid-cols-2 gap-y-2 text-sm">
            <span className="text-muted">Acción</span>
            <span className="font-semibold text-warn">{s.current_action}</span>
            <span className="text-muted">Motivo NO_TRADE</span>
            <span>{s.no_trade_reason ?? "—"}</span>
            <span className="text-muted">P(subida)</span>
            <span>{s.p_up === null ? "—" : s.p_up.toFixed(3)}</span>
            <span className="text-muted">Umbral CALL</span>
            <span className="text-pos">{s.threshold_call.toFixed(3)}</span>
            <span className="text-muted">Umbral PUT</span>
            <span className="text-neg">{s.threshold_put.toFixed(3)}</span>
            <span className="text-muted">Stake propuesto</span>
            <span>{money(s.proposed_stake)}</span>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-panel p-4">
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-muted">
            Estado del sistema
          </h2>
          <div className="grid grid-cols-2 gap-y-2 text-sm">
            <span className="text-muted">Bot</span>
            <span>{s.bot_status}</span>
            <span className="text-muted">Datos</span>
            <span className={s.data_status === "disconnected" ? "text-neg" : "text-pos"}>
              {s.data_status}
            </span>
            <span className="text-muted">Modelo</span>
            <span>{s.model_status}</span>
            <span className="text-muted">Kill switch</span>
            <span className={s.kill_switch ? "text-neg" : "text-pos"}>
              {s.kill_switch ? "ACTIVADO" : "ok"}
            </span>
            <span className="text-muted">Pérdidas consecutivas</span>
            <span>{num(s.consecutive_losses)}</span>
            <span className="text-muted">Ejecución real</span>
            <span className="text-pos">deshabilitada</span>
          </div>
        </div>
      </section>

      <p className="text-xs text-muted">
        Datos de ejemplo (Fase 1). No constituyen evidencia de ninguna ventaja. El motor
        cuantitativo y el tiempo real se incorporan en fases posteriores.
      </p>
    </div>
  );
}
