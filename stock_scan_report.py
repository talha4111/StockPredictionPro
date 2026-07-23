"""Generate a compact, self-contained stock scan report."""

from __future__ import annotations

import html
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence


DECISION_LABELS = {
    "AL_ADAYI": "AL ADAYI",
    "BEKLE_GERI_CEKILME": "GERI CEKILME BEKLE",
    "IZLE": "IZLE",
    "OLAY_RISKI": "OLAY RISKI",
    "REDDET_TREND": "TREND UYGUN DEGIL",
    "VERI_YETERSIZ": "VERI YETERSIZ",
}


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _rounded(value, digits=1):
    number = _finite(value)
    return round(number, digits) if number is not None else None


def _trend_status(row):
    price = _finite(row.get("fiyat"))
    sma50 = _finite(row.get("sma_50"))
    sma200 = _finite(row.get("sma_200"))
    if None in (price, sma50, sma200):
        return "VERI YOK"
    if price > sma200 and sma50 > sma200:
        return "UYGUN"
    if price >= sma200 * 0.97 or sma50 >= sma200:
        return "SINIRDA"
    return "UYGUN DEGIL"


def _rsi_status(value):
    rsi = _finite(value)
    if rsi is None:
        return "VERI YOK"
    if 35 <= rsi <= 65:
        return "UYGUN"
    if 30 <= rsi <= 72:
        return "SINIRDA"
    return "UYGUN DEGIL"


def build_report_rows(
    baseline_ranked: Sequence[Mapping[str, object]],
    challenger_ranked: Sequence[Mapping[str, object]],
) -> list[dict]:
    """Return one concise row per stock with pure factor ranks."""
    baseline = sorted(
        (dict(row) for row in baseline_ranked),
        key=lambda row: (
            -(_finite(row.get("faktor_skor")) if _finite(row.get("faktor_skor")) is not None else -1.0),
            str(row.get("sembol", "")),
        ),
    )
    challenger = sorted(
        (dict(row) for row in challenger_ranked),
        key=lambda row: (
            -(_finite(row.get("faktor_skor")) if _finite(row.get("faktor_skor")) is not None else -1.0),
            str(row.get("sembol", "")),
        ),
    )
    challenger_map = {
        str(row.get("sembol")): {
            "rank": rank,
            "score": _rounded(row.get("faktor_skor")),
        }
        for rank, row in enumerate(challenger, start=1)
    }

    result = []
    for rank, row in enumerate(baseline, start=1):
        symbol = str(row.get("sembol", ""))
        comparison = challenger_map.get(symbol, {})
        m00_rank = comparison.get("rank")
        decision = str(row.get("karar") or "IZLE")
        result.append({
            "rank": rank,
            "symbol": symbol,
            "sector": str(row.get("sektor") or "Bilinmiyor"),
            "decision": decision,
            "decision_label": DECISION_LABELS.get(decision, decision),
            "setup": str(row.get("kurulum") or "IZLE"),
            "factor_score": _rounded(row.get("faktor_skor")),
            "quality_score": _rounded(row.get("kalite_skor")),
            "value_score": _rounded(row.get("deger_skor")),
            "momentum_score": _rounded(row.get("momentum_skor")),
            "risk_score": _rounded(row.get("risk_skor")),
            "m00_rank": m00_rank,
            "m00_score": comparison.get("score"),
            "rank_delta": rank - m00_rank if m00_rank is not None else None,
            "price": _rounded(row.get("fiyat"), 2),
            "rsi": _rounded(row.get("rsi")),
            "trend_status": _trend_status(row),
            "rsi_status": _rsi_status(row.get("rsi")),
            "volume_status": "UYGUN" if row.get("hacim_teyit") else "SINIRDA",
            "data_status": str(row.get("veri_durumu") or "UNKNOWN"),
            "positive": ", ".join(
                str(item) for item in (row.get("olumlu_nedenler") or [])
            ) or "-",
            "negative": ", ".join(
                str(item) for item in (row.get("olumsuz_nedenler") or [])
            ) or "-",
        })
    return result


def generate_stock_scan_report(
    baseline_ranked: Sequence[Mapping[str, object]],
    challenger_ranked: Sequence[Mapping[str, object]],
    vix_value,
    output_dir: str | Path | None = None,
    generated_at: datetime | None = None,
) -> Path:
    rows = build_report_rows(baseline_ranked, challenger_ranked)
    now = generated_at or datetime.now()
    report_dir = (
        Path(output_dir)
        if output_dir
        else Path(__file__).resolve().parent / "reports"
    )
    report_dir.mkdir(parents=True, exist_ok=True)
    output_path = report_dir / "stock_scan_latest.html"

    counts = Counter(row["decision"] for row in rows)
    market_dates = sorted({
        str(row.get("veri_tarihi"))[:10]
        for row in baseline_ranked
        if row.get("veri_tarihi")
    })
    market_date = market_dates[-1] if market_dates else "Bilinmiyor"
    payload = json.dumps(rows, ensure_ascii=True, allow_nan=False)
    payload = (
        payload.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    decision_options = "".join(
        '<option value="' + html.escape(key) + '">' + html.escape(label) + "</option>"
        for key, label in DECISION_LABELS.items()
        if counts.get(key)
    )

    template = """<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hisse Tarama Raporu</title>
<style>
:root{--ink:#17212b;--muted:#66727e;--line:#dce2e7;--bg:#f4f6f8;--surface:#fff;--blue:#1769aa;--green:#207a4b;--amber:#9a6512;--red:#a63b32}
*{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);font-family:Segoe UI,Arial,sans-serif;font-size:14px;letter-spacing:0}
header{background:#fff;border-bottom:1px solid var(--line);padding:18px 24px 16px} h1{margin:0 0 5px;font-size:22px;font-weight:650}.meta{color:var(--muted);font-size:13px}
main{padding:16px 24px 28px}.summary{display:grid;grid-template-columns:repeat(6,minmax(110px,1fr));gap:8px;margin-bottom:14px}
.metric{background:var(--surface);border:1px solid var(--line);border-radius:4px;padding:10px 12px}.metric b{display:block;font-size:19px;margin-top:3px}.metric span{color:var(--muted);font-size:12px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 10px}input,select,button{height:34px;border:1px solid #bcc6ce;border-radius:4px;background:#fff;color:var(--ink);padding:0 10px;font:inherit}
input{min-width:230px}button{cursor:pointer}button:hover{border-color:var(--blue)}.count{margin-left:auto;color:var(--muted)}
.table-wrap{overflow:auto;border:1px solid var(--line);background:#fff}table{width:100%;border-collapse:collapse;min-width:1240px}
th{position:sticky;top:0;z-index:1;background:#eef2f5;color:#42515e;font-size:12px;text-align:left;padding:9px 8px;border-bottom:1px solid #cfd7de;white-space:nowrap}
td{padding:8px;border-bottom:1px solid #e8ecef;vertical-align:top;white-space:nowrap}tbody tr:hover{background:#f7fafc}.symbol{font-weight:700}.sub{display:block;color:var(--muted);font-size:11px;margin-top:2px}
.score{font-variant-numeric:tabular-nums;text-align:right}.badge{display:inline-block;border-radius:3px;padding:3px 6px;font-size:11px;font-weight:650}
.good{color:var(--green);background:#e8f4ed}.warn{color:var(--amber);background:#fff3d9}.bad{color:var(--red);background:#fbe9e7}.neutral{color:#50606d;background:#edf1f4}
.reason{white-space:normal;min-width:220px;max-width:300px;line-height:1.35}.up{color:var(--green)}.down{color:var(--red)}footer{color:var(--muted);font-size:12px;margin-top:10px}
@media(max-width:900px){main,header{padding-left:12px;padding-right:12px}.summary{grid-template-columns:repeat(2,minmax(120px,1fr))}.count{width:100%;margin-left:0}}
@media print{.toolbar{display:none}main{padding:8px}.table-wrap{overflow:visible}}
</style>
</head>
<body>
<header><h1>Hisse Tarama Raporu</h1><div class="meta">Piyasa verisi: __MARKET_DATE__ &nbsp;|&nbsp; Uretim: __GENERATED_AT__ &nbsp;|&nbsp; Danisman modu, emir acmaz</div></header>
<main>
<section class="summary" aria-label="Tarama ozeti">
<div class="metric"><span>Taranan</span><b>__TOTAL__</b></div><div class="metric"><span>AL adayi</span><b>__BUY__</b></div>
<div class="metric"><span>Geri cekilme</span><b>__PULLBACK__</b></div><div class="metric"><span>Izle</span><b>__WATCH__</b></div>
<div class="metric"><span>Olay riski</span><b>__EVENT__</b></div><div class="metric"><span>VIX</span><b>__VIX__</b></div>
</section>
<div class="toolbar"><input id="search" type="search" placeholder="Hisse veya sektor ara" aria-label="Hisse veya sektor ara">
<select id="decision" aria-label="Karara gore filtrele"><option value="">Tum kararlar</option>__OPTIONS__</select>
<button id="csv" type="button">CSV indir</button><button type="button" onclick="window.print()">Yazdir</button><span class="count" id="visibleCount"></span></div>
<div class="table-wrap"><table><thead><tr><th>Sira</th><th>Hisse</th><th>Karar</th><th>Faktor</th><th>Kalite</th><th>Deger</th><th>Momentum</th><th>Risk</th><th>m00</th><th>Trend</th><th>RSI</th><th>Hacim</th><th>Guclu</th><th>Zayif</th></tr></thead><tbody id="rows"></tbody></table></div>
<footer>m00 sutunu, momentum agirligi sifir olan arastirma modelindeki sirayi gosterir. Bu rapor yatirim tavsiyesi degildir.</footer>
</main>
<script>
const allRows=__ROWS__;
const tbody=document.getElementById('rows'),search=document.getElementById('search'),decision=document.getElementById('decision'),visibleCount=document.getElementById('visibleCount');
const esc=value=>String(value??'-').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const badge=value=>{const cls=value==='UYGUN'?'good':value==='SINIRDA'?'warn':value==='UYGUN DEGIL'?'bad':'neutral';return '<span class="badge '+cls+'">'+esc(value)+'</span>'};
const decisionBadge=row=>{const cls=row.decision==='AL_ADAYI'?'good':(row.decision==='BEKLE_GERI_CEKILME'||row.decision==='OLAY_RISKI')?'warn':row.decision==='REDDET_TREND'?'bad':'neutral';return '<span class="badge '+cls+'">'+esc(row.decision_label)+'</span><span class="sub">'+esc(row.setup)+'</span>'};
function render(){const q=search.value.trim().toLocaleLowerCase('tr'),selected=decision.value;const rows=allRows.filter(r=>(!selected||r.decision===selected)&&(!q||(r.symbol+' '+r.sector).toLocaleLowerCase('tr').includes(q)));
tbody.innerHTML=rows.map(r=>{const delta=r.rank_delta==null||r.rank_delta===0?'':'<span class="'+(r.rank_delta>0?'up':'down')+'"> ('+(r.rank_delta>0?'+':'')+r.rank_delta+')</span>';
return '<tr><td class="score">'+r.rank+'</td><td><span class="symbol">'+esc(r.symbol)+'</span><span class="sub">'+esc(r.sector)+' | $'+esc(r.price)+'</span></td><td>'+decisionBadge(r)+'</td><td class="score"><b>'+esc(r.factor_score)+'</b></td><td class="score">'+esc(r.quality_score)+'</td><td class="score">'+esc(r.value_score)+'</td><td class="score">'+esc(r.momentum_score)+'</td><td class="score">'+esc(r.risk_score)+'</td><td class="score">#'+esc(r.m00_rank)+delta+'<span class="sub">'+esc(r.m00_score)+'</span></td><td>'+badge(r.trend_status)+'</td><td>'+badge(r.rsi_status)+'<span class="sub">'+esc(r.rsi)+'</span></td><td>'+badge(r.volume_status)+'</td><td class="reason">'+esc(r.positive)+'</td><td class="reason">'+esc(r.negative)+'</td></tr>'}).join('');visibleCount.textContent=rows.length+' / '+allRows.length+' hisse'}
search.addEventListener('input',render);decision.addEventListener('change',render);
document.getElementById('csv').addEventListener('click',()=>{const headers=['Sira','Hisse','Sektor','Karar','Faktor','Kalite','Deger','Momentum','Risk','m00 Sira','m00 Faktor','Trend','RSI','RSI Durum','Hacim','Guclu','Zayif'];
const values=allRows.map(r=>[r.rank,r.symbol,r.sector,r.decision_label,r.factor_score,r.quality_score,r.value_score,r.momentum_score,r.risk_score,r.m00_rank,r.m00_score,r.trend_status,r.rsi,r.rsi_status,r.volume_status,r.positive,r.negative]);
const csv=[headers].concat(values).map(row=>row.map(value=>'"'+String(value??'').replace(/"/g,'""')+'"').join(',')).join('\\r\\n');const link=document.createElement('a');link.href=URL.createObjectURL(new Blob(['\\ufeff'+csv],{type:'text/csv;charset=utf-8'}));link.download='hisse_tarama_raporu.csv';link.click();URL.revokeObjectURL(link.href)});
render();
</script>
</body></html>"""
    replacements = {
        "__MARKET_DATE__": html.escape(market_date),
        "__GENERATED_AT__": now.strftime("%Y-%m-%d %H:%M"),
        "__TOTAL__": str(len(rows)),
        "__BUY__": str(counts.get("AL_ADAYI", 0)),
        "__PULLBACK__": str(counts.get("BEKLE_GERI_CEKILME", 0)),
        "__WATCH__": str(counts.get("IZLE", 0)),
        "__EVENT__": str(counts.get("OLAY_RISKI", 0)),
        "__VIX__": str(_rounded(vix_value) if _rounded(vix_value) is not None else "-"),
        "__OPTIONS__": decision_options,
        "__ROWS__": payload,
    }
    document = template
    for placeholder, value in replacements.items():
        document = document.replace(placeholder, value)
    output_path.write_text(document, encoding="utf-8")
    return output_path.resolve()