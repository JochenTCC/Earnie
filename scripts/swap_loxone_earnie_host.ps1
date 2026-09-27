#Requires -Version 5.1
<#
.SYNOPSIS
  Toggle Earnie HTTP host in a Loxone Config project (NAS <-> Dev-PC).

.DESCRIPTION
  Detects whether the project currently points at the NAS or Dev-PC host,
  then swaps all matching Virtual In/Out base URLs to the other host:
    http://DS-KO-DO-2:8541  <->  http://dev-pc:8541
    http://DS-KO-DO-2:8501  <->  http://dev-pc:8501

  Supports plain XML/text and .Loxone ZIP projects. Creates a .bak next to
  the file before modifying it.

.PARAMETER Path
  Path to the .Loxone project (default: Haussteuerung-Gen2.Loxone).

.EXAMPLE
  .\scripts\swap_loxone_earnie_host.ps1

.EXAMPLE
  .\scripts\swap_loxone_earnie_host.ps1 -Path "D:\Loxone\Haus.Loxone"
#>
param(
    [Parameter(Mandatory = $false, Position = 0)]
    [string]$Path = "C:\Users\joche\Documents\Loxone\Loxone Config\Projects\Haussteuerung-Gen2.Loxone"
)

$ErrorActionPreference = "Stop"

$NasHost = "DS-KO-DO-2"
$PcHost = "dev-pc"
$Ports = @(8541, 8501)

function Get-HostUrlList {
    param([string]$HostName)
    $urls = @()
    foreach ($port in $Ports) {
        $urls += "http://${HostName}:${port}"
    }
    return $urls
}

function Get-ReplacementPairs {
    param([string]$Direction)
    $pairs = @()
    foreach ($port in $Ports) {
        $nasUrl = "http://${NasHost}:${port}"
        $pcUrl = "http://${PcHost}:${port}"
        if ($Direction -eq "pc") {
            $pairs += [pscustomobject]@{ From = $nasUrl; To = $pcUrl }
        }
        else {
            $pairs += [pscustomobject]@{ From = $pcUrl; To = $nasUrl }
        }
    }
    return $pairs
}

function Get-UrlHitCount {
    param(
        [string]$Text,
        [string[]]$Urls
    )
    $total = 0
    foreach ($url in $Urls) {
        $regex = [regex]::new(
            [regex]::Escape($url),
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
        $total += $regex.Matches($Text).Count
    }
    return $total
}

function Invoke-HostSwap {
    param(
        [string]$Text,
        [object[]]$Pairs
    )
    $total = 0
    $updated = $Text
    foreach ($pair in $Pairs) {
        $regex = [regex]::new(
            [regex]::Escape($pair.From),
            [System.Text.RegularExpressions.RegexOptions]::IgnoreCase
        )
        $m = $regex.Matches($updated)
        if ($m.Count -gt 0) {
            $total += $m.Count
            $updated = $regex.Replace($updated, $pair.To)
        }
    }
    return @{ Text = $updated; Count = $total }
}

function Test-IsZipFile {
    param([string]$FilePath)
    $fs = [System.IO.File]::OpenRead($FilePath)
    try {
        $b0 = $fs.ReadByte()
        $b1 = $fs.ReadByte()
        # ZIP local header PK\x03\x04
        return ($b0 -eq 0x50 -and $b1 -eq 0x4B)
    }
    finally {
        $fs.Dispose()
    }
}

function Get-ProjectTextSamples {
    param([string]$FilePath)
    $samples = @()
    if (Test-IsZipFile -FilePath $FilePath) {
        Add-Type -AssemblyName System.IO.Compression
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $zip = [System.IO.Compression.ZipFile]::OpenRead($FilePath)
        try {
            foreach ($entry in $zip.Entries) {
                if ($entry.Length -le 0) { continue }
                if ($entry.FullName -match '\.(png|jpg|jpeg|gif|bmp|ico|pdf|exe|dll)$') { continue }
                $reader = New-Object System.IO.StreamReader($entry.Open())
                try {
                    $samples += $reader.ReadToEnd()
                }
                finally {
                    $reader.Dispose()
                }
            }
        }
        finally {
            $zip.Dispose()
        }
    }
    else {
        $samples += [System.IO.File]::ReadAllText($FilePath)
    }
    return $samples
}

function Resolve-SwapDirection {
    param([string]$FilePath)
    $nasUrls = Get-HostUrlList -HostName $NasHost
    $pcUrls = Get-HostUrlList -HostName $PcHost
    $nasHits = 0
    $pcHits = 0
    foreach ($sample in (Get-ProjectTextSamples -FilePath $FilePath)) {
        $nasHits += Get-UrlHitCount -Text $sample -Urls $nasUrls
        $pcHits += Get-UrlHitCount -Text $sample -Urls $pcUrls
    }
    if ($nasHits -gt 0 -and $pcHits -gt 0) {
        Write-Error ("Ambiguous hosts in project: NAS hits={0}, Dev-PC hits={1}. Fix manually first." -f $nasHits, $pcHits)
    }
    if ($nasHits -gt 0) {
        return @{ Direction = "pc"; FromHost = $NasHost; ToHost = $PcHost; Hits = $nasHits }
    }
    if ($pcHits -gt 0) {
        return @{ Direction = "nas"; FromHost = $PcHost; ToHost = $NasHost; Hits = $pcHits }
    }
    Write-Error "No Earnie URLs found for host '$NasHost' or '$PcHost' (ports $($Ports -join ', '))."
}

function Update-PlainFile {
    param(
        [string]$FilePath,
        [object[]]$Pairs
    )
    $encoding = New-Object System.Text.UTF8Encoding $false
    $raw = [System.IO.File]::ReadAllText($FilePath)
    $result = Invoke-HostSwap -Text $raw -Pairs $Pairs
    if ($result.Count -eq 0) {
        return 0
    }
    [System.IO.File]::WriteAllText($FilePath, $result.Text, $encoding)
    return $result.Count
}

function Update-LoxoneZip {
    param(
        [string]$FilePath,
        [object[]]$Pairs
    )
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $total = 0
    $zip = [System.IO.Compression.ZipFile]::Open(
        $FilePath,
        [System.IO.Compression.ZipArchiveMode]::Update
    )
    try {
        $entries = @($zip.Entries)
        foreach ($entry in $entries) {
            if ($entry.Length -le 0) { continue }
            $name = $entry.FullName
            if ($name -match '\.(png|jpg|jpeg|gif|bmp|ico|pdf|exe|dll)$') { continue }

            $reader = New-Object System.IO.StreamReader($entry.Open())
            try {
                $content = $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }

            $result = Invoke-HostSwap -Text $content -Pairs $Pairs
            if ($result.Count -eq 0) { continue }

            $entry.Delete()
            $newEntry = $zip.CreateEntry($name, [System.IO.Compression.CompressionLevel]::Optimal)
            $writer = New-Object System.IO.StreamWriter($newEntry.Open())
            try {
                $writer.Write($result.Text)
            }
            finally {
                $writer.Dispose()
            }
            $total += $result.Count
            Write-Host ("  updated entry: {0} ({1} replacement(s))" -f $name, $result.Count)
        }
    }
    finally {
        $zip.Dispose()
    }
    return $total
}

# --- main ---
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
    Write-Error "File not found: $Path"
}

$filePath = (Resolve-Path -LiteralPath $Path).Path
$detected = Resolve-SwapDirection -FilePath $filePath
$pairs = Get-ReplacementPairs -Direction $detected.Direction

Write-Host ("Path: {0}" -f $filePath)
Write-Host ("Detected host: {0} ({1} hit(s)) -> swap to {2}" -f $detected.FromHost, $detected.Hits, $detected.ToHost)
foreach ($p in $pairs) {
    Write-Host ("  {0}  ->  {1}" -f $p.From, $p.To)
}

$bak = "$filePath.bak"
Copy-Item -LiteralPath $filePath -Destination $bak -Force
Write-Host ("Backup: {0}" -f $bak)

$count = 0
if (Test-IsZipFile -FilePath $filePath) {
    Write-Host "Format: ZIP (.Loxone or similar)"
    $count = Update-LoxoneZip -FilePath $filePath -Pairs $pairs
}
else {
    Write-Host "Format: plain text/XML"
    $count = Update-PlainFile -FilePath $filePath -Pairs $pairs
}

if ($count -eq 0) {
    Write-Warning "No replacements applied (backup kept)."
    exit 2
}

Write-Host ("Done: {0} replacement(s)." -f $count)
Write-Host "Reload/save the project in Loxone Config and upload to the Miniserver."
exit 0
