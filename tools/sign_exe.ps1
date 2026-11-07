# Подпись exe для Chitalka.
# Варианты:
#   1) Сертификат в хранилище Windows (токен/HSM/Certum SimplySign):
#      $env:CHITALKA_CERT_THUMBPRINT = "ABCDEF..."
#   2) Старый PFX (если ваш CA всё ещё выдаёт такой формат):
#      $env:CHITALKA_CERT_PFX = "C:\certs\chitalka.pfx"
#      $env:CHITALKA_CERT_PASSWORD = "..."
#
# Требуется Windows SDK (signtool.exe) и timestamp-сервер.
# Пример:
#   powershell -ExecutionPolicy Bypass -File tools\sign_exe.ps1

param(
    [string]$Exe = "dist\Chitalka\Chitalka.exe",
    [string]$Thumbprint = $env:CHITALKA_CERT_THUMBPRINT,
    [string]$Pfx = $env:CHITALKA_CERT_PFX,
    [string]$Password = $env:CHITALKA_CERT_PASSWORD,
    [string]$Timestamp = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path $Exe)) {
    throw "Не найден $Exe. Сначала соберите exe."
}
if (-not $Thumbprint -and (-not $Pfx -or -not (Test-Path $Pfx))) {
    throw "Укажите CHITALKA_CERT_THUMBPRINT или CHITALKA_CERT_PFX."
}

$signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
if (-not $signtool) {
    $roots = @(
        "${env:ProgramFiles(x86)}\Windows Kits\10\bin",
        "$env:ProgramFiles\Windows Kits\10\bin"
    )
    $candidates = foreach ($root in $roots) {
        Get-ChildItem $root -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match "x64" } | Sort-Object FullName -Descending
    }
    $signtool = $candidates | Select-Object -First 1
}
if (-not $signtool) {
    throw "signtool.exe не найден. Установите Windows SDK."
}

if ($Thumbprint) {
    & $signtool.Path sign /fd SHA256 /sha1 $Thumbprint /tr $Timestamp /td SHA256 $Exe
} else {
    & $signtool.Path sign /fd SHA256 /f $Pfx /p $Password /tr $Timestamp /td SHA256 $Exe
}
if ($LASTEXITCODE -ne 0) { throw "Подпись не удалась: $LASTEXITCODE" }
& $signtool.Path verify /pa /v $Exe
Write-Host "Подписано: $Exe"
