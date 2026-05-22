@echo off
echo ============================================================
echo   TachoVision Pro - Installazione Windows
echo ============================================================
echo.

:: Installa dipendenze base (sempre funzionano)
echo [1/3] Installazione dipendenze base...
pip install dash dash-bootstrap-components plotly pandas reportlab
echo.

:: Installa dipendenze cloud (opzionali, ignorano errori)
echo [2/3] Installazione dipendenze cloud (opzionali)...
pip install google-api-python-client google-auth-oauthlib msal dropbox 2>nul
echo.

:: Tenta installazione pyscard (lettore smartcard)
echo [3/3] Tentativo installazione pyscard (lettore smartcard USB)...
echo      Se fallisce, il programma funziona comunque senza lettore fisico.
echo.

:: Prima prova wheel precompilato
pip install pyscard 2>nul
IF %ERRORLEVEL% EQU 0 (
    echo [OK] pyscard installato - lettore smartcard USB disponibile
) ELSE (
    echo [WARN] pyscard non installato.
    echo        Per usare il lettore smartcard USB, installa prima:
    echo        "Microsoft C++ Build Tools" da:
    echo        https://visualstudio.microsoft.com/visual-cpp-build-tools/
    echo        Poi rilancia questo script.
    echo.
    echo        Il programma funziona normalmente caricando file .DDD.
)

echo.
echo ============================================================
echo   Installazione completata!
echo   Avvia il programma con:  python app.py
echo   Poi apri:  http://localhost:8050
echo ============================================================
pause
