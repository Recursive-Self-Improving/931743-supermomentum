"""Immutable descriptive index inputs; deliberately not executable market Bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

DataStatus = Literal["current", "historical", "awaiting_close", "market_closed"]


class IndexReportError(ValueError):
    """Data/calendar/publication failure that must block a new public report."""


@dataclass(frozen=True, slots=True)
class Candle:
    session: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal


@dataclass(frozen=True, slots=True)
class SessionPlan:
    as_of: date
    expected_sessions: tuple[date, ...]
    status: DataStatus
    scheduled_due: bool

    @property
    def expected_session(self) -> date:
        return self.expected_sessions[-1]


@dataclass(frozen=True, slots=True)
class MarketHistory:
    plan: SessionPlan
    candles: tuple[Candle, ...]
    raw_payload: bytes
    source_url: str
    requested_at_utc: datetime
    fetched_at_utc: datetime
    calendar_version: str
    calendar_spec: bytes
