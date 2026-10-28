@echo off
title StockPredictionPro Web Dashboard
cd /d "c:\Users\talha\OneDrive\Desktop\StockPredictionPro"
echo StockPredictionPro Web Paneli Baslatiliyor...
start http://localhost:8501
call ".venv\Scripts\streamlit.exe" run web\app.py --server.headless=true --server.port=8501
pause
