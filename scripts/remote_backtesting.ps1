# Wrapper für Remote-Backtesting (Windows).
# Aufruf: .\scripts\remote_backtesting.ps1 sync-run -- --start-month 6 --end-month 7
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Error "python nicht im PATH gefunden."
}
& python -m scripts.remote_backtesting @args
exit $LASTEXITCODE
