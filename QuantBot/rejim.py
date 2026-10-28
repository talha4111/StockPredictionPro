import pandas as pd
from enum import Enum

class PiyasaRejimi(Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    YATAY = "YATAY"
    YUKSEK_RISK = "YUKSEK_RISK"

def piyasa_rejimi_belirle(mevcut_bar: pd.Series, btc_kalkan_aktif_mi: bool = False) -> str:
    """
    Verilen bar verilerine ve btc kalkanı durumuna göre piyasa rejimini belirler.
    
    Args:
        mevcut_bar: O anki barın hesaplanmış teknik indikatörlerini içeren pandas Series.
        btc_kalkan_aktif_mi: BTC Kalkanı veya benzeri bir risk koruma sisteminin aktiflik durumu.
        
    Returns:
        PiyasaRejimi enum'unun string değeri (BULL, BEAR, YATAY, YUKSEK_RISK).
    """
    # 1. Kriz / Yüksek Risk Kontrolü
    # Eğer 'Kriz' adlı bir kolon varsa ve 1.0 ise veya BTC kalkanı aktifse
    kriz_durumu = mevcut_bar.get('Kriz', 0.0)
    if kriz_durumu == 1.0 or btc_kalkan_aktif_mi:
        return PiyasaRejimi.YUKSEK_RISK.value

    # 2. Yatay Piyasa Kontrolü
    # CHOP (Choppiness Index) yüksekse veya ADX (Average Directional Index) düşükse trend zayıftır.
    chop = mevcut_bar.get('CHOP', 0)
    adx = mevcut_bar.get('ADX', 100) # Eğer yoksa yatay olmasın diye yüksek bir değer varsayıyoruz.
    
    if chop > 65 or adx < 15:
        return PiyasaRejimi.YATAY.value

    # 3. Trend Yönü Kontrolü (BULL / BEAR)
    # Eğer EMA_Slope varsa onu kullan
    if 'EMA_Slope' in mevcut_bar:
        if mevcut_bar['EMA_Slope'] > 0:
            return PiyasaRejimi.BULL.value
        else:
            return PiyasaRejimi.BEAR.value
            
    # Eğer EMA_Slope yoksa fiyat ve SMA ilişkisini kontrol et
    fiyat = mevcut_bar.get('close', mevcut_bar.get('Close', 0.0))
    sma = mevcut_bar.get('SMA_50', mevcut_bar.get('SMA', 0.0)) # Örnek bir SMA kullanıyoruz
    
    if fiyat > 0 and sma > 0:
        if fiyat > sma:
            return PiyasaRejimi.BULL.value
        else:
            return PiyasaRejimi.BEAR.value
            
    # Eğer hiçbir belirleyici metrik yoksa, varsayılan olarak yatay diyelim
    return PiyasaRejimi.YATAY.value
