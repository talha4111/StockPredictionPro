import os
import sys
import subprocess
import time

# Bagimliliklari kontrol et
try:
    import paramiko
except ImportError:
    print("Paramiko yukleniyor...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko

from remote_config import connect_ssh

def run_remote_command(ssh, cmd):
    print(f"[Remote] {cmd}")
    stdin, stdout, stderr = ssh.exec_command(cmd)
    
    # Canli log akisi icin
    while not stdout.channel.exit_status_ready():
        if stdout.channel.recv_ready():
            chunk = stdout.channel.recv(1024).decode('utf-8', errors='ignore')
            print(chunk.encode('cp1254', 'ignore').decode('cp1254'), end="", flush=True)
        if stderr.channel.recv_ready():
            chunk = stderr.channel.recv(1024).decode('utf-8', errors='ignore')
            print(chunk.encode('cp1254', 'ignore').decode('cp1254'), end="", flush=True)
        time.sleep(0.1)
    
    # Kalanlari bas
    t_out = stdout.read().decode('utf-8', errors='ignore')
    print(t_out.encode('cp1254', 'ignore').decode('cp1254'))
    t_err = stderr.read().decode('utf-8', errors='ignore')
    print(t_err.encode('cp1254', 'ignore').decode('cp1254'))
    return stdout.channel.recv_exit_status()

print("Sunucuya baglaniliyor...")
ssh = None

try:
    ssh = connect_ssh(timeout=10)
    print("Baglanti Basarili!")
    
    print("\nAdim 1: Sunucu guncelleniyor ve gerekli paketler yukleniyor...")
    run_remote_command(ssh, "apt-get update && apt-get install -y python3-pip python3-venv zip unzip tmux htop")
    
    print("\nAdim 2: Lokal dosya zipleniyor...")
    # QuantBot klasorunu zipleyelim
    local_dir = r"C:\Users\talha\OneDrive\Desktop\StockPredictionPro\QuantBot"
    os.chdir(os.path.dirname(local_dir))
    
    zip_cmd = f"tar -a -c -f QuantBot.zip QuantBot"
    subprocess.check_call(zip_cmd, shell=True)
    print("Zip olusturuldu: QuantBot.zip")
    
    print("\nAdim 3: Zip dosyasi sunucuya yukleniyor...")
    sftp = ssh.open_sftp()
    sftp.put("QuantBot.zip", "/root/QuantBot.zip")
    sftp.close()
    print("Yukleme tamamlandi.")
    
    print("\nAdim 4: Dosyalar sunucuda cikariliyor...")
    run_remote_command(ssh, "unzip -o /root/QuantBot.zip -d /root/ && rm /root/QuantBot.zip")
    
    print("\nAdim 5: Python sanal ortami (venv) olusturuluyor ve kutuphaneler kuruluyor...")
    run_remote_command(ssh, "cd /root/QuantBot && python3 -m venv venv && ./venv/bin/pip install --upgrade pip")
    run_remote_command(ssh, "cd /root/QuantBot && ./venv/bin/pip install -r requirements.txt")
    
    print("\nAdim 6: TMUX icinde bot baslatiliyor...")
    # Once eger varsa eski oturumu kapat
    run_remote_command(ssh, "tmux kill-session -t quantbot || true")
    # Yeni tmux session ac ve main.py'yi calistir
    run_remote_command(ssh, "cd /root/QuantBot && tmux new-session -d -s quantbot './venv/bin/python main.py'")
    
    print("\n=======================================================")
    print(">>> KURULUM TAMAMLANDI VE BOT BULUTTA CALISMAYA BASLADI! <<<")
    print("=======================================================")
    
finally:
    if ssh:
        ssh.close()
    # Temizlik
    if os.path.exists("QuantBot.zip"):
        os.remove("QuantBot.zip")
