"""Shadow modelin testnet/live asamasina gecis uygunlugunu raporlar."""

from __future__ import annotations

import json
from typing import Any

from live_model_compare import LiveModelComparator


def candidate_failure_reasons(summary: dict[str, Any]) -> dict[str, list[str]]:
    """Her modelin terfi kapısında nerede takıldığını açıklar.

    Terfi kararı ikili kalmalıdır; ancak ``BASARISIZ`` tek başına hangi
    ölçütün bozulduğunu söylemez. Bu yardımcı yalnızca mevcut gölge-test
    özetini yorumlar, hiçbir model veya canlı ayar değiştirmez.
    """
    acceptance = summary.get("config", {}).get("acceptance", {}) or {}
    min_signals = int(acceptance.get("min_signals", 50) or 50)
    min_profit_factor = float(acceptance.get("min_profit_factor", 1.20) or 1.20)
    min_brier_skill = float(acceptance.get("min_brier_skill", 0.0) or 0.0)
    max_brier_score = float(acceptance.get("max_brier_score", 0.26) or 0.26)
    min_positive_regimes = int(
        acceptance.get("min_positive_regimes", 2) or 2
    )
    positive_regime_counts = summary.get("positive_regime_counts") or {}

    failures: dict[str, list[str]] = {}
    for model_name, metrics in (summary.get("models") or {}).items():
        reasons: list[str] = []
        signals = int(metrics.get("signals", 0) or 0)
        net_pnl = float(metrics.get("net_pnl", 0.0) or 0.0)
        profit_factor = float(metrics.get("profit_factor", 0.0) or 0.0)
        brier_score = metrics.get("brier_score")
        brier_skill = metrics.get("brier_skill_score")
        positive_regimes = int(positive_regime_counts.get(model_name, 0) or 0)

        if signals < min_signals:
            reasons.append(f"sinyal={signals}<{min_signals}")
        if net_pnl <= 0.0:
            reasons.append(f"net_pnl={net_pnl:.4f}<=0")
        if profit_factor < min_profit_factor:
            reasons.append(
                f"profit_factor={profit_factor:.4f}<{min_profit_factor:.4f}"
            )
        if brier_score is None or float(brier_score) > max_brier_score:
            shown_score = "yok" if brier_score is None else f"{float(brier_score):.4f}"
            reasons.append(f"brier_score={shown_score}>{max_brier_score:.4f}")
        if brier_skill is None or float(brier_skill) <= min_brier_skill:
            shown_skill = "yok" if brier_skill is None else f"{float(brier_skill):.4f}"
            reasons.append(f"brier_skill={shown_skill}<={min_brier_skill:.4f}")
        if positive_regimes < min_positive_regimes:
            reasons.append(
                f"pozitif_rejim={positive_regimes}<{min_positive_regimes}"
            )
        failures[str(model_name)] = reasons
    return failures


def evaluate_promotion(summary: dict[str, Any]) -> dict[str, Any]:
    config = summary.get("config", {}).get("acceptance", {})
    settled = int(summary.get("settled", 0) or 0)
    required_observations = int(config.get("min_common_observations", 500) or 500)
    leader = str(summary.get("leader") or "VERI_BIRIKIYOR")
    accepted = list(summary.get("accepted_models") or [])
    positive_regime_counts = summary.get("positive_regime_counts") or {}
    required_regimes = int(config.get("min_positive_regimes", 2) or 2)

    reasons = []
    if settled < required_observations:
        reasons.append(f"ortak_gozlem={settled}<{required_observations}")
    if leader in {"VERI_BIRIKIYOR", "BASARISIZ"}:
        reasons.append(f"lider={leader}")
    if leader not in accepted:
        reasons.append("lider_mutlak_kapilari_gecmedi")
    if int(positive_regime_counts.get(leader, 0) or 0) < required_regimes:
        reasons.append(
            f"pozitif_rejim={int(positive_regime_counts.get(leader, 0) or 0)}"
            f"<{required_regimes}"
        )

    return {
        "promotion_ready": not reasons,
        "target_stage": "TESTNET_TINY_RISK",
        "leader": leader,
        "settled": settled,
        "accepted_models": accepted,
        "reasons": reasons,
        "candidate_failures": candidate_failure_reasons(summary),
        "policy": config,
    }


def main() -> int:
    comparator = LiveModelComparator()
    result = evaluate_promotion(comparator.summary())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["promotion_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
