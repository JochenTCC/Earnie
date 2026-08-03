#Requires -Version 5.1
<#
.SYNOPSIS
  Issue earnie_registry.json (Ed25519) for a hardware fingerprint.

.DESCRIPTION
  Operator-only wrapper around ``python -m scripts.issue_dev_registry_token``.
  Requires the PKCS8 PEM private key (never commit it).

.PARAMETER Fingerprint
  Full 64-char SHA-256 hex hardware fingerprint from Info / About or
  ``python -m scripts.print_hardware_fingerprint``.

.PARAMETER Out
  Output path for the entitlement JSON (default: .\earnie_registry.json).

.PARAMETER PrivateKey
  Path to Ed25519 PKCS8 PEM. Default: env EARNIE_REGISTRY_PRIVATE_KEY_PATH,
  else <repo>\secrets\earnie_registry_private.pem.

.PARAMETER ExpiresAt
  Optional ISO-8601 expiry (e.g. 2027-12-31T23:59:59Z). Omit for forever.

.PARAMETER Issuer
  Issuer label (default: earnie).

.EXAMPLE
  .\scripts\issue_earnie_registry.ps1 -Fingerprint 7afc0243...c1ac91

.EXAMPLE
  .\scripts\issue_earnie_registry.ps1 `
    -Fingerprint 7afc0243254d84018cefdfbbd9d46598b950fbd4f493788a2b72515c27c1ac91 `
    -Out .\out\earnie_registry.json `
    -PrivateKey .\secrets\earnie_registry_private.pem
#>
param(
    [Parameter(Mandatory = $true)]
    [string]$Fingerprint,

    [string]$Out = "",

    [string]$PrivateKey = "",

    [string]$ExpiresAt = "",

    [string]$Issuer = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $RepoRoot

$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python venv not found: $Python"
}

if (-not $Out) {
    $Out = Join-Path $RepoRoot "earnie_registry.json"
}

if (-not $PrivateKey) {
    $PrivateKey = $env:EARNIE_REGISTRY_PRIVATE_KEY_PATH
}
if (-not $PrivateKey) {
    $PrivateKey = Join-Path $RepoRoot "secrets\earnie_registry_private.pem"
}
if (-not (Test-Path -LiteralPath $PrivateKey)) {
    throw @"
Private key not found: $PrivateKey
Set -PrivateKey or EARNIE_REGISTRY_PRIVATE_KEY_PATH to the PKCS8 PEM
(operator vault / secrets\earnie_registry_private.pem). Never commit the key.
"@
}

$fp = $Fingerprint.Trim().ToLowerInvariant()
if ($fp.Length -ne 64 -or ($fp -notmatch '^[0-9a-f]{64}$')) {
    throw "-Fingerprint must be exactly 64 hex characters (0-9a-f)."
}

$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONUTF8 = "1"
$env:EARNIE_REGISTRY_PRIVATE_KEY_PATH = (Resolve-Path -LiteralPath $PrivateKey).Path

$argsList = @(
    "-m", "scripts.issue_dev_registry_token",
    "--fingerprint", $fp,
    "--out", $Out,
    "--private-key", $env:EARNIE_REGISTRY_PRIVATE_KEY_PATH
)
if ($Issuer) {
    $argsList += @("--issuer", $Issuer)
}
if ($ExpiresAt) {
    $argsList += @("--expires-at", $ExpiresAt)
}

& $Python @argsList
if ($LASTEXITCODE -ne 0) {
    throw "Issuer failed with exit code $LASTEXITCODE"
}

Write-Host "OK: $Out"
Write-Host "Send this file to the user; they place it under earnie_env\runtime\earnie_registry.json"
