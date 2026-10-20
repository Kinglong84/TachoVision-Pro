# Crea il collegamento "TachoVision Pro" (con l'icona del programma) che avvia
# start_app.bat: uno nella cartella del programma e uno sul Desktop.
$dir  = $PSScriptRoot
$icon = Join-Path $dir "assets\favicon.ico"
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath("Desktop")

foreach ($folder in @($dir, $desktop)) {
    $lnk = $shell.CreateShortcut((Join-Path $folder "TachoVision Pro.lnk"))
    $lnk.TargetPath       = Join-Path $dir "start_app.bat"
    $lnk.WorkingDirectory = $dir
    $lnk.IconLocation     = "$icon,0"
    $lnk.Description      = "Avvia TachoVision Pro"
    $lnk.Save()
}
Write-Host "  Collegamento 'TachoVision Pro' creato sul Desktop e nella cartella del programma." -ForegroundColor Green
