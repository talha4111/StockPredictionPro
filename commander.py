import subprocess
import threading
import time
import sys
from collections import deque
import os

try:
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
except ImportError:
    print("❌ 'rich' kütüphanesi eksik! Lütfen 'pip install rich' komutunu çalıştırın.")
    sys.exit(1)

# Ekranda gösterilecek maksimum satır sayısı
MAX_LINES = 30

kripto_log = deque(maxlen=MAX_LINES)
borsa_log = deque(maxlen=MAX_LINES)

kripto_log.append("🚀 Kripto Motoru (main.py) Hazırlanıyor...")
borsa_log.append("🚀 Borsa Motoru (stock_engine.py) Hazırlanıyor...")

def process_baslat(komut, log_queue, name):
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1" # Aninda log akisi icin
    env["PYTHONIOENCODING"] = "utf-8" # Unicode emoji çökmelerini önlemek için
    
    while True: # Yeniden baslatilabilirlik icin dongu
        try:
            process = subprocess.Popen(
                komut, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                encoding='utf-8', 
                bufsize=1, 
                errors='replace',
                env=env
            )
            
            while True:
                satir = process.stdout.readline()
                if not satir and process.poll() is not None:
                    break
                if satir:
                    s_strip = satir.strip()
                    if s_strip:
                        log_queue.append(s_strip)
                    
            rc = process.poll()
            if rc != 0:
                log_queue.append(f"[!] {name} kapandi. Cikis Kodu: {rc}")
                log_queue.append(f"[*] 15 saniye icinde yeniden baslatilmayi deneyecek...")
                time.sleep(15)
            else:
                log_queue.append(f"[-] {name} sonlandi. Tekrar baslatiliyor...")
                time.sleep(5)
                
        except Exception as e:
            log_queue.append(f"[X] Baslatma hatasi ({name}): {e}")
            log_queue.append(f"[*] 15 saniye icinde tekrar denenecek...")
            time.sleep(15)

def ui_olustur():
    # Ekrani dikey (yan yana) ikiye böl
    layout = Layout()
    layout.split_row(
        Layout(name="kripto"),
        Layout(name="borsa")
    )
    
    # Koleksiyondaki satırları metin bloğuna çevir
    kripto_metin = "\n".join(kripto_log)
    borsa_metin = "\n".join(borsa_log)
    
    # Panelleri Rich Kütüphanesi ile süsle
    layout["kripto"].update(Panel(
        Text(kripto_metin, justify="left"), 
        title="[cyan bold]⚡ Kripto Operasyonları ⚡[/]", 
        border_style="cyan",
        padding=(1, 2)
    ))
    
    layout["borsa"].update(Panel(
        Text(borsa_metin, justify="left"), 
        title="[green bold]📈 Borsa Operasyonları 📈[/]", 
        border_style="green",
        padding=(1, 2)
    ))
    
    return layout

if __name__ == "__main__":
    print("Sistem Hazırlanıyor, Komuta Merkezi Yükleniyor...")
    time.sleep(1)

    # İki süreci (Process) ayrı arka plan thread'leri üzerinden canlandırıyoruz
    t_kripto = threading.Thread(target=process_baslat, args=(["python", "main.py"], kripto_log, "Kripto Botu"), daemon=True)
    t_borsa = threading.Thread(target=process_baslat, args=(["python", "stock_engine.py"], borsa_log, "Hisse Botu"), daemon=True)
    
    t_kripto.start()
    t_borsa.start()
    
    # Kaydırılabilir (Scrolling) Panel Modu
    from rich.console import Console
    console = Console()
    
    try:
        while True:
            # Panelleri ekrana bas
            console.print(ui_olustur())
            # Her döngü arasına görsel ayraç ekle
            console.print("\n[bold yellow]--------------------[/]\n")
            time.sleep(10)
    except KeyboardInterrupt:
        print("\n\n🛑 Commander Merkezi Komut ile Kapatıldı.")
        sys.exit(0)
