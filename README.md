# 931743 指数动量日报

本仓库从中证指数官网获取 **中证半导体材料设备主题指数（931743）** 自 2023-07-19 起的完整日线，按已完成交易日计算慢速／快速动量条件，生成可离线阅读的单页图表和 CSV。它是**指数指标的描述性报告**，不是多市场交易系统；不提供持仓、订单、成交、止损执行、收益回测、隐含波动率或研究引擎。指数本身不可直接交易，信号不是投资建议。

## 本地生成

需要 Python 3.12、[uv](https://docs.astral.sh/uv/) 和可访问中证指数官网的网络。使用锁定依赖（`uv.lock`）；CLI 每次实时请求官网完整历史，没有离线重放或旧缓存替代选项。

```sh
uv sync --frozen --no-dev
uv run --frozen --no-dev python -m supermomentum.index_report --output reports/index-report/manual-2026-09-29
```

`--output` 必须是**尚不存在**的目录；再次运行请换新目录。默认按运行时北京时间选择最近已完成的交易日；盘中只展示上一完整交易日。要固定非未来的历史截止日期，可加 `--as-of YYYY-MM-DD`（例如 `--as-of 2026-09-25`）；计划任务使用 `--scheduled`，非交易日或收盘确认前会输出 `publish: false` 的跳过状态，且不创建报告。两个选项不能同时使用。日历只核验至 **2026-12-31**，超出范围会拒绝而不会猜测交易日。失败时不发布旧数据。

运行目录包含 `site/`（可公开的派生页面、逐日数据和条件 CSV）及 `audit/`（官网原始响应字节、日历、配置和来源记录），顶层 `manifest.json` 记录两者哈希；只有 `site/` 可上 Pages。打开 `site/index.html` 即可查看图表；不要将 `audit/` 当作公开站点上传。详见[指标定义](docs/methodology.md)及[运行与发布](docs/operations.md)。

## 维护范围

```text
.github/workflows/daily-index-report.yml  定时与手动生成、产物保留、Pages 部署
src/supermomentum/config.py           打包默认配置的严格模型与指纹
src/supermomentum/defaults.toml        单一报告配置
src/supermomentum/index_report/        日历、官网数据、指标、页面和 CLI
  calendars.json                       已核验交易日历来源与 2026 休市区间
docs/methodology.md                    可核对的指标口径与限制
docs/operations.md                     本地运行及 Actions/Pages 操作
```

配置由随包的 `defaults.toml` 唯一加载，`schema_version = "931743-config-v1"`、`timeframe = "1d"`、`strategy_version = "supermomentum-baseline-v1"`；冻结的窗口为快速 8、慢速 16/32/64，年化因子 244。CLI 没有配置文件或环境变量覆盖参数。公开站点仅是当前来源版本数据的派生视图，不能当作逐日可得的历史真值。
