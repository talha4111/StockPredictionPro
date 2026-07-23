#!/bin/bash
set -x

cd /home/ubuntu

sudo apt-get update
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv screen git

rm -rf QuantBot
git clone https://talha4111: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@github.com/talha4111/QuantBot.git
cd QuantBot

python3 -m venv venv

sudo fallocate -l 2G /swapfile || true
sudo chmod 600 /swapfile || true
sudo mkswap /swapfile || true
sudo swapon /swapfile || true

/home/ubuntu/QuantBot/venv/bin/python3 -m pip install numpy pandas xgboost binance-futures-connector ccxt pandas_ta textblob scikit-learn python-dotenv feedparser rich

python3 -c "import json; open('/home/ubuntu/QuantBot/ayar.json', 'w').write(json.dumps({'portfoy': ['BTC/USDT','ETH/USDT','SOL/USDT','BNB/USDT','AVAX/USDT','LINK/USDT','DOT/USDT','ADA/USDT','LTC/USDT','XRP/USDT'], 'referans_varlik': 'BTC/USDT', 'risk_yonetimi': {'kullan': True, 'sl_atr_carpani': 1.0, 'tp_atr_carpani': 2.5}, 'islem_miktari_usdt': 50, 'sl_yuzde': 0.01, 'tp_yuzde': 0.02, 'telegram': {'aktif_mi': True, 'bot_token': '8609459728:AAHGQlxs1yuy_w4GxBC77gbbrQWcZEkonvI', 'chat_id': '6610085196'}}))"

sed -i 's/"python", "main.py"/"\/home\/ubuntu\/QuantBot\/venv\/bin\/python3", "main.py"/' /home/ubuntu/QuantBot/commander.py
sed -i 's/"python", "mufettis.py"/"\/home\/ubuntu\/QuantBot\/venv\/bin\/python3", "mufettis.py"/' /home/ubuntu/QuantBot/commander.py

echo "KURULUM TAMAMLANDI - QUANTBOT SAVASA HAZIR!"
