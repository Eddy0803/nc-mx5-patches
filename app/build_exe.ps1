# Build NCPatcher.exe (single file, 32-bit so it can load 32-bit J2534 drivers).
# Needs a 32-bit Python 3.12 with tkinter (the python.org 32-bit installer) and PyInstaller:
#   <32-bit python> -m pip install pyinstaller
# Usage:  powershell -ExecutionPolicy Bypass -File app\build_exe.ps1 [-Python <path to 32-bit python.exe>]
param([string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python312-32\python.exe")
$ErrorActionPreference = 'Stop'
$bits = & $Python -c "import struct; print(struct.calcsize('P') * 8)"
if ($bits -ne '32') { throw "$Python is $bits-bit - use a 32-bit Python so the app can load 32-bit J2534 drivers" }
Push-Location $PSScriptRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --distpath ..\dist --workpath ..\build NCPatcher.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    Get-Item ..\dist\NCPatcher.exe | Select-Object FullName, @{n='MB';e={[math]::Round($_.Length/1MB, 1)}}
} finally { Pop-Location }
