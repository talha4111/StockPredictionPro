"""Read the production A/B test state without changing remote files."""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from remote_config import connect_ssh


REMOTE_DIR = "/root/QuantBot"
MIN_SETTLED = 300
MIN_SIGNALS = 30


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_report(
    state: dict[str, Any],
    runtime: dict[str, Any],
    *,
    service: str,
    now: float | None = None,
) -> dict[str, Any]:
    now = float(now or time.time())
    models = state.get("models", {}) if isinstance(state, dict) else {}
    model_report: dict[str, Any] = {}
    evaluated_values = []

    for name in ("450_8", "400_5"):
        raw = models.get(name, {}) if isinstance(models, dict) else {}
        evaluated = int(_number(raw.get("evaluated")))
        signals = int(_number(raw.get("signals")))
        wins = int(_number(raw.get("wins")))
        gross_profit = _number(raw.get("gross_profit"))
        gross_loss = _number(raw.get("gross_loss"))
        brier_sum = _number(raw.get("brier_sum"))
        model_report[name] = {
            "evaluated": evaluated,
            "signals": signals,
            "wins": wins,
            "win_rate_pct": round(100.0 * wins / signals, 2) if signals else 0.0,
            "net_pnl_usdt": round(_number(raw.get("net_pnl")), 4),
            "cost_usdt": round(_number(raw.get("cost")), 4),
            "profit_factor": round(gross_profit / abs(gross_loss), 4)
            if gross_loss < 0
            else (999.0 if gross_profit > 0 else 0.0),
            "brier_score": round(brier_sum / evaluated, 6) if evaluated else None,
            "signal_progress_pct": round(min(100.0, 100.0 * signals / MIN_SIGNALS), 1),
        }
        evaluated_values.append(evaluated)

    settled = min(evaluated_values) if evaluated_values else 0
    pending = len(state.get("pending", {})) if isinstance(state, dict) else 0
    started_at = _number(state.get("started_at"), now) if isinstance(state, dict) else now
    ready = settled >= MIN_SETTLED and all(
        model_report[name]["signals"] >= MIN_SIGNALS for name in model_report
    )
    return {
        "service": service,
        "schema": state.get("schema") if isinstance(state, dict) else None,
        "elapsed_hours": round(max(0.0, now - started_at) / 3600.0, 2),
        "pending": pending,
        "settled": settled,
        "settled_target": MIN_SETTLED,
        "settled_progress_pct": round(min(100.0, 100.0 * settled / MIN_SETTLED), 1),
        "ready_for_decision": ready,
        "models": model_report,
        "runtime": {
            "updated": runtime.get("guncelleme_zamani"),
            "phase": runtime.get("faz"),
            "status": runtime.get("bot_durumu"),
            "demo_orders": bool(runtime.get("demo_emir_aktif")),
            "live_mode": bool(runtime.get("live_mod")),
            "last_error": runtime.get("son_hata") or {},
        },
    }


def _read_json(sftp, path: str) -> dict[str, Any]:
    with sftp.open(path, "r") as remote_file:
        raw = remote_file.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    data = json.loads(raw)
    return data if isinstance(data, dict) else {}


def fetch_report() -> dict[str, Any]:
    ssh = connect_ssh(timeout=12)
    sftp = ssh.open_sftp()
    try:
        state = _read_json(sftp, f"{REMOTE_DIR}/live_model_compare_state.json")
        runtime = _read_json(sftp, f"{REMOTE_DIR}/runtime_status.json")
        _, stdout, _ = ssh.exec_command(
            "systemctl is-active quantbot.service", timeout=12
        )
        service = stdout.read().decode("utf-8", errors="replace").strip()
        return build_report(state, runtime, service=service)
    finally:
        sftp.close()
        ssh.close()


def print_human(report: dict[str, Any]) -> None:
    print("A/B TEST DURUMU")
    print(f"Service         : {report['service']}")
    print(f"Gecen sure      : {report['elapsed_hours']:.2f} saat")
    print(f"Bekleyen        : {report['pending']}")
    print(
        f"Sonuclanan      : {report['settled']}/{report['settled_target']} "
        f"(%{report['settled_progress_pct']:.1f})"
    )
    for name in ("450_8", "400_5"):
        model = report["models"][name]
        print(
            f"{name:15}: sinyal={model['signals']}/{MIN_SIGNALS} | "
            f"win=%{model['win_rate_pct']:.2f} | "
            f"net={model['net_pnl_usdt']:+.4f} USDT | "
            f"PF={model['profit_factor']:.4f} | brier={model['brier_score']}"
        )
    print(
        "Karar durumu    : "
        + ("DEGERLENDIRMEYE HAZIR" if report["ready_for_decision"] else "VERI BIRIKIYOR")
    )
    runtime = report["runtime"]
    print(
        f"Bot             : {runtime['phase']} | {runtime['status']} | "
        f"demo_emir={runtime['demo_orders']} | live={runtime['live_mode']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only QuantBot A/B status")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")
    args = parser.parse_args()
    report = fetch_report()
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2))
    else:
        print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
