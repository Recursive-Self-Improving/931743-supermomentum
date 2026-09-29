"""Strict, deterministic configuration for the CSI 931743 index report."""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

DEFAULT_CONFIG_PATH: Final[Traversable] = files("supermomentum").joinpath("defaults.toml")


class ConfigLoadError(ValueError):
    """Bundled configuration could not be read."""


class ConfigValidationError(ValueError):
    """Bundled configuration is invalid."""


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class BaselineStrategyConfig(ConfigModel):
    kind: Literal["baseline_v1"] = "baseline_v1"
    fast_window: int = Field(gt=0)
    slow_windows: tuple[int, int, int]

    @model_validator(mode="after")
    def validate_windows(self) -> BaselineStrategyConfig:
        if any(window <= 0 for window in self.slow_windows):
            raise ValueError("slow windows must be positive")
        if (
            tuple(sorted(self.slow_windows)) != self.slow_windows
            or len(set(self.slow_windows)) != 3
        ):
            raise ValueError("slow windows must be strictly increasing")
        if self.fast_window >= self.slow_windows[0]:
            raise ValueError("fast_window must be smaller than the first slow window")
        return self


class StrategyParameters(ConfigModel):
    windows: BaselineStrategyConfig
    score_near_tie_delta: Decimal = Field(gt=0)
    minimum_r_squared: Decimal = Field(ge=0, le=1)
    volatility_floor: Decimal = Field(gt=0)
    entry_threshold: Decimal = Field(gt=0)
    exit_threshold: Decimal = Field(ge=0)
    fast_loss_delta: Decimal = Field(gt=0)
    entry_persistence: int = Field(gt=0)
    minimum_warmup_bars: int = Field(gt=0)
    atr_period: int = Field(gt=0)
    ewma_lambda: Decimal = Field(gt=0, lt=1)
    ewma_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_thresholds(self) -> StrategyParameters:
        if self.exit_threshold >= self.entry_threshold:
            raise ValueError("exit_threshold must be smaller than entry_threshold")
        if self.minimum_warmup_bars < max(self.windows.slow_windows):
            raise ValueError("minimum_warmup_bars must cover the largest slow window")
        return self


class ReportConfig(ConfigModel):
    schema_version: Literal["931743-config-v1"]
    timeframe: Literal["1d"]
    strategy_version: Literal["supermomentum-baseline-v1"]
    annualization_factor: int = Field(gt=0)
    strategy: StrategyParameters


_DECIMAL_FIELDS: Final = frozenset(
    {
        "score_near_tie_delta",
        "minimum_r_squared",
        "volatility_floor",
        "entry_threshold",
        "exit_threshold",
        "fast_loss_delta",
        "ewma_lambda",
    }
)


def _normalize_decimal_inputs(value: object) -> object:
    if isinstance(value, Mapping):
        normalized: dict[object, object] = {}
        for key, item in value.items():
            if key in _DECIMAL_FIELDS:
                if isinstance(item, bool) or not isinstance(item, (str, int, float, Decimal)):
                    raise ConfigValidationError(f"{key} must be a decimal number")
                try:
                    decimal = Decimal(str(item))
                except (InvalidOperation, ValueError) as exc:
                    raise ConfigValidationError(f"{key} must be a decimal number") from exc
                if not decimal.is_finite():
                    raise ConfigValidationError(f"{key} must be finite")
                normalized[key] = decimal
            else:
                normalized[key] = _normalize_decimal_inputs(item)
        return normalized
    if isinstance(value, (list, tuple)):
        return tuple(_normalize_decimal_inputs(item) for item in value)
    return value


def load_config() -> ReportConfig:
    """Read only the packaged report defaults, rejecting unknown and invalid keys."""
    try:
        with DEFAULT_CONFIG_PATH.open("rb") as stream:
            data = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigLoadError("unable to load bundled report configuration") from exc
    try:
        normalized = _normalize_decimal_inputs(data)
        return ReportConfig.model_validate(normalized)
    except ValidationError as exc:
        errors = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_url=False, include_input=False, include_context=False)
        ]
        raise ConfigValidationError(
            "configuration validation failed: " + "; ".join(errors)
        ) from exc


def _canonical_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _canonical_value(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ConfigValidationError("canonical configuration contains a nonfinite Decimal")
        # Decimal.normalize() rounds to the ambient context; fixed-point formatting does not.
        text = format(value, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return "0" if not value else text
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ConfigValidationError(f"unsupported canonical configuration type: {type(value).__name__}")


def canonical_config_bytes(config: ReportConfig) -> bytes:
    """Return canonical UTF-8 JSON for the validated report configuration."""
    return (
        json.dumps(
            _canonical_value(config), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        + "\n"
    ).encode("utf-8")


def config_sha256(config: ReportConfig) -> str:
    return hashlib.sha256(canonical_config_bytes(config)).hexdigest()


__all__ = [
    "BaselineStrategyConfig",
    "ConfigLoadError",
    "ConfigValidationError",
    "ReportConfig",
    "StrategyParameters",
    "canonical_config_bytes",
    "config_sha256",
    "load_config",
]
