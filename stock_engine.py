"""
STOCK ENGINE V8 — Otonom Infaz ve Karar Motoru (Tam IBKR Entegrasyonu)
========================================================================
Gorev: ibkr_bridge.py ve ai_core.py entegrasyonu ile tam otonom islem yapmak.
Eskimiş yfinance ve sanal kasa modulleri tamamen kaldirilmis olup; 
Isı radarı (Margin), asenkron hiz hatti (toplu tarama) ve Bracket Order sistemi eklenmistir.
"""

import sys
import io
import asyncio
import logging
import pandas as pd
import pandas_ta as ta

# ib_insync'in senkron fonksiyonlarini (reqHistoricalData vs.) asyncio.run icerisinde 
# Event Loop hatasi vermeden calistirmak amaciyla nest_asyncio uyguluyoruz.
import nest_asyncio
nest_asyncio.apply()

from ib_insync import Stock
from ibkr_bridge import (
    ibkr_baglan, bakiye_getir, toplu_veri_cek_async,
    gecmis_veri_cek, bracket_emri_gonder, sozlesme_dogrula
)
from ai_core import BeyinMotoru

# Windows CMD Unicode Hatasi Onleyici
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except:
        pass

# Loglama ayarlari
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
#  SİSTEM KONFİGÜRASYONU
# ============================================================
# AVRUPA (ACIK) + ASYA (KAPALI/ACILIS) + ABD (KAPALI/ACILIS)
HISSE_LISTESI = [
    'SAP.DE', 'ASML.AS', 'VOW3.DE',  # Avrupa Devleri (ŞU AN AÇIK)
    '0700.HK', '9988.HK',           # Asya Devleri (Hong Kong)
    'NVDA', 'AAPL', 'TSLA'          # ABD Devleri (16:30'da Açılacak)
]
MAX_ISI_YUZDESI = 0.80  # Portföyün %80'inden fazlası riske edilemez

async def motor_baslat():
    logger.info("============================================")
    logger.info("   STOCK ENGINE V8 | OTONOM INFAZ MOTORU")
    logger.info("============================================")

    # 1. IBKR'ye Baglan (Port 7497 => Paper Trading)
    ib = ibkr_baglan(host='127.0.0.1', port=7497, client_id=10)
    if not ib:
        logger.critical("IBKR TWS Baglantisi kurulamadi. Sistem kapatiliyor.")
        return

    # AI Beynini baslat (XGBoost)
    beyin = BeyinMotoru()

    try:
        while True:
            logger.info("\n--- [V8] YENI OTONOM TARAMA DONGUSU BASLIYOR ---")

            # ============================================================
            #  2. Gerçek Kasa Okuması ve Portföy Isısı (Sanal Kasa İPTAL)
            # ============================================================
            bakiye = bakiye_getir(ib)
            pozisyonlar = ib.positions()
            
            # Aynı hisseye tekrar girmemek için açık pozisyonlardaki sembolleri topla
            acik_semboller = [p.contract.symbol for p in pozisyonlar if p.position != 0]
            
            # Kullanılan margin hesaplaması (Pozisyon adedi * Ortalama Maliyet)
            kullanilan_margin = sum(abs(p.position * p.avgCost) for p in pozisyonlar)
            toplam_kasa = bakiye + kullanilan_margin

            if toplam_kasa <= 0:
                logger.error("Kasa bilgisi okunamadi (0$). TWS hesap bakiyesini kontrol edin. 1 Dakika bekleniyor...")
                await asyncio.sleep(60)
                continue

            isi_yuzdesi = kullanilan_margin / toplam_kasa
            logger.info(f"Kasa (Nakit Bakiye): ${bakiye:,.2f} | Kullanilan Margin: ${kullanilan_margin:,.2f}")
            logger.info(f"Portfoy Isisi: %{isi_yuzdesi*100:.1f} (Maksimum Isı Siniri: %{MAX_ISI_YUZDESI*100:.0f})")

            # Isı sınırı kalkanı 
            if isi_yuzdesi > MAX_ISI_YUZDESI:
                logger.warning("🚨 SISTEM SOGUMAYA ALINDI! Portfoy isisi kritik siniri asiyor. Yeni islem acilmayacak.")
                await asyncio.sleep(60 * 5) # 5 dakika bekle
                continue

            # ============================================================
            #  3. Hedef Filtreleme
            # ============================================================
            # Zaten acik pozisyonumuz olan hisseleri tarama disi birak (Tekrari onle)
            tarama_listesi = [s for s in HISSE_LISTESI if s not in acik_semboller]
            
            if not tarama_listesi:
                logger.info("Havuzdaki tum hisselerde aktif pozisyonumuz var. Bekleniyor...")
                await asyncio.sleep(60 * 5)
                continue

            logger.info(f"Taranacak Semboller ({len(tarama_listesi)} adet): {tarama_listesi}")

            # ============================================================
            #  4. Faz 3: Asenkron Hız Hattı ile Anlık Fiyatlar
            # ============================================================
            anlik_veriler = await toplu_veri_cek_async(ib, tarama_listesi, bekleme_sn=3)

            for sembol in tarama_listesi:
                veri = anlik_veriler.get(sembol)
                if not veri or not veri.get('ask') or not veri.get('bid'):
                    logger.warning(f"[{sembol}] Canli fiyat okunamadi. Esgeciliyor.")
                    continue
                
                logger.info(f"\n=> Analiz: {sembol} (Bid: ${veri['bid']:.2f} | Ask: ${veri['ask']:.2f} | Spread: {veri['spread_bps']} bps)")

                # ============================================================
                #  5. XGBoost Entegrasyonu (15 mins, 5 D)
                # ============================================================
                contract = sozlesme_dogrula(ib, sembol)
                if not contract:
                    logger.warning(f"[{sembol}] Contract bulunamadi, pas geciliyor.")
                    continue

                # pipeline_uygula=True oldugu icin DataFrame XGBoost feature'lariyla gelir.
                df = gecmis_veri_cek(ib, contract, bar_boyutu='15 mins', sure='5 D', pipeline_uygula=True)
                
                if df is None or df.empty:
                    logger.warning(f"[{sembol}] XGBoost icin yeterli gecmis veri alinamadi.")
                    continue

                # Beyin ile skorlama
                skor = beyin.tahmin_et(sembol, df, is_crypto=False)
                logger.info(f"[{sembol}] AI GUVEN SKORU: {skor:.3f}")

                # ============================================================
                #  6. Faz 4: Karar ve Bracket İnfaz (SL/TP)
                # ============================================================
                # Fraksiyonel Kelly mantığıyla işlem büyüklüğü (Kasadan %5 risk alarak orantılı pay ayırıyoruz)
                islem_butcesi = toplam_kasa * 0.05
                anlik_fiyat = (veri['ask'] + veri['bid']) / 2.0
                miktar = int(islem_butcesi / anlik_fiyat)

                if miktar < 1:
                    logger.warning(f"[{sembol}] Butce (${islem_butcesi:.2f}) 1 adet hisse almaya yetmiyor.")
                    continue

                yon = None
                if skor > 0.52:
                    yon = 'BUY'   # LONG
                elif skor < 0.48:
                    yon = 'SELL'  # SHORT (Kısa satis)
                    
                if yon:
                    # Dinamik ATR Hesaplama (pandas_ta ile 14 periyotluk gercek ATR)
                    atr_df = ta.atr(df['High'], df['Low'], df['Close'], length=14)
                    if atr_df is not None and not atr_df.empty and not pd.isna(atr_df.iloc[-1]):
                        atr_degeri = float(atr_df.iloc[-1])
                    else:
                        atr_degeri = anlik_fiyat * 0.015 # Yeterli veri yoksa %1.5 ortalama proxy ATR al
                    
                    # Kullanici kurali: TP = 1.5 ATR, SL = 0.8 ATR
                    if yon == 'BUY':
                        giris_fiyati = veri['ask']
                        tp_fiyat = round(giris_fiyati + (atr_degeri * 1.5), 2)
                        sl_fiyat = round(giris_fiyati - (atr_degeri * 0.8), 2)
                    else:
                        giris_fiyati = veri['bid']
                        tp_fiyat = round(giris_fiyati - (atr_degeri * 1.5), 2)
                        sl_fiyat = round(giris_fiyati + (atr_degeri * 0.8), 2)
                        
                    logger.info(f"[{sembol}] ⚡ INFAS EMRİ: {yon} Sinyali! Miktar: {miktar} | Beklenen Giris: ~${giris_fiyati:.2f}")
                    logger.info(f"         TP: ${tp_fiyat:.2f} (+1.5 ATR) | SL: ${sl_fiyat:.2f} (-0.8 ATR)")
                    
                    # Maliyet filtresini ve IBKR atesini tetikle
                    basarili = bracket_emri_gonder(ib, sembol, yon, miktar, tp_fiyat, sl_fiyat)
                    
                    if basarili:
                        logger.info(f"👍 [{sembol}] Islem Borsaya Aktarildi.")
                        # Ayni döngü vagonunda aynı hisseye ikinciye girmemesi icin acik_semboller listesine manuel ekle
                        acik_semboller.append(sembol) 
                else:
                    logger.info(f"[{sembol}] Skor Nötr bölgede (0.48 - 0.52). Bekleniyor...")

            # Tüm liste bittikten sonra dongu dinlenmesi
            logger.info("Tarama dongusu sonlandi. 5 dakika bekleme basladi...")
            await asyncio.sleep(60 * 5)

    except KeyboardInterrupt:
        logger.info("TWS Motoru Kaptan tarafindan manuel olarak kapatildi. (KeyboardInterrupt)")
    except Exception as e:
        logger.critical(f"Beklenmeyen MOTOR HATASI: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if ib.isConnected():
            ib.disconnect()
            logger.info("[SISTEM] IBKR baglantisi guvenle sonlandirildi.")

if __name__ == "__main__":
    try:
        asyncio.run(motor_baslat())
    except KeyboardInterrupt:
        print("Sistemden cikildi.")
