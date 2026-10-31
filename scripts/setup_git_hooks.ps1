# Aktiviert versionierte Git-Hooks aus .githooks/ für dieses Repository.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

git config core.hooksPath .githooks
Write-Host "Git hooksPath gesetzt auf .githooks"
Write-Host "pre-commit fuehrt 'pytest tests' aus (uebersprungen bei nur *.md, docs/, .cursor/)."
Write-Host "pre-push fuehrt die Regression-Suite aus (scripts.run_regression; Arbeitsbaum muss dem gepushten Commit entsprechen)."
Write-Host "JUnit wird in .pytest_cache/test-metrics/ ingestiert (scripts.test_health_report)."
Write-Host "post-commit fragt interaktiv nach Token-Report (Download / vorhandene CSV / Skip)."
