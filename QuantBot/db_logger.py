"""
db_logger.py — İşlem kayıt, detay yönetimi ve Telegram bildirim modülü.
main.py'den ayrıştırıldı (modülerleştirme sprint'i).
"""
import os
import json
import csv
import sqlite3
import time
import requests
from datetime import datetime
from config import TELEGRAM_AYAR, DEMO_CALISMA_PROFILI, DEMO_LIVE_SHADOW_AKTIF, SHORT_ISLEM_AKTIF

try:
    from runtime_status import status_yaz
except Exception:
    def status_yaz(guncelleme=None, event=None):
        return {}

try:
    from demo_trade_journal import (
        kapanis_kaydet as demo_kapanis_kaydet,
        olay_yaz as demo_olay_yaz,
        ozet_hesapla as demo_journal_ozet_hesapla,
    )
except Exception:
    def demo_kapanis_kaydet(**detay): return {}
    def demo_olay_yaz(tip, **detay): return {}
    def demo_journal_ozet_hesapla(): return {}

try:
    from demo_performance_analyzer import analiz_uret as demo_performans_analiz_uret
except Exception:
    def demo_performans_analiz_uret(): return {}

# ===== DETAY DOSYA YÖNETİMİ (aktif_detay.json) =====
_DETAY_DOSYA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'aktif_detay.json')

def _detay_yukle():
    """Bot restart olduğunda AI skorları, TP/SL hedefleri kaybolmasın."""
    try:
        if os.path.exists(_DETAY_DOSYA):
            with open(_DETAY_DOSYA, 'r') as f:
                data = json.load(f)
            for k, v in data.items():
                if isinstance(v, dict) and 'Acilis_Zamani' in v:
                    try: v['Acilis_Zamani'] = datetime.fromisoformat(v['Acilis_Zamani'])
                    except: v['Acilis_Zamani'] = datetime.now()
            return data
    except Exception as e:
        print(f"[STATE] aktif_detay.json okunamadi: {e}")
    return {}

def _detay_kaydet(detay_dict):
    """Detayları diske yaz — restart'a dayanıklı."""
    try:
        kayit = {}
        for k, v in detay_dict.items():
            if isinstance(v, dict):
                kayit[k] = {dk: (dv.isoformat() if isinstance(dv, datetime) else dv) for dk, dv in v.items()}
            else:
                kayit[k] = v
        tmp_dosya = _DETAY_DOSYA + '.tmp'
        with open(tmp_dosya, 'w', encoding='utf-8') as f:
            json.dump(kayit, f, indent=2)
        os.replace(tmp_dosya, _DETAY_DOSYA)
    except Exception as e:
        print(f"[STATE] aktif_detay.json yazilamadi: {e}")

_SON_DETAY_SYNC = 0

def _detay_senkronize(aktif_semboller_set, aktif_islemler_detay):
    """aktif_detay.json'daki yetim (orphan) kayıtları temizler. Her 10dk'da bir çalışır."""
    global _SON_DETAY_SYNC
    simdi = time.time()
    if simdi - _SON_DETAY_SYNC < 600:
        return
    _SON_DETAY_SYNC = simdi

    aktif_sembol_isimleri = set()
    for sk in aktif_semboller_set:
        parts = sk.rsplit('_', 1)
        if parts:
            aktif_sembol_isimleri.add(parts[0])

    temizlenen = []
    for detay_key in list(aktif_islemler_detay.keys()):
        if detay_key.startswith('_tsl_max_'):
            base = detay_key.replace('_tsl_max_', '')
            sembol = base.rsplit('_', 1)[0] if '_' in base else base
            if sembol not in aktif_sembol_isimleri:
                temizlenen.append(detay_key)
            continue
        if isinstance(aktif_islemler_detay[detay_key], dict):
            sembol = detay_key.rsplit('_', 1)[0] if '_' in detay_key else detay_key
            if sembol not in aktif_sembol_isimleri:
                temizlenen.append(detay_key)

    if temizlenen:
        for tk in temizlenen:
            del aktif_islemler_detay[tk]
        _detay_kaydet(aktif_islemler_detay)
        kisa_isimler = list(set([k.split('_')[0].replace('_tsl_max_','') for k in temizlenen]))
        print(f"🧹 [DETAY SYNC] {len(temizlenen)} yetim kayıt temizlendi: {kisa_isimler}")

# ===== CSV + SQLITE KAYIT =====
csv_dosya_yolu = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_history.csv')
if not os.path.exists(csv_dosya_yolu):
    try:
        with open(csv_dosya_yolu, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Tarih_Saat', 'Parite', 'Hesap_Tipi', 'Islem_Yonu', 'Giris_Fiyati', 'Cikis_Fiyati', 'Net_PNL_USDT', 'PNL_Yuzde', 'AI_Guven_Skoru'])
    except Exception as e:
        print(f"[!] CSV Olusturulamadi: {e}")

def islem_kaydet(sembol, hesap_tipi, yon, giris, cikis, pnl_usdt, pnl_yuzde, ai_skoru, aktif_islemler_detay=None):
    tarih_saat = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    csv_dosya = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trade_history.csv')
    db_dosya = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db')
    uyari = not os.path.exists(csv_dosya)

    # CSV Kayıt
    try:
        with open(csv_dosya, mode='a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            if uyari:
                writer.writerow(['Tarih_Saat', 'Parite', 'Hesap_Tipi', 'Islem_Yonu', 'Giris_Fiyati', 'Cikis_Fiyati', 'Net_PNL_USDT', 'PNL_Yuzde', 'AI_Guven_Skoru'])
            writer.writerow([tarih_saat, sembol, hesap_tipi, yon, giris, cikis, pnl_usdt, pnl_yuzde, ai_skoru])
    except Exception as e:
        print(f"[MUHASEBE] CSV kaydi yazilamadi ({sembol}): {e}")

    # SQLite Database Kayıt
    try:
        baglanti = sqlite3.connect(db_dosya)
        cursor = baglanti.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS closed_trades (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            Tarih_Saat TEXT, Parite TEXT, Hesap_Tipi TEXT, Islem_Yonu TEXT, Giris_Fiyati REAL,
                            Cikis_Fiyati REAL, Net_PNL_USDT REAL, PNL_Yuzde REAL, AI_Guven_Skoru REAL
                        )''')
        cursor.execute("INSERT INTO closed_trades (Tarih_Saat, Parite, Hesap_Tipi, Islem_Yonu, Giris_Fiyati, Cikis_Fiyati, Net_PNL_USDT, PNL_Yuzde, AI_Guven_Skoru) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (tarih_saat, sembol, hesap_tipi, yon, giris, cikis, pnl_usdt, pnl_yuzde, ai_skoru))
        baglanti.commit()
        baglanti.close()
    except Exception as e:
        print(f"[MUHASEBE] SQLite kaydi yazilamadi ({sembol}): {e}")

    # Demo Journal Kapanış Kaydı
    aktif_islemler_detay = aktif_islemler_detay or {}
    detay = {}
    for detay_key in (f"{sembol}_{hesap_tipi}", f"{sembol}_TESTNET", f"{sembol}_DEMO"):
        aday = aktif_islemler_detay.get(detay_key)
        if isinstance(aday, dict):
            detay = aday
            break

    try:
        demo_kapanis_kaydet(
            hesap_tipi=hesap_tipi, sembol=sembol, yon=yon, giris=giris, cikis=cikis,
            pnl_usdt=pnl_usdt, pnl_yuzde=pnl_yuzde, ai_skoru=ai_skoru,
            tp=detay.get('TP_Fiyat'), sl=detay.get('SL_Fiyat'),
            rr=detay.get('Planlanan_RR'), risk_metni=detay.get('Risk_Metni', ''),
            tahmini_zarar=detay.get('Tahmini_Zarar', 0.0),
            demo_profil=detay.get('Demo_Profil', DEMO_CALISMA_PROFILI),
            demo_live_shadow=detay.get('Demo_Live_Shadow', DEMO_LIVE_SHADOW_AKTIF),
            short_islem_aktif=detay.get('Short_Islem_Aktif', SHORT_ISLEM_AKTIF),
            model_walk_forward_skoru=detay.get('Model_Walk_Forward_Skoru'),
            min_model_walk_forward_skoru=detay.get('Min_Model_Walk_Forward_Skoru'),
            model_kalite_bolgesi=detay.get('Model_Kalite_Bolgesi'),
            model_kalite_sari=detay.get('Model_Kalite_Sari'),
            model_kalite_sari_margin_carpani=detay.get('Model_Kalite_Sari_Margin_Carpani'),
            kapanis_sebebi=detay.get('Son_Kapanma_Sebebi', ''),
        )
    except Exception as e:
        print(f"[MUHASEBE] Demo journal kaydi yazilamadi ({sembol}): {e}")

# ===== TELEGRAM =====
def telegrama_gonder(mesaj):
    if not TELEGRAM_AYAR.get("aktif_mi"): return
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_AYAR['bot_token']}/sendMessage",
                      data={"chat_id": TELEGRAM_AYAR['chat_id'], "text": mesaj, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def gunluk_rapor_gonder(performans, KASA_DURUM, _DEMO_CACHE, KARANTINA_LISTESI):
    """Otomatik tetiklenen Telegram performans raporu."""
    try:
        toplam_islem = performans['kazanc'] + performans['kayip']
        win_rate = (performans['kazanc'] / toplam_islem * 100) if toplam_islem > 0 else 0
        demo_kasa = KASA_DURUM.get('DEMO_KASA', 0.0)
        acik_poz = len(_DEMO_CACHE.get('pozisyonlar', [])) if _DEMO_CACHE else 0
        karantina_sayisi = len(KARANTINA_LISTESI)

        bugunun_islemleri = ""
        toplam_pnl = 0.0
        try:
            conn = sqlite3.connect(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trading_bot.db'))
            cursor = conn.cursor()
            bugun_str = datetime.now().strftime('%Y-%m-%d')
            cursor.execute("SELECT Parite, Islem_Yonu, Net_PNL_USDT, PNL_Yuzde FROM closed_trades WHERE Tarih_Saat LIKE ?", (f"{bugun_str}%",))
            satirlar = cursor.fetchall()
            conn.close()
            if satirlar:
                bugunun_islemleri = "\n*📋 Son Kapanan İşlemler:*\n"
                for s in satirlar[-10:]:
                    pnl_str = f"+{s[2]:.2f}" if s[2] >= 0 else f"{s[2]:.2f}"
                    bugunun_islemleri += f"  `{s[0]}` {s[1]} → {pnl_str}$ (%{s[3]:.1f})\n"
                for s in satirlar:
                    toplam_pnl += s[2]
        except: pass

        rapor = f"""
📋 *SİSTEM DURUM RAPORU — {datetime.now().strftime('%d.%m.%Y %H:%M')}*
━━━━━━━━━━━━━━━━━━━
🎮 *DEMO Kasa:* ${demo_kasa:.2f}
💰 *Bugünkü Net Kâr/Zarar:* {toplam_pnl:+.2f} USDT
📊 *Toplam Günlük İşlem:* {toplam_islem}
✅ *Kazanç:* {performans['kazanc']} | ❌ *Kayıp:* {performans['kayip']}
🏆 *Günlük Win Rate:* %{win_rate:.0f}
📂 *Açık Pozisyon:* {acik_poz}
🚫 *Karantina:* {karantina_sayisi} coin
━━━━━━━━━━━━━━━━━━━{bugunun_islemleri}
⚡ _Savaş Modu V9.2 — Tam Otonom_
"""
        telegrama_gonder(rapor.strip())
        print("📨 [TELEGRAM] Durum raporu başarıyla gönderildi!")

        try:
            import subprocess, sys
            print("🧠 [AI HOOK] Gemini Dijital Analist (llm_analist.py) tetikleniyor...")
            subprocess.Popen([sys.executable, "llm_analist.py"])
        except Exception as e:
            print(f"⚠️ Gemini Analist tetiklenemedi: {e}")

    except Exception as e:
        print(f"⚠️ [TELEGRAM] Rapor gönderilemedi: {e}")

# ===== DEMO JOURNAL HELPERS =====
DEMO_ANALIZ_ARALIK_SN = 300
_SON_DEMO_ANALIZ_TS = 0.0

def demo_journal_status_guncelle(force=False):
    global _SON_DEMO_ANALIZ_TS
    try:
        ozet = demo_journal_ozet_hesapla()
        guncelleme = {}
        if ozet:
            guncelleme["demo_journal"] = ozet
        simdi_ts = time.time()
        if force or (simdi_ts - _SON_DEMO_ANALIZ_TS) >= DEMO_ANALIZ_ARALIK_SN:
            analiz = demo_performans_analiz_uret()
            if analiz:
                guncelleme["demo_analiz"] = analiz
            _SON_DEMO_ANALIZ_TS = simdi_ts
        if guncelleme:
            status_yaz(guncelleme)
    except Exception:
        pass

def demo_dispatch_ret_kaydet(sinyal, neden):
    try:
        demo_olay_yaz(
            "dispatch_ret",
            coin=sinyal.get("coin"), yon=sinyal.get("yon"),
            guven_skoru=sinyal.get("guven_skoru"), rr=sinyal.get("rr"),
            demo_ok=sinyal.get("demo_ok"), live_ok=sinyal.get("live_ok"),
            red_sebebi=neden,
        )
        demo_journal_status_guncelle()
    except Exception:
        pass
