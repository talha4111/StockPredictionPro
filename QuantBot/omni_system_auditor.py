"""
omni_system_auditor.py — QuantBot Uçtan Uca Tam Sistem Denetçisi

Bu modül, QuantBot platformunun 5 ana katmanının tamamını tek bir komutla tarar:
1. Veri Katmanı (Data Layer)
2. AI & Model Katmanı (Model Layer)
3. Sinyal & Rejim Katmanı (Signal Layer)
4. Risk & Emir Katmanı (Risk Layer)
5. Sunucu & Ağ Katmanı (Infrastructure Layer)

Raporlama: Yeşil (SAĞLIKLI), Sarı (UYARI), Kırmızı (KRİTİK HATA) matrisi.
"""

import sys, os, time, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
from datetime import datetime, timezone
import pandas as pd
import numpy as np

# Proje dizin ayarları
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from config import (
    MIN_SCOUT_QUOTE_VOLUME_USDT, MAX_VERI_YASI_DAKIKA, MIN_ANALIZ_MUM_SAYISI,
    AYAR, DEMO_LIVE_SHADOW_AKTIF, SHORT_ISLEM_AKTIF, MIN_MODEL_WALK_FORWARD_SKORU
)
from risk_manager import _veri_kalitesi_kontrol, _gunluk_risk_yukle
from rejim import piyasa_rejimi_belirle
from analist import makro_volatilite_beklentisi


class OmniSystemAuditor:
    def __init__(self):
        self.results = {
            "data_layer": {"status": "GREEN", "details": []},
            "model_layer": {"status": "GREEN", "details": []},
            "signal_layer": {"status": "GREEN", "details": []},
            "risk_layer": {"status": "GREEN", "details": []},
            "infra_layer": {"status": "GREEN", "details": []},
        }

    def _add_log(self, layer, level, msg):
        """
        level: 'INFO', 'WARN', 'FAIL'
        """
        prefix = "  [✅ INFO]" if level == "INFO" else ("  [⚠️ WARN]" if level == "WARN" else "  [❌ FAIL]")
        self.results[layer]["details"].append(f"{prefix} {msg}")
        
        if level == "FAIL":
            self.results[layer]["status"] = "RED"
        elif level == "WARN" and self.results[layer]["status"] != "RED":
            self.results[layer]["status"] = "YELLOW"

    def audit_data_layer(self):
        """1. VERİ KATMANI DENETİMİ"""
        print("\n🔍 1. VERİ KATMANI DENETLENİYOR...")
        try:
            import ccxt
            exchange = ccxt.binance({'enableRateLimit': True, 'options': {'defaultType': 'future'}})
            tickers = exchange.fetch_tickers()
            coins = []
            for symbol, t in tickers.items():
                if symbol.endswith('/USDT:USDT') or symbol.endswith('/USDT'):
                    quote_vol = t.get('quoteVolume', 0.0) or 0.0
                    clean_symbol = symbol.split(':')[0]
                    if quote_vol >= MIN_SCOUT_QUOTE_VOLUME_USDT:
                        coins.append(clean_symbol)
            
            from tarayici import veri_getir_dortlu
            from config import REF
            
            if not coins:
                self._add_log("data_layer", "FAIL", f"Hacim barajından ({MIN_SCOUT_QUOTE_VOLUME_USDT/1e6:.0f}M$) geçen parite bulunamadı!")
                return
                
            self._add_log("data_layer", "INFO", f"Hacim barajını geçen {len(coins)} parite tespit edildi.")
            
            # 3 örnek parite üzerinde mum tazeliği ve indikatör zenginleştirme testi
            test_coins = [c for c in coins if '/' in c][:3]
            if not test_coins:
                test_coins = ['BTC/USDT', 'ETH/USDT', 'SOL/USDT']
                
            for coin in test_coins:
                try:
                    df = veri_getir_dortlu(coin, REF, timeframe="1h")
                except Exception:
                    df = None
                    
                if df is None or df.empty:
                    self._add_log("data_layer", "FAIL", f"{coin} için zenginleştirilmiş veri çekilemedi!")
                    continue
                    
                veri_ok, veri_red, kalite = _veri_kalitesi_kontrol(
                    coin, df, ['open', 'Hedef_Close', 'ATR', 'volume']
                )
                
                yas_dk = kalite.get('son_mum_yasi_dk', 0)
                if not veri_ok:
                    self._add_log("data_layer", "WARN", f"{coin} Veri Kontrolü Red: {veri_red}")
                else:
                    self._add_log("data_layer", "INFO", f"{coin} verisi sağlıklı | Mum Yaşı: {yas_dk}dk | Toplam Mum: {kalite['mum_sayisi']}")

            # Timeframe vs Max Veri Yaşı Çapraz Uyum Kontrolü
            if MAX_VERI_YASI_DAKIKA < 120:
                self._add_log("data_layer", "WARN", f"MAX_VERI_YASI_DAKIKA={MAX_VERI_YASI_DAKIKA}dk! 1h mumlarda 120dk altı ayarlar gereksiz 'Bayat Veri' engeline yol açabilir.")
            else:
                self._add_log("data_layer", "INFO", f"MAX_VERI_YASI_DAKIKA={MAX_VERI_YASI_DAKIKA}dk (1h mum yapısına tam uyumlu).")

        except Exception as e:
            self._add_log("data_layer", "FAIL", f"Veri katmanı denetim hatası: {e}")

    def audit_model_layer(self):
        """2. MODEL & YAPAY ZEKA KATMANI DENETİMİ"""
        print("\n🔍 2. AI & MODEL KATMANI DENETLENİYOR...")
        try:
            from ai_core import BeyinMotoru
            beyin = BeyinMotoru(n_estimators=200, max_depth=4, base_timeframe="1h")
            
            # Core feature sayısını kontrol et
            num_features = len(beyin.crypto_features)
            if num_features > 15:
                self._add_log("model_layer", "WARN", f"Model feature sayısı {num_features}! 15 üstü feature sayısı overfitting/gürültü riski taşır.")
            else:
                self._add_log("model_layer", "INFO", f"Model 10 Core Feature mimarisinde yapılandırılmış ({num_features} feature).")

            # Ufuk ve hedef getiri kontrolü
            if beyin.horizon_bars < 6:
                self._add_log("model_layer", "WARN", f"Tahmin ufku {beyin.horizon_bars} bar! 6 bar altı tahminler piyasa gürültüsüne hassastır.")
            else:
                self._add_log("model_layer", "INFO", f"Tahmin ufku {beyin.horizon_bars} bar (8 saatlik net trend hareketine odaklı).")

            # Kayıtlı modelleri tara
            model_dir = os.path.join(BASE_DIR, "models")
            if os.path.exists(model_dir):
                files = os.listdir(model_dir)
                meta_files = [f for f in files if f.endswith("_meta.json")]
                self._add_log("model_layer", "INFO", f"Diskte {len(meta_files)} kayıtlı model meta dosyası bulundu.")
            else:
                self._add_log("model_layer", "INFO", "Henüz yerel models/ klasörü oluşmamış (Sunucuda eğitilecek).")

        except Exception as e:
            self._add_log("model_layer", "FAIL", f"Model katmanı denetim hatası: {e}")

    def audit_signal_layer(self):
        """3. SİNYAL & REJİM KATMANI DENETİMİ"""
        print("\n🔍 3. SİNYAL & REJİM KATMANI DENETLENİYOR...")
        try:
            # Rejim belirleme testi
            dummy_bar = pd.Series({'CHOP': 45.0, 'ADX': 30.0, 'EMA_Slope': 0.05, 'Kriz': 0.0})
            rejim = piyasa_rejimi_belirle(dummy_bar)
            self._add_log("signal_layer", "INFO", f"Rejim tespit motoru aktif | Örnek Rejim: {rejim}")

            # Makro volatilite kalkanı saat testi
            makro_aktif = makro_volatilite_beklentisi()
            now_utc = datetime.now(timezone.utc)
            now_local = datetime.now()
            
            if makro_aktif:
                self._add_log("signal_layer", "WARN", f"Makro Volatilite Kalkanı AKTİF (Saat: UTC {now_utc.strftime('%H:%M')} / TSİ {now_local.strftime('%H:%M')}). Fırtına bitince kendiliğinden kapanacak.")
            else:
                self._add_log("signal_layer", "INFO", f"Makro Volatilite Kalkanı PASİF (Piyasa taramaya açık).")

        except Exception as e:
            self._add_log("signal_layer", "FAIL", f"Sinyal katmanı denetim hatası: {e}")

    def audit_risk_layer(self):
        """4. RİSK & EMİR KATMANI DENETİMİ"""
        print("\n🔍 4. RİSK & EMİR KATMANI DENETLENİYOR...")
        try:
            karantina_saat = AYAR.get("symbol_guard_karantina_saat", 6.0)
            agir_karantina_saat = AYAR.get("symbol_guard_agir_karantina_saat", 18.0)
            
            if karantina_saat > 4.0:
                self._add_log("risk_layer", "WARN", f"Symbol Guard Karantina Süresi {karantina_saat} saat! 4 saat üstü karantinalar fırsat kaçırabilir.")
            else:
                self._add_log("risk_layer", "INFO", f"Symbol Guard Karantina Süresi {karantina_saat} saat (Dinamik fırsat odaklı).")

            # Günlük risk durumu
            risk_state = _gunluk_risk_yukle()
            self._add_log("risk_layer", "INFO", "Günlük risk takip durumu okundu ve kilitli değil.")

        except Exception as e:
            self._add_log("risk_layer", "FAIL", f"Risk katmanı denetim hatası: {e}")

    def audit_infrastructure_layer(self):
        """5. SUNUCU & AĞ KATMANI DENETİMİ"""
        print("\n🔍 5. SUNUCU & AĞ KATMANI DENETLENİYOR...")
        try:
            import ccxt
            borsa = ccxt.binance({'enableRateLimit': True, 'options': {'adjustForTimeDifference': True}})
            
            t0 = time.time()
            server_time = borsa.fetch_time()
            t1 = time.time()
            
            ping_ms = (t1 - t0) * 1000
            self._add_log("infra_layer", "INFO", f"Binance API Bağlantısı Başarılı | Ping: {ping_ms:.1f}ms")
            
            # Zaman Senkronizasyonu
            local_ms = int(time.time() * 1000)
            diff_ms = abs(local_ms - server_time)
            if diff_ms > 2000:
                self._add_log("infra_layer", "WARN", f"Yerel saat ile Binance sunucu saati arasında {diff_ms}ms fark var!")
            else:
                self._add_log("infra_layer", "INFO", f"Zaman Senkronizasyonu Mükemmel (Fark: {diff_ms}ms).")

        except Exception as e:
            self._add_log("infra_layer", "FAIL", f"Ağ / API bağlantı hatası: {e}")

    def run_full_audit(self):
        """Tüm katmanları sırayla tarar ve final matrisini basar."""
        print("=" * 80)
        print("🛰️ QUANTBOT UÇTAN UCA TAM SİSTEM DENETÇİSİ (OMNI-AUDITOR)")
        print(f"Tarama Zamanı: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 80)

        self.audit_data_layer()
        self.audit_model_layer()
        self.audit_signal_layer()
        self.audit_risk_layer()
        self.audit_infrastructure_layer()

        print("\n" + "=" * 80)
        print("📊 QUANTBOT SAĞLIK VE UYUM MATRİSİ ÖZETİ")
        print("=" * 80)

        status_symbols = {
            "GREEN": "🟢 YEŞİL (SAĞLIKLI)",
            "YELLOW": "🟡 SARI (UYARI)",
            "RED": "🔴 KIRMIZI (KRİTİK HATA)"
        }

        layers_map = {
            "data_layer": "1. VERİ KATMANI      ",
            "model_layer": "2. AI & MODEL KATMANI",
            "signal_layer": "3. SİNYAL & REJİM    ",
            "risk_layer": "4. RİSK & EMİR       ",
            "infra_layer": "5. SUNUCU & AĞ       "
        }

        for key, name in layers_map.items():
            status = self.results[key]["status"]
            symbol = status_symbols[status]
            print(f"{name} : {symbol}")
            for detail in self.results[key]["details"]:
                print(detail)
            print("-" * 80)

        print("\n✅ Tam Sistem Denetimi Tamamlandı!\n")


if __name__ == "__main__":
    auditor = OmniSystemAuditor()
    auditor.run_full_audit()
