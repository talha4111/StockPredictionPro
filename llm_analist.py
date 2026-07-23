"""
🤖 DİJİTAL QUANT STRATEJİ RAPORU OLUŞTURUCU 🤖
Gemini LLM kullanarak günlük trade_history.csv verisini analiz eder.
"""
import warnings
warnings.filterwarnings('ignore')
import os
import json
import requests
import google.generativeai as genai
import pandas as pd
from datetime import datetime, timedelta

def load_env():
    """ .env dosyasından GEMINI_API_KEY okur """
    env_vars = {}
    if os.path.exists('.env'):
        with open('.env', 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    env_vars[k.strip()] = v.strip().strip("'").strip('"')
    return env_vars

def generate_context():
    """ Son 24 saatin PNL ve Expectancy özetini hazırlar """
    if not os.path.exists('trade_history.csv'):
        return None
        
    expected_cols = ['Tarih_Saat', 'Parite', 'Hesap_Tipi', 'Islem_Yonu', 'Giris_Fiyati', 'Cikis_Fiyati', 'Net_PNL_USDT', 'PNL_Yuzde', 'AI_Guven_Skoru']
    try:
        df = pd.read_csv('trade_history.csv', header=None, skiprows=1, names=expected_cols)
    except Exception as e:
        print(f"Hata: {e}")
        return None
    
    if df.empty: return None
    
    date_col = 'Tarih_Saat'
                
    print(f"DEBUG: Tespit edilen gerçek tarih sütunu: {date_col}")
    print(f"DEBUG: CSV'deki ilk tarih örneği: {df[date_col].iloc[0]}")
    print(f"DEBUG: Sistem şu anki zamanı: {pd.Timestamp.now()}")
    
    df[date_col] = pd.to_datetime(df[date_col], dayfirst=True, errors='coerce')
    df = df.dropna(subset=[date_col])
    
    simdi = pd.Timestamp.now().replace(tzinfo=None)
    df[date_col] = df[date_col].dt.tz_localize(None)
    yirmidort_saat_once = simdi - pd.Timedelta(hours=24)
    
    df_son_24 = df[df[date_col] >= yirmidort_saat_once]
    print(f"DEBUG: Filtre sonrası bulunan işlem sayısı: {len(df_son_24)}")
    
    if df_son_24.empty:
        return None
    
    toplam_islem = len(df_son_24)
    karlar = df_son_24[df_son_24['Net_PNL_USDT'] > 0]['Net_PNL_USDT']
    zararlar = df_son_24[df_son_24['Net_PNL_USDT'] <= 0]['Net_PNL_USDT']
    
    win_rate = len(karlar) / toplam_islem if toplam_islem > 0 else 0
    loss_rate = 1.0 - win_rate
    
    avg_kar = karlar.mean() if not karlar.empty else 0.0
    avg_zarar = abs(zararlar.mean()) if not zararlar.empty else 0.0
    
    net_pnl = df_son_24['Net_PNL_USDT'].sum()
    expectancy = (win_rate * avg_kar) - (loss_rate * avg_zarar)
    
    context = f"""--- BUGÜNÜN İŞLEM ÖZETİ (Son 24 Saat) ---
Toplam İşlem: {toplam_islem}
Kazanma Oranı (Win-Rate): %{win_rate*100:.1f}
Net Kâr / Zarar (PNL): {net_pnl:+.4f} USDT
Ortalama Kazanç: {avg_kar:.4f} USDT | Ortalama Kayıp: {avg_zarar:.4f} USDT
Matematiksel Beklenti (Expectancy): {expectancy:+.4f} USDT

Son İşlemler:
"""
    for _, row in df_son_24.tail(15).iterrows():
        yon = row.get('Islem_Yonu', 'BELİRSİZ')
        pnl = row.get('Net_PNL_USDT', 0)
        coin = row.get('Parite', 'N/A')
        context += f"- {coin} {yon} | PNL: {pnl:+.2f} USDT\n"
        
    return context

def ana_gorev():
    env_vars = load_env()
    api_key = env_vars.get('GEMINI_API_KEY') or env_vars.get('LLM_API_KEY')
    
    if not api_key:
        print("❌ HATA: '.env' dosyasında 'GEMINI_API_KEY' bulunamadı!")
        return

    context_txt = generate_context()
    if not context_txt:
        print("⚠️ Son 24 saat içinde analiz edilecek işlem bulunamadı.")
        return

    print("🧠 Dijital Quant Analisti uyanıyor... (Google Gemini'ye Bağlanılıyor)")
    
    genai.configure(api_key=api_key)
    
    system_instruction = (
        "Sen profesyonel bir Quant Trading Analistisin. Aşağıdaki son 24 saatlik işlem verilerine bakarak:\n"
        "- Piyasanın mevcut karakterini (Trend mi, yatay mı?) yorumla.\n"
        "- Mevcut RSI, MACD ve ATR ayarlarımızın bu piyasada neden başarılı veya başarısız olduğunu açıkla.\n"
        "- Kaptan'a bir sonraki gün için somut, eyleme geçirilebilir 3 tavsiye ver."
    )
    
    try:
        model = genai.GenerativeModel('gemini-2.5-flash', system_instruction=system_instruction)
    except Exception:
        # Fallback
        model = genai.GenerativeModel('gemini-2.5-pro')
        context_txt = system_instruction + "\n\nİŞLEM VERİSİ:\n" + context_txt
        
    try:    
        response = model.generate_content(context_txt)
        
        print("\n" + "=" * 60)
        print("🤖 DİJİTAL QUANT STRATEJİ RAPORU 🤖")
        print("=" * 60)
        rapor = response.text
        print(rapor)
        print("=" * 60)
        
        # --- TELEGRAM GÖNDERİMİ ---
        try:
            if os.path.exists('ayar.json'):
                with open('ayar.json', 'r', encoding='utf-8') as f:
                    ayarlar = json.load(f)
                tele = ayarlar.get('telegram', {})
                if tele.get('aktif_mi') and tele.get('bot_token') != "bot token buraya " and len(tele.get('bot_token', '')) > 10:
                    token = tele.get('bot_token')
                    chat_id = tele.get('chat_id')
                    url = f"https://api.telegram.org/bot{token}/sendMessage"
                    msg = f"🤖 *DİJİTAL QUANT STRATEJİ RAPORU*\n\n{rapor}"
                    requests.post(url, json={'chat_id': chat_id, 'text': msg, 'parse_mode': 'Markdown'})
        except Exception as e:
            print(f"⚠️ Telegram gönderim hatası: {e}")
            
    except Exception as e:
        print(f"❌ LLM Yanıt Üretemedi: {e}")

if __name__ == "__main__":
    ana_gorev()
