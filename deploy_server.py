import paramiko
import os
import time
from remote_config import connect_ssh

LOCAL_QUANTBOT = r"c:\Users\Talha\Desktop\StockPredictionPro\QuantBot"
REMOTE_QUANTBOT = "/root/QuantBot"

DEPLOY_FILES = [
    "main.py", "scanner_loop.py", "position_tracker.py", "order_engine.py",
    "signal_engine.py", "exit_rules.py", "risk_manager.py", "config.py",
    "db_logger.py", "state.py", "ai_core.py", "tarayici.py", "demo_trade_journal.py",
    "runtime_status.py", "mufettis.py", "ops_scan.py",
]

def run_cmd(ssh, cmd, timeout=60):
    stdin, stdout, stderr = ssh.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', errors='replace').strip()
    err = stderr.read().decode('utf-8', errors='replace').strip()
    return out, err

ssh = connect_ssh(timeout=15)
sftp = ssh.open_sftp()

# 1) Eski bot zaten önceki scriptte durduruldu, kontrol et
print("=" * 60)
print("AŞAMA 1: Bot durumu kontrol...")
out, _ = run_cmd(ssh, "ps aux | grep 'python.*main.py' | grep -v grep || echo 'Bot calismadi (temiz)'")
print(f"  {out}")

# Eğer hâlâ çalışıyorsa durdur
if 'main.py' in out and 'calismadi' not in out:
    run_cmd(ssh, "tmux kill-session -t quantbot 2>/dev/null; pkill -9 -f 'python.*main.py' 2>/dev/null")
    time.sleep(2)
    print("  Bot durduruldu.")

# 2) Sadece .py dosyalarını yedekle (hızlı)
print("\n" + "=" * 60)
print("AŞAMA 2: Sadece .py dosyaları yedekleniyor (hızlı)...")
out, _ = run_cmd(ssh, f"mkdir -p {REMOTE_QUANTBOT}/backup_pre_modular && cp {REMOTE_QUANTBOT}/*.py {REMOTE_QUANTBOT}/backup_pre_modular/ 2>/dev/null && echo 'Yedek tamam' || echo 'Yedek hatasi'")
print(f"  {out}")

# 3) Swap kontrolü
print("\n" + "=" * 60)
print("AŞAMA 3: Swap kontrolü...")
out, _ = run_cmd(ssh, "swapon --show")
if not out:
    print("  Swap yok, 2GB oluşturuluyor...")
    run_cmd(ssh, "fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile", timeout=30)
    run_cmd(ssh, "grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab")
    out2, _ = run_cmd(ssh, "free -h | grep Swap")
    print(f"  {out2}")
else:
    print(f"  Swap mevcut: {out}")

# 4) Dosyaları yükle
print("\n" + "=" * 60)
print("AŞAMA 4: Yeni modüler kodlar yükleniyor...")
yuklenen = 0
for dosya in DEPLOY_FILES:
    local_path = os.path.join(LOCAL_QUANTBOT, dosya)
    remote_path = f"{REMOTE_QUANTBOT}/{dosya}"
    if not os.path.exists(local_path):
        print(f"  ⚠  {dosya} -> lokal yok, ATLANDI")
        continue
    boyut = os.path.getsize(local_path) / 1024
    try:
        sftp.put(local_path, remote_path)
        print(f"  OK {dosya:<30} -> {boyut:.1f} KB")
        yuklenen += 1
    except Exception as e:
        print(f"  XX {dosya} -> HATA: {e}")

print(f"\n  Toplam {yuklenen} dosya yuklendi.")

# 5) Syntax kontrolü
print("\n" + "=" * 60)
print("ASAMA 5: Syntax kontrolu...")
hata_var = False
for dosya in DEPLOY_FILES:
    local_path = os.path.join(LOCAL_QUANTBOT, dosya)
    if not os.path.exists(local_path):
        continue
    out, err = run_cmd(ssh, f"cd {REMOTE_QUANTBOT} && ./venv/bin/python -m py_compile {dosya} 2>&1")
    if out or err:
        print(f"  XX {dosya}: {out or err}")
        hata_var = True
    else:
        print(f"  OK {dosya}")

if hata_var:
    print("\n  SYNTAX HATASI VAR! Bot baslatilmadi.")
    sftp.close()
    ssh.close()
    exit(1)

# 6) Botu başlat
print("\n" + "=" * 60)
print("ASAMA 6: Bot tmux icinde baslatiliyor...")
out, _ = run_cmd(ssh, f"cd {REMOTE_QUANTBOT} && tmux new-session -d -s quantbot './venv/bin/python main.py' && echo 'Bot baslatildi!'")
print(f"  {out}")

time.sleep(5)

out, _ = run_cmd(ssh, "tmux list-sessions 2>/dev/null")
print(f"  Tmux: {out}")

out, _ = run_cmd(ssh, "ps aux | grep 'python.*main.py' | grep -v grep || echo 'Bot calismadi!'")
if 'main.py' in out:
    print(f"  Bot CALISIYOR!")
else:
    print(f"  UYARI: Bot calismadi gibi gorunuyor: {out}")

# 7) Son durum
print("\n" + "=" * 60)
print("ASAMA 7: Sunucu son durumu")
out, _ = run_cmd(ssh, "free -h")
print(f"{out}")

sftp.close()
ssh.close()

print("\n" + "=" * 60)
print("DEPLOYMENT TAMAMLANDI!")
print("=" * 60)
