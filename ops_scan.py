from __future__ import annotations

import ast
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class Report:
    def __init__(self) -> None:
        self.ok_count = 0
        self.warn_count = 0
        self.fail_count = 0

    def section(self, title: str) -> None:
        print(f"\n{title}")
        print("-" * len(title))

    def ok(self, name: str, detail: str = "") -> None:
        self.ok_count += 1
        self._line("OK", name, detail)

    def warn(self, name: str, detail: str = "") -> None:
        self.warn_count += 1
        self._line("WARN", name, detail)

    def fail(self, name: str, detail: str = "") -> None:
        self.fail_count += 1
        self._line("FAIL", name, detail)

    @staticmethod
    def _line(level: str, name: str, detail: str = "") -> None:
        suffix = f" - {detail}" if detail else ""
        print(f"[{level:<4}] {name}{suffix}")


def proje_yollarini_bul() -> tuple[Path, Path]:
    script_dir = Path(__file__).resolve().parent
    if (script_dir / "QuantBot" / "main.py").exists():
        return script_dir, script_dir / "QuantBot"
    if script_dir.name.lower() == "quantbot" and (script_dir / "main.py").exists():
        return script_dir.parent, script_dir
    return script_dir, script_dir / "QuantBot"


ROOT, QUANTBOT = proje_yollarini_bul()


def oku(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def syntax_kontrol(report: Report, path: Path) -> None:
    if not path.exists():
        report.warn("Syntax kontrol", f"{path.name} bulunamadi")
        return
    try:
        compile(oku(path), str(path), "exec")
    except SyntaxError as exc:
        report.fail("Syntax kontrol", f"{path.relative_to(ROOT)}: {exc}")
    except UnicodeDecodeError as exc:
        report.fail("Syntax kontrol", f"{path.relative_to(ROOT)} okunamadi: {exc}")
    else:
        report.ok("Syntax kontrol", str(path.relative_to(ROOT)))


def ast_oku(report: Report, path: Path) -> tuple[ast.Module | None, dict[str, object]]:
    if not path.exists():
        report.fail("Ana bot dosyasi", f"{path} bulunamadi")
        return None, {}
    try:
        tree = ast.parse(oku(path), filename=str(path))
    except SyntaxError as exc:
        report.fail("Ana bot dosyasi AST", str(exc))
        return None, {}

    sabitler: dict[str, object] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        sabitler[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    return tree, sabitler


def bool_kapali_kontrol(report: Report, sabitler: dict[str, object], ad: str) -> None:
    if ad not in sabitler:
        report.fail("LIVE kapali kural", f"{ad} sabiti bulunamadi")
    elif sabitler[ad] is False:
        report.ok("LIVE kapali kural", f"{ad}=False")
    else:
        report.fail("LIVE kapali kural", f"{ad} su an {sabitler[ad]!r}")


def sayisal_ust_limit(report: Report, sabitler: dict[str, object], ad: str, limit: float) -> None:
    deger = sabitler.get(ad)
    if not isinstance(deger, (int, float)):
        report.fail("Risk limiti", f"{ad} sayisal degil veya yok")
        return
    if float(deger) <= limit:
        report.ok("Risk limiti", f"{ad}={float(deger):.4f} <= {limit:.4f}")
    else:
        report.fail("Risk limiti", f"{ad}={float(deger):.4f} > {limit:.4f}")


def fonksiyon_kontrol(report: Report, tree: ast.Module | None, gerekli: set[str]) -> None:
    if tree is None:
        return
    bulunan = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
    for ad in sorted(gerekli):
        if ad in bulunan:
            report.ok("Kritik fonksiyon", ad)
        else:
            report.fail("Kritik fonksiyon", f"{ad} eksik")


def metin_kontrol(report: Report, path: Path, kontroller: dict[str, str], fail_on_missing: bool = True) -> None:
    if not path.exists():
        report.fail("Metin kontrol", f"{path} bulunamadi")
        return
    metin = oku(path)
    for ad, parca in kontroller.items():
        if parca in metin:
            report.ok(ad)
        elif fail_on_missing:
            report.fail(ad, f"'{parca}' bulunamadi")
        else:
            report.warn(ad, f"'{parca}' bulunamadi")


def metin_kontrol_coklu(report: Report, paths: list[Path], kontroller: dict[str, str], fail_on_missing: bool = True) -> None:
    metinler: list[str] = []
    mevcut_paths: list[Path] = []
    for path in paths:
        if path.exists():
            mevcut_paths.append(path)
            metinler.append(oku(path))
    if not metinler:
        report.fail("Metin kontrol", "kontrol edilecek modul bulunamadi")
        return

    tum_metin = "\n".join(metinler)
    modul_listesi = ", ".join(str(path.relative_to(ROOT)) for path in mevcut_paths)
    for ad, parca in kontroller.items():
        if parca in tum_metin:
            report.ok(ad, modul_listesi)
        elif fail_on_missing:
            report.fail(ad, f"'{parca}' bulunamadi")
        else:
            report.warn(ad, f"'{parca}' bulunamadi")


def tehlikeli_true_kontrol(report: Report, path: Path) -> None:
    if not path.exists():
        return
    metin = oku(path)
    desen = re.compile(r"^\s*(LIVE_MOD_AKTIF|ALIM_SATIM_TETIGI_ACIK|PING_MODU)\s*=\s*True\b", re.MULTILINE)
    eslesmeler = [f"{m.group(1)} True" for m in desen.finditer(metin)]
    if eslesmeler:
        report.fail("LIVE tetik taramasi", ", ".join(eslesmeler))
    else:
        report.ok("LIVE tetik taramasi", f"{path.relative_to(ROOT)} icinde acik tetik yok")


def json_oku(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def demo_kasa_kontrol(report: Report) -> None:
    adaylar = [QUANTBOT / "sanal_kasa_kripto.json", ROOT / "sanal_kasa_kripto.json"]
    for path in adaylar:
        if path.exists():
            veri = json_oku(path)
            if not isinstance(veri, dict):
                report.warn("Demo kasa", f"{path.relative_to(ROOT)} okunamadi")
                return
            bakiye = veri.get("bakiye")
            if isinstance(bakiye, (int, float)):
                report.ok("Demo kasa", f"{path.relative_to(ROOT)} bakiye={float(bakiye):.2f} USDT")
            else:
                report.warn("Demo kasa", f"{path.relative_to(ROOT)} icinde bakiye yok")
            return
    report.warn("Demo kasa", "sanal_kasa_kripto.json bulunamadi")


def runtime_status_kontrol(report: Report) -> None:
    path = QUANTBOT / "runtime_status.json"
    if not path.exists():
        report.warn("Runtime status", "Bot calismadiysa normal; dosya henuz olusmamis")
        return
    veri = json_oku(path)
    if not isinstance(veri, dict):
        report.warn("Runtime status", "JSON okunamadi")
        return
    if veri.get("live_mod") is True or veri.get("live_tetik") is True:
        report.fail("Runtime status", "Canli mod/tetik acik gorunuyor")
    else:
        faz = veri.get("faz", "bilinmiyor")
        durum = veri.get("bot_durumu", "durum yok")
        report.ok("Runtime status", f"faz={faz}, durum={durum}")

    for alan in ("son_ret", "son_risk_ret", "son_hata"):
        deger = veri.get(alan)
        if deger:
            report.warn(f"Runtime {alan}", str(deger)[:180])


def db_kontrol(report: Report) -> None:
    adaylar = [QUANTBOT / "trading_bot.db", ROOT / "trading_bot.db"]
    db_path = next((path for path in adaylar if path.exists()), None)
    if db_path is None:
        report.warn("Trade DB", "trading_bot.db bulunamadi; demo calisinca olusabilir")
        return
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='closed_trades'")
        if cur.fetchone() is None:
            report.warn("Trade DB", f"{db_path.relative_to(ROOT)} icinde closed_trades tablosu yok")
            return
        cur.execute("PRAGMA table_info(closed_trades)")
        kolonlar = {row[1] for row in cur.fetchall()}
        cur.execute("SELECT COUNT(*) FROM closed_trades")
        toplam = int(cur.fetchone()[0])
        if "Net_PNL_USDT" in kolonlar:
            cur.execute("SELECT COUNT(*) FROM closed_trades WHERE Net_PNL_USDT > 0")
            kazanan = int(cur.fetchone()[0])
            win_rate = (kazanan / toplam * 100.0) if toplam else 0.0
            report.ok("Trade DB", f"{toplam} islem, win_rate={win_rate:.1f}%")
        else:
            report.ok("Trade DB", f"{toplam} islem, PNL kolonu yok")
    except sqlite3.Error as exc:
        report.warn("Trade DB", f"okunamadi: {exc}")
    finally:
        try:
            conn.close()
        except Exception:
            pass


def surec_kontrol(report: Report) -> None:
    if os.name != "nt":
        report.warn("Python surecleri", "Bu kontrol sadece Windows tasklist ile yapiliyor")
        return
    try:
        sonuc = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        adet = sonuc.stdout.lower().count("python.exe")
        report.ok("Python surecleri", f"{adet} adet python.exe gorundu")
    except Exception as exc:
        report.warn("Python surecleri", f"kontrol edilemedi: {exc}")


def gizli_bilgi_taramasi(report: Report) -> None:
    desenler = [
        ("Sabit uzak sunucu IP", re.compile(r"164[.]92")),
        ("Sabit uzak sunucu parola", re.compile("tara" + "ntula", re.IGNORECASE)),
        ("Legacy IP sabiti", re.compile(r"(?m)^\s*IP\s*=")),
        ("Legacy USER sabiti", re.compile(r"(?m)^\s*USER\s*=")),
        ("Legacy PASS sabiti", re.compile(r"(?m)^\s*PASS\s*=")),
    ]
    sorunlar: list[str] = []
    atlanacak_dizinler = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".vs",
        ".venv",
        "__init__.py",
        "__pycache__",
        "build",
        "dist",
        "env",
        "node_modules",
        "venv",
    }
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [ad for ad in dirnames if ad not in atlanacak_dizinler]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            if not path.is_file():
                continue
            try:
                metin = oku(path)
            except (UnicodeDecodeError, OSError):
                continue
            for ad, desen in desenler:
                if desen.search(metin):
                    sorunlar.append(f"{path.relative_to(ROOT)}: {ad}")
    if sorunlar:
        report.fail("Gizli bilgi taramasi", "; ".join(sorunlar[:8]))
    else:
        report.ok("Gizli bilgi taramasi", "Python dosyalarinda bilinen sabit sir yok")


def main() -> int:
    report = Report()

    print("=" * 72)
    print("OPERASYONEL SAGLIK TARAMASI - DEMO ONCELIKLI")
    print("=" * 72)
    print(f"Proje: {ROOT}")
    print(f"Bot:   {QUANTBOT}")

    report.section("1. Dosya ve syntax")
    for path in [
        ROOT / "main.py",
        ROOT / "commander.py",
        ROOT / "remote_config.py",
        ROOT / "ops_scan.py",
        QUANTBOT / "main.py",
        QUANTBOT / "config.py",
        QUANTBOT / "risk_manager.py",
        QUANTBOT / "signal_engine.py",
        QUANTBOT / "scanner_loop.py",
        QUANTBOT / "order_engine.py",
        QUANTBOT / "position_tracker.py",
        QUANTBOT / "commander.py",
        QUANTBOT / "ai_core.py",
        QUANTBOT / "runtime_status.py",
        QUANTBOT / "demo_trade_journal.py",
        QUANTBOT / "demo_performance_analyzer.py",
        QUANTBOT / "performance_metrics.py",
        QUANTBOT / "optimizer.py",
        QUANTBOT / "ops_scan.py",
    ]:
        syntax_kontrol(report, path)

    report.section("2. LIVE kapali / demo oncelikli kural")
    config_tree, config_sabitler = ast_oku(report, QUANTBOT / "config.py")
    main_tree, main_sabitler = ast_oku(report, QUANTBOT / "main.py")
    sabitler = {**config_sabitler, **main_sabitler}
    for ad in ("LIVE_MOD_AKTIF", "ALIM_SATIM_TETIGI_ACIK", "PING_MODU"):
        bool_kapali_kontrol(report, sabitler, ad)
    tehlikeli_true_kontrol(report, QUANTBOT / "config.py")
    tehlikeli_true_kontrol(report, QUANTBOT / "main.py")
    tehlikeli_true_kontrol(report, ROOT / "main.py")

    report.section("3. Risk ve sinyal kalitesi")
    risk_tree, _ = ast_oku(report, QUANTBOT / "risk_manager.py")
    sayisal_ust_limit(report, sabitler, "MAX_LIVE_MARGIN_YUZDESI", 0.10)
    sayisal_ust_limit(report, sabitler, "MAX_DEMO_MARGIN_YUZDESI", 0.07)
    sayisal_ust_limit(report, sabitler, "MAX_POZISYON_ZARAR_YUZDESI", 0.02)
    sayisal_ust_limit(report, sabitler, "MAX_ATR_FIYAT_YUZDESI", 12.0)
    fonksiyon_kontrol(
        report,
        risk_tree,
        {"_risk_kapisi_kontrolu", "_veri_kalitesi_kontrol", "_ret_raporu"},
    )
    metin_kontrol_coklu(
        report,
        [
            QUANTBOT / "config.py",
            QUANTBOT / "risk_manager.py",
            QUANTBOT / "signal_engine.py",
            QUANTBOT / "scanner_loop.py",
            QUANTBOT / "order_engine.py",
            QUANTBOT / "position_tracker.py",
            QUANTBOT / "db_logger.py",
            QUANTBOT / "main.py",
        ],
        {
            "Runtime status baglantisi": "status_yaz",
            "Demo journal rapor baglantisi": "demo_rapor_kaydet",
            "Demo journal acilis baglantisi": "demo_acilis_kaydet",
            "Demo journal kapanis baglantisi": "demo_kapanis_kaydet",
            "Demo analiz baglantisi": "demo_performans_analiz_uret",
            "Demo profil secimi": "DEMO_CALISMA_PROFILI",
            "Demo live-shadow bayragi": "DEMO_LIVE_SHADOW_AKTIF",
            "SHORT guvenlik kapisi": "SHORT_ISLEM_AKTIF",
            "Demo shadow short kapisi": "DEMO_SHADOW_SHORT_KAPALI",
            "Planlanan RR kaydi": "Planlanan_RR",
            "Scout hacim ayari": "MIN_SCOUT_QUOTE_VOLUME_USDT",
            "Scout aday limiti": "MAX_SCOUT_COIN_SAYISI",
            "Tek dongu tani modu": "TEK_DONGU_TANI_MODU",
            "Tani coin limiti": "TANI_MAX_COIN_SAYISI",
            "Model kalite kapisi": "MODEL_KALITE_KAPISI_AKTIF",
            "Model kalite esigi": "MIN_MODEL_WALK_FORWARD_SKORU",
            "Model kalite sari esik": "MODEL_KALITE_SARI_ESIK",
            "Model kalite sari margin": "MODEL_KALITE_SARI_MARGIN_CARPANI",
            "Model kalite ret": "MODEL_KALITE",
            "Sinyal darbogaz ozeti": "_sinyal_darbogaz_ozeti",
            "Volatilite anomali filtresi": "Volatilite anomalisi ATR/Fiyat",
            "Risk ret statusu": "son_risk_ret",
            "Ret ozeti statusu": "ret_ozeti",
            "LIVE islem kilidi": "LIVE_ISLEM_KILIDI",
            "Stop sonrasi reduceOnly koruma": "reduceOnly",
        },
    )
    metin_kontrol(
        report,
        QUANTBOT / "demo_trade_journal.py",
        {
            "Demo journal olay yazimi": "olay_yaz",
            "Demo journal rapor kaydi": "rapor_kaydet",
            "Demo journal ozet": "ozet_hesapla",
            "Demo journal dispatch ret": "dispatch_ret",
            "Demo journal short alani": "short_islem_aktif",
            "Demo journal kapanis sebebi": "kapanis_sebebi",
            "Demo journal ret kategorisi": "ret_kategori",
            "Demo journal guven farki": "guven_farki",
            "Demo journal model kalite": "model_walk_forward_skoru",
            "Demo journal model kalite bolgesi": "model_kalite_bolgesi",
            "Demo journal kalite kapanis aktarimi": "model_kalite_sari_margin_carpani",
        },
    )
    metin_kontrol(
        report,
        QUANTBOT / "demo_performance_analyzer.py",
        {
            "Demo analiz uretimi": "analiz_uret",
            "Live aday kapilari": "_live_kapilari",
            "Analiz tavsiyeleri": "_tavsiyeler",
            "Eski CSV fallback": "_csv_kapanislari_oku",
            "Outlier analizi": "_outlier_analizi",
            "Degerlendirme performansi": "degerlendirme_performansi",
            "Temiz yon metrikleri": "temiz_yon_metrikleri",
            "Problemli coin metrikleri": "problemli_coin_metrikleri",
            "Ret kategori sayaci": "ret_kategori_sayaci",
            "Tum ret kategori sayaci": "ret_kategori_tum_sayaci",
            "Model kalite sayaci": "model_kalite_sayaci",
            "Model kalite karnesi": "model_kalite_karnesi",
            "Temiz model kalite metrikleri": "temiz_bolge_metrikleri",
            "En yakin retler": "en_yakin_retler",
            "Analiz raporu": "demo_analysis_report.json",
        },
    )
    metin_kontrol(
        report,
        QUANTBOT / "commander.py",
        {
            "Commander model kalite karnesi": "Model Karne",
        },
    )
    metin_kontrol(
        report,
        ROOT / "commander.py",
        {
            "Root commander model kalite karnesi": "Model Karne",
        },
    )

    report.section("4. Model ve forward-test parcalari")
    metin_kontrol(
        report,
        QUANTBOT / "ai_core.py",
        {
            "Feature dogrulama": "_featureleri_dogrula",
            "Tahmin aciklamasi": "son_tahmin_aciklama",
            "Dengesiz veri agirligi": "scale_pos_weight",
        },
    )
    metin_kontrol(
        report,
        QUANTBOT / "performance_metrics.py",
        {
            "Trade metrikleri": "trade_metriklerini_hesapla",
            "Train-forward bolme": "train_forward_bol",
            "Metrik ozeti": "metrik_ozeti",
        },
    )
    metin_kontrol(
        report,
        QUANTBOT / "optimizer.py",
        {
            "Forward raporu": "forward_test_report.json",
            "Train-forward kullanim": "train_forward_bol",
            "Performans metrigi kullanim": "trade_metriklerini_hesapla",
        },
    )

    report.section("5. Calisma durumu ve veri")
    demo_kasa_kontrol(report)
    runtime_status_kontrol(report)
    db_kontrol(report)
    surec_kontrol(report)
    gizli_bilgi_taramasi(report)

    print("\n" + "=" * 72)
    print(f"SONUC: OK={report.ok_count} WARN={report.warn_count} FAIL={report.fail_count}")
    if report.fail_count:
        print("Karar: DUZELTME GEREKIYOR")
        return 1
    print("Karar: DEMO CALISMA ICIN SAGLIKLI")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
