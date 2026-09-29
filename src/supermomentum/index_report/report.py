"""Render a self-contained, read-only descriptive index dashboard."""

from __future__ import annotations

import json
from html import escape
from importlib.resources import files


def render_report(payload: dict[str, object]) -> str:
    """Embed supplied historical rows and local assets in one offline HTML document."""
    assets = files(__package__)
    css = assets.joinpath("dashboard.css").read_text(encoding="utf-8")
    js = assets.joinpath("dashboard.js").read_text(encoding="utf-8")
    # JSON is data, not markup: protect script terminators and HTML parsing,
    # including when the source provider supplies unexpected text.
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for original, replacement in (
        ("&", "\\u0026"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("\u2028", "\\u2028"),
        ("\u2029", "\\u2029"),
    ):
        data = data.replace(original, replacement)
    title = escape(str(payload.get("name", "指数信号观察")))
    latest = escape(str(payload.get("latest_session", "未知")))
    status = escape(str(payload.get("data_status_label", "未知")))
    coverage = payload.get("coverage", {})
    coverage = coverage if isinstance(coverage, dict) else {}
    bars = escape(str(coverage.get("bars", "未知")))
    first = escape(str(coverage.get("first_session", "未知")))
    strategy = payload.get("strategy", {})
    strategy = strategy if isinstance(strategy, dict) else {}
    entry = escape(str(strategy.get("entry_threshold", "未知")))
    persistence = escape(str(strategy.get("entry_persistence", "未知")))
    exit_threshold = escape(str(strategy.get("exit_threshold", "未知")))
    fast_delta = escape(str(strategy.get("fast_loss_delta", "未知")))
    template = assets.joinpath("dashboard.html").read_text(encoding="utf-8")
    return template.format(
        title=title,
        css=css,
        js=js,
        data=data,
        latest=latest,
        status=status,
        bars=bars,
        first=first,
        entry=entry,
        persistence=persistence,
        exit_threshold=exit_threshold,
        fast_delta=fast_delta,
    )
