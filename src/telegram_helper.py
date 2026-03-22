import requests

def telegram_gonder(token, chat_id, mesaj):
    """Metin mesajı gönderir."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": mesaj, "parse_mode": "Markdown"}
    try:
        requests.post(url, data=payload)
    except Exception as e:
        print(f"❌ Telegram Mesaj Hatası: {e}")

def telegram_resim_gonder(token, chat_id, resim_yolu, aciklama=""):
    """Grafik (PNG) dosyası gönderir."""
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    try:
        with open(resim_yolu, 'rb') as photo:
            payload = {"chat_id": chat_id, "caption": aciklama}
            files = {"photo": photo}
            requests.post(url, data=payload, files=files)
    except Exception as e:
        print(f"❌ Telegram Resim Hatası: {e}")