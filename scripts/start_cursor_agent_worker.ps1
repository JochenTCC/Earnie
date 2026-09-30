#Requires -Version 5.1
<#
.SYNOPSIS
  Start the Cursor Agent worker (My Machines / Remote Control) and register logon auto-start.

.DESCRIPTION
  Runs `agent worker start` for this repository so cursor.com/agents and the mobile app
  can reach your PC after a reboot.

  One-time setup (elevated PowerShell not required):
    .\scripts\start_cursor_agent_worker.ps1 -Action install-task

  Manual start:
    .\scripts\start_cursor_agent_worker.ps1 -Action start

  Prerequisites: Cursor Agent CLI installed (`agent login` once).

.PARAMETER Action
  start | install-task | uninstall-task | status

.PARAMETER WorkerName
  Display name in Cursor (default: jochen-pc).

.PARAMETER RepoRoot
  Workspace passed to the worker (default: repo root containing this script).

.PARAMETER LogonDelaySec
  Seconds to wait after logon before starting (network / desktop readiness).

.EXAMPLE
  .\scripts\start_cursor_agent_worker.ps1 -Action install-task

.EXAMPLE
  .\scripts\start_cursor_agent_worker.ps1 -Action start
#>
param(
    [ValidateSet("start", "install-task", "uninstall-task", "status")]
    [string] $Action = "start",

    [string] $WorkerName = "jochen-pc",

    [string] $RepoRoot = "",

    [int] $LogonDelaySec = 45
)

$ErrorActionPreference = "Stop"

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$AgentDir = Join-Path $env:LOCALAPPDATA "cursor-agent"
$AgentCmd = Join-Path $AgentDir "agent.cmd"
$LockFile = Join-Path $AgentDir "worker.lock"
$LogDir = Join-Path $AgentDir "logs"
$LogFile = Join-Path $LogDir "worker-autostart.log"
$TaskName = "CursorAgentWorker-$WorkerName"
$ScriptPath = $MyInvocation.MyCommand.Path

function Write-WorkerLog {
    param([string] $Message)
    $stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$stamp] $Message"
    if (-not (Test-Path $LogDir)) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $line
}

function Ensure-AgentAvailable {
    if (-not (Test-Path $AgentCmd)) {
        throw "Cursor Agent CLI not found at '$AgentCmd'. Install: irm 'https://cursor.com/install?win32=true' | iex"
    }
    $env:Path = "$AgentDir;$env:Path"
}

function Test-WorkerAlreadyRunning {
    if (Test-Path $LockFile) {
        return $true
    }
    $proc = Get-CimInstance Win32_Process -Filter "Name = 'node.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "cursor-agent.*worker" }
    return [bool]$proc
}

function Start-CursorAgentWorker {
    Ensure-AgentAvailable
    Set-Location $RepoRoot

    if (Test-WorkerAlreadyRunning) {
        Write-WorkerLog "Worker already running (lock or process found). Nothing to do."
        return
    }

    Write-WorkerLog "Starting worker '$WorkerName' in '$RepoRoot'..."
    & $AgentCmd worker start --name $WorkerName --verbose 2>&1 | ForEach-Object {
        Write-WorkerLog $_
    }
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        Write-WorkerLog "Worker exited with code $exitCode"
        exit $exitCode
    }
}

function Install-WorkerScheduledTask {
    Ensure-AgentAvailable
    if (-not (Test-Path $ScriptPath)) {
        throw "Cannot resolve script path for scheduled task registration."
    }

    $arguments = @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-WindowStyle", "Hidden",
        "-File", "`"$ScriptPath`"",
        "-Action", "start",
        "-WorkerName", "`"$WorkerName`"",
        "-RepoRoot", "`"$RepoRoot`""
    ) -join " "

    $taskAction = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory $RepoRoot

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    if ($LogonDelaySec -gt 0) {
        $trigger.Delay = "PT${LogonDelaySec}S"
    }

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $taskAction `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Cursor Agent worker ($WorkerName) for Remote Control / My Machines." `
        -Force | Out-Null

    Write-WorkerLog "Scheduled task registered: $TaskName (logon + ${LogonDelaySec}s delay)."
    Write-WorkerLog "Logs: $LogFile"
    Write-Host "Done. Task '$TaskName' will start the worker at each logon."
    Write-Host "Run 'agent login' once if the worker fails with auth errors."
}

function Uninstall-WorkerScheduledTask {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task '$TaskName' (if it existed)."
}

function Show-WorkerStatus {
    Ensure-AgentAvailable
    Write-Host "Worker name : $WorkerName"
    Write-Host "Repo root   : $RepoRoot"
    Write-Host "Agent CLI   : $AgentCmd"
    Write-Host "Log file    : $LogFile"
    Write-Host "Lock file   : $LockFile ($(if (Test-Path $LockFile) { 'present' } else { 'absent' }))"
    Write-Host "Running     : $(if (Test-WorkerAlreadyRunning) { 'yes' } else { 'no' })"

    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($task) {
        $info = Get-ScheduledTaskInfo -TaskName $TaskName
        Write-Host "Scheduled task: $TaskName (state: $($task.State), last result: $($info.LastTaskResult))"
    }
    else {
        Write-Host "Scheduled task: not installed (run -Action install-task)"
    }

    & $AgentCmd status 2>&1 | ForEach-Object { Write-Host "Auth: $_" }
}

switch ($Action) {
    "start" { Start-CursorAgentWorker }
    "install-task" { Install-WorkerScheduledTask }
    "uninstall-task" { Uninstall-WorkerScheduledTask }
    "status" { Show-WorkerStatus }
}
