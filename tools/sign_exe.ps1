# Подпись exe для Chitalka.
# Требуется сертификат Code Signing (.pfx) и Windows SDK (signtool.exe).
# Пример:
#   $env:CHITALKA_CERT_PFX = "C:\certs\chitalka.pfx"
#   $env:CHITALKA_CERT_PASSWORD = "..."
#   powershell -ExecutionPolicy Bypass -File tools\sign_exe.ps1

param(
    [string]$Exe = "dist\Chitalka\Chitalka.exe",
    [string]$Pfx = $env:CHITALKA_CERT_PFX,
    [string]$Password = $env:CHITALKA_CERT_PASSWORD,
    [string]$Timestamp = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
if (-not $Pfx -or -not (Test-Path $Pfx)) {
    throw "Не задан CHITALKA_CERT_PFX или файл сертификата не найден."
}
if (-not (Test-Path $Exe)) {
    throw "Не найден $Exe. Сначала соберите exe."
}

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    $candidates = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin" -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "x64" } | Sort-Object FullName -Descending
    $signtool = $candidates | Select-Object -First 1
}
if (-not $signtool) {
    throw "signtool.exe не найден. Установите Windows SDK."
}

& $signtool.Path sign /fd SHA256 /f $Pfx /p $Password /tr $Timestamp /td SHA256 $Exe
if ($LASTEXITCODE -ne 0) { throw "Подпись не удалась: $LASTEXITCODE" }
& $signtool.Path verify /pa /v $Exe
Write-Host "Подписано: $Exe"
