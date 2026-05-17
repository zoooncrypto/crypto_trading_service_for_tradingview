"""Flask dashboard: stat cards + signal list (mirrors the product UI)."""
from __future__ import annotations

import time

from flask import Flask, jsonify, render_template_string, request

from .config import Config
from .stats import summarize, summarize_by_strategy
from .storage import Storage
from .strategies import available, label_of

_PAGE = """<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>諧波交易訊號專區</title>
<style>
body{background:#0c0c14;color:#e6e6f0;font-family:-apple-system,system-ui,sans-serif;margin:0;padding:16px}
h2{font-size:18px;margin:8px 0 4px}
.note{background:#1a1530;border-radius:14px;padding:14px;font-size:13px;color:#b9b4d0;line-height:1.6}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:14px 0}
.card{background:#15151f;border-radius:14px;padding:16px;text-align:center}
.card .v{font-size:26px;font-weight:700}
.card .l{font-size:12px;color:#8a8aa0;margin-top:4px}
.g{color:#37e0a6}.r{color:#9aa}.p{color:#a98bff}.red{color:#ff5d73}
.big .v{font-size:22px}
table{width:100%;border-collapse:collapse;margin-top:12px;font-size:13px}
th,td{padding:8px;border-bottom:1px solid #20202c;text-align:left}
th{color:#8a8aa0;font-weight:600}
.tag{padding:2px 8px;border-radius:8px;font-size:11px}
select{background:#15151f;color:#e6e6f0;border:1px solid #2a2a38;border-radius:10px;padding:8px;margin:4px 4px 4px 0}
</style></head><body>
<h2>🦇 🦋 🦀 🐬 諧波交易訊號專區</h2>
<div class="note">本頁訊號來自 Bybit 諧波型態（Bat / Butterfly / Crab / Shark / Gartley / Cypher）的 PRZ 反應。
⚠️ PRZ 訊號是觀察點，並非進場訊號，不構成投資建議。</div>
<div class="grid">
 <div class="card"><div class="v">{{s.total}}</div><div class="l">總計</div></div>
 <div class="card"><div class="v p">{{s.running}}</div><div class="l">進行中</div></div>
 <div class="card"><div class="v g">{{s.tp1}}</div><div class="l">止盈1</div></div>
 <div class="card"><div class="v g">{{s.tp2}}</div><div class="l">止盈2</div></div>
 <div class="card"><div class="v r">{{s.no_entry}}</div><div class="l">無 T-Bar</div></div>
 <div class="card"><div class="v red">{{s.stopped}}</div><div class="l">止損</div></div>
</div>
<div class="grid big">
 <div class="card"><div class="v g">{{'+' if s.cum_r>=0 else ''}}{{s.cum_r}}R</div><div class="l">累計盈虧</div></div>
 <div class="card"><div class="v g">{{s.win_rate}}%</div><div class="l">勝率</div></div>
 <div class="card"><div class="v r">{{s.loss_rate}}%</div><div class="l">敗率</div></div>
</div>
<form method="get">
<select name="strategy" onchange="this.form.submit()">
 <option value="">全部策略</option>
 {% for n,lbl in strategies %}
 <option value="{{n}}" {{'selected' if n==fstrategy}}>{{lbl}}</option>{% endfor %}
</select>
<select name="days" onchange="this.form.submit()">
 {% for d in [1,3,7,30,0] %}<option value="{{d}}" {{'selected' if d==days}}>{{'全部' if d==0 else d ~ ' 日'}}</option>{% endfor %}
</select>
<select name="status" onchange="this.form.submit()">
 <option value="">全部訊號</option>
 {% for v in ['pending','running','tp1','tp2','tp3','stopped','expired'] %}
 <option value="{{v}}" {{'selected' if v==fstatus}}>{{v}}</option>{% endfor %}
</select>
</form>
<h2>各策略統計</h2>
<table><tr><th>策略</th><th>總計</th><th>進行中</th><th>止盈1</th><th>止盈2</th>
<th>止盈3</th><th>止損</th><th>勝率</th><th>累計R</th></tr>
{% for name, bs in by_strategy.items() %}
<tr><td>{{ labels.get(name, name) }}</td><td>{{bs.total}}</td>
<td class="p">{{bs.running}}</td><td class="g">{{bs.tp1}}</td>
<td class="g">{{bs.tp2}}</td><td class="g">{{bs.tp3}}</td>
<td class="red">{{bs.stopped}}</td><td class="g">{{bs.win_rate}}%</td>
<td class="{{'g' if bs.cum_r>=0 else 'red'}}">{{'+' if bs.cum_r>=0 else ''}}{{bs.cum_r}}R</td></tr>
{% endfor %}
</table>
<h2>訊號清單 ({{rows|length}})</h2>
<table><tr><th>策略</th><th>標的</th><th>週期</th><th>型態</th><th>方向</th><th>狀態</th>
<th>進場</th><th>止損</th><th>TP1/2/3</th><th>品質</th><th>R</th></tr>
{% for r in rows %}
<tr><td>{{ labels.get(r.strategy, r.strategy) }}</td>
<td>{{r.symbol}}</td><td>{{r.timeframe}}</td><td>{{r.pattern}}</td>
<td>{{r.direction}}</td><td><span class="tag">{{r.status}}</span></td>
<td>{{'%.4f'|format(r.entry)}}</td><td>{{'%.4f'|format(r.stop)}}</td>
<td>{{'%.4f'|format(r.tp1)}} / {{'%.4f'|format(r.tp2)}} / {{'%.4f'|format(r.tp3)}}</td>
<td>{{'%.2f'|format(r.quality)}}</td>
<td class="{{'g' if r.realized_r>=0 else 'red'}}">{{'%.2f'|format(r.realized_r)}}</td></tr>
{% endfor %}
</table></body></html>"""


def create_app(cfg: Config) -> Flask:
    app = Flask(__name__)
    store = Storage(cfg.db_path)

    def _filtered():
        days = int(request.args.get("days", 7))
        fstatus = request.args.get("status", "")
        fstrategy = request.args.get("strategy", "")
        since = None
        if days:
            since = int((time.time() - days * 86400) * 1000)
        sigs = store.all_signals(since)
        # by_strategy is computed before the strategy filter so the
        # per-strategy table always shows every strategy.
        by_strategy = summarize_by_strategy(sigs)
        if fstrategy:
            sigs = [s for s in sigs if s.strategy == fstrategy]
        if fstatus:
            sigs = [s for s in sigs if s.status.value == fstatus]
        return sigs, days, fstatus, fstrategy, by_strategy

    @app.route("/")
    def index():
        sigs, days, fstatus, fstrategy, by_strategy = _filtered()
        labels = {n: label_of(n) for n in available()}
        return render_template_string(
            _PAGE, s=summarize(sigs),
            rows=[s.to_row() for s in sigs[:300]],
            days=days, fstatus=fstatus, fstrategy=fstrategy,
            by_strategy=by_strategy, labels=labels,
            strategies=[(n, label_of(n)) for n in available()],
        )

    @app.route("/api/stats")
    def api_stats():
        sigs, _, _, _, by_strategy = _filtered()
        return jsonify({"overall": summarize(sigs),
                        "by_strategy": by_strategy})

    @app.route("/api/signals")
    def api_signals():
        sigs, _, _, _, _ = _filtered()
        return jsonify([s.to_row() for s in sigs])

    return app
