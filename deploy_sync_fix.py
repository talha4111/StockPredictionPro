import time
from remote_config import connect_ssh

LOCAL = r"c:\Users\Talha\Desktop\StockPredictionPro\QuantBot"
REMOTE = "/root/QuantBot"

ssh = connect_ssh(timeout=15)
sftp = ssh.open_sftp()

def run(cmd, t=30):
    si, so, se = ssh.exec_command(cmd, timeout=t)
    return so.read().decode('utf-8', errors='replace').strip()

# 1) Eski botu durdur
print("1) Bot durduruluyor...")
run("tmux kill-session -t quantbot 2>/dev/null")
run("pkill -9 -f 'python.*main.py' 2>/dev/null")
time.sleep(2)
print(f"   {run('ps aux | grep python.*main.py | grep -v grep || echo Temiz')}")

# 2) Sadece degisen dosyalari yukle
print("2) Dosyalar yukleniyor...")
for f in ["main.py", "position_tracker.py"]:
    sftp.put(f"{LOCAL}\\{f}", f"{REMOTE}/{f}")
    print(f"   OK {f}")

# 3) Syntax kontrol
print("3) Syntax kontrol...")
for f in ["main.py", "position_tracker.py"]:
    out = run(f"cd {REMOTE} && ./venv/bin/python -m py_compile {f} 2>&1")
    print(f"   {'OK' if not out else 'HATA: '+out} {f}")

# 4) Botu baslat
print("4) Bot baslatiliyor...")
run(f"cd {REMOTE} && tmux new-session -d -s quantbot './venv/bin/python main.py'")
time.sleep(5)

out = run("ps aux | grep 'python.*main.py' | grep -v grep")
if 'main.py' in out:
    print("   BOT CALISIYOR!")
else:
    print("   UYARI: Bot calismadi!")

# 5) Ilk loglari goster
print("\n5) Ilk loglar:")
out = run("tmux capture-pane -t quantbot -p -S -20 2>/dev/null")
for line in out.split('\n'):
    clean = line.encode('ascii', errors='replace').decode()
    print(f"   {clean}")

sftp.close()
ssh.close()
print("\nDeploy tamamlandi!")
