from datetime import datetime
from typing import Any, Tuple

def process_demo_exit_rules(
    islem_yonu: str,
    giris_fiyat: float,
    guncel_fiyat: float,
    pnl: float,
    pnl_yuzde: float,
    amt: float,
    sl_hedef: float,
    zirve_pnl: float,
    tsl_activation_yuzde: float,
    callback: float,
    atr_yuzde: float,
    acilis_zamani: datetime,
    scale_out_yapildi: bool,
    demo_kasa_anlik: float,
    btc_1h_ret: float = 0.0,
    btc_15m_ret: float = 0.0
) -> Tuple[str, float]:
    """
    Pozisyon icin cikis kurallarini isler ve kapanis sebebini (varsa) dondurur.
    Return: (kapanma_sebebi_metni, kapanma_miktari)
    Eger kapanma yoksa (None, 0.0) doner.
    """
    kapanma_sebebi = None
    kapanma_miktari = abs(amt)  # Tam kapanis varsayilan
    
    # 1: ATR BAZLI SABIT STOP-LOSS
    if sl_hedef > 0:
        if islem_yonu == 'LONG' and guncel_fiyat <= sl_hedef:
            kapanma_sebebi = f"🛑 ATR STOP-LOSS | SL: {sl_hedef:.5f} (Zarar: %{pnl_yuzde:.2f})"
        elif islem_yonu == 'SHORT' and guncel_fiyat >= sl_hedef:
            kapanma_sebebi = f"🛑 ATR STOP-LOSS | SL: {sl_hedef:.5f} (Zarar: %{pnl_yuzde:.2f})"
            
    # 2: FALLBACK HARD STOP (%4.0)
    if not kapanma_sebebi and pnl_yuzde <= -4.0 and pnl < 0:
        kapanma_sebebi = f"🛑 HARD STOP (Zarar: %{pnl_yuzde:.2f}, PNL: {pnl:+.2f}$)"
        
    # 3: MAKSIMUM TEK ISLEM ZARAR LIMITI (%4)
    if not kapanma_sebebi and pnl < 0:
        max_zarar_limit = demo_kasa_anlik * 0.04
        if abs(pnl) >= max_zarar_limit:
            kapanma_sebebi = f"🚨 MAX ZARAR LIMITI (PNL: {pnl:+.2f}$ > Limit: -{max_zarar_limit:.0f}$)"
            
    # 4: HİBRİT KISMİ KÂR ALMA (Scale-Out: +%4.5 ve üstü -> %40 Satış ile Kâr Kasaya Kilitlenir)
    if not kapanma_sebebi and not scale_out_yapildi:
        if pnl_yuzde >= 4.5:
            kapanma_sebebi = f"💰 HİBRİT SCALE-OUT (%40 kâr kilidi, +%4.5 Ralli) | Kâr: %{pnl_yuzde:.2f}"
            kapanma_miktari = abs(amt) * 0.40
            
    # 5: DİNAMİK TRAILING STOP (Büyük Trend Sürücü)
    tsl_esik = max(4.5, atr_yuzde * 1.2)
    tsl_callback = max(2.0, atr_yuzde * 0.7)
    if not kapanma_sebebi and zirve_pnl >= tsl_esik:
        if pnl_yuzde <= (zirve_pnl - tsl_callback):
            kapanma_sebebi = f"🎯 TRAILING STOP (Zirve: %{zirve_pnl:.2f} -> Şimdi: %{pnl_yuzde:.2f}, Callback: %{tsl_callback:.1f})"
            
    # 6: BTC FLASH DUMP KALKANI (Ani Makro Çöküş Önleyici)
    if not kapanma_sebebi and islem_yonu == 'LONG':
        if btc_1h_ret <= -0.025 or btc_15m_ret <= -0.018:
            if pnl_yuzde >= 1.5:
                kapanma_sebebi = f"⚡ BTC FLASH DUMP (Kâr Kilitlendi: %{pnl_yuzde:.2f}, BTC 1h: %{btc_1h_ret*100:.1f})"
            elif pnl_yuzde > -1.5:
                kapanma_sebebi = f"⚡ BTC FLASH DUMP ERKEN KAÇIŞ (Zarar Önlendi: %{pnl_yuzde:.2f}, BTC 1h: %{btc_1h_ret*100:.1f})"

    # 7: BAŞA-BAŞ KORUMA (Break-Even Stop: +%3.0 zirve veya Scale-Out sonrası girişe çekme)
    if not kapanma_sebebi and (zirve_pnl >= 3.0 or scale_out_yapildi) and pnl_yuzde <= 0.20:
        kapanma_sebebi = f"🔒 BREAK-EVEN STOP (Zirve: %{zirve_pnl:.2f} -> Başa-başa dönüş: %{pnl_yuzde:.2f})"
        
    # 8: ZAMAN ASIMI (4H Swing: 72 Saatlik Trend Tanima Ufku)
    if not kapanma_sebebi:
        gecen_saat = (datetime.now() - acilis_zamani).total_seconds() / 3600
        if gecen_saat >= 72 and pnl_yuzde < 1.0:
            kapanma_sebebi = f"🕐 72H ZAMAN ASIMI ({gecen_saat:.1f}h, Momentum yok: %{pnl_yuzde:.2f})"
            
    return kapanma_sebebi, kapanma_miktari
