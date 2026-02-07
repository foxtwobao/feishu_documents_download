Param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..")
$DistDir = Join-Path $ProjectRoot "releases\dist-windows"
$BuildDir = Join-Path $ProjectRoot "releases\build-windows"
$SpecDir = Join-Path $ProjectRoot "releases\spec-windows"
$VenvDir = Join-Path $ProjectRoot "releases\.venv-windows"

& $Python -m venv $VenvDir

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

& $VenvPip install --upgrade pip wheel
& $VenvPip install -e $ProjectRoot
& $VenvPip install pyinstaller

if (Test-Path $DistDir) { Remove-Item $DistDir -Recurse -Force }
if (Test-Path $BuildDir) { Remove-Item $BuildDir -Recurse -Force }
if (Test-Path $SpecDir) { Remove-Item $SpecDir -Recurse -Force }

& $VenvPython -m PyInstaller `
    "$ProjectRoot\larksync\cli.py" `
    --name larksync `
    --onefile `
    --console `
    --clean `
    --distpath $DistDir `
    --workpath $BuildDir `
    --specpath $SpecDir

Write-Host "Windows executable available at $DistDir\larksync.exe"
