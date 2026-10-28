import pytest
from slippage_model import slippage_tahmini, slippage_uygula, MIN_SLIPPAGE_BPS, MAX_SLIPPAGE_BPS

def test_high_volume_low_slippage():
    # 100M volume should give MIN_SLIPPAGE_BPS base
    pct = slippage_tahmini(volume_24h_usdt=100_000_000, atr_pct=0.01, notional_usdt=10_000, is_stop=False)
    # base should be around 0.0002. Since vol_mult = 1.3 for atr_pct=0.01
    # total around 0.00026
    assert pct < 0.001

def test_low_volume_high_slippage():
    # 100k volume should give near MAX_SLIPPAGE_BPS base
    pct = slippage_tahmini(volume_24h_usdt=100_000, atr_pct=0.01, notional_usdt=1_000, is_stop=False)
    # base near 0.0030, mult 1.3 -> ~0.0039
    assert pct > 0.003

def test_stop_order_penalty():
    pct_normal = slippage_tahmini(volume_24h_usdt=10_000_000, atr_pct=0.01, notional_usdt=10_000, is_stop=False)
    pct_stop = slippage_tahmini(volume_24h_usdt=10_000_000, atr_pct=0.01, notional_usdt=10_000, is_stop=True)
    assert pct_stop > pct_normal
    assert pytest.approx(pct_stop, rel=1e-5) == pct_normal * 1.5

def test_slippage_uygula_directions():
    price = 1000.0
    slip = 0.01 # 1%

    # LONG Entry (worse price -> higher)
    assert slippage_uygula(price, slip, "LONG", True) == 1010.0
    
    # LONG Exit (worse price -> lower)
    assert slippage_uygula(price, slip, "LONG", False) == 990.0

    # SHORT Entry (worse price -> lower)
    assert slippage_uygula(price, slip, "SHORT", True) == 990.0
    
    # SHORT Exit (worse price -> higher)
    assert slippage_uygula(price, slip, "SHORT", False) == 1010.0

def test_boundary_cases():
    # Zero volume
    pct_zero = slippage_tahmini(0, 0.01, 1000, False)
    assert pct_zero > 0.003
    
    # Negative values
    pct_neg = slippage_tahmini(-5000, 0.01, 1000, False)
    assert pct_neg > 0.003
    
    # Huge position impact
    pct_impact = slippage_tahmini(1_000_000, 0.01, 500_000, False)
    assert pct_impact == (MAX_SLIPPAGE_BPS * 2) / 10000.0 # Should hit cap
