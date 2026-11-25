"""
StockPredictionPro Local Stdio MCP Server
Exposes live quantitative telemetry, Dip Hunter staged zones, Triple-Barrier AI
probabilities, Earnings Catalyst sell-the-news checks, and Midas FIFO lot tracking
to MCP-compatible AI workspaces (e.g., Tencent WorkBuddy via ~/.workbuddy-ai/mcp.json).
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from typing import Any

# Ensure UTF-8 streams on Windows and keep stdout strictly reserved for JSON-RPC lines.
if hasattr(sys.stdin, "reconfigure"):
    sys.stdin.reconfigure(encoding="utf-8")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_REAL_STDOUT = sys.stdout
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

SERVER_INFO = {
    "name": "stockpredictionpro-quant",
    "version": "1.0.0",
}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "get_stock_quant_snapshot",
        "description": (
            "Fetch live stock quote, moving averages (SMA20/50/200), Dip Hunter staged "
            "entry zones (zone1/zone2/stop/targets), 15-day Triple-Barrier AI win vs. "
            "stop-loss probability, and factor conflict checks for US or BIST (.IS) stocks."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol, e.g. AAPL, MU, COHR, MRVL, BE, NVDA, or THYAO.IS",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "check_earnings_catalyst",
        "description": (
            "Pre-trade earnings guardrail: returns days until next earnings report, "
            "pre-earnings 15-day runup, historical average post-earnings 1-day move, and "
            "sell-the-news beat-and-drop rate so position sizing avoids earnings traps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "US stock ticker symbol, e.g. AAPL, MU, COHR, MRVL",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "inspect_fifo_lots",
        "description": (
            "Inspect per-lot FIFO cost basis, unrealized PnL, and tax/trimming awareness "
            "for held positions in the portfolio (instead of aggregate average cost only)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Optional symbol filter, e.g. MU (leave empty for all holdings)",
                }
            },
        },
    },
    {
        "name": "get_market_regime",
        "description": (
            "Return current macro market regime, VIX fear gauge, and risk posture "
            "for sizing decisions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def _normalize_symbol(raw_symbol: str) -> str:
    sym = (raw_symbol or "").strip().upper()
    if sym.startswith("US."):
        sym = sym[3:]
    elif sym.startswith("HK."):
        sym = f"{sym[3:]}.HK"
    return sym


def _handle_stock_quant_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    from web.components.ai_analyst import collect_symbol_intelligence

    sym = _normalize_symbol(str(args.get("symbol", "")))
    if not sym:
        return {"error": "Missing required parameter: symbol"}

    intel = collect_symbol_intelligence(sym)
    if not intel.get("valid"):
        return {"symbol": sym, "valid": False, "error": f"No live market data found for {sym}"}

    dip = intel.get("dip") or {}
    ai_pred = intel.get("ai_pred") or {}
    fnd = intel.get("fundamentals") or {}
    conflicts = intel.get("conflicts") or {}
    news = dip.get("news") or intel.get("news") or {}
    diagnosis = dip.get("diagnosis") or intel.get("diagnosis") or {}

    return {
        "symbol": intel.get("symbol"),
        "name": intel.get("name"),
        "currency": intel.get("currency"),
        "price": intel.get("price"),
        "daily_chg_pct": intel.get("daily_chg_pct"),
        "chg_5d_pct": intel.get("chg_5d_pct"),
        "chg_1m_pct": intel.get("chg_1m_pct"),
        "high_52w": intel.get("high_52w"),
        "drop_52w_pct": intel.get("drop_52w_pct"),
        "technicals": {
            "rsi14": intel.get("rsi14"),
            "sma20": intel.get("sma20"),
            "sma50": intel.get("sma50"),
            "sma200": intel.get("sma200"),
            "vol_ratio": intel.get("vol_ratio"),
            "fib_382": intel.get("fib_382"),
            "fib_500": intel.get("fib_500"),
        },
        "dip_hunter": {
            "state_code": dip.get("state_code"),
            "state_badge": dip.get("state_badge"),
            "passed_checks": f"{dip.get('passed_count', 0)}/{dip.get('total_checks', 8)}",
            "zone1_low": dip.get("zone1_low"),
            "zone1_high": dip.get("zone1_high"),
            "zone2_low": dip.get("zone2_low"),
            "zone2_high": dip.get("zone2_high"),
            "stop_level": dip.get("stop_level"),
            "target1": dip.get("target1"),
            "target2": dip.get("target2"),
            "upside_pct": dip.get("upside_pct"),
        },
        "gates": dip.get("gates", []),
        "size_hint": dip.get("size_hint", "YOK"),
        "rr_ratio": dip.get("rr_ratio"),
        "news": {
            "status": news.get("status"),
            "score": news.get("score"),
            "veto_active": news.get("veto_active"),
            "absorbed": news.get("absorbed"),
            "red_events": news.get("red_events", []),
        },
        "diagnosis": {
            "code": diagnosis.get("code"),
            "label": diagnosis.get("label"),
        },
        "triple_barrier_ai": {
            "available": ai_pred.get("available"),
            "horizon_days": ai_pred.get("horizon_days", 15),
            "win_prob_pct": ai_pred.get("win_prob_pct"),
            "stop_prob_pct": ai_pred.get("stop_prob_pct"),
            "analog_count": ai_pred.get("analog_count"),
            "analog_win_rate_pct": ai_pred.get("analog_win_rate_pct"),
            "analog_avg_ret_pct": ai_pred.get("analog_avg_ret_pct"),
            "verdict": ai_pred.get("verdict_short"),
        },
        "fundamentals": {
            "forward_pe": fnd.get("forward_pe"),
            "gross_margin_pct": fnd.get("gross_margin_pct"),
            "rev_growth_yoy_pct": fnd.get("rev_growth_yoy_pct"),
            "analyst_target": fnd.get("analyst_target"),
            "recommendation": fnd.get("recommendation"),
        },
        "factors": intel.get("factors"),
        "factor_conflicts": conflicts.get("conflicts", []),
        "unified_verdict": intel.get("unified_verdict"),
    }


def _handle_earnings_catalyst(args: dict[str, Any]) -> dict[str, Any]:
    from web.components.ai_analyst import collect_symbol_intelligence

    sym = _normalize_symbol(str(args.get("symbol", "")))
    if not sym:
        return {"error": "Missing required parameter: symbol"}

    intel = collect_symbol_intelligence(sym)
    earn = intel.get("earnings") or {}
    days = earn.get("days_to_earnings")

    if days is not None and days <= 7:
        guardrail = "BLOCK_NEW_FULL_SIZE — Earnings within 7 days (binary event risk)"
    elif days is not None and days <= 21:
        guardrail = "CAUTION_HALF_SIZE — Earnings within 21 days (check sell-the-news rate)"
    else:
        guardrail = "SAFE_WINDOW — No immediate earnings event trap"

    return {
        "symbol": sym,
        "guardrail_status": guardrail,
        "next_earnings_date": earn.get("next_earnings_date"),
        "days_to_earnings": days,
        "pre_earnings_runup_15d_pct": earn.get("pre_earnings_runup_15d_pct"),
        "priced_in_warning": earn.get("priced_in_warning"),
        "avg_abs_1d_move_pct": earn.get("avg_abs_1d_move_pct"),
        "drop_count_1d": earn.get("drop_count_1d"),
        "total_quarters_checked": earn.get("total_count"),
        "sell_the_news_count": earn.get("sell_the_news_count"),
        "summary": earn.get("summary_text"),
        "recent_quarters": intel.get("earnings_releases", []),
    }


def _handle_fifo_lots(args: dict[str, Any]) -> dict[str, Any]:
    from web.components.ai_analyst import collect_portfolio_intelligence, load_ai_memory

    sym_filter = _normalize_symbol(str(args.get("symbol", "")))
    port = collect_portfolio_intelligence()
    mem = load_ai_memory()
    profile = mem.get("user_profile", {})
    open_positions = port.get("open_positions", {})
    if sym_filter and sym_filter in open_positions:
        open_positions = {sym_filter: open_positions[sym_filter]}

    fifo_notes = [
        {
            "id": n.get("id"),
            "date": n.get("date"),
            "title": n.get("title"),
            "symbols": n.get("symbols", []),
            "content": n.get("content"),
        }
        for n in mem.get("memory_notes", [])
        if any(
            k in (str(n.get("title", "")) + " " + str(n.get("content", "")) + " " + " ".join(n.get("symbols", []))).lower()
            for k in ["fifo", "midas", "lot", sym_filter.lower() if sym_filter else "mu"]
        )
    ]

    return {
        "usdtry": port.get("usdtry"),
        "broker": profile.get("broker"),
        "lot_rule": profile.get("lot_rule"),
        "open_positions": open_positions,
        "fifo_notes": fifo_notes,
    }


def _handle_market_regime(_args: dict[str, Any]) -> dict[str, Any]:
    from web.components.investment_committee import get_market_regime_summary

    return get_market_regime_summary()


def _dispatch_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    with contextlib.redirect_stdout(sys.stderr):
        if name == "get_stock_quant_snapshot":
            return _handle_stock_quant_snapshot(arguments)
        if name == "check_earnings_catalyst":
            return _handle_earnings_catalyst(arguments)
        if name == "inspect_fifo_lots":
            return _handle_fifo_lots(arguments)
        if name == "get_market_regime":
            return _handle_market_regime(arguments)
    raise ValueError(f"Unknown tool: {name}")


def _send(payload: dict[str, Any]) -> None:
    line = json.dumps(payload, ensure_ascii=False, default=str)
    _REAL_STDOUT.write(line + "\n")
    _REAL_STDOUT.flush()


def _process_request(req: dict[str, Any]) -> None:
    req_id = req.get("id")
    method = req.get("method", "")
    params = req.get("params") or {}

    # Notifications have no id and expect no response.
    if req_id is None:
        return

    if method == "initialize":
        proto = params.get("protocolVersion") or "2024-11-05"
        _send({
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": proto,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        })
        return

    if method == "ping":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {}})
        return

    if method == "tools/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}})
        return

    if method == "resources/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"resources": []}})
        return

    if method == "prompts/list":
        _send({"jsonrpc": "2.0", "id": req_id, "result": {"prompts": []}})
        return

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            data = _dispatch_tool(tool_name, arguments)
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2, default=str)}],
                    "isError": False,
                },
            })
        except Exception as exc:
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": f"Tool execution error: {exc}"}],
                    "isError": True,
                },
            })
        return

    _send({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"},
    })


def main() -> None:
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(req, dict):
            _process_request(req)


if __name__ == "__main__":
    main()
