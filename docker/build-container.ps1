#Requires -Version 5.1
<#
.SYNOPSIS
    Baut das Docker-Image für Synology (amd64), LoxBerry (arm64) oder beide (Multi-Arch).

.EXAMPLE
    .\docker\build-container.ps1
    .\docker\build-container.ps1 --target synology --push
    .\docker\build-container.ps1 --target all --push
    .\docker\build-container.ps1 --tag ghcr.io/jochentcc/earnie-energy:latest --push
#>
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

Push-Location $repoRoot
try {
    & $python -m scripts.build_container @args
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
