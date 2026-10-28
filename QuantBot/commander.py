import subprocess
import threading
import time
import sys
import os
import json
from pathlib import Path
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

def _status_dosyasi():
    base = Path(__file__).resolve().parent
    adaylar = [base / "runtime_status.json", base / "QuantBot" / "runtime_status.json"]
    for aday in adaylar:
        if aday.exists():
            return aday
    return adaylar[0]

def runtime_status_oku():
    try:
        with _status_dosyasi().open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _kisalt(deger, limit=46):
    metin = str(deger or "—")
    return metin if len(metin) <= limit else metin[:limit - 1] + "…"

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
    status = runtime_status_oku()
    isi = kasa_durum['ISI']
    live_kasa = kasa_durum['LIVE_KASA']
    live_pnl  = kasa_durum['LIVE_PNL']
    demo_kasa = kasa_durum['DEMO_KASA']
    demo_pnl  = kasa_durum['DEMO_PNL']
    try:
        if status.get("demo_kasa") is not None:
            demo_kasa = f"{float(status.get('demo_kasa')):.2f}"
        if status.get("demo_pnl") is not None:
            demo_pnl = f"{float(status.get('demo_pnl')):+.2f}"
        if status.get("live_kasa") is not None:
            live_kasa = f"{float(status.get('live_kasa')):.2f}"
        perf = status.get("performans", {}) or {}
        if perf.get("live_pnl") is not None:
            live_pnl = f"{float(perf.get('live_pnl')):+.2f}"
    except Exception:
        pass

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
    status = runtime_status_oku()
    table = Table(expand=True, border_style="bright_blue", show_lines=False)
    table.add_column("Alan", style="bold bright_cyan", width=14)
    table.add_column("Durum", style="bright_white")

    faz = status.get("faz", "bekleniyor")
    bot_durumu = status.get("bot_durumu", "durum dosyası bekleniyor")
    live = "AKTİF" if status.get("live_mod") else "KAPALI"
    tetik = "AÇIK" if status.get("live_tetik") else "KAPALI"
    table.add_row("Faz", f"[bold]{_kisalt(faz, 18)}[/] - {_kisalt(bot_durumu, 44)}")
    table.add_row("LIVE", f"{live} | Tetik: {tetik} | Güncelleme: {_kisalt(status.get('guncelleme_zamani'), 22)}")
    demo_profil = status.get("demo_profil", "LIVE_SHADOW")
    demo_shadow = "ON" if status.get("demo_live_shadow", True) else "OFF"
    short_kapi = "ON" if status.get("short_islem_aktif", False) else "OFF"
    table.add_row("Demo Profil", f"{demo_profil} | Shadow: {demo_shadow} | Short: {short_kapi}")
    hedge = status.get("hedge_sniper", {}) or {}
    if hedge:
        hedge_durum = "ON" if hedge.get("aktif") else "OFF"
        table.add_row(
            "Hedge Mode",
            f"{hedge_durum} | RR>={hedge.get('min_rr', '-')} | Guven>={hedge.get('min_guven', '-')} | MaxPoz: {hedge.get('max_pozisyon', '-')}",
        )

    dongu = status.get("son_dongu", {}) or {}
    dongu_metni = (
        f"Aday: {dongu.get('aday_sayisi', '—')} | "
        f"Tahmin: {dongu.get('tahmin_sayisi', '—')} | "
        f"Sinyal: {dongu.get('sinyal_sayisi', '—')} | "
        f"Gönderilen: {dongu.get('gonderilen_sinyal_sayisi', '—')}"
    )
    table.add_row("Son Döngü", dongu_metni)

    darbogaz = status.get("sinyal_darbogaz", {}) or {}
    if darbogaz:
        kategoriler = darbogaz.get("ret_kategorileri", {}) or {}
        ilk_kategori = next(iter(kategoriler.items()), ("—", 0))
        darbogaz_metni = (
            f"Oran: %{darbogaz.get('sinyal_orani', 0)} | "
            f"Ret: {darbogaz.get('ret_sayisi', 0)} | "
            f"En çok: {_kisalt(ilk_kategori[0], 18)} ({ilk_kategori[1]})"
        )
        table.add_row("Darboğaz", darbogaz_metni)

    demo_journal = status.get("demo_journal", {}) or {}
    if demo_journal:
        try:
            net_pnl = float(demo_journal.get("net_pnl", 0.0))
        except Exception:
            net_pnl = 0.0
        pf = demo_journal.get("profit_factor")
        try:
            pf_metni = "-" if pf is None else f"{float(pf):.2f}"
        except Exception:
            pf_metni = "-"
        demo_metin = (
            f"Sinyal: {demo_journal.get('sinyal', 0)} | "
            f"Dispatch Ret: {demo_journal.get('dispatch_ret', 0)} | "
            f"A/K: {demo_journal.get('acilis', 0)}/{demo_journal.get('kapanis', 0)} | "
            f"Net: {net_pnl:+.2f}$ | PF: {pf_metni}"
        )
        table.add_row("Demo Gunluk", demo_metin)

    demo_muhasebe = status.get("demo_muhasebe", {}) or {}
    if demo_muhasebe:
        try:
            mtm = float(demo_muhasebe.get("net_pnl_mtm", 0.0))
            realized = float(demo_muhasebe.get("realized_net", 0.0))
            open_delta = float(demo_muhasebe.get("open_pnl_delta", 0.0))
        except Exception:
            mtm = realized = open_delta = 0.0
        table.add_row(
            "Muhasebe",
            f"Net: {mtm:+.2f}$ | Realized: {realized:+.2f}$ | Acik: {open_delta:+.2f}$ | Kaynak: Binance",
        )

    demo_analiz = status.get("demo_analiz", {}) or {}
    if demo_analiz:
        perf = demo_analiz.get("degerlendirme_performansi", {}) or demo_analiz.get("performans", {}) or {}
        outlier = demo_analiz.get("outlier_analizi", {}) or {}
        try:
            expectancy = float(perf.get("expectancy", 0.0))
        except Exception:
            expectancy = 0.0
        try:
            pf = float(perf.get("profit_factor", 0.0))
        except Exception:
            pf = 0.0
        live_metni = "ADAY" if demo_analiz.get("live_adayi") else "BEKLE"
        analiz_metin = (
            f"{_kisalt(demo_analiz.get('karar'), 22)} | "
            f"Islem: {perf.get('toplam_islem', 0)} | "
            f"E: {expectancy:+.3f} | PF: {pf:.2f} | "
            f"Out: {outlier.get('outlier_sayisi', 0)} | Live: {live_metni}"
        )
        table.add_row("Demo Analiz", analiz_metin)

        karne = demo_analiz.get("model_kalite_karnesi", {}) or {}
        if karne:
            temiz_bolgeler = karne.get("temiz_bolge_metrikleri", {}) or {}

            def _bolge_ozet(ad):
                metrik = temiz_bolgeler.get(ad, {}) or {}
                if not metrik:
                    return f"{ad[:1].upper()}: -"
                try:
                    bolge_pf = float(metrik.get("profit_factor", 0.0))
                except Exception:
                    bolge_pf = 0.0
                try:
                    bolge_e = float(metrik.get("expectancy", 0.0))
                except Exception:
                    bolge_e = 0.0
                return f"{ad[:1].upper()}: {metrik.get('toplam_islem', 0)} PF {bolge_pf:.2f} E {bolge_e:+.2f}"

            karne_metin = (
                f"Etiket: {karne.get('etiketli_kapanis', 0)}/{karne.get('kapanis_sayisi', 0)} | "
                f"{_bolge_ozet('sari')} | {_bolge_ozet('yesil')}"
            )
            table.add_row("Model Karne", karne_metin)

    son_ret = status.get("son_ret", {}) or {}
    table.add_row("Son Ret", f"{son_ret.get('coin', '—')} | {_kisalt(son_ret.get('neden'), 52)}")

    risk = status.get("son_risk_ret", {}) or {}
    table.add_row("Risk Kapısı", f"{risk.get('sembol', '—')} | {_kisalt(risk.get('neden'), 52)}")

    son_islem = status.get("son_islem", {}) or {}
    islem_metni = f"{son_islem.get('hesap', '—')} {son_islem.get('sembol', '—')} {_kisalt(son_islem.get('yon'), 18)}"
    table.add_row("Son İşlem", islem_metni)

    hata = status.get("son_hata", {}) or {}
    table.add_row("Son Hata", f"{hata.get('modul', '—')} | {_kisalt(hata.get('mesaj'), 52)}")

    ret_ozeti = status.get("ret_ozeti", {}) or {}
    if ret_ozeti:
        ilkler = sorted(ret_ozeti.items(), key=lambda x: x[1], reverse=True)[:2]
        table.add_row("Ret Özeti", " | ".join(f"{_kisalt(k, 22)}: {v}" for k, v in ilkler))

    return Panel(table, title="[bold bright_cyan]🛸 KRİPTO OPERASYON DURUMU[/]")

def draw_stock_table() -> Panel:
    table = Table(expand=True, border_style="bright_blue", show_lines=True)
    table.add_column("Hisse", style="bold bright_white", width=8)
    table.add_column("Yön", justify="center", width=6)
    table.add_column("Kural Skoru", justify="left", ratio=2)
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
            skor = s.get('kural_skoru', s.get('teknik_skor', s.get('ai_skor', 0)))
            table.add_row(
                f"{s['sembol']}{gc_icon}",
                "[bold bright_green]LONG[/]",
                ai_bar(skor),
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
    threading.Thread(target=process_baslat, args=([sys.executable, "main.py"], kripto_log, "Kripto Botu"), daemon=True).start()
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
