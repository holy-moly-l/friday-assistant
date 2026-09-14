$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$fridayExe = Join-Path $projectRoot 'release\Friday-win32-x64\Friday.exe'
if (Get-Process Friday -ErrorAction SilentlyContinue) {
    throw 'Закройте Пятницу перед запуском режима диагностики.'
}
$env:FRIDAY_DEBUG = '1'
Start-Process -FilePath $fridayExe -WorkingDirectory $projectRoot
Write-Host ('Локальный журнал: ' + (Join-Path $projectRoot 'data\backend.log'))
