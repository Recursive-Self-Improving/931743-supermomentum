(() => {
  "use strict";
  const report = JSON.parse(document.getElementById("report-data").textContent);
  const rows = report.rows || [];
  const $ = id => document.getElementById(id);
  const svgNS = "http://www.w3.org/2000/svg";
  const controls = ["variant", "range", "signal-mode", "signal-side"];
  let selected = rows.length - 1;
  let visible = [];

  function text(id, value) { $(id).textContent = String(value ?? "—"); }
  function node(tag, className, value) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) el.textContent = String(value);
    return el;
  }
  function appendLine(parent, label, value) {
    const line = node("div", "detail-line");
    line.append(node("span", "detail-label", label), node("span", "detail-value", value));
    parent.append(line);
  }
  function fmt(value, digits = 2) {
    if (value === null || value === undefined || value === "") return "未知";
    const num = Number(value);
    return Number.isFinite(num) ? num.toLocaleString("zh-CN", {maximumFractionDigits: digits, minimumFractionDigits: digits}) : String(value);
  }
  function condition(value, known = true) { return known && value !== null && value !== undefined ? (value ? "满足" : "未满足") : "未知"; }
  function reason(row, variant = $("variant").value) {
    const names = {M: "M · 慢线阈值", F: "F · 非正", D: "D · 快速回落"};
    return (row.sell_reasons || []).filter(code => variant === "fast" || code === "M").map(code => names[code] || code).join(" / ") || "—";
  }
  function known(row) { return row.warmup_complete && row.segment_status === "ACTIVE"; }
  function mark(row, side) {
    const variant = $("variant").value;
    const first = $("signal-mode").value === "first";
    if (side === "buy") return row.slow_buy === true && (!first || row.buy_start === true);
    return row[variant + "_sell"] === true && (!first || row[variant + "_sell_start"] === true);
  }
  function cutoff() {
    const range = $("range").value;
    if (range === "all") return "";
    const end = new Date(report.as_of + "T00:00:00Z");
    const day = end.getUTCDate();
    end.setUTCDate(1);
    if (range === "3m") end.setUTCMonth(end.getUTCMonth() - 3);
    else end.setUTCFullYear(end.getUTCFullYear() - (range === "2y" ? 2 : 1));
    const lastDay = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth() + 1, 0)).getUTCDate();
    end.setUTCDate(Math.min(day, lastDay));
    return end.toISOString().slice(0, 10);
  }
  function sideEnabled(side) { return $("signal-side").value === "all" || $("signal-side").value === side; }
  function svg(tag, attributes = {}) {
    const el = document.createElementNS(svgNS, tag);
    for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, String(value));
    return el;
  }
  function line(parent, x1, y1, x2, y2, className) {
    parent.append(svg("line", {x1, y1, x2, y2, class: className}));
  }
  function chart() {
    const chart = $("chart"), pane = $("chart-scroll");
    const oldScroll = pane.scrollLeft;
    chart.replaceChildren();
    if (!visible.length) { chart.setAttribute("viewBox", "0 0 600 460"); return; }
    const width = Math.max(880, visible.length * 10 + 100);
    const xAt = i => 54 + i * (width - 105) / Math.max(visible.length - 1, 1);
    const lo = Math.min(...visible.map(i => Number(rows[i].low)));
    const hi = Math.max(...visible.map(i => Number(rows[i].high)));
    const spread = Math.max(hi - lo, 1);
    const priceY = v => 301 - (Number(v) - lo) / spread * 245;
    const indicators = visible.flatMap(i => [rows[i].M, rows[i].F]).filter(v => v !== null && Number.isFinite(Number(v))).map(Number);
    const entryThreshold = report.strategy.entry_threshold, exitThreshold = report.strategy.exit_threshold;
    const indLo = Math.min(0, exitThreshold, ...indicators), indHi = Math.max(entryThreshold, ...indicators);
    const indY = v => 427 - (Number(v) - indLo) / Math.max(indHi - indLo, 0.01) * 91;
    chart.setAttribute("viewBox", `0 0 ${width} 470`);
    chart.setAttribute("width", width);
    chart.setAttribute("height", 470);
    chart.setAttribute("aria-label", `${$("variant").value === "slow" ? "慢线" : "快线"}，${visible.length} 个日线；方向键选取交易日`);
    for (let j = 0; j <= 4; j++) {
      const y = 56 + j * 245 / 4;
      line(chart, 42, y, width - 21, y, "chart-grid");
      const tick = svg("text", {x: 39, y: y - 5, class: "chart-tick", "text-anchor": "end"});
      tick.textContent = fmt(hi - spread * j / 4, 0);
      chart.append(tick);
    }
    line(chart, 42, 319, width - 21, 319, "chart-separator");
    for (const [value, name] of [[entryThreshold, `M ${entryThreshold}`], [exitThreshold, `M ${exitThreshold}`], [0, "0"]]) {
      if (value < indLo || value > indHi) continue;
      const y = indY(value);
      line(chart, 42, y, width - 21, y, "chart-guide");
      const tag = svg("text", {x: 46, y: y - 4, class: "chart-tick"}); tag.textContent = name; chart.append(tag);
    }
    for (const [field, klass] of [["M", "indicator-m"], ["F", "indicator-f"]]) {
      let points = [];
      const flush = () => { if (points.length > 1) chart.append(svg("polyline", {points: points.join(" "), class: klass})); points = []; };
      visible.forEach((i, pos) => {
        const value = rows[i][field];
        if (value === null || !Number.isFinite(Number(value))) flush();
        else points.push(`${xAt(pos)},${indY(value)}`);
      });
      flush();
    }
    visible.forEach((i, pos) => {
      const row = rows[i], x = xAt(pos);
      const up = Number(row.close) >= Number(row.open);
      line(chart, x, priceY(row.high), x, priceY(row.low), up ? "wick up" : "wick down");
      const top = priceY(Math.max(Number(row.open), Number(row.close)));
      const bodyHeight = Math.max(1.8, Math.abs(priceY(row.open) - priceY(row.close)));
      chart.append(svg("rect", {x: x - 2.8, y: top, width: 5.6, height: bodyHeight, class: up ? "candle up" : "candle down"}));
      if (mark(row, "buy") && sideEnabled("buy")) {
        chart.append(svg("path", {d: `M ${x - 4} ${priceY(row.low) + 17} L ${x + 4} ${priceY(row.low) + 17} L ${x} ${priceY(row.low) + 9} Z`, class: "marker-buy"}));
      }
      if (mark(row, "sell") && sideEnabled("sell")) {
        chart.append(svg("path", {d: `M ${x - 4} ${priceY(row.high) - 17} L ${x + 4} ${priceY(row.high) - 17} L ${x} ${priceY(row.high) - 9} Z`, class: "marker-sell"}));
      }
      if (i === selected) line(chart, x, 48, x, 437, "selected-guide");
      if (pos === 0 || pos === visible.length - 1 || pos % 25 === 0) {
        const label = svg("text", {x, y: 459, class: "chart-date", "text-anchor": "middle"});
        label.textContent = row.date.slice(2, 7); chart.append(label);
      }
      const hit = svg("rect", {x: x - Math.max(4, (width - 105) / Math.max(visible.length - 1, 1) / 2), y: 48, width: Math.max(8, (width - 105) / Math.max(visible.length - 1, 1)), height: 391, class: "chart-hit"});
      hit.addEventListener("click", () => select(i));
      const tip = svg("title"); tip.textContent = `${row.date} 收盘 ${row.close} · 点击查看`; hit.append(tip);
      chart.append(hit);
    });
    pane.scrollLeft = oldScroll;
  }
  function selectedDetail() {
    const target = $("selected-bar"); target.replaceChildren();
    if (selected < 0) return;
    const row = rows[selected];
    const heading = node("div", "detail-heading");
    heading.append(node("strong", "selected-date", row.date), node("span", "detail-session-note", row.date === report.latest_session ? "也是最新收录日" : `最新收录：${report.latest_session}`));
    target.append(heading);
    const prices = node("div", "price-grid");
    for (const [label, field] of [["开盘 O", "open"], ["最高 H", "high"], ["最低 L", "low"], ["收盘 C", "close"]]) {
      const card = node("div", "price-item"); card.append(node("span", "detail-label", label), node("strong", "price-value", row[field])); prices.append(card);
    }
    target.append(prices);
    const indicators = node("div", "indicator-grid");
    appendLine(indicators, "慢速动量 M", fmt(row.M, 3)); appendLine(indicators, "快速动量 F", fmt(row.F, 3));
    appendLine(indicators, "活跃窗口", row.active_window === null ? "未知" : `${row.active_window} 日`);
    appendLine(indicators, "拟合 R²", fmt(row.active_r2, 3));
    target.append(indicators);
    const state = node("div", "state-note", row.segment_status === "WARMUP" ? "预热期：条件尚不可判定" : row.segment_status === "NO_ACTIVE_SEGMENT" ? "无有效活动区间：卖出条件未知" : "有效活动区间：显示独立的慢线 / 快线卖出条件");
    target.append(state);
    if (row.resumed_after_unknown) target.append(node("div", "state-note", "本日从未知区间恢复；首次标记以全历史状态为准。"));
    const badges = node("div", "condition-grid");
    for (const [label, value, isKnown] of [["慢线 · 买入", row.slow_buy, known(row)], ["慢线 · 卖出", row.slow_sell, known(row)], ["快线 · 买入", row.fast_buy, known(row)], ["快线 · 卖出", row.fast_sell, known(row)]]) {
      const item = node("div", "condition-card");
      item.append(node("span", "detail-label", label), node("strong", "", (value === true && isKnown ? (label.includes("买入") ? "▲ " : "▼ ") : "") + condition(value, isKnown)));
      badges.append(item);
    }
    target.append(badges);
    appendLine(target, "慢 / 快买入连续日", `${row.positive_persistence} 日`);
    appendLine(target, "负向连续日", `${row.negative_persistence} 日`);
    appendLine(target, "卖出条件原因", known(row) ? reason(row) : "未知");
    appendLine(target, "成交量 / 成交额", `${fmt(row.volume, 0)} / ${fmt(row.turnover, 0)}`);
    appendLine(target, "ATR14 / 年化波动率", `${row.atr14 === null ? "未知" : fmt(row.atr14)} / ${row.annualized_volatility === null ? "未知" : fmt(row.annualized_volatility * 100) + "%"}`);
    target.append(node("div", "execution-note", "仅供描述性观察 · 不构成交易或执行信号"));
  }
  function events() {
    const tbody = $("signal-table").querySelector("tbody"); tbody.replaceChildren();
    let buyCount = 0, sellCount = 0;
    for (const i of visible) {
      const row = rows[i];
      for (const side of ["buy", "sell"]) {
        if (!sideEnabled(side) || !mark(row, side)) continue;
        if (side === "buy") buyCount++; else sellCount++;
        const tr = node("tr", side === "buy" ? "event-buy" : "event-sell");
        if (i === selected) tr.classList.add("selected-row");
        tr.tabIndex = 0;
        tr.setAttribute("aria-label", `${row.date} ${side === "buy" ? "买入" : "卖出"}条件，选择查看交易日`);
        const first = side === "buy" ? row.buy_start : row[$("variant").value + "_sell_start"];
        const label = first ? (row.resumed_after_unknown ? "未知后恢复" : "首次触发") : "持续满足";
        const cells = [row.date, side === "buy" ? "▲ 买入" : "▼ 卖出", label, fmt(row.close), `${fmt(row.M, 3)} / ${fmt(row.F, 3)}`, side === "sell" ? reason(row) : "M · 连续阈值"];
        for (const cell of cells) tr.append(node("td", "", cell));
        tr.addEventListener("click", () => select(i));
        tr.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(i); } });
        tbody.append(tr);
      }
    }
    text("buy-count", buyCount); text("sell-count", sellCount);
    text("events-summary", `${buyCount + sellCount} 条条件记录 · 买入 ${buyCount} / 卖出 ${sellCount}`);
    if (!buyCount && !sellCount) {
      const tr = node("tr"); const td = node("td", "empty-state", "当前筛选范围内无符合条件的日期；未知区间不会计作持有或卖出未满足。");
      td.colSpan = 6; tr.append(td); tbody.append(tr);
    }
  }
  function select(index) {
    if (index < 0 || index >= rows.length) return;
    selected = index;
    selectedDetail(); events(); chart();
    const pane = $("chart-scroll"), guide = $("chart").querySelector(".selected-guide");
    if (guide) {
      const x = Number(guide.getAttribute("x1"));
      if (x < pane.scrollLeft + 20 || x > pane.scrollLeft + pane.clientWidth - 20) {
        pane.scrollLeft = Math.max(0, x - pane.clientWidth / 2);
      }
    }
  }
  function refresh() {
    const minDate = cutoff();
    visible = rows.map((row, i) => row.date >= minDate ? i : -1).filter(i => i >= 0);
    if (visible.length && !visible.includes(selected)) selected = visible[visible.length - 1];
    text("view-count", `${visible.length} 个交易日 · ${$("variant").value === "slow" ? "慢线" : "快线"}`);
    text("chart-dates", visible.length ? `${rows[visible[0]].date} — ${rows[visible[visible.length - 1]].date}` : "无交易日");
    selectedDetail(); events(); chart();
    if (selected === visible[visible.length - 1]) $("chart-scroll").scrollLeft = $("chart-scroll").scrollWidth;
  }
  $("chart").addEventListener("keydown", event => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key) || !visible.length) return;
    event.preventDefault();
    const pos = visible.indexOf(selected);
    const next = event.key === "Home" ? 0 : event.key === "End" ? visible.length - 1 : Math.max(0, Math.min(visible.length - 1, pos + (event.key === "ArrowRight" ? 1 : -1)));
    select(visible[next]);
  });
  controls.forEach(id => $(id).addEventListener("change", refresh));
  text("report-title", report.name || "931743 指数信号观察");
  text("latest-date", report.latest_session);
  text("latest-status", report.data_status_label || report.data_status);
  text("latest-foot", `截至 ${report.as_of} · 预期交易日 ${report.expected_session}`);
  text("coverage-bars", `${report.coverage.bars} 个交易日`);
  text("coverage-dates", `${report.coverage.first_session} — ${report.coverage.last_session}`);
  function provenance(id, entries) {
    const el = $(id);
    for (const [label, value] of entries) appendLine(el, label, value);
  }
  provenance("source-info", [["数据提供方", report.source.provider], ["来源地址", report.source.url], ["抓取时间 (UTC)", report.source.fetched_at_utc], ["生成时间 (UTC)", report.generated_at_utc], ["原始数据 SHA-256", report.source.raw_sha256]]);
  provenance("method-info", [["日线覆盖", `${report.coverage.first_session} — ${report.coverage.last_session}`], ["预热长度", `${report.coverage.minimum_warmup_bars} 根日线`], ["预热完成起点", report.coverage.first_signal_session || "暂无"], ["策略版本", report.strategy.version], ["配置 SHA-256", report.strategy.config_sha256], ["日历版本", report.source.calendar_version]]);
  if (report.warnings && report.warnings.length) {
    $("warnings").hidden = false;
    $("warnings").append(node("strong", "", "数据提示"));
    for (const warning of report.warnings) $("warnings").append(node("p", "", warning));
  }
  refresh();
})();
