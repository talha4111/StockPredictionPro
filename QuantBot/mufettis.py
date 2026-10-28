"""
╔══════════════════════════════════════════════════════════════╗
║           KAPTAN KRİPTO — SİSTEM MÜFETTİŞİ v3.0            ║
║   Görev: Sistemi tarayıp hataları bul, performansı analiz   ║
║   et ve analist gözüyle somut tavsiyeler sun.                ║
╚══════════════════════════════════════════════════════════════╝
"""

import sys
# Windows cp1254 Türkçe encoding emoji çökmelerini önle
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import os
import re
import csv
import sqlite3
import ccxt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
LOG_FILE  = os.path.join(BASE_DIR, 'bot.log')
CSV_FILE  = os.path.join(BASE_DIR, 'trade_history.csv')
DB_FILE   = os.path.join(BASE_DIR, 'trading_bot.db')

# ─── Renkler (terminal) ────────────────────────────────────────
OK    = "✅"
WARN  = "⚠️ "
ERR   = "❌"
INFO  = "ℹ️ "
IDEA  = "💡"
MONEY = "💰"
SKULL = "☠️ "

# ─── API Yükleme ───────────────────────────────────────────────
def _env_yukle():
    env_path = os.path.join(BASE_DIR, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                if '=' in line and not line.startswith('#'):
                    k, v = line.strip().split('=', 1)
                    os.environ[k.strip()] = v.strip()
_env_yukle()

TESTNET_API_KEY = os.environ.get('TESTNET_API_KEY', '').strip()
TESTNET_SECRET  = os.environ.get('TESTNET_SECRET', '').strip()

# .env'de yoksa ayar.json'dan oku
if not TESTNET_API_KEY:
    try:
        import json as _json
        _ayar_path = os.path.join(BASE_DIR, 'ayar.json')
        if os.path.exists(_ayar_path):
            with open(_ayar_path, 'r', encoding='utf-8') as _f:
                _ayar = _json.load(_f)
            TESTNET_API_KEY = _ayar.get('testnet_api_key', '').strip()
            TESTNET_SECRET  = _ayar.get('testnet_secret', '').strip()
    except:
        pass

def _borsa_baglant():
    if not TESTNET_API_KEY:
        return None
    try:
        b = ccxt.binanceusdm({
            'apiKey': TESTNET_API_KEY, 'secret': TESTNET_SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'future', 'adjustForTimeDifference': True, 'recvWindow': 60000}
        })
        b.enable_demo_trading(True)
        return b
    except:
        return None

# ══════════════════════════════════════════════════════════════════
# BÖLÜM 1: SİSTEM SAĞLIĞI — LOG TARAMASI
# ══════════════════════════════════════════════════════════════════
def sistem_sagligi_tara():
    print("\n" + "═"*65)
    print("🩺  BÖLÜM 1: SİSTEM SAĞLIĞI — LOG TARAMASI")
    print("═"*65)

    bulgular = {
        'kritik_hatalar': [],
        'api_hatalari':   [],
        'veri_hatalari':  [],
        'uyarilar':       [],
        'sinyal_blos':    0,
        'toplam_tarama':  0,
        'crash_var':      False,
    }

    if not os.path.exists(LOG_FILE):
        print(f"  {WARN} bot_rapor.txt bulunamadı. Bot hiç çalışmadı ya da log dosyası yanlış yerde.")
        return bulgular

    # Son 3000 satırı oku (son birkaç saat)
    try:
        with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
            satirlar = f.readlines()[-3000:]
    except:
        print(f"  {ERR} Log dosyası okunamadı.")
        return bulgular

    for satir in satirlar:
        s = satir.strip()
        sl = s.lower()

        # Kritik Python hataları
        if any(x in s for x in ['Traceback', 'Exception', 'Error:', 'CRITICAL']):
            bulgular['kritik_hatalar'].append(s[:120])
            if 'KeyboardInterrupt' not in s:
                bulgular['crash_var'] = True

        # API hataları
        elif any(x in sl for x in ['-2015', '-1021', 'invalid api', 'api key', 'unauthorized', 'signature']):
            bulgular['api_hatalari'].append(s[:120])

        # Veri hataları
        elif any(x in sl for x in ['eksik kolon', 'veri hatası', 'none', 'nan', 'boş geldi']):
            bulgular['veri_hatalari'].append(s[:100])

        # Uyarılar
        elif any(x in sl for x in ['⚠️', 'uyari', 'dikkat', 'bağlantı bekleniyor']):
            bulgular['uyarilar'].append(s[:100])

        # Tarama turları
        if 'AŞAMA 1: SCOUT' in s:
            bulgular['toplam_tarama'] += 1

        # Sinyal ama işlem yok
        if 'sinyal yetersiz' in sl or 'filteler engelledi' in sl:
            bulgular['sinyal_blos'] += 1

    # Rapor
    if bulgular['toplam_tarama'] == 0:
        print(f"  {WARN} Log'da hiç tarama turu bulunamadı — bot çalışmıyor olabilir!")
    else:
        print(f"  {OK} Log'da {bulgular['toplam_tarama']} tarama turu tespit edildi.")

    if bulgular['kritik_hatalar']:
        print(f"\n  {ERR} KRİTİK HATALAR ({len(bulgular['kritik_hatalar'])} adet, son 3'ü):")
        for h in bulgular['kritik_hatalar'][-3:]:
            print(f"     → {h}")
    else:
        print(f"  {OK} Kritik Python hatası (Exception/Traceback) yok.")

    if bulgular['api_hatalari']:
        benzersiz_api = list(dict.fromkeys(bulgular['api_hatalari']))[-3:]
        print(f"\n  {WARN} API HATALARI ({len(bulgular['api_hatalari'])} tekrar, son 3 benzersiz):")
        for h in benzersiz_api:
            print(f"     → {h}")
    else:
        print(f"  {OK} API bağlantı hatası yok.")

    if bulgular['veri_hatalari']:
        print(f"\n  {WARN} VERİ HATALARI ({len(bulgular['veri_hatalari'])} adet, son 3'ü):")
        for h in bulgular['veri_hatalari'][-3:]:
            print(f"     → {h}")
    else:
        print(f"  {OK} Veri/Kolon hatası yok.")

    if bulgular['sinyal_blos'] > 0:
        print(f"\n  {INFO} Sinyal oluştu ama filtreler engelledi: {bulgular['sinyal_blos']} kez")

    return bulgular

# ══════════════════════════════════════════════════════════════════
# BÖLÜM 2: AÇIK POZİSYON ANALİZİ
# ══════════════════════════════════════════════════════════════════
def acik_pozisyon_analizi():
    print("\n" + "═"*65)
    print("📊  BÖLÜM 2: AÇIK POZİSYONLAR (Anlık Durum)")
    print("═"*65)

    sonuclar = {'acik_sayi': 0, 'toplam_pnl': 0.0, 'agir_zarar': [], 'bakiye': 0.0}

    borsa = _borsa_baglant()
    if not borsa:
        print(f"  {WARN} Testnet API Key bulunamadı.")
        return sonuclar

    try:
        pozisyonlar = borsa.fetch_positions()
        acik = [p for p in pozisyonlar
                if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0]

        try:
            sonuclar['bakiye'] = float(borsa.fetch_balance({'type': 'future'}).get('USDT', {}).get('total', 0))
        except: pass

        if not acik:
            print(f"  {INFO} Şu an hiç açık pozisyon yok.")
            return sonuclar

        sonuclar['acik_sayi'] = len(acik)
        print(f"  {INFO} Toplam {len(acik)} açık pozisyon\n")
        print(f"  {'COİN':<14} {'YÖN':<6} {'GİRİŞ':<11} {'GÜNCEL':<11} {'PNL':>10}  {'PNL%':>7}  {'DURUM'}")
        print("  " + "-"*72)

        for p in acik:
            sembol   = p.get('symbol', '?')
            yon      = p.get('side', '?').upper()
            adet     = abs(float(p.get('contracts', 0)))
            giris    = float(p.get('entryPrice', 0))
            guncel   = float(p.get('markPrice', giris))
            pnl      = float(p.get('unrealizedPnl', 0))
            pnl_yuz  = ((pnl / (giris * adet)) * 100) if (giris * adet) > 0 else 0
            sonuclar['toplam_pnl'] += pnl

            # Durum değerlendirmesi
            if pnl_yuz <= -3.0:
                durum = f"{SKULL} AĞIR ZARAR"
                sonuclar['agir_zarar'].append((sembol, pnl, pnl_yuz))
            elif pnl_yuz <= -1.5:
                durum = f"{WARN} Zararla Bekle"
            elif pnl_yuz >= 3.0:
                durum = f"{OK} Kârda — İzle"
            elif pnl_yuz >= 1.0:
                durum = f"{OK} Hafif Kâr"
            else:
                durum = f"⚖️  Başa Baş"

            isaret = "🟢" if pnl >= 0 else "🔴"
            print(f"  {sembol:<14} {yon:<6} {giris:<11.5f} {guncel:<11.5f} {isaret}{pnl:>+8.3f}$  {pnl_yuz:>+6.2f}%  {durum}")

        print("  " + "-"*72)
        isaret_t = "🟢" if sonuclar['toplam_pnl'] >= 0 else "🔴"
        print(f"  {'TOPLAM AÇIK PNL':<40} {isaret_t}{sonuclar['toplam_pnl']:>+8.3f}$")
        print(f"  {MONEY} Demo Kasa: {sonuclar['bakiye']:.2f}$")

    except Exception as e:
        print(f"  {ERR} Binance API Hatası: {e}")

    return sonuclar

# ══════════════════════════════════════════════════════════════════
# BÖLÜM 3: KAPANMIŞ İŞLEM PERFORMANS ANALİZİ
# ══════════════════════════════════════════════════════════════════
def performans_analizi():
    print("\n" + "═"*65)
    print("📁  BÖLÜM 3: KAPANMIŞ İŞLEM PERFORMANS ANALİZİ")
    print("═"*65)

    sonuclar = {
        'toplam': 0, 'win_rate': 0.0, 'net_pnl': 0.0,
        'expectancy': 0.0, 'max_seri_zarar': 0, 'veri_var': False
    }

    df_list = []
    for dosya, oku in [(CSV_FILE, lambda: pd.read_csv(dosya)),
                       (DB_FILE,  lambda: _db_oku())]:
        if os.path.exists(dosya):
            try:
                df = oku()
                if df is not None and not df.empty:
                    df_list.append(df)
            except: pass

    if not df_list:
        print(f"  {INFO} Henüz kapanmış işlem kaydı yok.")
        print(f"     (Normal — botun açtığı işlemler henüz TP/SL'e vurmadıysa bu boş kalır.)")
        return sonuclar

    df = pd.concat(df_list, ignore_index=True).drop_duplicates(
        subset=['Tarih_Saat', 'Parite', 'Hesap_Tipi']
    )

    # Son 30 günü al
    gunler = [(datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(30)]
    df = df[df['Tarih_Saat'].astype(str).apply(lambda x: any(x.startswith(g) for g in gunler))]

    if df.empty:
        print(f"  {INFO} Son 30 günde kapanmış işlem yok.")
        return sonuclar

    sonuclar['veri_var'] = True
    sonuclar['toplam']   = len(df)
    karlar   = df[df['Net_PNL_USDT'] > 0]['Net_PNL_USDT']
    zararlar = df[df['Net_PNL_USDT'] <= 0]['Net_PNL_USDT']
    win_rate = len(karlar) / len(df) if len(df) > 0 else 0
    avg_kar  = karlar.mean() if len(karlar) > 0 else 0.0
    avg_zarar= abs(zararlar.mean()) if len(zararlar) > 0 else 0.0
    exp      = (win_rate * avg_kar) - ((1 - win_rate) * avg_zarar)
    net_pnl  = df['Net_PNL_USDT'].sum()

    sonuclar.update({'win_rate': win_rate, 'net_pnl': net_pnl, 'expectancy': exp})

    # Max losing streak
    streak = max_s = 0
    for pnl in df.sort_values('Tarih_Saat')['Net_PNL_USDT']:
        if pnl <= 0:
            streak += 1
            max_s = max(max_s, streak)
        else:
            streak = 0
    sonuclar['max_seri_zarar'] = max_s

    print(f"  Toplam Kapanmış İşlem : {len(df)}")
    print(f"  Win-Rate               : %{win_rate*100:.1f}  ({len(karlar)} Kâr / {len(zararlar)} Zarar)")
    print(f"  Net PNL                : {net_pnl:+.4f} USDT")
    print(f"  Ort. Kazanç            : {avg_kar:+.4f} USDT")
    print(f"  Ort. Kayıp             : {avg_zarar:+.4f} USDT")
    print(f"  Matematiksel Beklenti  : {exp:+.4f} USDT/işlem")
    print(f"  Max Ardışık Zarar      : {max_s} işlem")

    return sonuclar

def _db_oku():
    conn = sqlite3.connect(DB_FILE)
    df   = pd.read_sql_query("SELECT * FROM closed_trades", conn)
    conn.close()
    if 'id' in df.columns:
        df = df.drop(columns=['id'])
    return df

# ══════════════════════════════════════════════════════════════════
# BÖLÜM 4: ANALIST TAVSİYELERİ (En Kritik Bölüm)
# ══════════════════════════════════════════════════════════════════
def analist_tavsiyeler(log_bulgular, acik_sonuclar, perf_sonuclar):
    print("\n" + "═"*65)
    print("🧠  BÖLÜM 4: ANALİST TAVSİYELERİ")
    print("═"*65)

    tavsiyeler    = []  # (öncelik 1=KRİTİK 2=ÖNEMLİ 3=İYİLEŞTİRME, başlık, detay, aksiyon)
    acil_aksiyon  = []

    # ── 1. LOG TARAMA BULGULARINA GÖRE ────────────────────────────
    if log_bulgular.get('crash_var'):
        tavsiyeler.append((1,
            "Sistemde Exception/Crash Hatası Var",
            f"{log_bulgular['toplam_tarama']} tarama turundan birinde kritik Python hatası oluştu.",
            "Sunucuda: grep 'Traceback' bot_rapor.txt | tail -20  →  tam hatayı bul, bize bildir."
        ))

    if len(log_bulgular.get('api_hatalari', [])) > 5:
        tavsiyeler.append((1,
            "Tekrarlayan API Bağlantı Hataları",
            f"{len(log_bulgular['api_hatalari'])} API hatası tespit edildi. Sunucu IP'si bloklanmış ya da API key yetkisi eksik olabilir.",
            "Binance → API Management → IP Whitelist'i kontrol et. TESTNET_API_KEY .env'de doğru mu diye doğrula."
        ))

    if log_bulgular.get('toplam_tarama', 0) == 0:
        acil_aksiyon.append("Bot ÇALIŞMIYOR! Sunucuda: nohup venv/bin/python3 -u main.py > bot_rapor.txt 2>&1 &")

    # ── 2. AÇIK POZİSYONLARA GÖRE ─────────────────────────────────
    if acik_sonuclar.get('agir_zarar'):
        for sem, pnl, yuz in acik_sonuclar['agir_zarar']:
            tavsiyeler.append((1,
                f"{sem} POZİSYONU AĞIR ZARARDA ({yuz:.1f}%)",
                f"Stop-Loss devreye girmeden {pnl:.2f}$ kayıp birikti. Manuel müdahale gerekebilir.",
                f"Binance demo.binance.com → {sem} → Pozisyonu manuel kapat ya da Stop-Loss'u fiyata yaklaştır."
            ))

    if acik_sonuclar.get('acik_sayi', 0) >= 8:
        tavsiyeler.append((2,
            f"Portföy Yoğunluğu Yüksek ({acik_sonuclar['acik_sayi']} pozisyon)",
            "Çok sayıda açık pozisyon, olumsuz bir piyasa hareketi olduğunda zincirleme kayıp riski yaratır.",
            "main.py → MAX_PORTFOY_ISI_YUZDESI = 0.30  (0.40'dan 0.30'a düşür, max ~7-8 işleme indir)"
        ))

    if acik_sonuclar.get('toplam_pnl', 0) < -50:
        tavsiyeler.append((1,
            f"Toplam Açık Kayıp Kritik Seviyede ({acik_sonuclar['toplam_pnl']:.2f}$)",
            "Açık pozisyonların birleşik zararı kasanın tehlikeli bir seviyesine ulaştı.",
            "Yeni pozisyon açmayı durdur. ALIM_SATIM_TETIGI_ACIK = False yap, mevcut işlemlerin kapanmasını bekle."
        ))

    # ── 3. PERFORMANSA GÖRE ────────────────────────────────────────
    if perf_sonuclar.get('veri_var'):
        wr  = perf_sonuclar['win_rate']
        exp = perf_sonuclar['expectancy']
        pnl = perf_sonuclar['net_pnl']
        msx = perf_sonuclar['max_seri_zarar']

        if exp < 0:
            tavsiyeler.append((1,
                f"Matematiksel Beklenti Negatif ({exp:.4f} USDT/işlem)",
                "Her işlemde ortalama para kaybediliyor. Sistem bu haliyle uzun vadede kasayı eritir.",
                "XGBoost eşiğini yükselt: dinamik_esik = 0.57 yap. ADX'i 20'ye çek. R/R'ı 2.0 yap."
            ))
        elif exp > 0.5:
            tavsiyeler.append((3,
                f"Beklenti Pozitif ({exp:.4f} USDT/işlem) — Mükemmel!",
                "Sistem matematiksel olarak kârlı çalışıyor.",
                "Mevcut filtre ayarlarını koru. Portföy ısı sınırını %45'e biraz gevşetebilirsin."
            ))

        if wr < 0.40:
            tavsiyeler.append((1,
                f"Win-Rate Kritik Düşük (%{wr*100:.0f})",
                "Her 10 işlemin 6'sından fazlası zarar ile kapanıyor.",
                "CHOP'u 60'a düşür, ADX'i 22'ye çıkar. Böylece sadece güçlü trend anlarında girer."
            ))
        elif wr < 0.50:
            tavsiyeler.append((2,
                f"Win-Rate Düşük (%{wr*100:.0f}) — İyileşme Gerekli",
                "Kazanan işlem sayısı kaybedeni geçemiyor.",
                "R/R oranını 2.0'a yükselt. Daha az ama daha kaliteli sinyal için vol_zscore > 0.3 yap."
            ))
        elif wr >= 0.60:
            tavsiyeler.append((3,
                f"Win-Rate İyi (%{wr*100:.0f}) 👍",
                "Sistem sinyallerin çoğunu doğru tahmin ediyor.",
                "Pozisyon başı marjini %5'e çık (margin_override_demo = 0.05) — daha fazla kâr al."
            ))

        if msx >= 4:
            tavsiyeler.append((2,
                f"Tehlikeli Ardışık Zarar Serisi (Max {msx} işlem)",
                "Sistem arka arkaya 4 ya da daha fazla kez zarar etmiş. Drawdown riski yüksek.",
                "Devre kesici eşiğini sıkılaştır: CANLI_DEVRE_KESICI eşiğini -0.15'e çek. Cooldown'ı artır."
            ))

        if pnl > 0 and wr >= 0.55:
            tavsiyeler.append((3,
                "Sistem Genel İtibarıyla Sağlıklı Çalışıyor",
                f"Net PNL: {pnl:+.4f}$ | Win-Rate: %{wr*100:.0f} | Beklenti: {exp:+.4f}$",
                "Yeni bir altcoin dalgasında çeşitliliği artır: sicak_coinler[:120] yap (100'den 120'ye)."
            ))

    # ── Eğer hiç kapalı işlem yoksa ────────────────────────────────
    else:
        tavsiyeler.append((3,
            "Henüz Kapanmış İşlem Yok — Erken Dönem",
            "Bot yeni kuruldu ya da açtığı işlemler henüz TP/SL'e vurmadı.",
            "Sabırlı ol. İlk 10 kapanmış işlem birikmeden performans değerlendirmesi yapmak güvenilmez."
        ))

    # ── RAPOR ET ────────────────────────────────────────────────────
    if acil_aksiyon:
        print(f"\n  {SKULL} ACİL AKSİYON GEREKİYOR:")
        for a in acil_aksiyon:
            print(f"  ➡️  {a}")

    sirali = sorted(tavsiyeler, key=lambda x: x[0])
    etiket = {1: f"{ERR} [KRİTİK]  ", 2: f"{WARN}[ÖNEMLİ]  ", 3: f"{IDEA}[İYİLEŞT.]"}

    for oncelik, baslik, detay, aksiyon in sirali:
        print(f"\n  {etiket[oncelik]} {baslik}")
        print(f"     Durum  : {detay}")
        print(f"     Aksiyon: {aksiyon}")

    if not tavsiyeler:
        print(f"\n  {OK} Sistem sağlıklı görünüyor — tavsiye verilecek kritik bulgu yok.")

# ══════════════════════════════════════════════════════════════════
# BÖLÜM 5: GEMİNİ LLM — GENEL SİSTEM ANALİZİ (Dijital Quant Analist)
# ══════════════════════════════════════════════════════════════════
def llm_genel_analiz(log_bulgular, acik_sonuclar, perf_sonuclar):
    print("\n" + "═"*65)
    print("🤖  BÖLÜM 5: DİJİTAL QUANT ANALİST (Gemini LLM)")
    print("═"*65)

    # API Key kontrolü
    gemini_key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not gemini_key:
        print(f"  {WARN} GEMINI_API_KEY .env dosyasında bulunamadı — LLM analizi atlanıyor.")
        print(f"     .env'ye ekle: GEMINI_API_KEY=senin_key_in")
        return

    try:
        from google import genai
    except ImportError:
        try:
            import google.generativeai as genai_old
            # Eski kütüphane ile uyumluluk (fallback)
            genai = None
            genai_legacy = genai_old
        except ImportError:
            print(f"  {WARN} google-genai kütüphanesi yüklü değil: pip install google-genai")
            return

    # ── Tüm verileri tek bir context'e derle ─────────────────
    context_parts = []

    # 1) Açık pozisyonlar
    context_parts.append("=== ŞU AN AÇIK POZİSYONLAR ===")
    borsa = _borsa_baglant()
    if borsa:
        try:
            pozlar = borsa.fetch_positions()
            acik = [p for p in pozlar if float(p.get('contracts', p.get('info', {}).get('positionAmt', 0))) != 0]
            if acik:
                toplam_pnl = 0
                for p in acik:
                    sembol  = p.get('symbol', '?')
                    yon     = p.get('side', '?').upper()
                    adet    = abs(float(p.get('contracts', 0)))
                    giris   = float(p.get('entryPrice', 0))
                    guncel  = float(p.get('markPrice', giris))
                    pnl     = float(p.get('unrealizedPnl', 0))
                    pnl_yuz = ((pnl / (giris * adet)) * 100) if (giris * adet) > 0 else 0
                    toplam_pnl += pnl
                    context_parts.append(f"  {sembol} | {yon} | Giriş: {giris:.5f} | Güncel: {guncel:.5f} | PNL: {pnl:+.3f}$ ({pnl_yuz:+.2f}%)")
                context_parts.append(f"  TOPLAM AÇIK PNL: {toplam_pnl:+.3f}$")
                context_parts.append(f"  Açık Pozisyon Sayısı: {len(acik)}")
            else:
                context_parts.append("  Hiç açık pozisyon yok.")

            try:
                bakiye = float(borsa.fetch_balance({'type': 'future'}).get('USDT', {}).get('total', 0))
                context_parts.append(f"  Demo Kasa Bakiyesi: {bakiye:.2f}$")
            except: pass
        except Exception as e:
            context_parts.append(f"  API Hatası: {e}")
    else:
        context_parts.append("  API bağlantısı kurulamadı.")

    # 2) Kapanmış işlem istatistikleri
    context_parts.append("\n=== KAPANMIŞ İŞLEM İSTATİSTİKLERİ ===")
    if perf_sonuclar.get('veri_var'):
        context_parts.append(f"  Toplam Kapanmış: {perf_sonuclar['toplam']}")
        context_parts.append(f"  Win-Rate: %{perf_sonuclar['win_rate']*100:.1f}")
        context_parts.append(f"  Net PNL: {perf_sonuclar['net_pnl']:+.4f}$")
        context_parts.append(f"  Matematiksel Beklenti: {perf_sonuclar['expectancy']:+.4f}$/işlem")
        context_parts.append(f"  Max Ardışık Zarar: {perf_sonuclar['max_seri_zarar']}")
    else:
        context_parts.append("  Henüz kapanmış işlem yok (Bot yeni, işlemler henüz TP/SL'e vurmadı).")

    # 3) Son kapanmış işlem detayları (varsa)
    if os.path.exists(CSV_FILE):
        try:
            df_csv = pd.read_csv(CSV_FILE)
            if not df_csv.empty and len(df_csv) > 0:
                context_parts.append("\n=== SON 15 KAPANMIŞ İŞLEM DETAYLARI ===")
                for _, row in df_csv.tail(15).iterrows():
                    context_parts.append(
                        f"  {row.get('Tarih_Saat','')} | {row.get('Parite','')} | "
                        f"{row.get('Islem_Yonu','')} | PNL: {row.get('Net_PNL_USDT',0):+.3f}$ | "
                        f"AI Güven: %{row.get('AI_Guven_Skoru',0):.1f}"
                    )
        except: pass

    # 4) Log sağlığı
    context_parts.append("\n=== SİSTEM SAĞLIĞI (LOG TARAMASI) ===")
    context_parts.append(f"  Toplam Tarama Turu: {log_bulgular.get('toplam_tarama', 0)}")
    context_parts.append(f"  Kritik Hata Sayısı: {len(log_bulgular.get('kritik_hatalar', []))}")
    context_parts.append(f"  API Hata Sayısı: {len(log_bulgular.get('api_hatalari', []))}")
    context_parts.append(f"  Veri Hata Sayısı: {len(log_bulgular.get('veri_hatalari', []))}")
    context_parts.append(f"  Sinyal Oluştu Ama Filtre Engelledi: {log_bulgular.get('sinyal_blos', 0)} kez")
    if log_bulgular.get('kritik_hatalar'):
        context_parts.append("  Son Kritik Hatalar:")
        for h in log_bulgular['kritik_hatalar'][-5:]:
            context_parts.append(f"    → {h}")

    # 5) Mevcut filtre ayarları (Güncel değerler)
    context_parts.append("\n=== MEVCUT FİLTRE AYARLARI ===")
    context_parts.append("  XGBoost Giriş Eşiği: %60 (dinamik_esik = 0.60)")
    context_parts.append("  R/R (Risk/Reward) Minimum: Demo=1.5, Live=1.5")
    context_parts.append("  Kaldıraç: 5x | Marjin: %5-%8 (güvene göre dinamik)")
    context_parts.append("  Portföy Isı Sınırı: Kasanın %40'ı | Sektör Limiti: 2 pozisyon/sektör")

    full_context = "\n".join(context_parts)

    # ── Gemini'ye gönder ─────────────────────────────────────
    system_prompt = (
        "Sen dünya çapında deneyimli bir Quant Trading Analistisin. "
        "Bir kripto futures bot sisteminin tüm verilerini inceliyorsun.\n\n"
        "GÖREV:\n"
        "1. GENEL DURUM DEĞERLENDİRMESİ: Açık pozisyonların toplu durumunu değerlendir. "
        "Hepsi aynı yönde mi? Sektör çeşitliliği var mı? Toplam risk ne durumda?\n"
        "2. PERFORMANS ANALİZİ: Win-rate, beklenti ve PNL'e bakarak sistem kârlı mı yoksa eritiyor mu?\n"
        "3. SİSTEM SAĞLIĞI: Log hatalarına bakarak teknik bir problem var mı?\n"
        "4. FİLTRE OPTİMİZASYONU: Mevcut filtre ayarları (ADX, CHOP, R/R, XGBoost eşiği) bu sonuçlara göre "
        "doğru kalibre edilmiş mi? Sıkılaştırmalı mı, gevşetmeli mi?\n"
        "5. SOMUT TAVSİYELER: En az 3 tane eyleme geçirilebilir, spesifik tavsiye ver. "
        "Örneğin 'ADX değerini 22ye çıkar' veya 'CHOP filtresini 60a düşür' gibi net değerlerle.\n\n"
        "KURALLAR:\n"
        "- Türkçe yaz.\n"
        "- Kısa ve öz ol, gereksiz tekrar yapma.\n"
        "- Her tavsiyeyi 'AKSİYON:' ile başlat.\n"
        "- Eğer yeterli veri yoksa (kapanmış işlem yoksa), mevcut açık pozisyonlara ve filtre ayarlarına göre tavsiye ver.\n"
    )

    print(f"\n  🧠 Gemini'ye bağlanılıyor...")

    # Birden fazla model dene (ücretsiz kotası en geniş olandan başla)
    modeller = ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.5-flash']
    
    # Yeni google.genai API kullan
    if genai is not None:
        client = genai.Client(api_key=gemini_key)
    else:
        # Fallback: eski kütüphane
        genai_legacy.configure(api_key=gemini_key)
    
    for model_adi in modeller:
        try:
            print(f"  📡 Model deneniyor: {model_adi}")
            
            if genai is not None:
                # Yeni API
                response = client.models.generate_content(
                    model=model_adi,
                    contents=full_context,
                    config=genai.types.GenerateContentConfig(
                        system_instruction=system_prompt
                    )
                )
                rapor = response.text
            else:
                # Eski API (fallback)
                model = genai_legacy.GenerativeModel(model_adi, system_instruction=system_prompt)
                response = model.generate_content(full_context)
                rapor = response.text

            print(f"\n  {'─'*60}")
            print(rapor)
            print(f"  {'─'*60}")

            # Telegram'a da gönder (varsa)
            _telegram_gonder(f"🤖 *SİSTEM MÜFETTİŞİ — QUANT ANALİZ RAPORU*\n\n{rapor}")
            return  # Başarılı, çık
            
        except Exception as e:
            hata_str = str(e).lower()
            if 'quota' in hata_str or 'rate' in hata_str or '429' in hata_str:
                print(f"  ⚠️  {model_adi} kota dolmuş, sonraki model deneniyor...")
                continue
            else:
                print(f"  {ERR} {model_adi} hatası: {e}")
                continue
    
    print(f"\n  {WARN} Tüm modellerde kota dolmuş. LLM analizi atlanıyor.")
    print(f"     İlk 4 bölümdeki kural bazlı tavsiyeler hâlâ geçerlidir!")
    print(f"     Kota genelde 1-24 saat içinde sıfırlanır.")

def _telegram_gonder(mesaj):
    """Telegram'a rapor gönder (bilgiler .env'den okunur)."""
    try:
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
        chat_id   = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
        if bot_token and chat_id:
            import requests
            # Mesajı 4096 karaktere kırp (Telegram limiti)
            if len(mesaj) > 4000:
                mesaj = mesaj[:4000] + "\n\n... (kırpıldı)"
            requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={'chat_id': chat_id, 'text': mesaj, 'parse_mode': 'Markdown'},
                timeout=10
            )
    except: pass

# ══════════════════════════════════════════════════════════════════
# ANA ÇALIŞTIRICI
# ══════════════════════════════════════════════════════════════════
def gunluk_rapor_olustur():
    print("\n" + "╔" + "═"*63 + "╗")
    print("║       KAPTAN KRİPTO — SİSTEM MÜFETTİŞİ v3.0" + " "*17 + "║")
    print(f"║   Tarih: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + " "*32 + "║")
    print("╚" + "═"*63 + "╝")

    log_bulgular  = sistem_sagligi_tara()
    acik_sonuclar = acik_pozisyon_analizi()
    perf_sonuclar = performans_analizi()

    analist_tavsiyeler(log_bulgular, acik_sonuclar, perf_sonuclar)

    # BÖLÜM 5: Gemini LLM ile genel sistem analizi
    llm_genel_analiz(log_bulgular, acik_sonuclar, perf_sonuclar)

    print("\n" + "═"*65)
    print("✅  Müfettiş denetimi tamamlandı.")
    print("═"*65 + "\n")

if __name__ == "__main__":
    gunluk_rapor_olustur()
