#!/bin/bash
set -x

# QuantBot sunucu kurulum scripti.
# Kullanım: GITHUB_TOKEN ve TELEGRAM_* env varlarini doldurup calistirin.
# Örnek:
#   export GITHUB_TOKEN="ghp_xxxx"
#   export TELEGRAM_BOT_TOKEN="123:ABC"
#   export TELEGRAM_CHAT_ID="999"
#   bash setup.sh

cd /home/ubuntu

if [ -z "$GITHUB_TOKEN" ]; then
    echo "HATA: GITHUB_TOKEN ortam degiskeni gerekli."
    exit 1
fi

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv screen git

rm -rf QuantBot
git clone "https://talha4111:${GITHUB_TOKEN}@github.com/talha4111/QuantBot.git"
cd QuantBot

python3 -m venv venv

sudo fallocate -l 2G /swapfile || true
sudo chmod 600 /swapfile || true
sudo mkswap /swapfile || true
sudo swapon /swapfile || true

/home/ubuntu/QuantBot/venv/bin/python3 -m pip install numpy pandas xgboost binance-futures-connector ccxt pandas_ta textblob scikit-learn python-dotenv feedparser rich

# ayar.json olustur (Telegram bilgileri env'den alinir)
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TG_CHAT="${TELEGRAM_CHAT_ID:-}"
python3 -c "
import json, os
ayar = {
    'portfoy': ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','AVAX/USDT','LINK/USDT','DOT/USDT','ADA/USDT','LTC/USDT','XRP/USDT'],
    'referans_varlik': 'BTC/USDT',
    'risk_yonetimi': {'kullan': True, 'sl_atr_carpani': 1.0, 'tp_atr_carpani': 2.5},
    'islem_miktari_usdt': 50,
    'sl_yuzde': 0.01,
    'tp_yuzde': 0.02,
    'telegram': {
        'aktif_mi': True,
        'bot_token': os.environ.get('TELEGRAM_BOT_TOKEN', ''),
        'chat_id': os.environ.get('TELEGRAM_CHAT_ID', ''),
    }
}
with open('/home/ubuntu/QuantBot/ayar.json', 'w') as f:
    json.dump(ayar, f, indent=2)
"

sed -i 's/"python", "main.py"/"\/home\/ubuntu\/QuantBot\/venv\/bin\/python3", "main.py"/' /home/ubuntu/QuantBot/commander.py
sed -i 's/"python", "mufettis.py"/"\/home\/ubuntu\/QuantBot\/venv\/bin\/python3", "mufettis.py"/' /home/ubuntu/QuantBot/commander.py

echo "KURULUM TAMAMLANDI - QUANTBOT SAVASA HAZIR!"
