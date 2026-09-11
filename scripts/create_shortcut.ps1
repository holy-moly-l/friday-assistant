$ErrorActionPreference = 'Stop'
$fridayRoot = Split-Path -Parent $PSScriptRoot
$fridayExecutable = Join-Path $fridayRoot 'release\Friday-win32-x64\Friday.exe'
if (-not (Test-Path -LiteralPath $fridayExecutable)) { throw 'Build the app first.' }
$fridayShell = New-Object -ComObject WScript.Shell
$fridayName = -join ([char[]](0x041F,0x044F,0x0442,0x043D,0x0438,0x0446,0x0430))
$fridayDestinations = @([Environment]::GetFolderPath('Desktop'), $fridayRoot)
foreach ($fridayDestination in $fridayDestinations) {
    $fridayLinkPath = Join-Path $fridayDestination ($fridayName + '.lnk')
    if (Test-Path -LiteralPath $fridayLinkPath) {
        $fridayExisting = $fridayShell.CreateShortcut($fridayLinkPath)
        if ($fridayExisting.TargetPath -ne $fridayExecutable) {
            $fridayLinkPath = Join-Path $fridayDestination ($fridayName + ' AI.lnk')
        }
    }
    $fridayShortcut = $fridayShell.CreateShortcut($fridayLinkPath)
    $fridayShortcut.TargetPath = $fridayExecutable
    $fridayShortcut.WorkingDirectory = $fridayRoot
    $fridayShortcut.IconLocation = (Join-Path $fridayRoot 'public\friday.ico')
    $fridayShortcut.Description = 'Friday - local personal voice assistant'
    $fridayShortcut.Save()
    Write-Output $fridayLinkPath
}
