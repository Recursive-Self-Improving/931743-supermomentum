"""Build one immutable run; only its site/ subtree may be deployed to Pages."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from supermomentum.config import ReportConfig, canonical_config_bytes, config_sha256
from supermomentum.index_report import REPORT_VERSION
from supermomentum.index_report.models import IndexReportError, MarketHistory
from supermomentum.index_report.report import render_report
from supermomentum.index_report.signals import SignalRow, compute_signals, signal_events

_STATUS_LABELS = {
    "current": "最新完整交易日已更新",
    "historical": "指定日期历史分析, 不代表今日状态",
    "awaiting_close": "今日尚未完成收盘确认, 仅展示上一完整交易日",
    "market_closed": "请求日期休市, 展示最近完整交易日",
}
_EVENT_FIELDS = [
    "date",
    "variant",
    "condition",
    "close",
    "M",
    "F",
    "first_trigger",
    "reasons",
    "simultaneous_buy_and_sell",
    "resumed_after_unknown",
    "execution_eligible",
]


def _digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n").encode()


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _csv_rows(rows: list[SignalRow]) -> Iterable[dict[str, object]]:
    for row in rows:
        converted: dict[str, object] = dict(row)
        converted["sell_reasons"] = "|".join(row["sell_reasons"])
        yield converted


def _source_hashes() -> dict[str, str]:
    package = files("supermomentum.index_report")
    return {
        name: _digest(package.joinpath(name).read_bytes())
        for name in (
            "__init__.py",
            "models.py",
            "data.py",
            "calendars.json",
            "signals.py",
            "application.py",
            "report.py",
            "dashboard.html",
            "dashboard.js",
            "dashboard.css",
            "__main__.py",
        )
    }


def build_payload(
    history: MarketHistory, config: ReportConfig, *, generated_at: datetime | None = None
) -> dict[str, object]:
    """Use the same feature rows for chart, latest status and every CSV condition."""
    generated_at = generated_at or datetime.now(UTC)
    if generated_at.tzinfo is None or generated_at.utcoffset() is None:
        raise IndexReportError("报告生成时间必须包含时区")
    if not history.candles or history.candles[-1].session != history.plan.expected_session:
        raise IndexReportError("最新行情未覆盖期望的完整交易日, 不发布旧数据")
    rows = compute_signals(history.candles, config)
    params = config.strategy
    return {
        "schema_version": REPORT_VERSION,
        "symbol": "931743",
        "name": "中证半导体材料设备主题指数",
        "generated_at_utc": generated_at.astimezone(UTC).isoformat(),
        "as_of": history.plan.as_of.isoformat(),
        "latest_session": history.plan.expected_session.isoformat(),
        "expected_session": history.plan.expected_session.isoformat(),
        "data_status": history.plan.status,
        "data_status_label": _STATUS_LABELS[history.plan.status],
        "coverage": {
            "first_session": rows[0]["date"],
            "last_session": rows[-1]["date"],
            "bars": len(rows),
            "minimum_warmup_bars": params.minimum_warmup_bars,
            "first_signal_session": next(
                (row["date"] for row in rows if row["warmup_complete"]), None
            ),
        },
        "strategy": {
            "version": config.strategy_version,
            "fast_window": params.windows.fast_window,
            "slow_windows": list(params.windows.slow_windows),
            "entry_threshold": float(params.entry_threshold),
            "entry_persistence": params.entry_persistence,
            "exit_threshold": float(params.exit_threshold),
            "fast_loss_delta": float(params.fast_loss_delta),
            "minimum_r_squared": float(params.minimum_r_squared),
            "config_sha256": config_sha256(config),
        },
        "source": {
            "provider": "中证指数官网公开行情接口",
            "url": history.source_url,
            "requested_at_utc": history.requested_at_utc.isoformat(),
            "fetched_at_utc": history.fetched_at_utc.isoformat(),
            "raw_sha256": _digest(history.raw_payload),
            "calendar_version": history.calendar_version,
            "calendar_sha256": _digest(history.calendar_spec),
            "availability_time_utc": None,
            "adjustment_version": "official-price-index-current-vintage-no-extra-adjustment-v1",
        },
        "warnings": [
            "仅展示指数收盘后的指标条件, 不是实际订单、成交、持仓或投资建议。",
            "两版买入条件相同; 快速版增加退出条件。同日买卖条件可同时成立, 不能解释为配对交易。",
            "未知动量段与预热不足单独标注, 不代表 HOLD; 这些表不包含持仓止损或强制退出。",
            "历史数据是提供方当前版本, 缺少历史发布时间和修订证据, 不构成可执行回测。",
            "931743 不可直接交易; 成分股成交额不是指数或 ETF 的可执行流动性。",
            "公开页面没有发布原始 API 响应; 原始响应及配置作为独立审计产物保留。",
        ],
        "latest": rows[-1],
        "rows": rows,
        "downloads": {
            "daily": "daily.csv",
            "signals": "signals.csv",
            "summary": "summary.json",
            "manifest": "manifest.json",
        },
    }


def publish_report(history: MarketHistory, config: ReportConfig, output: Path) -> dict[str, object]:
    """Publish only after HTML, exports and both manifests are complete and verified."""
    if output.exists():
        raise IndexReportError(f"不覆盖已有报告目录: {output}; 请选择新的输出目录")
    payload = build_payload(history, config)
    # Typed rows are obtained once here and passed unchanged into every surface.
    rows_value = payload["rows"]
    if not isinstance(rows_value, list):
        raise IndexReportError("报告行结构无效")
    rows: list[SignalRow] = rows_value
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".index-report-", dir=output.parent))
    try:
        site = stage / "site"
        audit = stage / "audit"
        site.mkdir()
        audit.mkdir()
        (audit / "raw-index.json").write_bytes(history.raw_payload)
        (audit / "calendar.json").write_bytes(history.calendar_spec)
        (audit / "config.json").write_bytes(canonical_config_bytes(config))
        (audit / "source.json").write_bytes(_json_bytes(payload["source"]))
        _write_csv(site / "daily.csv", _csv_rows(rows), list(rows[0]))
        _write_csv(site / "signals.csv", signal_events(rows), _EVENT_FIELDS)
        (site / "summary.json").write_bytes(_json_bytes(payload))
        (site / "index.html").write_text(render_report(payload), encoding="utf-8")
        public_manifest = {
            "schema_version": REPORT_VERSION + "-site-manifest",
            "execution_eligible": False,
            "research_eligible": False,
            "source": payload["source"],
            "config_sha256": config_sha256(config),
            "implementation": _source_hashes(),
            "files": {p.name: _digest(p.read_bytes()) for p in sorted(site.iterdir())},
        }
        (site / "manifest.json").write_bytes(_json_bytes(public_manifest))
        manifest_files = {
            p.relative_to(stage).as_posix(): _digest(p.read_bytes())
            for folder in (site, audit)
            for p in sorted(folder.iterdir())
        }
        root_manifest = {
            "schema_version": REPORT_VERSION + "-run-manifest",
            "source": payload["source"],
            "execution_eligible": False,
            "files": manifest_files,
        }
        (stage / "manifest.json").write_bytes(_json_bytes(root_manifest))
        for name, expected in manifest_files.items():
            if _digest((stage / name).read_bytes()) != expected:
                raise IndexReportError(f"报告发布前哈希核验失败: {name}")
        os.rename(stage, output)
    except BaseException:
        shutil.rmtree(stage)
        raise
    return payload
