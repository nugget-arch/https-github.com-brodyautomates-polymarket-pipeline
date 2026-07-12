"""Command-line interface.

    python -m otc_lab.cli synth        --out data/sample
    python -m otc_lab.cli validate     --config config/default.yaml
    python -m otc_lab.cli research     --config config/default.yaml
    python -m otc_lab.cli paper        --config config/default.yaml --asset EURUSD_OTC
    python -m otc_lab.cli verify-journal --path artifacts/journal.jsonl
    python -m otc_lab.cli holdout      --config config/default.yaml --i-am-done-researching

`research` = train + walk-forward validation + backtest + report + registry.
`holdout` refuses to run unless the explicit flag is passed AND the config has
holdout_unlocked: true — the final test is meant to be spent exactly once.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import ExperimentConfig, load_config
from .logging_setup import setup_logging


def cmd_synth(args: argparse.Namespace) -> int:
    from .data.synthetic import generate_synthetic_dataset

    paths = generate_synthetic_dataset(args.out, n_bars=args.bars, seed=args.seed,
                                       edge_autocorr=args.edge)
    for p in paths:
        print(f"wrote {p}")
    if args.edge:
        print(f"NOTE: injected AR(1) coefficient {args.edge} — this is a positive "
              "control for the pipeline, not a market claim.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    from .data.loader import load_candles
    from .data.validate import validate_candles

    cfg = load_config(args.config)
    df = load_candles(cfg.data.paths, cfg.data)
    _, report = validate_candles(df, cfg.data)
    print(report.summary())
    return 0 if report.ok else 1


def cmd_research(args: argparse.Namespace) -> int:
    from .experiments.registry import ExperimentRegistry
    from .pipeline import run_experiment
    from .report.builder import build_report

    cfg = load_config(args.config)
    if args.seed is not None:
        cfg = cfg.model_copy(update={"seed": args.seed})
    result = run_experiment(cfg)

    print("\n=== VEREDICTO ===")
    print(result.verdict)
    print("=================\n")
    for c in sorted(result.combos, key=lambda c: c.strategy):
        m = c.metrics
        wr = f"{m.win_rate*100:.2f}%" if m.n_trades else "—"
        print(f"  {c.strategy:10s} exp={c.expiry_bars}  trades={m.n_trades:5d}  "
              f"win={wr}  edge={m.edge_over_breakeven*100 if m.n_trades else 0:+.2f}pt  "
              f"candidata={'sí' if c.is_candidate else 'no'}")

    written = build_report(result)
    for p in written:
        print(f"\nreport: {p}")

    registry = ExperimentRegistry(cfg.registry_db)
    exp_id = registry.record(
        seed=cfg.seed,
        config=json.loads(cfg.model_dump_json()),
        verdict=result.verdict,
        summary={
            "n_combos": len(result.combos),
            "any_candidate": result.any_candidate,
            "n_bars_research": result.n_bars_research,
            "n_bars_holdout": result.n_bars_holdout,
        },
        results=[
            {"strategy": c.strategy, "expiry_bars": c.expiry_bars,
             "metrics": c.metrics.to_dict()}
            for c in result.combos
        ],
    )
    print(f"experiment recorded: id={exp_id} in {cfg.registry_db}")
    return 0


def cmd_paper(args: argparse.Namespace) -> int:
    import numpy as np

    from .data.loader import load_candles, split_holdout
    from .data.validate import validate_candles
    from .features.engine import build_features, feature_columns
    from .labels.binary import build_labels
    from .paper_trading.replayer import MarketReplayer
    from .pipeline import _attach_features
    from .strategies.base import make_strategy

    cfg = load_config(args.config)
    if args.mode:
        cfg = cfg.model_copy(update={"paper": cfg.paper.model_copy(update={"mode": args.mode})})
    df = load_candles(cfg.data.paths, cfg.data)
    df, _ = validate_candles(df, cfg.data)
    research, _holdout = split_holdout(df, cfg.data)

    asset_df = research[research["asset"] == args.asset.upper()].reset_index(drop=True)
    if asset_df.empty:
        print(f"asset {args.asset} not found; available: {sorted(research['asset'].unique())}")
        return 1

    # fit on the first 70% of the *research* slice, replay the remaining 30%
    cut = int(len(asset_df) * 0.7)
    fit_df, replay_df = asset_df.iloc[:cut], asset_df.iloc[cut:].reset_index(drop=True)

    feats = build_features(fit_df, cfg.features)
    fcols = feature_columns(feats)
    labels = build_labels(fit_df, args.expiry, cfg.labels, cfg.data.bar_seconds)
    samples = _attach_features(labels.frame, feats, fcols)
    if samples.empty:
        print("not enough data to fit")
        return 1
    n_val = max(200, int(len(samples) * 0.2))
    train, val = samples.iloc[:-n_val], samples.iloc[-n_val:]

    strat = make_strategy(args.strategy, cfg.strategies, cfg.seed)
    strat.fit(train[fcols], train["y_up"].to_numpy(),
              val[fcols], val["y_up"].to_numpy())

    replayer = MarketReplayer(cfg, strat)
    summary = replayer.run(replay_df, expiry_bars=args.expiry)
    print(json.dumps(summary, indent=2, default=str))
    print(f"journal: {cfg.paper.journal_path} (verified={summary['journal_ok']})")
    return 0


def cmd_verify_journal(args: argparse.Namespace) -> int:
    from .paper_trading.journal import Journal

    ok = Journal(args.path).verify()
    print("journal OK (hash chain intact)" if ok else "journal CORRUPTED")
    return 0 if ok else 1


def cmd_holdout(args: argparse.Namespace) -> int:
    from .pipeline import run_experiment
    from .report.builder import build_report

    cfg = load_config(args.config)
    if not cfg.data.holdout_unlocked:
        print("REFUSED: config data.holdout_unlocked is false.\n"
              "The final holdout is meant to be evaluated exactly once, after\n"
              "research is frozen. Flip the flag consciously.")
        return 2
    if not args.confirm:
        print("REFUSED: pass --i-am-done-researching to confirm this is the final,\n"
              "one-shot evaluation.")
        return 2

    # evaluate ONLY the holdout segment: invert the split
    from .data.loader import load_candles, split_holdout
    from .data.validate import validate_candles

    df = load_candles(cfg.data.paths, cfg.data)
    df, _ = validate_candles(df, cfg.data)
    _research, holdout = split_holdout(df, cfg.data)
    # inside the holdout run, don't split again
    inner = cfg.model_copy(deep=True)
    inner.data.holdout_fraction = 0.0
    result = run_experiment(inner, df=holdout)
    print("\n=== VEREDICTO (HOLDOUT FINAL) ===")
    print(result.verdict)
    for p in build_report(result, out_dir=Path(cfg.report.out_dir) / "holdout"):
        print(f"report: {p}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="otc-lab",
                                     description="OTC binary-options research platform "
                                                 "(paper/shadow only; live execution disabled)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("synth", help="generate synthetic sample data")
    p.add_argument("--out", default="data/sample")
    p.add_argument("--bars", type=int, default=30000)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--edge", type=float, default=0.0,
                   help="AR(1) coefficient injected into the OTC asset (positive control)")
    p.set_defaults(func=cmd_synth)

    p = sub.add_parser("validate", help="validate configured data files")
    p.add_argument("--config", default="config/default.yaml")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("research", help="walk-forward research + report + registry")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--seed", type=int, default=None)
    p.set_defaults(func=cmd_research)

    p = sub.add_parser("paper", help="replay history through a strategy (shadow/paper)")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--asset", required=True)
    p.add_argument("--strategy", default="logistic")
    p.add_argument("--expiry", type=int, default=1)
    p.add_argument("--mode", choices=["shadow", "paper"], default=None)
    p.set_defaults(func=cmd_paper)

    p = sub.add_parser("verify-journal", help="verify the immutable journal hash chain")
    p.add_argument("--path", default="artifacts/journal.jsonl")
    p.set_defaults(func=cmd_verify_journal)

    p = sub.add_parser("holdout", help="ONE-SHOT final evaluation on the locked holdout")
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--i-am-done-researching", dest="confirm", action="store_true")
    p.set_defaults(func=cmd_holdout)

    args = parser.parse_args(argv)
    setup_logging()
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
