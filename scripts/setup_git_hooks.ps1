# Aktiviert versionierte Git-Hooks aus .githooks/ für dieses Repository.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

git config core.hooksPath .githooks
Write-Host "Git hooksPath gesetzt auf .githooks"
Write-Host "pre-commit fuehrt 'pytest tests' aus (uebersprungen bei nur *.md, docs/, .cursor/)."
