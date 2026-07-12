"""Experiment report: Markdown + standalone HTML with embedded plots.

Plots: equity curve, drawdown, calibration (reliability), rolling win-rate
stability. The verdict — including the honest negative — is stated at the top,
followed by the criteria checklist, metric tables, and a fixed section on
leakage sources, assumptions and limitations.
"""
from __future__ import annotations

import base64
import html as _html
import io
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from ..config import ExperimentConfig
from ..pipeline import ComboResult, ExperimentResult, NO_EDGE_SENTENCE

_LEAKAGE_NOTES = """\
### Posibles fuentes de leakage (controladas, pero léelas)

1. **Look-ahead en features** — controlado: todas las features son causales y
   hay un test de invarianza por truncado. Riesgo residual: bugs futuros que
   introduzcan `shift(-k)`; el test lo detectaría.
2. **Solapamiento de etiquetas** — operaciones con vencimientos solapados
   comparten barras futuras; controlado con *purge* (el horizonte de cada
   muestra de entrenamiento debe cerrar antes de validación) y *embargo*.
3. **Selección de umbral** — el umbral se deriva del payout mínimo, un margen
   de seguridad y la incertidumbre de VALIDACIÓN; nunca del test.
4. **Selección de estrategia/expiración** — probar muchas combinaciones infla
   los falsos positivos; controlado con corrección de comparaciones múltiples
   (Benjamini-Hochberg / Bonferroni).
5. **Snooping del holdout** — el tramo final está bloqueado; evaluarlo exige
   desbloqueo explícito y debería hacerse UNA sola vez.
6. **Supervivencia del dato** — si los CSV de origen ya excluyen periodos
   malos, ningún control estadístico lo corrige. Documenta la procedencia.
"""

_ASSUMPTIONS = """\
### Supuestos y limitaciones

* Los datos OTC son generados por el bróker; incluso una ventaja histórica
  puede no persistir porque el generador puede cambiar sin aviso.
* El simulador asume ejecución al open de la barra de entrada tras la latencia
  configurada; la ejecución real puede ser peor (requotes, deslizamiento de
  payout, rechazos correlacionados con la señal).
* El payout se modela como U(base±jitter) independiente de la dirección; un
  bróker adversarial podría correlacionarlo con tu flujo.
* Empates tratados según configuración (por defecto, reembolso).
* Los tests estadísticos asumen muestras suficientemente informativas; con
  pocas operaciones los intervalos son anchos y el veredicto será negativo.
* Paper trading aquí NO implica viabilidad en real: es una cota superior
  optimista.
"""


def _fig_to_b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def _plot_equity_drawdown(combo: ComboResult, initial: float) -> tuple[str, str]:
    settled = combo.trade_log[combo.trade_log["outcome"].isin(["win", "loss", "tie"])]
    if settled.empty:
        return "", ""
    eq = pd.concat([pd.Series([initial]), settled["capital_after"]], ignore_index=True)

    fig, ax = plt.subplots(figsize=(8, 3))
    ax.plot(eq.values, lw=1.2)
    ax.axhline(initial, color="grey", ls="--", lw=0.8)
    ax.set_title(f"Equity — {combo.strategy} exp={combo.expiry_bars}")
    ax.set_xlabel("operación"); ax.set_ylabel("capital")
    equity_b64 = _fig_to_b64(fig)

    peak = eq.cummax()
    dd = (peak - eq) / peak
    fig, ax = plt.subplots(figsize=(8, 2.2))
    ax.fill_between(range(len(dd)), -dd.values * 100, 0, alpha=0.6, color="firebrick")
    ax.set_title("Drawdown (%)"); ax.set_xlabel("operación")
    dd_b64 = _fig_to_b64(fig)
    return equity_b64, dd_b64


def _plot_calibration(combo: ComboResult) -> str:
    cal = combo.metrics.calibration
    if not cal:
        return ""
    fig, ax = plt.subplots(figsize=(4.2, 4))
    xs = [c["p_mean"] for c in cal]
    ys = [c["y_rate"] for c in cal]
    ns = [c["n"] for c in cal]
    ax.plot([0, 1], [0, 1], "--", color="grey", lw=0.8, label="perfecta")
    ax.scatter(xs, ys, s=[max(10, min(200, n / 5)) for n in ns], alpha=0.8)
    ax.set_xlabel("P(subida) predicha"); ax.set_ylabel("frecuencia observada")
    ax.set_title("Calibración"); ax.legend()
    return _fig_to_b64(fig)


def _plot_stability(combo: ComboResult) -> str:
    settled = combo.trade_log[combo.trade_log["outcome"].isin(["win", "loss"])]
    if len(settled) < 30:
        return ""
    win = (settled["outcome"] == "win").astype(float).reset_index(drop=True)
    roll = win.rolling(100, min_periods=30).mean()
    fig, ax = plt.subplots(figsize=(8, 2.6))
    ax.plot(roll.values, lw=1.2)
    ax.axhline(combo.metrics.break_even_rate, color="firebrick", ls="--", lw=0.9,
               label=f"break-even {combo.metrics.break_even_rate:.3f}")
    ax.set_ylim(0, 1); ax.legend()
    ax.set_title("Win-rate móvil (100 ops) — estabilidad temporal")
    return _fig_to_b64(fig)


def _md_metrics_table(combo: ComboResult) -> str:
    m, mi = combo.metrics, combo.metrics_ideal
    def f(x, pct=False):
        if x is None or (isinstance(x, float) and not np.isfinite(x)):
            return "—"
        return f"{x*100:.2f}%" if pct else (f"{x:.4f}" if isinstance(x, float) else str(x))
    rows = [
        ("Señales evaluadas", f(m.n_signals), ""),
        ("Operaciones liquidadas", f(m.n_trades), f(mi.n_trades)),
        ("Win rate", f(m.win_rate, True), f(mi.win_rate, True)),
        ("Break-even (payout medio)", f(m.break_even_rate, True), f(mi.break_even_rate, True)),
        ("Ventaja sobre break-even", f(m.edge_over_breakeven, True), f(mi.edge_over_breakeven, True)),
        ("IC 95% win rate", f"[{f(m.win_rate_ci_lo, True)}, {f(m.win_rate_ci_hi, True)}]", ""),
        ("p-valor vs break-even", f(m.pvalue_vs_breakeven), ""),
        ("VE por operación", f(m.expected_value_per_trade), f(mi.expected_value_per_trade)),
        ("Beneficio neto", f(m.net_profit), f(mi.net_profit)),
        ("Bootstrap IC PnL/op", f"[{f(m.bootstrap_pnl_lo)}, {f(m.bootstrap_pnl_hi)}]", ""),
        ("Drawdown máximo", f(m.max_drawdown, True), f(mi.max_drawdown, True)),
        ("Peor racha de pérdidas", f(m.max_loss_streak), f(mi.max_loss_streak)),
        ("Payout medio", f(m.avg_payout), f(mi.avg_payout)),
        ("Brier score", f(m.brier), ""),
        ("Log loss", f(m.log_loss), ""),
        ("Rechazadas / bloqueadas", f"{m.n_rejected} / {m.n_blocked}", "0 / —"),
    ]
    if combo.ruin and np.isfinite(combo.ruin.prob_ruin):
        rows.append(("P(ruina) Monte Carlo (50% DD)", f(combo.ruin.prob_ruin, True), ""))
    out = ["| Métrica | Con costes/latencia | Ideal (sin costes) |", "|---|---|---|"]
    out += [f"| {a} | {b} | {c} |" for a, b, c in rows]
    return "\n".join(out)


def _md_breakdown(title: str, d: dict[str, dict]) -> str:
    if not d:
        return ""
    out = [f"**{title}**\n", "| Grupo | N | Win rate | Break-even | Ventaja | PnL |", "|---|---|---|---|---|---|"]
    for k, s in sorted(d.items()):
        out.append(
            f"| {k} | {s['n']} | {s['win_rate']*100:.2f}% | {s['break_even']*100:.2f}% "
            f"| {s['edge']*100:+.2f}pt | {s['net_pnl']:.2f} |"
        )
    return "\n".join(out) + "\n"


def _md_criteria(combo: ComboResult) -> str:
    out = ["| Criterio | Resultado | Detalle |", "|---|---|---|"]
    for k, ok in combo.criteria.items():
        mark = "✅" if ok else "❌"
        out.append(f"| {k} | {mark} | {combo.criteria_notes.get(k, '')} |")
    return "\n".join(out)


def build_report(result: ExperimentResult, out_dir: str | Path | None = None) -> list[Path]:
    cfg: ExperimentConfig = result.config
    out = Path(out_dir or cfg.report.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    images: dict[str, str] = {}

    lines.append("# Informe de investigación — opciones binarias OTC\n")
    verdict_is_negative = result.verdict == NO_EDGE_SENTENCE
    lines.append(f"## Veredicto\n\n> **{result.verdict}**\n")
    if verdict_is_negative:
        lines.append(
            "_Este resultado negativo es un resultado válido: significa que, con "
            "estos datos, estrategias y controles estadísticos, operar sería "
            "apostar contra una esperanza matemática desconocida o negativa._\n"
        )
    lines.append(
        f"- Semilla: `{cfg.seed}` — los resultados se reproducen desde cero con esta semilla.\n"
        f"- Barras investigación / holdout bloqueado: {result.n_bars_research} / {result.n_bars_holdout}\n"
        f"- Corrección por comparaciones múltiples: `{cfg.validation.multiple_test_method}`\n"
    )
    lines.append("## Validación de datos\n\n```\n" + result.validation_report + "\n```\n")

    ranked = sorted(
        result.combos,
        key=lambda c: (c.is_candidate, c.metrics.edge_over_breakeven if np.isfinite(c.metrics.edge_over_breakeven) else -9),
        reverse=True,
    )
    for combo in ranked:
        tag = f"{combo.strategy}-exp{combo.expiry_bars}"
        lines.append(f"\n---\n\n## {combo.strategy} · expiración {combo.expiry_bars} barra(s)\n")
        lines.append(f"Umbral de decisión: `{combo.threshold:.4f}` "
                     f"(derivado de payout mínimo + margen + IC de validación)\n")
        lines.append("### Criterios de candidatura\n\n" + _md_criteria(combo) + "\n")
        lines.append("### Métricas\n\n" + _md_metrics_table(combo) + "\n")
        lines.append(_md_breakdown("Por activo", combo.metrics.by_asset))
        lines.append(_md_breakdown("Por hora (UTC)", combo.metrics.by_hour))
        lines.append(_md_breakdown("Por régimen de volatilidad", combo.metrics.by_regime))

        eq, dd = _plot_equity_drawdown(combo, cfg.risk.initial_capital)
        cal = _plot_calibration(combo)
        stab = _plot_stability(combo)
        for name, b64 in [("equity", eq), ("drawdown", dd), ("calibration", cal), ("stability", stab)]:
            if b64:
                images[f"{tag}-{name}"] = b64
                lines.append(f"![{name}]({tag}-{name}.png)\n")

    lines.append("\n---\n\n" + _LEAKAGE_NOTES)
    lines.append(_ASSUMPTIONS)

    md_text = "\n".join(lines)
    written: list[Path] = []

    for name, b64 in images.items():
        (out / f"{name}.png").write_bytes(base64.b64decode(b64))

    if "md" in cfg.report.formats:
        p = out / "report.md"
        p.write_text(md_text)
        written.append(p)

    if "html" in cfg.report.formats:
        body = _html.escape(md_text)
        # embed images inline so the HTML is standalone
        html_imgs = "".join(
            f'<h4>{name}</h4><img src="data:image/png;base64,{b64}" style="max-width:100%">'
            for name, b64 in images.items()
        )
        html = (
            "<!doctype html><meta charset='utf-8'><title>otc_lab report</title>"
            "<style>body{font-family:monospace;max-width:960px;margin:2rem auto;"
            "padding:0 1rem;line-height:1.45}pre{white-space:pre-wrap}</style>"
            f"<pre>{body}</pre><hr>{html_imgs}"
        )
        p = out / "report.html"
        p.write_text(html)
        written.append(p)

    return written
