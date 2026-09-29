# 运行、核对与发布

## 本地运行

需 Python 3.12、uv、访问[中证指数官网行情页](https://www.csindex.com.cn/csindex-home/perf/index-perf)的网络。工作流固定 uv 0.12.20，运行环境由 `uv.lock` 和 `--frozen` 约束；项目只使用随包的 `defaults.toml`（`931743-config-v1`、日线、冻结 baseline_v1 窗口、A 股年化 244），无 CLI 路径、环境变量或交互式参数覆盖配置。

```sh
uv sync --frozen --no-dev
uv run --frozen --no-dev python -m supermomentum.index_report --output reports/index-report/manual-2026-09-29
# 显式历史日期：目录须换成从未使用的新名字
uv run --frozen --no-dev python -m supermomentum.index_report --as-of 2026-09-25 --output reports/index-report/historical-2026-09-25
```

命令实时请求 2023-07-19 至期望交易日的**完整**官网历史。`--as-of` 按北京时间解释为非未来的截止日期；休市日期选最近完整交易日，指定过去日期标注历史分析，指定今日仍按今日状态判定。北京时间 **15:30** 前不会纳入当日未确认收盘日线（可以发布上一完整日的 `awaiting_close` 报告）；`--scheduled` 仅在北京时间当日为交易日且已到 15:30 时生成，否则打印 `{"status":"skipped", "reason":..., "publish":false}` 并成功退出，不抓行情、不建输出目录。`--scheduled` 不能和 `--as-of` 合用。若今日非交易日，普通运行可生成最近完整日的 `market_closed` 报告；指定过去日期为 `historical`；交易日收盘确认后当日为 `current`。计划任务未到时间／休市不会上传或部署。

官网请求失败、行数不足、任一交易日缺失／错序、代码不符、数值／OHLC 错误、期望完成交易日未覆盖，均报错且不以旧行情或其他来源发布。输出路径**必须不存在**；程序先在同级临时目录完成全部文件、清单哈希核验后重命名发布，失败不覆盖旧目录。交易日历依赖固定 `exchange-calendars==4.11.2` 的 XSHG 交易日（至 2025-12-31）及随包的 2026 年上海证券交易所休市区间，来源为[上证公告〔2025〕45号](https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml)；核验终点 **2026-12-31**，此后拒绝而不是推断下一年的日历。日历约束与来源字节记录在 `src/supermomentum/index_report/calendars.json`。

## 文件与核对

```text
<新输出目录>/
  site/index.html          内嵌 CSS、JS、完整历史与图表的离线页面
  site/daily.csv           每个官网交易日一行，含预热及未知段
  site/signals.csv         满足慢／快买卖条件的日期及原因（非成交）
  site/summary.json        全量派生行、当前状态、来源和警告
  site/manifest.json       公开文件哈希、版本与来源/实现指纹
  audit/raw-index.json     官网原始响应字节（非公开）
  audit/calendar.json      日历规范原始字节
  audit/config.json        规范化打包配置
  audit/source.json        请求时间、地址、来源摘要
  manifest.json            运行级 site/ 与 audit/ 文件哈希
```

例如运行后 `python -m json.tool reports/index-report/manual-2026-09-29/site/manifest.json` 查看公开清单，`python -m json.tool reports/index-report/manual-2026-09-29/manifest.json` 查看运行级清单，浏览器打开对应 `site/index.html` 查看真实图表和日期状态；用 `sha256sum reports/index-report/manual-2026-09-29/audit/raw-index.json` 对照清单来源 `raw_sha256`。执行成功的标准输出 JSON 有 `publish: true`、`latest_complete_session`、`data_status`、`site`、`audit`；检查 `latest_complete_session` 是否符合预期日历和官网记录。原始 API 响应是审计数据，**仅将 `site/` 公布到 Pages**；公开页面数据是衍生物而非历史逐时点快照。

## GitHub Actions 与 Pages

`.github/workflows/daily-index-report.yml` 在周一至周五 **10:00 UTC＝北京时间 18:00** 定时运行（交易所假日由程序跳过），也支持手动 `workflow_dispatch`。推送触发**仅限 `master`** 上变动 workflow、`src/supermomentum/index_report/**`、`src/supermomentum/config.py`、`src/supermomentum/defaults.toml`、`pyproject.toml` 或 `uv.lock`；推送其他文件（包括文档）不触发。`build` 作业另有**仓库默认分支**守卫，因此若默认分支不是 `master`，`master` push 即使匹配路径也不执行生成；手动与定时同样须满足默认分支守卫。定时事件传 `--scheduled`；手动／受路径过滤的推送不传此选项，盘中可生成上一完整日的有状态报告。

成功发布时工作流上传整个运行目录为 Actions 审计 artifact（配置的保留期 **90 天**），但 Pages artifact **只上传 `site/`**；`deploy` 仅在 `publish=true` 时配置并部署 Pages。仓库管理员需在 Settings → Pages 将构建/部署来源设为 **GitHub Actions**，允许 workflow 及 `github-pages` 环境部署；部署作业要求 `pages: write` 和 `id-token: write` 权限，并受仓库／组织 Pages 策略及环境保护规则制约。代码定义了工作流，**不表示当前已经上线或已有长期审计归档**；Actions 的 artifact 保留期限也不是永久保存承诺。

排障限于先看 Actions `build` 输出或本地 stderr：若 `skipped`，核对北京时间、交易日和是否传入 `--scheduled`；若日历超界，不能靠猜测或忽略日期继续运行；若官网响应缺失／改版，勿改用不完整缓存，应检查来源与预期交易日；若输出目录已存在，请选新的运行路径；若生成成功但未部署，核对 `publish`、默认分支守卫、Pages 设置和 `deploy` 作业日志。不要通过忽略缺口来取得过时的“成功”页面。

## 开发验证

```sh
uv sync --frozen
uv run --frozen pytest
uv run --frozen ruff check src tests
uv run --frozen mypy
uv build --wheel
```

`tests/test_config.py` 验证配置拒绝非法输入和规范化指纹；`tests/test_index_report.py` 验证交易日／收盘边界、官网数据解析、因果指标、未知段和发布失败行为，测试不访问网络。修改运行链路后，还需实际生成一个全新报告、核对清单和 CSV，并在浏览器检查页面；测试通过不代表官网数据完整或 Pages 已部署。修改打包配置时，应在仅含运行依赖的隔离环境安装 wheel，确认日历、默认配置和 HTML/CSS/JS 资源齐全。
