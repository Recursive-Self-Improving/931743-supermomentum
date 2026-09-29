"""Offline regressions for the descriptive daily-report data and signal boundaries."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from supermomentum.config import load_config
from supermomentum.index_report import __main__ as cli
from supermomentum.index_report.data import parse_history, plan_sessions
from supermomentum.index_report.models import Candle, IndexReportError
from supermomentum.index_report.signals import Fit, compute_signals, select_segment, signal_events

# Captured CSI OHLC fields for the first two verified sessions. No network in tests.
_CAPTURED = b"""{"code":"200","data":[
 {"tradeDate":"20230719","indexCode":"931743","open":3450.1,"high":3475.77,
  "low":3402.53,"close":3416.96,"tradingVol":536439769,"tradingValue":151.33},
 {"tradeDate":"20230720","indexCode":"931743","open":3424.76,"high":3429.85,
  "low":3375.58,"close":3379.06,"tradingVol":515459646,"tradingValue":119.72}
]}"""


@pytest.mark.parametrize(
    ("instant", "expected", "status", "due"),
    [
        ("2026-09-29T07:29:59+00:00", "2026-09-28", "awaiting_close", False),
        ("2026-09-29T07:30:00+00:00", "2026-09-29", "current", True),
        ("2026-09-25T10:00:00+00:00", "2026-09-24", "market_closed", False),
        ("2026-09-26T10:00:00+00:00", "2026-09-24", "market_closed", False),
        ("2026-09-28T06:00:00+00:00", "2026-09-24", "awaiting_close", False),
    ],
)
def test_close_buffer_and_exchange_holidays(
    instant: str, expected: str, status: str, due: bool
) -> None:
    plan = plan_sessions(now=datetime.fromisoformat(instant))
    assert plan.expected_session.isoformat() == expected
    assert plan.status == status
    assert plan.scheduled_due is due


def test_historical_cutoff_does_not_use_later_sessions() -> None:
    plan = plan_sessions(as_of=date(2026, 9, 24), now=datetime(2026, 9, 29, 10, tzinfo=UTC))
    assert plan.expected_session == date(2026, 9, 24)
    assert plan.status == "historical"
    assert not plan.scheduled_due


def test_unverified_calendar_year_fails_instead_of_guessing_weekdays() -> None:
    with pytest.raises(IndexReportError, match="calendar coverage"):
        plan_sessions(now=datetime(2027, 1, 4, 10, tzinfo=UTC))


def test_decimal_source_prices_and_turnover_units_are_lossless() -> None:
    plan = plan_sessions(as_of=date(2023, 7, 20), now=datetime(2026, 9, 29, tzinfo=UTC))
    bars = parse_history(_CAPTURED, plan)
    assert bars[0].close == Decimal("3416.96")
    assert bars[0].turnover == Decimal("15133000000")
    assert bars[1].volume == Decimal("515459646")


@pytest.mark.parametrize("fault", ["missing_latest", "duplicate", "bad_ohlc", "wrong_symbol"])
def test_corrupted_or_incomplete_history_never_becomes_no_signal(fault: str) -> None:
    payload = json.loads(_CAPTURED)
    if fault == "missing_latest":
        payload["data"].pop()
    elif fault == "duplicate":
        payload["data"][1]["tradeDate"] = "20230719"
    elif fault == "bad_ohlc":
        payload["data"][1]["low"] = 9000
    else:
        payload["data"][1]["indexCode"] = "931744"
    plan = plan_sessions(as_of=date(2023, 7, 20), now=datetime(2026, 9, 29, tzinfo=UTC))
    with pytest.raises(IndexReportError):
        parse_history(json.dumps(payload).encode(), plan)


def test_nonfinite_and_duplicate_json_fields_are_rejected() -> None:
    plan = plan_sessions(as_of=date(2023, 7, 20), now=datetime(2026, 9, 29, tzinfo=UTC))
    for raw in (
        _CAPTURED.replace(b'"close":3416.96', b'"close":NaN'),
        _CAPTURED.replace(b'"close":3416.96', b'"close":3416.96,"close":1'),
    ):
        with pytest.raises(IndexReportError):
            parse_history(raw, plan)


def _candles(prices: list[Decimal]) -> list[Candle]:
    return [
        Candle(
            date(2024, 1, 1) + timedelta(days=i),
            price,
            price + 1,
            price - 1,
            price,
            Decimal(1_000_000),
            Decimal(100_000_000),
        )
        for i, price in enumerate(prices)
    ]


def test_future_changes_do_not_change_past_signals_or_current_lagged_volatility() -> None:
    config = load_config()
    bars = _candles([Decimal(100 + i) for i in range(110)])
    full = compute_signals(bars, config)
    assert compute_signals(bars[:90], config) == full[:90]
    changed = list(bars)
    last = bars[-1]
    changed[-1] = Candle(
        last.session,
        last.open * 2,
        last.high * 2,
        last.low * 2,
        last.close * 2,
        last.volume,
        last.turnover,
    )
    shocked = compute_signals(changed, config)
    assert shocked[:-1] == full[:-1]
    assert shocked[-1]["annualized_volatility"] == full[-1]["annualized_volatility"]
    assert shocked[-1]["F"] != full[-1]["F"]


def test_warmup_and_no_active_segment_do_not_emit_sell_or_hold() -> None:
    config = load_config()
    rows = compute_signals(_candles([Decimal(100)] * 100), config)
    assert all(row["segment_status"] == "WARMUP" for row in rows[:79])
    assert all(row["segment_status"] == "NO_ACTIVE_SEGMENT" for row in rows[79:])
    assert all(row["slow_sell"] is None and row["fast_sell"] is None for row in rows)
    assert signal_events(rows) == []


def test_simultaneous_slow_entry_and_fast_exit_are_not_silently_collapsed() -> None:
    prices = [Decimal(100 + i if i < 94 else 193 - 2 * (i - 93)) for i in range(100)]
    rows = compute_signals(_candles(prices), load_config())
    latest = rows[-1]
    assert latest["slow_buy"] and latest["fast_buy"]
    assert latest["slow_sell"] is False
    assert latest["fast_sell"] is True
    events = [row for row in signal_events(rows) if row["date"] == latest["date"]]
    assert {(row["variant"], row["condition"]) for row in events} == {
        ("slow", "buy"),
        ("fast", "buy"),
        ("fast", "sell"),
    }


@pytest.mark.parametrize("sign", [1, -1])
def test_near_ties_are_not_transitive(sign: int) -> None:
    chosen = select_segment(
        [
            Fit(16, sign * 0.01, sign * 1.0, 0.5),
            Fit(32, sign * 0.01, sign * 0.96, 0.5),
            Fit(64, sign * 0.01, sign * 0.92, 0.5),
        ],
        load_config().strategy,
    )
    assert chosen is not None and chosen.window == 32


def test_rejected_selected_fit_does_not_fall_back_to_another_window() -> None:
    params = load_config().strategy
    assert (
        select_segment([Fit(32, -0.01, -0.82, 0.31), Fit(64, -0.01, -0.74, 0.45)], params) is None
    )
    chosen = select_segment([Fit(32, 0.01, 1.25, 0.5), Fit(64, -0.01, -1.25, 0.5)], params)
    assert chosen is not None and chosen.score > 0


def test_failed_live_capture_blocks_publication_and_success_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "report"
    github_output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    plan = plan_sessions(as_of=date(2026, 9, 28), now=datetime(2026, 9, 29, 10, tzinfo=UTC))
    monkeypatch.setattr(cli, "plan_sessions", lambda **kwargs: plan)

    def fail_capture(*args: object) -> None:
        raise IndexReportError("provider unavailable")

    monkeypatch.setattr(cli, "fetch_history", fail_capture)
    assert cli.main(["--output", str(output)]) == 1
    assert not output.exists()
    assert "publish=true" not in github_output.read_text()


def test_scheduled_holiday_does_not_fetch_or_replace_the_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_sessions(now=datetime(2026, 9, 25, 10, tzinfo=UTC))
    monkeypatch.setattr(cli, "plan_sessions", lambda **kwargs: plan)

    def unexpected_fetch(*args: object) -> None:
        raise AssertionError("A scheduled holiday must not fetch")

    monkeypatch.setattr(cli, "fetch_history", unexpected_fetch)
    output = tmp_path / "holiday"
    assert cli.main(["--output", str(output), "--scheduled"]) == 0
    assert not output.exists()
