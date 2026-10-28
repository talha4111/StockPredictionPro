@echo off
REM ───────────────────────────────────────────────────────
REM  Cloudflare Tunnel ile StockPredictionPro'yu internete ac
REM  Hesap gerekmez, ucretsiz "quick tunnel" kullanir.
REM  Her calistiginda yeni bir *.trycloudflare.com linki verir.
REM ───────────────────────────────────────────────────────
echo.
echo ============================================
echo  StockPredictionPro - Telefon Erisim Modu
echo ============================================
echo.
echo  Streamlit sunucusu port 8501'de calisiyor olmali.
echo  (Oncelikle baslat_web.bat ile sunucuyu baslattiginizdan emin olun)
echo.
echo  Cloudflare Tunnel baslatiliyor...
echo  Asagidaki linki telefonunuzun tarayicisina kopyalayin.
echo.
echo  Durdurmak icin: Ctrl+C
echo.

"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://localhost:8501
