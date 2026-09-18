#Requires -Version 5.1
<#
.SYNOPSIS
  Start, stop, update Earnie via VMware Workstation vctl (no Docker Compose).

.DESCRIPTION
  Uses the published GHCR image (same as Synology/Proxmox prod). Persist data under
  DataRoot\earnie_env\{config,runtime}. See docs/einrichtung/vmware-vctl.md.

.PARAMETER Action
  status | start-runtime | stop-runtime | ensure-dirs | login | pull |
  up | start | stop | restart | update | logs-hint

.PARAMETER Image
  Container image (default: ghcr.io/jochentcc/earnie-energy:latest).

.PARAMETER DataRoot
  Host folder for earnie_env (default: %USERPROFILE%\Earnie).

.PARAMETER ContainerName
  vctl container name (default: earnie-productive).

.PARAMETER UiPort
  Host UI port (default: 8501).

.PARAMETER DaemonPort
  Host daemon port (default: 8541).

.PARAMETER SkipLoxoneVerify
  Set EARNIE_VERIFY_LOXONE_ON_START=0 (useful for offline / what-if only).

.EXAMPLE
  .\scripts\run_earnie_vctl.ps1 -Action up

.EXAMPLE
  .\scripts\run_earnie_vctl.ps1 -Action update -Image ghcr.io/jochentcc/earnie-energy:2.5.2
#>
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(
        "status",
        "start-runtime",
        "stop-runtime",
        "ensure-dirs",
        "login",
        "pull",
        "up",
        "start",
        "stop",
        "restart",
        "update",
        "logs-hint"
    )]
    [string]$Action,

    [string]$Image = "ghcr.io/jochentcc/earnie-energy:latest",

    [string]$DataRoot = "",

    [string]$ContainerName = "earnie-productive",

    [int]$UiPort = 8501,

    [int]$DaemonPort = 8541,

    [switch]$SkipLoxoneVerify
)

$ErrorActionPreference = "Stop"

function Resolve-VctlPath {
    $candidates = @(
        "${env:ProgramFiles(x86)}\VMware\VMware Workstation\bin\vctl.exe",
        "${env:ProgramFiles}\VMware\VMware Workstation\bin\vctl.exe",
        "${env:ProgramFiles(x86)}\VMware\VMware Player\bin\vctl.exe",
        "${env:ProgramFiles}\VMware\VMware Player\bin\vctl.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path -LiteralPath $path) {
            return $path
        }
    }
    $fromPath = Get-Command vctl -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }
    throw "vctl.exe not found. Install VMware Workstation Pro/Player for Windows and retry."
}

function Get-DataRoot {
    if ($DataRoot) {
        return $DataRoot
    }
    return (Join-Path $env:USERPROFILE "Earnie")
}

function Get-ConfigDir([string]$Root) {
    return (Join-Path $Root "earnie_env\config")
}

function Get-RuntimeDir([string]$Root) {
    return (Join-Path $Root "earnie_env\runtime")
}

function Invoke-Vctl {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$VctlArgs)
    & $script:VctlExe @VctlArgs
    if ($LASTEXITCODE -ne 0) {
        throw "vctl failed (exit $LASTEXITCODE): $($VctlArgs -join ' ')"
    }
}

function Ensure-DataDirs([string]$Root) {
    $configDir = Get-ConfigDir $Root
    $runtimeDir = Get-RuntimeDir $Root
    New-Item -ItemType Directory -Force -Path $configDir | Out-Null
    New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
    Write-Host "Data dirs ready:"
    Write-Host "  $configDir"
    Write-Host "  $runtimeDir"
}

function Test-ContainerExists([string]$Name) {
    $raw = & $script:VctlExe ps -a 2>$null | Out-String
    return ($raw -match [regex]::Escape($Name))
}

function Test-ContainerRunning([string]$Name) {
    $raw = & $script:VctlExe ps 2>$null | Out-String
    return ($raw -match [regex]::Escape($Name))
}

function Start-ContainerRuntime {
    Write-Host "Starting vctl container runtime..."
    Invoke-Vctl system start
    Invoke-Vctl system info
}

function Stop-ContainerRuntime {
    Write-Host "Stopping vctl container runtime..."
    Invoke-Vctl system stop
}

function Show-Status {
    Write-Host "=== vctl system ==="
    & $script:VctlExe system info
    Write-Host ""
    Write-Host "=== containers ==="
    & $script:VctlExe ps -a
    Write-Host ""
    Write-Host "=== images (earnie) ==="
    & $script:VctlExe images 2>$null | Select-String -Pattern "earnie-energy|ernie-energy" -SimpleMatch:$false
    $root = Get-DataRoot
    Write-Host ""
    Write-Host "DataRoot: $root"
    Write-Host "UI:       http://localhost:$UiPort"
}

function Login-Ghcr {
    Write-Host "Login to ghcr.io (GitHub user + PAT with read:packages)..."
    Invoke-Vctl login ghcr.io
}

function Pull-Image {
    Write-Host "Pulling $Image ..."
    Invoke-Vctl pull $Image
}

function Stop-EarnieContainer {
    if (Test-ContainerRunning $ContainerName) {
        Write-Host "Stopping $ContainerName ..."
        Invoke-Vctl stop $ContainerName
    }
    else {
        Write-Host "Container not running: $ContainerName"
    }
}

function Remove-EarnieContainer {
    if (Test-ContainerExists $ContainerName) {
        if (Test-ContainerRunning $ContainerName) {
            Invoke-Vctl stop $ContainerName
        }
        Write-Host "Removing $ContainerName ..."
        Invoke-Vctl rm $ContainerName
    }
}

function Start-EarnieContainer {
    if (-not (Test-ContainerExists $ContainerName)) {
        throw "Container '$ContainerName' does not exist. Run -Action up first."
    }
    if (Test-ContainerRunning $ContainerName) {
        Write-Host "Already running: $ContainerName"
        return
    }
    Write-Host "Starting $ContainerName ..."
    Invoke-Vctl start $ContainerName
}

function Run-EarnieContainer {
    $root = Get-DataRoot
    Ensure-DataDirs $root

    $configDir = Get-ConfigDir $root
    $runtimeDir = Get-RuntimeDir $root
    $verify = if ($SkipLoxoneVerify) { "0" } else { "1" }

    if (Test-ContainerExists $ContainerName) {
        throw "Container '$ContainerName' already exists. Use -Action start, restart, or update."
    }

    Write-Host "Creating and starting $ContainerName from $Image ..."
    $vctlArgs = @(
        "run", "--name", $ContainerName, "-d",
        "--publish", "${UiPort}:8501",
        "--publish", "${DaemonPort}:8541",
        "--volume", "${configDir}:/app/config",
        "--volume", "${runtimeDir}:/app/runtime",
        "-e", "TZ=Europe/Vienna",
        "-e", "EARNIE_ENV_PATH=.",
        "-e", "EARNIE_STRICT_TARIFF_VALIDATE=1",
        "-e", "EARNIE_VERIFY_LOXONE_ON_START=$verify",
        "-e", "EARNIE_AUTO_START_MAIN=1",
        "-e", "EARNIE_UI_MODES=sunset2sunset,live_environment",
        $Image,
        "python", "-m", "scripts.run_streamlit", "--",
        "--server.enableCORS", "false",
        "--server.enableXsrfProtection", "false"
    )
    Invoke-Vctl @vctlArgs
    Write-Host "UI: http://localhost:$UiPort"
    Write-Host "Edit config under: $configDir"
}

function Update-EarnieContainer {
    Start-ContainerRuntime
    Pull-Image
    Remove-EarnieContainer
    Run-EarnieContainer
}

function Show-LogsHint {
    $logPath = Join-Path (Get-RuntimeDir (Get-DataRoot)) "earnie.log"
    Write-Host "Daemon log (after first start): $logPath"
    Write-Host "Container detail: vctl describe $ContainerName"
    Write-Host "Follow via: Get-Content -Wait `"$logPath`""
}

$script:VctlExe = Resolve-VctlPath
Write-Host "Using vctl: $script:VctlExe"

switch ($Action) {
    "status" { Show-Status }
    "start-runtime" { Start-ContainerRuntime }
    "stop-runtime" { Stop-ContainerRuntime }
    "ensure-dirs" { Ensure-DataDirs (Get-DataRoot) }
    "login" { Login-Ghcr }
    "pull" {
        Start-ContainerRuntime
        Pull-Image
    }
    "up" {
        Start-ContainerRuntime
        Pull-Image
        Run-EarnieContainer
    }
    "start" {
        Start-ContainerRuntime
        Start-EarnieContainer
    }
    "stop" { Stop-EarnieContainer }
    "restart" {
        Stop-EarnieContainer
        Start-EarnieContainer
    }
    "update" { Update-EarnieContainer }
    "logs-hint" { Show-LogsHint }
    default { throw "Unknown action: $Action" }
}
