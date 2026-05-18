import subprocess
import threading
import time
import sys
import os
from collections import deque

# --- Hisse Sinyal Motoru (Canlı Veri) ---
hisse_sinyalleri = []  # stock_value_engine'den gelen sinyallerin listesi
hisse_tarama_durumu = "Bekleniyor..."

def hisse_tarama_thread():
    """Arka planda stock_value_engine'i çalıştırarak sinyalleri günceller."""
    global hisse_sinyalleri, hisse_tarama_durumu
    try:
        from stock_value_engine import tam_tarama_baslat
        while True:
            try:
                hisse_tarama_durumu = "Tarama çalışıyor..."
                sonuclar = tam_tarama_baslat()
                if sonuclar:
                    hisse_sinyalleri = sonuclar[:10]  # Top 10 sinyal
                    hisse_tarama_durumu = f"{len(sonuclar)} sinyal bulundu"
                else:
                    hisse_sinyalleri = []
                    hisse_tarama_durumu = "Sinyal yok"
            except Exception as e:
                hisse_tarama_durumu = f"Hata: {str(e)[:30]}"
            # Her 4 saatte bir tekrar tara (günlük strateji)
            import time as _t
            _t.sleep(14400)
    except ImportError:
        hisse_tarama_durumu = "stock_value_engine.py bulunamadı"

try:
    from rich.live import Live
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, BarColumn, TextColumn
    from rich.console import Console
    from rich.align import Align
    from rich.text import Text
except ImportError:
    print("❌ 'rich' kütüphanesi eksik! 'pip install rich' komutunu çalıştırın.")
    sys.exit(1)

# Gerçek logları tutacağımız kuyruklar
MAX_LOG_LINES = 50
kripto_log = deque(maxlen=MAX_LOG_LINES)
borsa_log = deque(maxlen=MAX_LOG_LINES)
kripto_log.append("[SYSTEM] Kripto Motoru Başlatılıyor (XGBoost 15m)...")
borsa_log.append("[SYSTEM] Borsa Motoru Başlatılıyor (4H EMA İptal Edildi, Hız Odaklı)...")

# --- GLOBAL HAFIZA (Header Interceptor için) ---
kasa_durum = {
    "LIVE_KASA": "0.00", "LIVE_PNL": "+0.00",
    "DEMO_KASA": "0.00", "DEMO_PNL": "+0.00",
    "ISI": 0.0
}

import re as _re

# Alt Süreç (Subprocess) Çalıştırıcısı
def process_baslat(komut, log_queue, name):
    global kasa_durum
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"

    def _para_cikart(metin):
        """Metinden sayısal değeri çıkarır: '$10.5' veya '10.5$' veya '10.5' → '10.5'"""
        eslesme = _re.search(r'[\+\-]?\d+\.?\d*', metin.replace(',', ''))
        return eslesme.group(0) if eslesme else '0.00'

    while True:
        try:
            process = subprocess.Popen(komut, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, encoding='utf-8', bufsize=1, errors='replace', env=env)
            while True:
                satir = process.stdout.readline()
                if not satir and process.poll() is not None: break
                satir_temiz = satir.strip()
                if not satir_temiz: continue

                # --- LOG INTERCEPTOR MOTORU (Regex Tabanlı) ---
                try:
                    if '[DEMO]' in satir_temiz and 'Kasa:' in satir_temiz:
                        parcalar = satir_temiz.split('|')
                        for p in parcalar:
                            if 'Kasa:' in p:
                                kasa_kisim = p.split('Kasa:')[-1]
                                kasa_durum['DEMO_KASA'] = _para_cikart(kasa_kisim)
                            elif 'K/Z:' in p or 'PNL:' in p:
                                pnl_kisim = p.split(':')[-1]
                                kasa_durum['DEMO_PNL'] = _para_cikart(pnl_kisim)
                        continue

                    elif '[LIVE]' in satir_temiz and 'Kasa:' in satir_temiz:
                        parcalar = satir_temiz.split('|')
                        for p in parcalar:
                            if 'Kasa:' in p:
                                kasa_kisim = p.split('Kasa:')[-1]
                                kasa_durum['LIVE_KASA'] = _para_cikart(kasa_kisim)
                            elif 'K/Z:' in p or 'PNL:' in p:
                                pnl_kisim = p.split('K/Z:')[-1] if 'K/Z:' in p else p.split('PNL:')[-1]
                                # + veya - işaretini koru
                                pnl_val = _re.search(r'[\+\-]?\d+\.?\d*', pnl_kisim)
                                kasa_durum['LIVE_PNL'] = pnl_val.group(0) if pnl_val else '+0.00'
                        continue

                    elif 'Portf' in satir_temiz and '%' in satir_temiz:
                        try:
                            isi_str = _re.search(r'%([\d\.]+)', satir_temiz)
                            if isi_str: kasa_durum['ISI'] = float(isi_str.group(1))
                        except: pass
                        continue
                except Exception:
                    pass

                log_queue.append(satir_temiz)

            time.sleep(5)
        except Exception as e:
            log_queue.append(f"[X] {name} Çöktü: {e}")
            time.sleep(5)

# --- UI BİLEŞENLERİ ---

def draw_header() -> Panel:
    isi = kasa_durum['ISI']
    live_kasa = kasa_durum['LIVE_KASA']
    live_pnl  = kasa_durum['LIVE_PNL']
    demo_kasa = kasa_durum['DEMO_KASA']
    demo_pnl  = kasa_durum['DEMO_PNL']

    # PNL renk mantığı
    live_pnl_renk = "bright_green" if str(live_pnl).startswith('+') else "bright_red"
    demo_pnl_renk = "bright_green" if str(demo_pnl).startswith('+') else "bright_red"

    # Portföy ısısı renk mantığı
    if isi < 60:
        isi_renk = "bright_green"
        isi_ikon = "🟢"
    elif isi < 75:
        isi_renk = "bright_yellow"
        isi_ikon = "🟡"
    else:
        isi_renk = "blink bright_red"
        isi_ikon = "🔴"

    # Üst satır: LIVE (sol) | Başlık (orta) | DEMO (sağ)
    ust = Table.grid(expand=True)
    ust.add_column(justify="left",  ratio=1)
    ust.add_column(justify="center", ratio=1)
    ust.add_column(justify="right", ratio=1)
    ust.add_row(
        f"[bold bright_white]💰 LIVE Kasa:[/] [bright_cyan]${live_kasa}[/]  [bold bright_white]K/Z:[/] [{live_pnl_renk}]{live_pnl}$[/]",
        f"[bold bright_yellow]⚡ QUANT COMMAND CENTER V9.2 ⚡[/]",
        f"[bold bright_white]🎮 DEMO Kasa:[/] [bright_cyan]${demo_kasa}[/]  [bold bright_white]K/Z:[/] [{demo_pnl_renk}]{demo_pnl}$[/]",
    )

    # Alt satır: Portföy ısısı ortada
    alt = Table.grid(expand=True)
    alt.add_column(justify="center")
    alt.add_row(f"[{isi_renk}]{isi_ikon} Portföy Isısı: %{isi:.1f} / %80 LİMİT[/]")

    # İkisini birleştir
    birlesik = Table.grid(expand=True)
    birlesik.add_column()
    birlesik.add_row(ust)
    birlesik.add_row(alt)

    return Panel(birlesik, border_style="bright_blue")

def draw_crypto_table() -> Panel:
    table = Table(expand=True, border_style="bright_blue", show_lines=True)
    table.add_column("Sıra", justify="center", width=4)
    table.add_column("Parite", style="bold bright_white")
    table.add_column("Yön", justify="center")
    table.add_column("AI Güven (XGBoost)", justify="left", ratio=2)
    table.add_column("Bütçe (Kelly)", justify="center", style="bright_white")
    table.add_column("Volatilite", justify="right", style="bright_white")
    table.add_column("Net P&L", justify="right", style="bold")

    def ai_bar(skor):
        renk = "bright_green" if skor >= 75 else ("bright_yellow" if skor >= 55 else "bright_red")
        dolu = int(skor / 10)
        bos = 10 - dolu
        return f"[{renk}]{'█' * dolu}[/][white]{'░' * bos}[/] %{skor}"

    table.add_row("1", "BTC/USDT", "[bold bright_green]LONG[/]", ai_bar(88), "%60 (10x)", "245.5$", "[bright_green]+$12.50[/]")
    table.add_row("2", "SOL/USDT", "[bold bright_red]SHORT[/]", ai_bar(62), "%15 (5x)", "1.24$", "[bright_red]-$1.30[/]")
    table.add_row("3", "ETH/USDT", "[bold bright_green]LONG[/]", ai_bar(71), "%40 (10x)", "45.2$", "[bright_green]+$4.20[/]")
    table.add_row("4", "AVAX/USDT", "[bold white]NÖTR[/]", ai_bar(48), "-", "0.85$", "[white]0.00$[/]")

    return Panel(table, title="[bold bright_cyan]🛸 KRİPTO OPERASYONLARI (15M)[/]")

def draw_stock_table() -> Panel:
    table = Table(expand=True, border_style="bright_blue", show_lines=True)
    table.add_column("Hisse", style="bold bright_white", width=8)
    table.add_column("Yön", justify="center", width=6)
    table.add_column("Skor", justify="left", ratio=2)
    table.add_column("RSI", justify="center", width=5)
    table.add_column("Sektör", justify="center", style="bright_white", width=14)
    table.add_column("TP / SL", justify="right", style="bold", width=18)

    def ai_bar(skor):
        renk = "bright_green" if skor >= 80 else ("bright_yellow" if skor >= 70 else "bright_red")
        dolu = int(skor / 10)
        bos = 10 - dolu
        return f"[{renk}]{'█' * dolu}[/][white]{'░' * bos}[/] %{skor:.0f}"

    if hisse_sinyalleri:
        for s in hisse_sinyalleri[:5]:  # UI'da max 5 satır
            gc_icon = "⭐" if s.get('golden_cross') else ""
            table.add_row(
                f"{s['sembol']}{gc_icon}",
                "[bold bright_green]LONG[/]",
                ai_bar(s['ai_skor']),
                f"{s['rsi']:.0f}",
                s.get('sektor', 'N/A')[:14],
                f"[bright_green]${s['tp']:.0f}[/] / [bright_red]${s['sl']:.0f}[/]"
            )
    else:
        table.add_row("—", "—", f"[white]{hisse_tarama_durumu}[/]", "—", "—", "—")

    return Panel(table, title=f"[bold bright_green]📈 BORSA SİNYALLERİ (Danışman)[/]")

def draw_logs() -> Panel:
    grid = Table.grid(expand=True)
    grid.add_column("Kripto Logları", justify="left", ratio=1)
    grid.add_column("Borsa Logları", justify="left", ratio=1)
    
    k_text = "\n".join(list(kripto_log))
    b_text = "\n".join(list(borsa_log))
    
    # "dim" (soluk) efektler kaldırıldı, "bright_" renkler eklendi
    grid.add_row(
        Panel(Text(k_text, style="bright_white"), border_style="bright_cyan"),
        Panel(Text(b_text, style="bright_yellow"), border_style="bright_green")
    )
    return Panel(grid, title="[bold bright_white]📡 CANLI MOTOR AKIŞI (STDOUT)[/]", border_style="bright_blue")

def make_layout() -> Layout:
    layout = Layout()
    layout.split(
        Layout(name="header", size=5),  # Çift satır header için genişletildi
        Layout(name="tables", size=11),
        Layout(name="logs", ratio=1)
    )
    layout["tables"].split_row(
        Layout(name="kripto"),
        Layout(name="borsa")
    )
    return layout
if __name__ == "__main__":
    print("🚀 Komuta Merkezi Yükleniyor...")
    
    # Threadleri başlat
    threading.Thread(target=process_baslat, args=(["python", "main.py"], kripto_log, "Kripto Botu"), daemon=True).start()
    threading.Thread(target=hisse_tarama_thread, daemon=True, name="HisseTarama").start()
    borsa_log.append("[SYSTEM] Hisse Değer Motoru başlatıldı (Danışman Modu)...")
    
    layout = make_layout()
    
    os.system('cls' if os.name == 'nt' else 'clear')
    with Live(layout, refresh_per_second=2, screen=True):
        while True:
            # Her 0.5 saniyede bir ekranı UI verileriyle tazele
            layout["header"].update(draw_header())
            layout["kripto"].update(draw_crypto_table())
            layout["borsa"].update(draw_stock_table())
            layout["logs"].update(draw_logs())
            time.sleep(0.5)