"""Causally planned CSI 931743 history with an explicitly bounded exchange calendar."""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import exchange_calendars as xcals

from .models import Candle, DataStatus, IndexReportError, MarketHistory, SessionPlan

SOURCE_URL = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
HISTORY_START = date(2023, 7, 19)
CALENDAR_VERSION = "XSHG-exchange-calendars-4.11.2-through-2025+SSE-2025-45-2026"
_SHANGHAI = ZoneInfo("Asia/Shanghai")
_CALENDAR_END = date(2025, 12, 31)
_CLOSE_BUFFER = time(15, 30)
_MAX_RESPONSE_BYTES = 32_000_000
_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?\Z")
_DATE = re.compile(r"[0-9]{8}\Z")


def calendar_spec_bytes() -> bytes:
    """The exact checked-in calendar specification included in the audit artifact."""
    try:
        return Path(__file__).with_name("calendars.json").read_bytes()
    except OSError as error:
        raise IndexReportError("Calendar provenance specification is unavailable") from error


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise IndexReportError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise IndexReportError(f"Non-JSON numeric constant: {value}")


def _calendar_spec() -> dict[str, object]:
    try:
        spec = json.loads(calendar_spec_bytes(), object_pairs_hook=_reject_duplicate_keys)
        if not isinstance(spec, dict) or spec.get("version") != CALENDAR_VERSION:
            raise IndexReportError("Calendar specification version mismatch")
        exchange = spec["exchange_calendar"]
        if not isinstance(exchange, dict) or (
            exchange.get("exchange") != "XSHG"
            or exchange.get("version") != "4.11.2"
            or exchange.get("coverage_end") != _CALENDAR_END.isoformat()
            or spec.get("first_verified_session") != HISTORY_START.isoformat()
            or spec.get("coverage_end") != "2026-12-31"
        ):
            raise IndexReportError("Calendar specification coverage mismatch")
        if version("exchange-calendars") != "4.11.2":
            raise IndexReportError("Installed exchange calendar version is not the verified 4.11.2")
        return spec
    except (OSError, ValueError, KeyError, TypeError, PackageNotFoundError) as error:
        if isinstance(error, IndexReportError):
            raise
        raise IndexReportError("Invalid calendar provenance specification") from error


def _sessions_until(end: date) -> tuple[date, ...]:
    if end < HISTORY_START or end.year > 2026:
        raise IndexReportError(f"No verified exchange calendar coverage for {end}")
    spec = _calendar_spec()
    calendar_end = min(end, _CALENDAR_END)
    try:
        sessions = [
            stamp.date()
            for stamp in xcals.get_calendar(
                "XSHG", start=HISTORY_START.isoformat(), end=calendar_end.isoformat()
            ).sessions
        ]
        if end > _CALENDAR_END:
            supplements = spec["supplemental_years"]
            if not isinstance(supplements, dict):
                raise IndexReportError("Missing 2026 SSE calendar")
            year_spec = supplements["2026"]
            if not isinstance(year_spec, dict):
                raise IndexReportError("Invalid 2026 SSE calendar")
            intervals = year_spec["holiday_closures_inclusive"]
            if not isinstance(intervals, list) or not intervals:
                raise IndexReportError("Incomplete SSE holiday intervals")
            closed: set[date] = set()
            for interval in intervals:
                if not isinstance(interval, list) or len(interval) != 2:
                    raise IndexReportError("Invalid SSE holiday interval")
                first, last = (date.fromisoformat(item) for item in interval)
                if first.year != 2026 or last.year != 2026 or first > last:
                    raise IndexReportError("SSE holiday interval out of year")
                closed.update(
                    first + timedelta(days=offset) for offset in range((last - first).days + 1)
                )
            day = date(2026, 1, 1)
            while day <= end:
                if day.weekday() < 5 and day not in closed:
                    sessions.append(day)
                day += timedelta(days=1)
    except (KeyError, ValueError, TypeError) as error:
        if isinstance(error, IndexReportError):
            raise
        raise IndexReportError("Cannot calculate verified exchange sessions") from error
    if not sessions or sessions[0] != HISTORY_START:
        raise IndexReportError("Verified calendar does not cover the first CSI history session")
    return tuple(sessions)


def plan_sessions(*, as_of: date | None = None, now: datetime | None = None) -> SessionPlan:
    """Plan only published closes, never today's unfinished candle or unknown years."""
    instant = datetime.now(UTC) if now is None else now
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.utcoffset() is None:
        raise IndexReportError("Planning requires an aware timestamp")
    local = instant.astimezone(_SHANGHAI)
    if as_of is not None and (type(as_of) is not date or as_of > local.date()):
        raise IndexReportError("as_of must be a nonfuture date")
    requested = local.date() if as_of is None else as_of
    if requested < HISTORY_START:
        raise IndexReportError("as_of precedes verified CSI history")
    # This also checks the calendar coverage for a weekend or holiday in an unknown year.
    sessions = _sessions_until(requested)
    is_today = requested == local.date()
    trading_today = sessions[-1] == requested
    after_close = local.time() >= _CLOSE_BUFFER
    due = is_today and trading_today and after_close
    status: DataStatus
    if is_today and trading_today and not after_close:
        sessions = sessions[:-1]
        status = "awaiting_close"
    elif not trading_today:
        status = "market_closed" if is_today else "historical"
    else:
        status = "current" if is_today else "historical"
    if not sessions:
        raise IndexReportError("No completed sessions available for requested date")
    return SessionPlan(requested, sessions, status, due)


def _validated_plan(plan: SessionPlan) -> None:
    if not isinstance(plan, SessionPlan) or type(plan.as_of) is not date:
        raise IndexReportError("Invalid session plan")
    sessions = _sessions_until(plan.as_of)
    if plan.status == "awaiting_close":
        if not sessions or sessions[-1] != plan.as_of or plan.expected_sessions != sessions[:-1]:
            raise IndexReportError(
                "Awaiting-close plan must exclude exactly today's unfinished session"
            )
    elif plan.expected_sessions != sessions:
        raise IndexReportError("Session plan is not complete against the verified calendar")
    if not plan.expected_sessions:
        raise IndexReportError("Session plan contains no completed sessions")


def _decimal(raw: object, field: str) -> Decimal:
    if isinstance(raw, bool) or not isinstance(raw, (str, Decimal)):
        raise IndexReportError(f"Invalid CSI numeric field: {field}")
    text = str(raw)
    if not _NUMBER.fullmatch(text):
        raise IndexReportError(f"Malformed CSI numeric field: {field}")
    try:
        value = Decimal(text)
    except InvalidOperation as error:
        raise IndexReportError(f"Malformed CSI numeric field: {field}") from error
    if not value.is_finite():
        raise IndexReportError(f"Nonfinite CSI numeric field: {field}")
    return value


def parse_history(raw: bytes, plan: SessionPlan) -> tuple[Candle, ...]:
    """Normalize captured CSI bytes with lossless numerics and exact calendar coverage."""
    _validated_plan(plan)
    if not isinstance(raw, bytes) or not raw or len(raw) > _MAX_RESPONSE_BYTES:
        raise IndexReportError("Missing or oversized official CSI response")
    try:
        payload = json.loads(
            raw,
            parse_float=Decimal,
            parse_int=Decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_reject_duplicate_keys,
        )
        if not isinstance(payload, dict) or str(payload.get("code")) != "200":
            raise IndexReportError("Official CSI request did not succeed")
        rows = payload.get("data")
        if not isinstance(rows, list) or not rows:
            raise IndexReportError("Official CSI history is empty")
        expected = plan.expected_sessions
        if len(rows) != len(expected):
            raise IndexReportError(
                f"Incomplete CSI history: expected {len(expected)} sessions through "
                f"{plan.expected_session}, received {len(rows)}; no report published"
            )
        candles: list[Candle] = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or str(row.get("indexCode")) != "931743":
                raise IndexReportError("CSI index code mismatch or malformed row")
            trade_date = row.get("tradeDate")
            if not isinstance(trade_date, str) or not _DATE.fullmatch(trade_date):
                raise IndexReportError("Malformed CSI tradeDate")
            day = datetime.strptime(trade_date, "%Y%m%d").date()
            if day != expected[index]:
                raise IndexReportError(
                    f"CSI session mismatch at row {index}: got {day}, expected {expected[index]}"
                )
            opening, high, low, close, volume, amount_yi = (
                _decimal(row[key], key)
                for key in ("open", "high", "low", "close", "tradingVol", "tradingValue")
            )
            if not 0 < low <= min(opening, close) <= max(opening, close) <= high:
                raise IndexReportError(f"Invalid CSI OHLC on {day}")
            if volume < 0 or amount_yi < 0:
                raise IndexReportError(f"Negative CSI volume/turnover on {day}")
            amount_parts = amount_yi.as_tuple()
            exponent = amount_parts.exponent
            if not isinstance(exponent, int):
                raise IndexReportError("Nonfinite CSI turnover exponent")
            turnover = Decimal((amount_parts.sign, amount_parts.digits, exponent + 8))
            candles.append(Candle(day, opening, high, low, close, volume, turnover))
        return tuple(candles)
    except (UnicodeError, ValueError, TypeError, KeyError, InvalidOperation) as error:
        if isinstance(error, IndexReportError):
            raise
        raise IndexReportError("Malformed official CSI daily history") from error


def fetch_history(plan: SessionPlan) -> MarketHistory:
    """Fetch the entire planned CSI history without a stale-cache or provider fallback."""
    _validated_plan(plan)
    query = urlencode(
        {
            "indexCode": "931743",
            "startDate": HISTORY_START.strftime("%Y%m%d"),
            "endDate": plan.expected_session.strftime("%Y%m%d"),
        }
    )
    url = f"{SOURCE_URL}?{query}"
    request = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.csindex.com.cn/",
            "Accept": "application/json",
        },
    )
    requested_at = datetime.now(UTC)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        fetched_at = datetime.now(UTC)
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise IndexReportError("Official CSI history request failed") from error
    candles = parse_history(raw, plan)
    return MarketHistory(
        plan, candles, raw, url, requested_at, fetched_at, CALENDAR_VERSION, calendar_spec_bytes()
    )
