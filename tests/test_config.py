"""Consumer-visible validation and canonical identity for the daily report config."""

from __future__ import annotations

import json
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import supermomentum.config as config_module
from supermomentum.config import (
    ConfigLoadError,
    ConfigValidationError,
    ReportConfig,
    canonical_config_bytes,
    config_sha256,
    load_config,
)


def _data() -> dict[str, Any]:
    return load_config().model_dump(mode="python")


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "markets", {}),
        (None, "research", {}),
        (None, "iv", {}),
        ("strategy", "atr_multiplier", Decimal("2")),
        ("strategy", "cooldown_sessions", 1),
        ("strategy", "exit_persistence", 1),
        ("windows", "research_candidate_v1", True),
    ],
)
def test_removed_configuration_keys_are_rejected(
    section: str | None, key: str, value: object
) -> None:
    data = _data()
    target = data if section is None else data["strategy"]
    if section == "windows":
        target = target["windows"]
    target[key] = value
    with pytest.raises(ValidationError, match="extra_forbidden"):
        ReportConfig.model_validate(data)


@pytest.mark.parametrize(
    "slow", [(16, 32), (16, 32, 64, 128), (16, 16, 64), (32, 16, 64), (0, 32, 64)]
)
def test_slow_windows_require_three_positive_increasing_values(slow: tuple[int, ...]) -> None:
    data = _data()
    data["strategy"]["windows"]["slow_windows"] = slow
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(data)


def test_fast_window_must_precede_slow_windows() -> None:
    data = _data()
    data["strategy"]["windows"]["fast_window"] = 16
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(data)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("entry_threshold", Decimal("0")),
        ("exit_threshold", Decimal("-0.01")),
        ("score_near_tie_delta", Decimal("0")),
        ("volatility_floor", Decimal("0")),
        ("fast_loss_delta", Decimal("0")),
        ("minimum_r_squared", Decimal("1.01")),
        ("ewma_lambda", Decimal("1")),
        ("ewma_lambda", Decimal("NaN")),
        ("entry_persistence", 0),
        ("atr_period", 0),
        ("ewma_version", ""),
    ],
)
def test_invalid_strategy_numerics_are_rejected(field: str, value: object) -> None:
    data = _data()
    data["strategy"][field] = value
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(data)


def test_threshold_and_warmup_boundaries() -> None:
    data = _data()
    strategy = data["strategy"]
    strategy["exit_threshold"] = strategy["entry_threshold"]
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(data)
    strategy["exit_threshold"] = Decimal("0")
    strategy["minimum_warmup_bars"] = 63
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(data)
    strategy["minimum_warmup_bars"] = 64
    assert ReportConfig.model_validate(data).strategy.minimum_warmup_bars == 64


@pytest.mark.parametrize(
    "field,value",
    [
        ("annualization_factor", 0),
        ("annualization_factor", True),
        ("timeframe", "1h"),
        ("schema_version", "supermomentum-config-v1"),
        ("strategy_version", "research_candidate_v1"),
    ],
)
def test_report_contract_rejects_invalid_metadata(field: str, value: object) -> None:
    data = _data()
    data[field] = value
    with pytest.raises(ValidationError):
        ReportConfig.model_validate(data)


def test_packaged_defaults_reject_obsolete_keys_and_nonfinite_decimal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = config_module.DEFAULT_CONFIG_PATH.read_text(encoding="utf-8")
    source = tmp_path / "defaults.toml"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", source)
    source.write_text(original + "\n[strategy.obsolete]\nentry = 1\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError, match="obsolete") as caught:
        load_config()
    assert isinstance(caught.value, ValueError)
    source.write_text(
        original.replace('entry_threshold = "1.25"', 'entry_threshold = "NaN"'), encoding="utf-8"
    )
    with pytest.raises(ConfigValidationError, match="finite"):
        load_config()
    source.write_text("not = [valid TOML", encoding="utf-8")
    with pytest.raises(ConfigLoadError) as caught_load:
        load_config()
    assert isinstance(caught_load.value, ValueError)


def test_decimal_identity_preserves_precision_independent_of_context() -> None:
    data = _data()
    strategy = data["strategy"]
    precise_lambda = "0.987654321098765432109876543210987654321"
    strategy["ewma_lambda"] = Decimal(precise_lambda)
    strategy["entry_threshold"] = Decimal("1.250000")
    first = ReportConfig.model_validate(data)
    strategy["entry_threshold"] = Decimal("1.25")
    second = ReportConfig.model_validate(data)
    with localcontext() as context:
        context.prec = 4
        low_precision = canonical_config_bytes(first)
    with localcontext() as context:
        context.prec = 80
        high_precision = canonical_config_bytes(second)
    assert low_precision == high_precision
    assert config_sha256(first) == config_sha256(second)
    assert json.loads(low_precision)["strategy"]["ewma_lambda"] == precise_lambda
    strategy["entry_threshold"] = Decimal("1.2500000000000000000000000000000000000001")
    assert config_sha256(ReportConfig.model_validate(data)) != config_sha256(first)
