from __future__ import annotations

import math
from typing import Iterable

import pandas as pd


def _pnl_listesi(islemler: Iterable[dict]) -> list[float]:
    pnller: list[float] = []
    for islem in islemler:
        try:
            pnller.append(float(islem.get("pnl", islem.get("Net_PNL_USDT", 0.0))))
        except Exception:
            pnller.append(0.0)
    return pnller


def _max_drawdown(equity_curve: list[float]) -> tuple[float, float]:
    if not equity_curve:
        return 0.0, 0.0

    zirve = equity_curve[0]
    max_dd = 0.0
    max_dd_pct = 0.0

    for equity in equity_curve:
        zirve = max(zirve, equity)
        dd = zirve - equity
        dd_pct = (dd / zirve) if zirve > 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            max_dd_pct = dd_pct

    return max_dd, max_dd_pct


def _max_ardisik_zarar(pnller: list[float]) -> int:
    en_uzun = 0
    seri = 0
    for pnl in pnller:
        if pnl <= 0:
            seri += 1
            en_uzun = max(en_uzun, seri)
        else:
            seri = 0
    return en_uzun


def trade_metriklerini_hesapla(islemler: Iterable[dict], baslangic_kasa: float = 1000.0) -> dict:
    pnller = _pnl_listesi(islemler)
    toplam = len(pnller)
    karlar = [p for p in pnller if p > 0]
    zararlar = [p for p in pnller if p <= 0]

    equity_curve = [float(baslangic_kasa)]
    for pnl in pnller:
        equity_curve.append(equity_curve[-1] + pnl)

    gross_profit = sum(karlar)
    gross_loss = abs(sum(zararlar))
    win_rate = len(karlar) / toplam if toplam else 0.0
    loss_rate = 1.0 - win_rate if toplam else 0.0
    avg_kar = gross_profit / len(karlar) if karlar else 0.0
    avg_zarar = gross_loss / len(zararlar) if zararlar else 0.0
    expectancy = (win_rate * avg_kar) - (loss_rate * avg_zarar)
    max_dd, max_dd_pct = _max_drawdown(equity_curve)

    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    elif gross_profit > 0:
        profit_factor = math.inf
    else:
        profit_factor = 0.0

    if toplam > 1:
        ortalama = sum(pnller) / toplam
        varyans = sum((p - ortalama) ** 2 for p in pnller) / (toplam - 1)
        std = math.sqrt(varyans)
        sharpe_like = (ortalama / std) * math.sqrt(toplam) if std > 0 else 0.0
    else:
        sharpe_like = 0.0

    son_kasa = equity_curve[-1]
    getiri_pct = ((son_kasa - baslangic_kasa) / baslangic_kasa) if baslangic_kasa > 0 else 0.0

    return {
        "toplam_islem": toplam,
        "kazanan_islem": len(karlar),
        "kaybeden_islem": len(zararlar),
        "win_rate": win_rate,
        "net_pnl": sum(pnller),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": profit_factor,
        "avg_kar": avg_kar,
        "avg_zarar": avg_zarar,
        "payoff_ratio": (avg_kar / avg_zarar) if avg_zarar > 0 else math.inf if avg_kar > 0 else 0.0,
        "expectancy": expectancy,
        "max_drawdown": max_dd,
        "max_drawdown_pct": max_dd_pct,
        "son_kasa": son_kasa,
        "getiri_pct": getiri_pct,
        "sharpe_like": sharpe_like,
        "max_ardisik_zarar": _max_ardisik_zarar(pnller),
        "equity_curve": equity_curve,
    }


def train_forward_bol(
    df: pd.DataFrame,
    forward_oran: float = 0.30,
    min_train: int = 200,
    min_forward: int = 80,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if df is None or df.empty:
        raise ValueError("Train/forward bolumu icin veri yok.")
    if not 0.05 <= forward_oran <= 0.80:
        raise ValueError("forward_oran 0.05 ile 0.80 arasinda olmali.")

    toplam = len(df)
    split_idx = int(toplam * (1.0 - forward_oran))
    if split_idx < min_train:
        raise ValueError(f"Train verisi yetersiz: {split_idx} < {min_train}")
    if toplam - split_idx < min_forward:
        raise ValueError(f"Forward verisi yetersiz: {toplam - split_idx} < {min_forward}")

    return df.iloc[:split_idx].copy(), df.iloc[split_idx:].copy()


def metrik_satiri(metrik: dict) -> str:
    pf = metrik.get("profit_factor", 0.0)
    pf_txt = "sonsuz" if pf == math.inf else f"{pf:.2f}"
    return (
        f"Islem: {metrik.get('toplam_islem', 0)} | "
        f"Win: %{metrik.get('win_rate', 0.0) * 100:.1f} | "
        f"Net: {metrik.get('net_pnl', 0.0):+.2f} | "
        f"E: {metrik.get('expectancy', 0.0):+.4f} | "
        f"PF: {pf_txt} | "
        f"MaxDD: {metrik.get('max_drawdown', 0.0):.2f} "
        f"(%{metrik.get('max_drawdown_pct', 0.0) * 100:.1f})"
    )


def metrik_ozeti(metrik: dict) -> dict:
    anahtarlar = [
        "toplam_islem",
        "kazanan_islem",
        "kaybeden_islem",
        "win_rate",
        "net_pnl",
        "profit_factor",
        "avg_kar",
        "avg_zarar",
        "payoff_ratio",
        "expectancy",
        "max_drawdown",
        "max_drawdown_pct",
        "son_kasa",
        "getiri_pct",
        "sharpe_like",
        "max_ardisik_zarar",
    ]
    ozet = {}
    for anahtar in anahtarlar:
        deger = metrik.get(anahtar)
        if isinstance(deger, float) and not math.isfinite(deger):
            ozet[anahtar] = None
        else:
            ozet[anahtar] = deger
    return ozet


if __name__ == "__main__":
    ornek_islemler = [
        {"pnl": 12.5},
        {"pnl": -5.0},
        {"pnl": 8.0},
        {"pnl": -3.5},
        {"pnl": 6.0},
    ]
    print(metrik_satiri(trade_metriklerini_hesapla(ornek_islemler, baslangic_kasa=1000.0)))
