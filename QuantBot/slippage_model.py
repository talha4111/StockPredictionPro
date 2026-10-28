"""
Backtest Slippage Model — Hacim bazlı dinamik slippage tahmini.

Fiyat kaymasi (slippage) gercek piyasada kacinilmazdir. Bu modul,
backtest sonuclarini gercege yakinlastirmak icin hacme ve volatiliteye
bagli slippage tahmini uretir.
"""

import numpy as np

# --- Slippage Sabitleri ---
# Referans: Binance futures taker fee 0.05%, tipik BTC spread 0.01%
# Dusuk hacimli altcoinlerde spread+impact 0.10-0.30%
MIN_SLIPPAGE_BPS = 2.0    # 0.02% - BTC/ETH gibi yuksek hacimli coinler
MAX_SLIPPAGE_BPS = 30.0   # 0.30% - dusuk hacimli altcoinler
HACIM_REFERANS_USDT = 50_000_000  # 24h referans hacim (50M USDT)
VOLATILITE_CARPANI = 0.3  # ATR etkisi carpani

def slippage_tahmini(
    volume_24h_usdt: float,
    atr_pct: float = 0.0,
    notional_usdt: float = 0.0,
    is_stop: bool = False,
) -> float:
    """
    Hacim, volatilite ve emir boyutuna gore slippage yuzdesi hesaplar.
    
    Args:
        volume_24h_usdt: Coinin 24 saatlik islem hacmi (USDT)
        atr_pct: ATR'nin fiyata yuzdesi (ornegin 0.02 = %2)
        notional_usdt: Islem buyuklugu (USDT)
        is_stop: Stop emri mi? Stop emirlerinde slippage daha yuksek olur
    
    Returns:
        Slippage yuzdesi (ornegin 0.001 = %0.1)
    """
    if volume_24h_usdt <= 0:
        volume_24h_usdt = 1.0 # prevent division by zero
    
    # Base slippage from volume
    volume_ratio = min(volume_24h_usdt / HACIM_REFERANS_USDT, 1.0)
    base_bps = MIN_SLIPPAGE_BPS + (MAX_SLIPPAGE_BPS - MIN_SLIPPAGE_BPS) * (1.0 - volume_ratio)
    base_pct = base_bps / 10000.0
    
    # Volatility multiplier
    vol_mult = 1.0 + (atr_pct * VOLATILITE_CARPANI / 0.01)
    
    # Position size impact
    impact_pct = max(0.0, (notional_usdt / volume_24h_usdt) - 0.01) * 5.0
    
    total_pct = (base_pct * vol_mult) + impact_pct
    
    # Stop order penalty
    if is_stop:
        total_pct *= 1.5
        
    # Cap values
    min_pct = MIN_SLIPPAGE_BPS / 10000.0
    max_pct = (MAX_SLIPPAGE_BPS * 2) / 10000.0
    
    return max(min_pct, min(total_pct, max_pct))


def slippage_uygula(fiyat: float, slippage_pct: float, yon: str, giris_mi: bool) -> float:
    """
    Fiyata slippage uygular.
    
    Giris emirlerinde slippage her zaman aleyhte calısır:
    - LONG giris: fiyat YUKARI kayar (daha pahalı alırsın)
    - SHORT giris: fiyat ASAGI kayar (daha ucuza satarsın)
    
    Cikis emirlerinde de aleyhte:
    - LONG cikis (satis): fiyat ASAGI kayar
    - SHORT cikis (alis): fiyat YUKARI kayar
    """
    if yon.upper() == 'LONG':
        if giris_mi:
            return fiyat * (1.0 + slippage_pct)
        else:
            return fiyat * (1.0 - slippage_pct)
    elif yon.upper() == 'SHORT':
        if giris_mi:
            return fiyat * (1.0 - slippage_pct)
        else:
            return fiyat * (1.0 + slippage_pct)
    
    return fiyat
