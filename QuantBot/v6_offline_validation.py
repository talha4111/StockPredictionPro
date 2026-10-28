"""V6 modeli için üretimden izole, maliyet-duyarlı ileri-test çalıştırıcısı.

Bu araç canlı tahmin yolu açmaz. Model artefaktları yalnızca kendi zaman
damgalı rapor dizinine yazılır ve kalite kapısını geçmeyen adaylar artefakt
oluşturmadan raporlanır.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "backtest_reports"
DEFAULT_SYMBOLS = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
CANDIDATES = (
    {"name": "200_3", "n_estimators": 200, "max_depth": 3},
    {"name": "300_4", "n_estimators": 300, "max_depth": 4},
    {"name": "400_5", "n_estimators": 400, "max_depth": 5},
)


def parse_symbols(raw: str) -> list[str]:
    symbols: list[str] = []
    for item in str(raw or "").replace(";", ",").split(","):
        symbol = item.strip().upper().replace(":USDT", "")
        if not symbol:
            continue
        if "/" not in symbol and symbol.endswith("USDT"):
            symbol = f"{symbol[:-4]}/USDT"
        if symbol not in symbols:
            symbols.append(symbol)
    return symbols


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def candidate_row(
    *,
    symbol: str,
    frame,
    candidate: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    """Bir V6 adayını artefakt dizininde değerlendirir, sonucu kaydeder."""
    from ai_core import BeyinMotoru

    artifact_dir.mkdir(parents=True, exist_ok=True)
    motor = BeyinMotoru(
        n_estimators=int(candidate["n_estimators"]),
        max_depth=int(candidate["max_depth"]),
        model_prefix=f"v6_offline_{candidate['name']}",
        label_schema_version=6,
        base_timeframe=str(frame.attrs.get("base_timeframe") or "15m"),
    )
    previous_cwd = Path.cwd()
    started = time.time()
    error = None
    try:
        os.chdir(artifact_dir)
        motor.model_egit(symbol, frame.copy(), is_crypto=True)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        os.chdir(previous_cwd)

    meta = dict(motor.son_egitim_meta or {})
    quality_gate = dict(meta.get("offline_artifact_quality_gate") or {})
    diagnostics = dict(meta.get("prediction_diagnostics") or {})
    cv_diagnostics = dict(diagnostics.get("cv") or {})
    holdout_diagnostics = dict(diagnostics.get("holdout") or {})
    threshold_research = dict(diagnostics.get("threshold_research") or {})
    classification_research = dict(
        threshold_research.get("classification") or {}
    )
    signal_research = dict(threshold_research.get("signal") or {})
    return {
        "symbol": symbol,
        "candidate": candidate["name"],
        "n_estimators": candidate["n_estimators"],
        "max_depth": candidate["max_depth"],
        "error": error,
        "duration_seconds": round(time.time() - started, 2),
        "training_rows": int(meta.get("egitim_mum_sayisi", 0) or 0),
        "class_counts": list(meta.get("sinif_sayilari") or []),
        "holdout_rows": int(meta.get("recent_holdout_rows", 0) or 0),
        "cv_balanced_accuracy": _float(meta.get("cv_balanced_accuracy")),
        "holdout_balanced_accuracy": _float(
            meta.get("recent_balanced_accuracy")
        ),
        "cv_brier_score": _float(meta.get("cv_brier_score"), 1.0),
        "holdout_brier_score": _float(meta.get("recent_brier_score"), 1.0),
        "signals": int(meta.get("recent_signal_count", 0) or 0),
        "holdout_net_return": _float(meta.get("recent_strategy_net_return")),
        "holdout_profit_factor": _float(
            meta.get("recent_strategy_profit_factor")
        ),
        "holdout_max_drawdown": _float(
            meta.get("recent_strategy_max_drawdown")
        ),
        "quality_gate_passed": bool(quality_gate.get("passed")),
        "quality_gate_reasons": list(quality_gate.get("reasons") or []),
        "artifact_saved": bool(meta.get("artifact_saved")),
        "feature_contract_id": meta.get("feature_contract_id"),
        "coverage_contract_id": meta.get("coverage_contract_id"),
        "outcome_contract_id": meta.get("outcome_contract_id"),
        "split_contract_id": meta.get("split_contract_id"),
        "selected_classification_threshold": classification_research.get(
            "selected_threshold"
        ),
        "selected_signal_threshold": signal_research.get("selected_threshold"),
        "threshold_research": threshold_research,
        "cv_positive_prevalence": cv_diagnostics.get(
            "target_positive_prevalence"
        ),
        "holdout_positive_prevalence": holdout_diagnostics.get(
            "target_positive_prevalence"
        ),
        "cv_probability_summary": cv_diagnostics.get(
            "calibrated_probability_summary"
        ),
        "holdout_probability_summary": holdout_diagnostics.get(
            "calibrated_probability_summary"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="V6 isolated offline forward-validation"
    )
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--timeframe", default="15m")
    parser.add_argument("--history-limit", type=int, default=5000)
    parser.add_argument("--max-ohlcv-pages", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    symbols = parse_symbols(args.symbols)
    if not symbols:
        raise ValueError("En az bir sembol gerekli.")
    config = {
        "label_schema_version": 6,
        "feature_schema_version": 6,
        "trade_mode": "LONG_ONLY",
        "symbols": symbols,
        "timeframe": args.timeframe,
        "history_limit": max(500, int(args.history_limit)),
        "max_ohlcv_pages": min(32, max(1, int(args.max_ohlcv_pages))),
        "candidates": list(CANDIDATES),
        "artifact_scope": "report_directory_only",
        "live_prediction_enabled": False,
    }
    if args.dry_run:
        print(json.dumps(config, ensure_ascii=False, indent=2))
        return 0

    from tarayici import veri_getir_dortlu

    run_dir = REPORT_DIR / ("v6_offline_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    artifact_root = run_dir / "model_artifacts"
    run_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []

    print(f"[START] V6 symbols={symbols} timeframe={args.timeframe} history_limit={config['history_limit']}", flush=True)
    print(f"[REPORT] {run_dir}", flush=True)
    for symbol in symbols:
        print(f"[DATA] {symbol}", flush=True)
        frame = veri_getir_dortlu(
            symbol,
            "BTC/USDT",
            timeframe=args.timeframe,
            feature_schema_version=6,
            history_limit=config["history_limit"],
            max_ohlcv_pages=config["max_ohlcv_pages"],
        )
        if frame is None or frame.empty:
            rows.append({"symbol": symbol, "error": "veri_alinamadi"})
            continue
        print(f"  rows={len(frame)}", flush=True)
        for candidate in CANDIDATES:
            row = candidate_row(
                symbol=symbol,
                frame=frame,
                candidate=candidate,
                artifact_dir=(
                    artifact_root
                    / symbol.replace("/", "-")
                    / str(candidate["name"])
                ),
            )
            rows.append(row)
            status = "PASS" if row["quality_gate_passed"] else "BLOCK"
            print(
                f"  [{status}] {candidate['name']} "
                f"net={row['holdout_net_return']:+.5f} "
                f"pf={row['holdout_profit_factor']:.3f} "
                f"brier={row['holdout_brier_score']:.4f}",
                flush=True,
            )
            (run_dir / "results.json").write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "config": config,
                        "results": rows,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

    passed = [row for row in rows if row.get("quality_gate_passed")]
    print(f"[DONE] passed={len(passed)}/{len(rows)} report={run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
