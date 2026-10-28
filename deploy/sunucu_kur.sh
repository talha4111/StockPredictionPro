#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  StockPredictionPro — Oracle Cloud Sunucu Kurulum Scripti
#  Ubuntu 22.04+ / ARM64 (Ampere A1) için
# ═══════════════════════════════════════════════════════════
set -e

echo "══════════════════════════════════════════"
echo "  StockPredictionPro Sunucu Kurulumu"
echo "══════════════════════════════════════════"

# ── 1. Sistem güncellemesi ──
echo "[1/7] Sistem güncelleniyor..."
sudo apt update && sudo apt upgrade -y

# ── 2. Python 3.12 + pip + venv ──
echo "[2/7] Python kurulumu..."
sudo apt install -y python3.12 python3.12-venv python3-pip git nginx certbot

# ── 3. Proje klonla ──
echo "[3/7] Proje klonlanıyor..."
cd /home/ubuntu
if [ ! -d "StockPredictionPro" ]; then
    git clone https://github.com/KULLANICI_ADI/StockPredictionPro.git
fi
cd StockPredictionPro

# ── 4. Virtual environment ──
echo "[4/7] Python sanal ortam kuruluyor..."
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements_server.txt

# ── 5. Veritabanını başlat (ilk tarama) ──
echo "[5/7] Veritabanı başlatılıyor..."
python -c "
from stock_value_engine import tam_tarama_baslat
print('İlk tarama başlıyor... (5-10 dk sürebilir)')
tam_tarama_baslat()
print('Tarama tamamlandı!')
"

# ── 6. Systemd servisi kur ──
echo "[6/7] Streamlit servisi kuruluyor..."
sudo tee /etc/systemd/system/stockpro.service > /dev/null <<EOF
[Unit]
Description=StockPredictionPro Streamlit Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/StockPredictionPro
ExecStart=/home/ubuntu/StockPredictionPro/.venv/bin/streamlit run web/app.py --server.port 8501 --server.address 0.0.0.0 --server.headless true
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable stockpro
sudo systemctl start stockpro

# ── 7. Nginx reverse proxy ──
echo "[7/7] Nginx yapılandırılıyor..."
sudo tee /etc/nginx/sites-available/stockpro > /dev/null <<'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
EOF

sudo ln -sf /etc/nginx/sites-available/stockpro /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl restart nginx

# ── 8. Firewall ──
echo "Firewall ayarlanıyor..."
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save 2>/dev/null || true

# ── 9. Haftalık cron job ──
echo "Haftalık güncelleme cron job ekleniyor..."
(crontab -l 2>/dev/null; echo "0 18 * * 0 cd /home/ubuntu/StockPredictionPro && .venv/bin/python web/scripts/haftalik_guncelle.py >> /var/log/stockpro_weekly.log 2>&1") | crontab -

echo ""
echo "══════════════════════════════════════════"
echo "  ✅ Kurulum tamamlandı!"
echo "══════════════════════════════════════════"
echo ""
echo "  Streamlit:  http://$(curl -s ifconfig.me)"
echo "  Servis:     sudo systemctl status stockpro"
echo "  Loglar:     sudo journalctl -u stockpro -f"
echo ""
