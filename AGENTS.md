# Project Conventions

## Scope

This repository publishes a descriptive momentum dashboard for CSI index **931743** (Semiconductor Material & Equipment). Its production boundary is `.github/workflows/daily-index-report.yml` → `python -m supermomentum.index_report` → official history/calendar → configured indicators → immutable report → GitHub Pages. It is not a multi-market trading, position-management, execution, backtesting, IV, or research engine. Treat indicator calculations and data lineage as audit-sensitive code.

## Engineering rules

- Use Python 3.12 and the locked `uv` environment. Keep the implementation under `src/supermomentum`; no services, databases, or web frameworks are needed for a static daily report.
- Keep the runtime focused on `index_report/`, `config.py`, and `defaults.toml`. Do not restore the removed generic provider, market-rule, portfolio, research-governance, or chunk-ledger frameworks without a new requirement.
- Use completed Shanghai-local sessions, UTC capture timestamps, and trailing windows. Never include an unfinished session or use future bars to compute earlier indicators.
- Preserve official response bytes, the exact calendar specification, strict configuration, and source metadata in each immutable run, bound by SHA-256 manifests. Only `site/` belongs in the public Pages artifact; `audit/` remains separate.
- Fail closed on missing expected sessions, malformed data, insufficient warmup history, unsupported calendar years, or invalid configuration. Never substitute another provider, forward-fill gaps, publish stale data as current, or overwrite an existing run.
- Parse external numeric fields as `Decimal`; retain source precision and units. The index and its constituent turnover are not executable security prices or liquidity.
- Keep formulas and thresholds in strict, versioned packaged configuration. Unknown keys and invalid values are errors; there are no environment/file/CLI override paths. Configuration hashes must preserve exact Decimal values independently of the ambient decimal context. Secrets must not enter logs, manifests, hashes, fixtures, or reports.
- The chart, latest status, and exports consume the same computed rows. Preserve `WARMUP` and `NO_ACTIVE_SEGMENT`, explicit unknown values, and simultaneous buy/sell predicates. Conditions are not holdings, orders, fills, paired trades, returns, or investment advice.
- Preserve historical/current/awaiting-close/market-closed status. Current-vintage provider history without historical publication evidence remains execution/research-ineligible.
- Regular tests are offline. Defend causality, calendar/close boundaries, provider parsing, configuration identity, condition transitions, and fail-closed publication; do not retain tests for removed capabilities.
- Migrate every affected caller in the same change. No compatibility aliases or parallel conventions.

## Documentation and verification

- `README.md` is the project entrypoint; `docs/methodology.md` defines the report's calculation semantics; `docs/operations.md` documents generation, artifacts, calendar coverage, and Actions/Pages operations.
- Run the retained tests, Ruff, and strict mypy after integration. For runtime or packaging changes, generate a real report and check the affected behavior; tests alone do not prove publication works.
- Inspect actual desktop/mobile/offline browser rendering for changed report surfaces. Check wheel resources when packaging changes. Never claim a deployment based only on a local build or successful SSH access.
- Preserve existing ignored `reports/` runs as audit evidence. Smoke runs must use fresh output directories.

## Lessons

- CSI `index-perf` history starts at the verified real session 2023-07-19 because a non-session `startDate` can introduce a chart fill point. The identifier is **931743**, not 93174. `tradingValue` is in CNY 100 million units.
- Locked `exchange-calendars==4.11.2` contains XSHG holidays only through 2025. The report supplements it with the captured SSE 2026 holiday notice (2025-12-22, announcement 45); coverage ends 2026-12-31. Do not infer exchange holidays from weekdays or provider-returned dates, or silently upgrade the dependency.
- Both report variants use the same slow-entry condition. The fast variant adds exit predicates; `M < 0.25` is the slow exit condition, while the negative-persistence screen at `M < -1.25` is not a sell-to-close signal. Unknown/resumed condition runs and simultaneous predicates must not become inferred trades.
- The workflow's report path does not use the former generic data, domain, markets, reporting, research, or chunk-state subsystems. Direct runtime dependencies are `exchange-calendars`, `numpy`, and `pydantic`; pandas is still a transitive calendar dependency. Removing unused configuration changes its schema/hash, not the indicator formulas.
- `Decimal.normalize()` can round under the ambient context. Canonical report configuration uses fixed-point formatting with trailing-zero removal so long coefficients retain their exact identity.
- GitHub cron is UTC and cannot encode Chinese exchange holidays; the 18:00 Shanghai weekday schedule delegates holiday/close checks to the verified calendar. Initial Pages setup requires repository administration; ordinary deployment uses Pages/OIDC permissions.
- On this Linux ARM64 workstation, use an existing Playwright ARM64 Chrome through a localhost CDP session rather than the unsupported automatic Chrome download. Missing runtime libraries can be extracted into an isolated temporary root and supplied through `LD_LIBRARY_PATH` without sudo; add CJK fonts through an isolated `FONTCONFIG_FILE` so Chinese labels are visually verifiable. The browser helper's `focus` is HTMLElement-only: focus the SVG chart through native DOM focus in `tab.run`, then send keyboard input.
- A previous dashboard push was rejected because the repository was archived/read-only. That observation is not proof of current remote state. Distinguish local implementation, successful push, and successful Pages deployment; SSH read access alone proves none of the latter two.
