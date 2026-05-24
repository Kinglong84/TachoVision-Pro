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

:: Rileva versione Python
echo [3/3] Tentativo installazione pyscard (lettore smartcard USB)...
for /f "tokens=*" %%i in ('python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"') do set PY_VER=%%i
for /f "tokens=*" %%i in ('python -c "import sys; print(sys.version_info.minor)"') do set PY_MINOR=%%i
echo        Python rilevato: %PY_VER%
echo.

:: Prima prova wheel precompilato
pip install pyscard 2>nul
IF %ERRORLEVEL% EQU 0 (
    echo [OK] pyscard installato - lettore smartcard USB disponibile
    goto fine
)

:: Wheel non disponibile: messaggio specifico per versione
echo [INFO] pyscard non installato tramite wheel.
echo.

IF "%PY_MINOR%"=="9" (
    echo        Python 3.9 su Windows non ha un wheel pre-compilato per pyscard.
    echo        Consiglio: aggiorna a Python 3.10-3.13 per l'installazione diretta.
    goto istruzioni_build
)
IF %PY_MINOR% GEQ 14 (
    echo        Python %PY_VER% e' troppo recente: wheel pyscard non ancora disponibile.
    echo        Consiglio: usa Python 3.10-3.13 per l'installazione diretta.
    goto istruzioni_build
)

:istruzioni_build
echo.
echo        Per compilare pyscard da sorgente (Python %PY_VER%):
echo        1. Scarica Microsoft C++ Build Tools:
echo           https://visualstudio.microsoft.com/visual-cpp-build-tools/
echo        2. Installa "Sviluppo di applicazioni desktop con C++"
echo        3. Rilancia questo script
echo.
echo        Il programma funziona normalmente caricando file .DDD.

:fine
echo.
echo ============================================================
echo   Installazione completata!
echo   Avvia il programma con:  python app.py
echo   Poi apri:  http://localhost:8050
echo ============================================================
pause
