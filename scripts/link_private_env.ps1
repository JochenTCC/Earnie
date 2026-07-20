#Requires -Version 5.1
<#
.SYNOPSIS
  Links Earnie earnie_env/config to a private sibling site-pack repo via directory junction.

.PARAMETER PrivateRepoRoot
  Root of the private repo (default: ..\Earnie-env-home next to this Earnie clone).

.PARAMETER Force
  Replace an existing earnie_env\config directory or junction.
#>
param(
    [string]$PrivateRepoRoot = "",
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
if (-not $PrivateRepoRoot) {
    $PrivateRepoRoot = Join-Path (Split-Path -Parent $RepoRoot) "Earnie-env-home"
}

$PrivateConfig = Join-Path $PrivateRepoRoot "config"
$LinkPath = Join-Path $RepoRoot "earnie_env\config"
$RuntimeDir = Join-Path $RepoRoot "earnie_env\runtime"
$ShareTariffs = Join-Path $RepoRoot "share\config\tariffs.json"

if (-not (Test-Path -LiteralPath $PrivateConfig)) {
    throw "Private config missing: $PrivateConfig. Clone or create Earnie-env-home first."
}

New-Item -ItemType Directory -Path (Join-Path $RepoRoot "earnie_env") -Force | Out-Null
New-Item -ItemType Directory -Path $RuntimeDir -Force | Out-Null

function Test-IsJunction([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    $item = Get-Item -LiteralPath $Path -Force
    return [bool]($item.Attributes -band [IO.FileAttributes]::ReparsePoint)
}

if (Test-Path -LiteralPath $LinkPath) {
    $isJunction = Test-IsJunction $LinkPath
    if (-not $Force) {
        if ($isJunction) {
            Write-Host "Junction already exists: $LinkPath"
            Write-Host "Target: $((Get-Item -LiteralPath $LinkPath).Target)"
        } else {
            throw "Refusing to replace real directory $LinkPath (pass -Force after backing up)."
        }
    } else {
        if ($isJunction) {
            cmd /c "rmdir `"$LinkPath`""
            if (-not $?) { throw "Failed to remove existing junction: $LinkPath" }
        } else {
            $backup = "$LinkPath.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
            Move-Item -LiteralPath $LinkPath -Destination $backup
            Write-Host "Moved existing config dir to $backup"
        }
    }
}

if (-not (Test-Path -LiteralPath $LinkPath)) {
    cmd /c "mklink /J `"$LinkPath`" `"$PrivateConfig`""
    if (-not $?) { throw "mklink /J failed" }
    Write-Host "Created junction: $LinkPath -> $PrivateConfig"
}

$DestTariffs = Join-Path $LinkPath "tariffs.json"
if (-not (Test-Path -LiteralPath $DestTariffs)) {
    if (-not (Test-Path -LiteralPath $ShareTariffs)) {
        Write-Warning "Missing $ShareTariffs - cannot seed tariffs.json"
    } else {
        Copy-Item -LiteralPath $ShareTariffs -Destination $DestTariffs
        Write-Host "Seeded tariffs.json from share\config\tariffs.json"
    }
} else {
    Write-Host "tariffs.json already present in linked config"
}

Write-Host "Done."
