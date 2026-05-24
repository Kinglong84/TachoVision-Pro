# TachoVision Pro — Script installazione PowerShell
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  TachoVision Pro - Installazione Windows" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Dipendenze base (obbligatorie)
Write-Host "[1/3] Installazione dipendenze base..." -ForegroundColor Yellow
pip install dash dash-bootstrap-components plotly pandas reportlab
Write-Host "[OK] Dipendenze base installate" -ForegroundColor Green
Write-Host ""

# 2. Dipendenze cloud (opzionali)
Write-Host "[2/3] Installazione dipendenze cloud (opzionali)..." -ForegroundColor Yellow
pip install google-api-python-client google-auth-oauthlib msal dropbox 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] Dipendenze cloud installate" -ForegroundColor Green
} else {
    Write-Host "[WARN] Alcune dipendenze cloud non installate (Google Drive/OneDrive/Dropbox non disponibili)" -ForegroundColor DarkYellow
}
Write-Host ""

# 3. pyscard (lettore smartcard)
Write-Host "[3/3] Tentativo installazione pyscard (lettore smartcard USB)..." -ForegroundColor Yellow

# Rileva versione Python corrente
$pyVersion = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
Write-Host "       Python rilevato: $pyVersion" -ForegroundColor Gray

pip install pyscard 2>$null
if ($LASTEXITCODE -eq 0) {
    Write-Host "[OK] pyscard installato — lettore smartcard USB disponibile" -ForegroundColor Green
} else {
    Write-Host "[INFO] pyscard non installato tramite wheel." -ForegroundColor DarkYellow
    Write-Host ""

    # Messaggio specifico in base alla versione Python
    $pyMajor = python -c "import sys; print(sys.version_info.major)" 2>$null
    $pyMinor = python -c "import sys; print(sys.version_info.minor)" 2>$null
    $minor   = [int]$pyMinor

    if ($minor -eq 9) {
        Write-Host "       Python 3.9 su Windows non ha un wheel pre-compilato per pyscard." -ForegroundColor DarkYellow
        Write-Host "       Consiglio: aggiorna a Python 3.10-3.13 per l'installazione diretta." -ForegroundColor DarkYellow
    } elseif ($minor -ge 14) {
        Write-Host "       Python $pyVersion e' troppo recente: wheel pyscard non ancora disponibile." -ForegroundColor DarkYellow
        Write-Host "       Consiglio: usa Python 3.10-3.13 per l'installazione diretta." -ForegroundColor DarkYellow
    }

    Write-Host ""
    Write-Host "       Per compilare pyscard da sorgente (Python $pyVersion):" -ForegroundColor Gray
    Write-Host "       1. Scarica Microsoft C++ Build Tools:" -ForegroundColor Gray
    Write-Host "          https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Gray
    Write-Host "       2. Installa il workload 'Sviluppo di applicazioni desktop con C++'" -ForegroundColor Gray
    Write-Host "       3. Rilancia questo script" -ForegroundColor Gray
    Write-Host ""
    Write-Host "       Il programma funziona normalmente caricando file .DDD." -ForegroundColor Green
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Avvia il programma:" -ForegroundColor White
Write-Host "    python app.py" -ForegroundColor Yellow
Write-Host "  Poi apri nel browser:" -ForegroundColor White
Write-Host "    http://localhost:8050" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Read-Host "Premi INVIO per chiudere"
