#Requires -Version 5.1
<#
.SYNOPSIS
    Baut das Docker-Image für Synology (amd64), LoxBerry (arm64) oder beide (Multi-Arch).

.EXAMPLE
    .\build-container.ps1
    .\build-container.ps1 --target synology --push
    .\build-container.ps1 --target all --push
    .\build-container.ps1 --tag ghcr.io/jochentcc/earnie-energy:latest --push
#>
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $scriptDir ".venv\Scripts\python.exe"
$python = if (Test-Path $venvPython) { $venvPython } else { "python" }

& $python -m scripts.build_container @args
exit $LASTEXITCODE
