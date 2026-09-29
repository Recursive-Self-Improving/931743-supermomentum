"""Causal descriptive conditions shared by the daily chart and CSV exports."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, TypedDict

import numpy as np
from numpy.typing import NDArray

from supermomentum.config import ReportConfig, StrategyParameters
from supermomentum.index_report.models import Candle, IndexReportError


class SignalRow(TypedDict):
    date: str
    open: str
    high: str
    low: str
    close: str
    volume: str
    turnover: str
    M: float | None
    F: float | None
    active_window: int | None
    active_r2: float | None
    positive_persistence: int
    negative_persistence: int
    warmup_complete: bool
    segment_status: Literal["WARMUP", "NO_ACTIVE_SEGMENT", "ACTIVE"]
    slow_buy: bool
    fast_buy: bool
    slow_sell: bool | None
    fast_sell: bool | None
    buy_start: bool
    slow_sell_start: bool
    fast_sell_start: bool
    resumed_after_unknown: bool
    sell_reasons: list[str]
    atr14: str | None
    annualized_volatility: float | None
    execution_eligible: bool


@dataclass(frozen=True, slots=True)
class Fit:
    window: int
    beta: float
    score: float
    r_squared: float


def fit_window(log_prices: NDArray[np.float64], window: int, floor: float) -> Fit:
    """Apply design §2.2 to exactly the trailing W completed observations."""
    values = log_prices[-window:]
    if len(values) != window or not np.isfinite(values).all():
        raise IndexReportError("斜率窗口数据不足或含无效数值")
    x = np.arange(window, dtype=float) - (window - 1) / 2
    beta = float(12 / (window * (window * window - 1)) * np.dot(x, values))
    returns = np.diff(values)
    sigma = float(1.4826 * np.median(np.abs(returns - np.median(returns))))
    centered = values - np.mean(values)
    total = float(np.dot(centered, centered))
    residual = values - (float(np.mean(values)) + beta * x)
    quality = 0.0 if total == 0 else float(1 - np.dot(residual, residual) / total)
    return Fit(window, beta, beta * math.sqrt(window) / max(sigma, floor), quality)


def select_segment(fits: Sequence[Fit], params: StrategyParameters) -> Fit | None:
    """Tie sets are relative to the true extremum, never pairwise/chained."""
    survivors: list[Fit] = []
    for positive in (True, False):
        side = [fit for fit in fits if (fit.score > 0 if positive else fit.score < 0)]
        if not side:
            continue
        scores = [fit.score for fit in side]
        extreme = max(scores) if positive else min(scores)
        near = [
            fit
            for fit in side
            if abs(Decimal.from_float(extreme) - Decimal.from_float(fit.score))
            <= params.score_near_tie_delta
        ]
        chosen = max(near, key=lambda fit: fit.window)
        if chosen.r_squared >= float(params.minimum_r_squared):
            survivors.append(chosen)
    return max(survivors, key=lambda fit: (abs(fit.score), fit.score > 0), default=None)


def compute_signals(candles: Sequence[Candle], config: ReportConfig) -> list[SignalRow]:
    """Return every source session, retaining warmup and unknown-segment rows."""
    params = config.strategy
    if len(candles) < params.minimum_warmup_bars:
        raise IndexReportError("行情不足以完成策略预热")
    logs = np.log(np.array([float(bar.close) for bar in candles], dtype=np.float64))
    if not np.isfinite(logs).all():
        raise IndexReportError("指数点位无法形成有效对数价格")
    returns = np.diff(logs)
    fast_window = params.windows.fast_window
    slow_windows = params.windows.slow_windows
    annualization = config.annualization_factor
    floor = float(params.volatility_floor)
    lam = float(params.ewma_lambda)
    pairs = {window: np.triu_indices(window, 1) for window in slow_windows}
    records: list[SignalRow] = []
    seed: list[Decimal] = []
    atr: Decimal | None = None
    variance: float | None = None
    previous_fast: float | None = None
    positive = negative = 0
    for t, bar in enumerate(candles):
        if t > 0:
            previous_close = candles[t - 1].close
            true_range = max(
                bar.high - bar.low, abs(bar.high - previous_close), abs(bar.low - previous_close)
            )
            if atr is None:
                seed.append(true_range)
                if len(seed) == params.atr_period:
                    atr = sum(seed, Decimal(0)) / Decimal(params.atr_period)
            else:
                atr = ((params.atr_period - 1) * atr + true_range) / Decimal(params.atr_period)
        if t == 2:
            variance = float(returns[0] ** 2)
        elif t > 2:
            if variance is None:
                raise IndexReportError("EWMA 初始化缺失")
            variance = (1 - lam) * float(returns[t - 2] ** 2) + lam * variance
        fast = fit_window(logs[: t + 1], fast_window, floor).score if t + 1 >= fast_window else None
        active = None
        if t + 1 >= max(slow_windows):
            active = select_segment(
                [fit_window(logs[: t + 1], window, floor) for window in slow_windows], params
            )
        m = active.score if active else None
        positive = positive + 1 if m is not None and m > float(params.entry_threshold) else 0
        negative = negative + 1 if m is not None and m < -float(params.entry_threshold) else 0
        agrees = False
        if active is not None:
            y = logs[t - active.window + 1 : t + 1]
            left, right = pairs[active.window]
            theil_sen = float(np.median((y[right] - y[left]) / (right - left)))
            agrees = active.beta * theil_sen > 0
        warm = t + 1 >= params.minimum_warmup_bars
        buy = warm and positive >= params.entry_persistence and agrees
        slow_sell: bool | None = None
        fast_sell: bool | None = None
        reasons: list[str] = []
        if warm and m is not None and fast is not None:
            slow_sell = m < float(params.exit_threshold)
            if slow_sell:
                reasons.append("M")
            if fast <= 0:
                reasons.append("F")
            if previous_fast is not None and fast < previous_fast - float(params.fast_loss_delta):
                reasons.append("D")
            fast_sell = bool(reasons)
        previous = records[-1] if records else None
        status: Literal["WARMUP", "NO_ACTIVE_SEGMENT", "ACTIVE"] = (
            "WARMUP" if not warm else "NO_ACTIVE_SEGMENT" if active is None else "ACTIVE"
        )
        records.append(
            SignalRow(
                date=bar.session.isoformat(),
                open=str(bar.open),
                high=str(bar.high),
                low=str(bar.low),
                close=str(bar.close),
                volume=str(bar.volume),
                turnover=str(bar.turnover),
                M=m,
                F=fast,
                active_window=active.window if active else None,
                active_r2=active.r_squared if active else None,
                positive_persistence=positive,
                negative_persistence=negative,
                warmup_complete=warm,
                segment_status=status,
                slow_buy=buy,
                fast_buy=buy,
                slow_sell=slow_sell,
                fast_sell=fast_sell,
                buy_start=buy and (previous is None or not previous["slow_buy"]),
                slow_sell_start=slow_sell is True
                and (previous is None or previous["slow_sell"] is not True),
                fast_sell_start=fast_sell is True
                and (previous is None or previous["fast_sell"] is not True),
                resumed_after_unknown=status == "ACTIVE"
                and previous is not None
                and previous["segment_status"] == "NO_ACTIVE_SEGMENT",
                sell_reasons=reasons,
                atr14=str(atr) if atr is not None else None,
                annualized_volatility=math.sqrt(annualization * variance)
                if variance is not None
                else None,
                execution_eligible=False,
            )
        )
        previous_fast = fast
    return records


def signal_events(rows: Sequence[SignalRow]) -> list[dict[str, object]]:
    """All condition days, including both sides on the same date; not trades."""
    events: list[dict[str, object]] = []
    for row in rows:
        for variant in ("slow", "fast"):
            buy = row["slow_buy"] if variant == "slow" else row["fast_buy"]
            sell = row["slow_sell"] if variant == "slow" else row["fast_sell"]
            for side, matched in (("buy", buy), ("sell", sell)):
                if matched is not True:
                    continue
                first = (
                    row["buy_start"]
                    if side == "buy"
                    else (row["slow_sell_start"] if variant == "slow" else row["fast_sell_start"])
                )
                reasons = (
                    ["SLOW_ENTRY"]
                    if side == "buy"
                    else (["M"] if variant == "slow" else row["sell_reasons"])
                )
                events.append(
                    {
                        "date": row["date"],
                        "variant": variant,
                        "condition": side,
                        "close": row["close"],
                        "M": row["M"],
                        "F": row["F"],
                        "first_trigger": first,
                        "reasons": "|".join(reasons),
                        "simultaneous_buy_and_sell": buy and sell is True,
                        "resumed_after_unknown": first and row["resumed_after_unknown"],
                        "execution_eligible": False,
                    }
                )
    return events
