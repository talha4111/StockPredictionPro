@echo off
REM ───────────────────────────────────────────────────────
REM  Haftalık Model Güncelleme Betiği
REM  Windows Task Scheduler tarafindan Pazar 21:00'de calistirilir
REM ───────────────────────────────────────────────────────

REM Proje dizinine git
cd /d "c:\Users\talha\OneDrive\Desktop\StockPredictionPro"

echo [%date% %time%] Haftalik model guncelleme basliyor...

REM .venv Python ile calistir
"c:\Users\talha\OneDrive\Desktop\StockPredictionPro\.venv\Scripts\python.exe" "c:\Users\talha\OneDrive\Desktop\StockPredictionPro\web\scripts\haftalik_guncelle.py"

echo [%date% %time%] Guncelleme tamamlandi.
