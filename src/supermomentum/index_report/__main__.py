"""python -m supermomentum.index_report --output <new-run-directory>"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from supermomentum.config import load_config
from supermomentum.index_report.application import publish_report
from supermomentum.index_report.data import fetch_history, plan_sessions
from supermomentum.index_report.models import IndexReportError


def _github_output(published: bool, output: Path, latest: str = "") -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with Path(target).open("a", encoding="utf-8") as stream:
            stream.write(f"publish={str(published).lower()}\n")
            if published:
                stream.write(f"site_path={(output / 'site').resolve()}\n")
                stream.write(f"run_path={output.resolve()}\nlatest_session={latest}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="931743 完整历史慢速/快速条件及静态 HTML 报告")
    parser.add_argument("--output", type=Path, required=True, help="新的不可覆盖运行目录")
    parser.add_argument("--as-of", type=date.fromisoformat, help="历史截止日期 YYYY-MM-DD")
    parser.add_argument("--scheduled", action="store_true", help="休市或未收盘时跳过发布")
    args = parser.parse_args(argv)
    if args.scheduled and args.as_of:
        parser.error("--scheduled 与 --as-of 不能同时使用")
    _github_output(False, args.output)
    try:
        plan = plan_sessions(as_of=args.as_of)
        if args.scheduled and not plan.scheduled_due:
            print(
                json.dumps(
                    {
                        "status": "skipped",
                        "reason": plan.status,
                        "as_of": plan.as_of.isoformat(),
                        "publish": False,
                    },
                    ensure_ascii=False,
                )
            )
            return 0
        history = fetch_history(plan)
        config = load_config()
        payload = publish_report(history, config, args.output)
        latest = history.plan.expected_session.isoformat()
        result = {
            "publish": True,
            "data_status": plan.status,
            "as_of": plan.as_of.isoformat(),
            "latest_complete_session": latest,
            "history_bars": len(history.candles),
            "site": str(args.output / "site"),
            "audit": str(args.output / "audit"),
            "latest": payload["latest"],
        }
        summary_target = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_target:
            with Path(summary_target).open("a", encoding="utf-8") as stream:
                stream.write("## 931743 收盘指标条件\n\n```json\n")
                stream.write(json.dumps(result, ensure_ascii=False, indent=2))
                stream.write("\n```\n\n仅为指数指标条件, 不是订单、成交或策略收益。\n")
        _github_output(True, args.output, latest)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (IndexReportError, OSError, ValueError) as exc:
        print(f"931743 报告未发布: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
