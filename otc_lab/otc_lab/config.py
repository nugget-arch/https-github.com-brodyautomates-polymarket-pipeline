"""Typed configuration (Pydantic v2) loaded from YAML.

Every knob that affects results lives here so experiments are reproducible
from (config, seed, data) alone.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class DataConfig(BaseModel):
    paths: list[str] = Field(default_factory=list, description="CSV/Parquet candle files")
    timezone: str = "UTC"
    bar_seconds: int = 60
    max_gap_bars: int = 3
    otc_suffixes: tuple[str, ...] = ("_otc", "-otc", " otc")
    holdout_fraction: float = Field(0.2, ge=0.0, le=0.5)
    holdout_unlocked: bool = False  # final test stays locked until research ends


class LabelConfig(BaseModel):
    expiry_bars: list[int] = Field(default_factory=lambda: [1, 2, 3, 5])
    latency_bars: int = Field(1, ge=0, description="bars between signal close and entry")
    tie_policy: Literal["loss", "refund", "drop"] = "refund"


class FeatureConfig(BaseModel):
    momentum_windows: list[int] = Field(default_factory=lambda: [3, 5, 10])
    ema_fast: int = 9
    ema_slow: int = 21
    rsi_period: int = 14
    atr_period: int = 14
    realized_vol_window: int = 20
    bollinger_window: int = 20
    slope_window: int = 12


class StrategyConfig(BaseModel):
    names: list[str] = Field(
        default_factory=lambda: ["random", "trend", "meanrev", "logistic"]
    )
    logistic_c: float = 0.1  # inverse of L2 strength (regularized)
    calibration: Literal["sigmoid", "isotonic", "none"] = "sigmoid"
    use_lightgbm: bool = False
    lgbm_params: dict[str, float | int | str] = Field(
        default_factory=lambda: {
            "n_estimators": 200,
            "learning_rate": 0.05,
            "max_depth": 4,
            "subsample": 0.8,
            "colsample_bytree": 0.8,
        }
    )


class ValidationConfig(BaseModel):
    train_bars: int = 5000
    val_bars: int = 1000
    test_bars: int = 1000
    step_bars: int = 1000
    embargo_bars: int = 30
    n_bootstrap: int = 2000
    block_size: int = 50
    confidence: float = 0.95
    min_oos_trades: int = 1000
    multiple_test_method: Literal["benjamini_hochberg", "bonferroni"] = "benjamini_hochberg"


class BacktestConfig(BaseModel):
    payout_base: float = Field(0.80, gt=0.0, lt=1.0)
    payout_jitter: float = Field(0.05, ge=0.0, description="uniform ± jitter per trade")
    payout_floor: float = Field(0.70, gt=0.0)
    rejection_prob: float = Field(0.02, ge=0.0, le=0.5)
    threshold_margin: float = Field(
        0.02, ge=0.0, description="safety margin added to break-even win rate"
    )
    threshold_use_val_ci: bool = True  # widen margin by validation CI half-width

    @model_validator(mode="after")
    def _floor_below_base(self) -> "BacktestConfig":
        if self.payout_floor > self.payout_base:
            raise ValueError("payout_floor must be <= payout_base")
        return self


class RiskConfig(BaseModel):
    initial_capital: float = Field(10_000.0, gt=0)
    risk_per_trade: float = Field(0.0025, gt=0, le=0.005)  # 0.25% default
    max_risk_per_trade: float = 0.005                       # hard cap 0.50%
    daily_loss_limit: float = Field(0.01, gt=0)             # 1% of capital
    max_consecutive_losses: int = 3
    cooldown_bars: int = 60
    max_trades_per_session: int = 50
    drawdown_soft_limit: float = 0.05   # above this, exposure is reduced
    drawdown_scale: float = 0.5         # stake multiplier while in soft drawdown
    kill_switch_file: str = "KILL_SWITCH"

    @field_validator("risk_per_trade")
    @classmethod
    def _cap(cls, v: float) -> float:
        if v > 0.005:
            raise ValueError("risk_per_trade must be <= 0.005 (0.5%)")
        return v


class PaperConfig(BaseModel):
    mode: Literal["shadow", "paper"] = "shadow"
    speed: float = Field(0.0, ge=0.0, description="seconds of wall clock per bar; 0 = as fast as possible")
    journal_path: str = "artifacts/journal.jsonl"


class ReportConfig(BaseModel):
    out_dir: str = "artifacts"
    formats: list[Literal["md", "html"]] = Field(default_factory=lambda: ["md", "html"])


class ExperimentConfig(BaseModel):
    """Root config."""

    seed: int = 7
    log_level: str = "INFO"
    data: DataConfig = Field(default_factory=DataConfig)
    labels: LabelConfig = Field(default_factory=LabelConfig)
    features: FeatureConfig = Field(default_factory=FeatureConfig)
    strategies: StrategyConfig = Field(default_factory=StrategyConfig)
    validation: ValidationConfig = Field(default_factory=ValidationConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    paper: PaperConfig = Field(default_factory=PaperConfig)
    report: ReportConfig = Field(default_factory=ReportConfig)
    registry_db: str = "artifacts/experiments.sqlite"


def load_config(path: str | Path | None = None) -> ExperimentConfig:
    if path is None:
        return ExperimentConfig()
    raw = yaml.safe_load(Path(path).read_text()) or {}
    return ExperimentConfig.model_validate(raw)


def break_even_win_rate(payout: float) -> float:
    """Minimum win rate to break even: 1 / (1 + payout). 0.80 -> ~0.5556."""
    return 1.0 / (1.0 + payout)
