import requests
import json
import os

def test_telegram():
    if not os.path.exists('ayar.json'):
        print("❌ HATA: 'ayar.json' dosyası bulunamadı!")
        return
        
    try:
        with open('ayar.json', 'r', encoding='utf-8') as f:
            ayarlar = json.load(f)
        
        tele = ayarlar.get('telegram', {})
        token = tele.get('bot_token')
        chat_id = tele.get('chat_id')
        
        if not token or token == "bot token buraya ":
            print("❌ HATA: 'bot_token' boş veya varsayılan değerde!")
            return
            
        print(f"🔄 Bağlantı test ediliyor (Token: {token[:5]}...{token[-5:]})")
        
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        msg = "🚀 Kaptan, Telegram bağlantısı BAŞARILI! Sistem V3 Savaş Moduna hazır."
        
        response = requests.post(url, json={'chat_id': chat_id, 'text': msg})
        
        if response.status_code == 200:
            print("✅ BAŞARILI! Telefonuna mesaj gelmiş olmalı.")
        else:
            print(f"❌ BAŞARISIZ! Telegram Sunucu Hatası: {response.text}")
            
    except Exception as e:
        print(f"❌ SISTEM HATASI: {e}")

if __name__ == "__main__":
    test_telegram()
